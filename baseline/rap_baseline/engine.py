"""Engine orchestration: phases P0-P11 of the approved PR-S1 addendum (P11 added by review repair R2).

Order (fail closed at every step):

  P0  request validation; ``as_of`` must be timezone-aware (UTC-normalized)
  P1  targets + organization guard + policy scope          -- no authority call
  P2  metadata-only projection                             -- no authority call
  P3  organization guard over the projection               -- no authority call
  P4  structural validators (no claims/participations)     -- no authority call
  P5  source gate over every decision-relevant source      -- ``require_sources_admissible``
  P6  first value-dependent validation                     -- ``validate_recommendation_inputs`` (empty results)
  P7  freeze ``DecisionInputs`` (the only input to rules; also the fingerprinted object)
  P8  rules (SD-4/SD-5)
  P9  ``EligibilityResult`` (deterministic id, UTC ``evaluated_at``)
  P10 post-check: the same wrapper with the produced result + provenance subset check
  P11 provenance record (output digest, checks)

Source-integrity and authorization failures are refusals, never ``unknown``
rule outcomes. A post-check failure is an engine defect (``Errored``) and the
verifier is never relaxed. Any unexpected exception in any phase is returned as
``Errored``; ``assess`` never raises and never returns a partial ``Assessed``.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Any, Mapping

from pydantic import ValidationError

from rap_contracts.eligibility import EligibilityResult, PolicyPin, derive_decision, eligibility_source_refs
from rap_contracts.evidence import require_sources_admissible
from rap_contracts.invariants import ContractViolation
from rap_contracts.models import SourceSystem, SourceSystemCapabilities
from rap_contracts.recommendation import RecommendationContext, validate_recommendation_inputs

from . import EVALUATED_BY, rules
from .identity import (
    EngineIdentity,
    IdentityError,
    build_decision_inputs,
    input_fingerprint,
    normalize_ref,
    output_digest,
    result_id,
    to_utc,
)
from .inputs import gate_refs, organization_guard, project, resolve_targets, structural_checks
from .provenance import AssessmentProvenance, RecordingAuthority
from .request import Assessed, EligibilityRequest, Errored, Refused, Stage

ENGINE = EngineIdentity(evaluated_by=EVALUATED_BY, rule_table_version=rules.RULE_TABLE_VERSION,
                        citation_policy_version=rules.CITATION_POLICY_VERSION)


def assess(request: EligibilityRequest | Mapping[str, Any], context, authority,
           capabilities: Mapping[SourceSystem, SourceSystemCapabilities]) -> Assessed | Refused | Errored:
    """Assess one candidate x opportunity x pinned policy version from a supplied ``EligibilityContext``.

    ``context`` must contain no eligibility results (the type has no field for
    them). ``authority`` is a ``SourceAuthority``; in tests a synthetic stand-in.
    """
    recorder = RecordingAuthority(authority)
    calls = lambda: len(recorder.records)  # noqa: E731

    # P0
    try:
        req = request if isinstance(request, EligibilityRequest) else EligibilityRequest.model_validate(request)
        as_of = to_utc(req.as_of)
    except (ValidationError, IdentityError) as exc:
        return Errored(Stage.REQUEST, "invalid_request", str(exc).splitlines()[0], calls())

    stage = Stage.REFERENCE
    try:
        # P1-P4: metadata and structure only; no authority call
        targets = resolve_targets(req, context)
        stage = Stage.PROJECTION
        projected = project(context, targets)
        organization_guard(projected, targets, req.organization_id)
        stage = Stage.STRUCTURE
        structural_checks(projected, capabilities)
        refs = gate_refs(projected, targets)

        # P5: exact-version admission of every decision-relevant source
        stage = Stage.SOURCE_GATE
        require_sources_admissible(refs, recorder, req.principal_id, capabilities)

        # P6: first value-dependent step -- existing wrapper, empty read-only results map
        stage = Stage.CONTEXT
        validate_recommendation_inputs(RecommendationContext(
            eligibility=projected, eligibility_results=MappingProxyType({}), capabilities=capabilities))
    except ContractViolation as exc:
        return Refused(stage, exc.code, str(exc), calls())
    except Exception as exc:  # unexpected: an engine defect, never a refusal
        return Errored(stage, "unexpected_exception", type(exc).__name__, calls())

    # P7-P9
    try:
        inputs = build_decision_inputs(projected, req.organization_id, targets.candidate.id, targets.opportunity.id, ENGINE)
        fingerprint = input_fingerprint(inputs)
        outcomes = rules.evaluate(inputs)
        policy = targets.policy
        result = EligibilityResult(
            id=result_id(fingerprint, as_of),
            organization_id=req.organization_id,
            candidate_id=targets.candidate.id,
            opportunity_id=targets.opportunity.id,
            opportunity_ref=normalize_ref(targets.opportunity.source_ref),
            policy=PolicyPin(policy_set_id=policy.id, version=policy.version, source_ref=normalize_ref(policy.source_ref)),
            rule_outcomes=outcomes,
            decision=derive_decision(outcomes),
            evaluated_at=as_of,
            evaluated_by=EVALUATED_BY,
        )
    except rules.RuleEvaluationError as exc:
        return Errored(Stage.RESULT, "rule_evaluation_failed", str(exc), calls())
    except ValidationError as exc:
        return Errored(Stage.RESULT, "result_construction_failed", str(exc).splitlines()[0], calls())
    except Exception as exc:
        return Errored(Stage.RESULT, "unexpected_exception", type(exc).__name__, calls())

    # P10: independent post-check with the unmodified wrapper, then provenance subset
    try:
        validate_recommendation_inputs(RecommendationContext(
            eligibility=projected, eligibility_results=MappingProxyType({result.id: result}), capabilities=capabilities))
        dependencies = set(eligibility_source_refs(result, projected))
    except ContractViolation as exc:
        return Errored(Stage.POST_CHECK, "post_check_failed", f"{exc.code}: {exc}", calls())
    except Exception as exc:  # unexpected: fail closed inside the three-outcome boundary
        return Errored(Stage.POST_CHECK, "unexpected_exception", type(exc).__name__, calls())
    if not dependencies <= set(refs):
        return Errored(Stage.POST_CHECK, "provenance_not_gated", "a result dependency was not admitted", calls())

    # P11: provenance; nothing is returned as Assessed unless it is complete
    try:
        checks = tuple(r.answer for r in recorder.records if r.answer is not None)
        provenance = AssessmentProvenance(
            result_id=result.id, input_fingerprint=fingerprint, output_digest=output_digest(result),
            principal_id=req.principal_id, as_of=as_of, evaluated_by=EVALUATED_BY,
            rule_table_version=rules.RULE_TABLE_VERSION, citation_policy_version=rules.CITATION_POLICY_VERSION,
            gated_refs=tuple(normalize_ref(r) for r in refs), checks=checks)
    except Exception as exc:
        return Errored(Stage.PROVENANCE, "unexpected_exception", type(exc).__name__, calls())
    return Assessed(result=result, provenance=provenance)
