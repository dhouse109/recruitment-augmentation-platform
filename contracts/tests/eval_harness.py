"""TEST-ONLY conformance harness for D-004.12 evaluation cases.

This is test scaffolding, not an evaluation runner, not a baseline and not a
product component. It executes declared case steps against the EXISTING
reference validators, the MOCK source authority and chunk store
(``support.py``) and the in-memory review TEST DOUBLE (``review_double.py``),
then compares observations with the case's pinned expectations.

Everything it observes is evidence tier T2 (mock-level observed behavior). It
computes no eligibility (eligibility steps check hand-written labels), runs no
model, measures no latency or cost, and proves nothing about live Drupal
authorization, retrieval indexes, transactions or durable audit.

No hidden setup: a case's context contains only the shared base records, the
candidate-scoped records owned by ``scope.candidates`` in the pinned base
fixture layers, and the case-file records named in ``scope.include_records``.
The mock authority is seeded only from ``initial_state.authority`` and step
``authority_delta`` entries. The review double starts empty; verifications are
applied only by explicit ``verification_transition`` steps.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import support
from review_double import InMemoryReviewService, MockAuthenticator, MockAuthorizer
from rap_contracts.claims import CandidateClaim, ClaimVocabulary, ProgramParticipation
from rap_contracts.eligibility import (
    EligibilityContext,
    EligibilityResult,
    OpportunityRequirement,
    PolicySet,
    check_eligibility_result,
)
from rap_contracts.evaluation import (
    AuthorityOverride,
    CaseObservation,
    ContextValidationStep,
    DeniedChunk,
    EligibilitySupportStep,
    EvaluationCase,
    EvaluationDatasetManifest,
    ExpectedResult,
    ExpectedRuleOutcome,
    FixtureLayerPin,
    Measurement,
    MeasurementStatus,
    ObservationBasis,
    ObservedRecord,
    RecommendationCheckStep,
    RecordSetValidationStep,
    RetrievalAdmissionStep,
    ReviewCommandStep,
    SafetyDisposition,
    SafetyObservation,
    Split,
    StepObservation,
    StepRole,
    StepStatus,
    VerificationAcceptanceStep,
    VerificationTransitionStep,
    case_sha256,
    derive_case_outcome,
)
from rap_contracts.evidence import EvidenceRecord, RetrievalChunk, RetrievalRequest, admit_chunks, index_evidence
from rap_contracts.invariants import ContractRecordSet, ContractViolation, check_record_set
from rap_contracts.models import (
    AccessStatus,
    Application,
    Candidate,
    CandidateProfile,
    Opportunity,
    Program,
    SourceReference,
    SourceSystem,
    SourceSystemCapabilities,
    VersionStatus,
)
from rap_contracts.recommendation import (
    Recommendation,
    RecommendationContext,
    RecommendationStatus,
    VerificationResult,
    accept_verification,
    apply_verification,
    check_recommendation,
    index_eligibility_results,
    validate_recommendation_inputs,
)
from rap_contracts.review import AuthenticatedPrincipal, OutcomeStatus, ReviewerGrant, ReviewReasonVocabulary
from rap_contracts.source_checks import canonical_json_sha256

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures"
LAYER_FILES = ("foundations-v0.2.0-dev.json", "eligibility-evidence-v0.2.0-dev.json", "review-v0.2.0-dev.json")
SPLIT_FILES = {Split.GOLDEN: "evaluation-golden-v0.2.0-dev.json", Split.HELD_OUT: "evaluation-nominal-held-out-v0.2.0-dev.json"}
DEFINITIONS_FILE = "evaluation-definitions-v0.2.0-dev.json"
#: Proposed draft definitions v2 (F4, PR-A). Not the default: DEFINITIONS_FILE (v1) remains the harness default.
DEFINITIONS_V2_FILE = "evaluation-definitions-v2-v0.2.0-dev.json"
#: F3 (RAP-F3-PLAN-2026-11-04 rev. 1.1): golden v2 (g002/g008 separated) and the definitions file whose draft
#: safety-gate policy v3 pins it (metrics v1). Not the defaults: SPLIT_FILES and DEFINITIONS_FILE remain v1.
GOLDEN_V2_FILE = "evaluation-golden-v2-v0.2.0-dev.json"
DEFINITIONS_GOLDEN_V2_FILE = "evaluation-definitions-golden-v2-v0.2.0-dev.json"
#: Proposed draft reviewer rubric v2 (F4, PR-B). Rubric v1 in both definitions files is unchanged.
RUBRIC_V2_FILE = "evaluation-rubric-v2-v0.2.0-dev.json"

#: Candidate-scoped record kinds. Everything else in a context is shared base.
SCOPED_KINDS = ("candidates", "profiles", "applications", "evidence", "claims", "participations",
                "eligibility_results", "chunks", "recommendations", "verifications")


class HarnessError(Exception):
    """A case cannot be built as declared (scope, ownership or reference problem)."""


def load(name: str) -> dict[str, Any]:
    with (FIXTURE_DIR / name).open(encoding="utf-8") as fh:
        return json.load(fh)


def layer_pins() -> tuple[FixtureLayerPin, ...]:
    return tuple(FixtureLayerPin(name=n, sha256=canonical_json_sha256(load(n))) for n in LAYER_FILES)


def case_records_sha256(split_doc: dict[str, Any]) -> str:
    return canonical_json_sha256(split_doc["case_records"])


def split_doc(split: Split) -> dict[str, Any]:
    return load(SPLIT_FILES[split])


def cases_of(doc: dict[str, Any]) -> list[EvaluationCase]:
    return [EvaluationCase.model_validate(c) for c in doc["cases"]]


def manifest_of(doc: dict[str, Any]) -> EvaluationDatasetManifest:
    return EvaluationDatasetManifest.model_validate(doc["manifest"])


# ---------------------------------------------------------------------------
# Record pool and ownership
# ---------------------------------------------------------------------------


def base_pool() -> dict[str, Any]:
    """Every record from the three pinned base fixture layers, by kind (raw dicts)."""
    f, e, r = (load(n) for n in LAYER_FILES)
    extra = e["additional_records"]
    return {
        "candidates": f["candidates"] + extra["candidates"],
        "profiles": f["profiles"] + extra["profiles"],
        "applications": f["applications"] + extra["applications"],
        "programs": f["programs"],
        "opportunities": f["opportunities"],
        "policies": e["policies"],
        "requirements": e["requirements"],
        "vocabularies": e["vocabularies"],
        "evidence": e["evidence"],
        "claims": e["claims"],
        "participations": e["participations"],
        "eligibility_results": e["eligibility_results"],
        "chunks": e["chunks"],
        "chunk_store": dict(e["chunk_store"]),
        "recommendations": r["recommendations"],
        "verifications": r["verifications"],
        "reason_vocabularies": r["reason_vocabularies"],
        "principals": r["mock_principals"],
        "capabilities": e["capabilities"],
    }


def owner_of(kind: str, record: dict[str, Any], pool: dict[str, Any], extra: dict[str, Any] | None = None) -> str | None:
    """Owning candidate of a record, or None for shared base. Derived from the record graph, not declared."""
    extra = extra or {}
    if kind == "candidates":
        return record["id"]
    if kind in ("profiles", "applications", "claims", "participations", "eligibility_results", "recommendations"):
        return record["candidate_id"]
    if kind == "evidence":
        return record["subject"]["id"] if record["subject"]["kind"] == "candidate" else None
    if kind == "verifications":
        recs = pool["recommendations"] + extra.get("recommendations", [])
        rec = next((r for r in recs if r["id"] == record["recommendation_id"]), None)
        if rec is None:
            raise HarnessError(f"verification {record['id']} references an unknown recommendation")
        return rec["candidate_id"]
    if kind == "chunks":
        sources = pool["profiles"] + pool["applications"] + extra.get("profiles", []) + extra.get("applications", [])
        src = next((s for s in sources if s["source_ref"]["entity"] == record["source_ref"]["entity"]
                    and s["organization_id"] == record["organization_id"]), None)
        if src is None:
            raise HarnessError(f"chunk {record['id']} has no owning profile/application")
        return src["candidate_id"]
    return None


def all_owned_ids(doc_records: dict[str, Any], pool: dict[str, Any]) -> dict[str, str]:
    """record id -> owning candidate for every candidate-scoped record in a case_records section."""
    out: dict[str, str] = {}
    for kind in SCOPED_KINDS:
        for rec in doc_records.get(kind, []):
            out[rec["id"]] = owner_of(kind, rec, pool, doc_records)
    return out


# ---------------------------------------------------------------------------
# Scoped context
# ---------------------------------------------------------------------------


@dataclass
class Scoped:
    records: ContractRecordSet
    eligibility: EligibilityContext
    context: RecommendationContext
    results: dict[str, EligibilityResult]
    recommendations: dict[str, Recommendation]
    verifications: dict[str, VerificationResult]
    chunks: dict[str, RetrievalChunk]
    chunk_store: dict[str, str]
    capabilities: dict[SourceSystem, SourceSystemCapabilities]
    principals: list[dict[str, Any]]
    reason_vocabularies: list[ReviewReasonVocabulary]
    loaded_ids: set[str] = field(default_factory=set)


def build_scope(case: EvaluationCase, doc: dict[str, Any], pool: dict[str, Any] | None = None) -> Scoped:
    pool = pool if pool is not None else base_pool()
    extra = doc.get("case_records", {})
    cands = set(case.scope.candidates)
    chosen: dict[str, list[dict[str, Any]]] = {}
    for kind in SCOPED_KINDS:
        chosen[kind] = [r for r in pool[kind] if owner_of(kind, r, pool) in cands]
    wanted = list(case.scope.include_records)
    for rid in wanted:
        hits = [(k, r) for k in SCOPED_KINDS for r in extra.get(k, []) if r["id"] == rid]
        if len(hits) != 1:
            raise HarnessError(f"{case.id}: include_records {rid} must name exactly one case record")
        kind, rec = hits[0]
        if owner_of(kind, rec, pool, extra) not in cands:
            raise HarnessError(f"{case.id}: {rid} is not owned by a candidate in scope")
        chosen[kind].append(rec)
    store = {k: v for k, v in pool["chunk_store"].items()}
    store.update(extra.get("chunk_store", {}))
    chunk_pointers = {c["text_pointer"] for c in chosen["chunks"]}
    store = {k: v for k, v in store.items() if k in chunk_pointers}

    records = ContractRecordSet(
        candidates=tuple(Candidate.model_validate(r) for r in chosen["candidates"]),
        profiles=tuple(CandidateProfile.model_validate(r) for r in chosen["profiles"]),
        programs=tuple(Program.model_validate(r) for r in pool["programs"]),
        opportunities=tuple(Opportunity.model_validate(r) for r in pool["opportunities"]),
        applications=tuple(Application.model_validate(r) for r in chosen["applications"]),
    )
    shared_evidence = [e for e in pool["evidence"] if owner_of("evidence", e, pool) is None]
    eligibility = EligibilityContext(
        records=records,
        policies=tuple(PolicySet.model_validate(r) for r in pool["policies"]),
        requirements=tuple(OpportunityRequirement.model_validate(r) for r in pool["requirements"]),
        claims=tuple(CandidateClaim.model_validate(r) for r in chosen["claims"]),
        participations=tuple(ProgramParticipation.model_validate(r) for r in chosen["participations"]),
        evidence=index_evidence(EvidenceRecord.model_validate(r) for r in chosen["evidence"] + shared_evidence),
        vocabularies=tuple(ClaimVocabulary.model_validate(r) for r in pool["vocabularies"]),
    )
    results = index_eligibility_results(EligibilityResult.model_validate(r) for r in chosen["eligibility_results"])
    capabilities = {c.source_system: c for c in (SourceSystemCapabilities.model_validate(x) for x in pool["capabilities"])}
    loaded = {r["id"] for k in SCOPED_KINDS for r in chosen[k]}
    return Scoped(
        records=records,
        eligibility=eligibility,
        context=RecommendationContext(eligibility=eligibility, eligibility_results=results, capabilities=capabilities),
        results=results,
        recommendations={r["id"]: Recommendation.model_validate(r) for r in chosen["recommendations"]},
        verifications={v["id"]: VerificationResult.model_validate(v) for v in chosen["verifications"]},
        chunks={c["id"]: RetrievalChunk.model_validate(c) for c in chosen["chunks"]},
        chunk_store=store,
        capabilities=capabilities,
        principals=pool["principals"],
        reason_vocabularies=[ReviewReasonVocabulary.model_validate(v) for v in pool["reason_vocabularies"]],
        loaded_ids=loaded,
    )


def scope_source_refs(s: Scoped) -> set[SourceReference]:
    refs: set[SourceReference] = set()
    for rec in s.records.profiles + s.records.applications + s.records.opportunities + s.records.programs:
        refs.add(rec.source_ref)
    refs |= {e.source_ref for e in s.eligibility.evidence.values()}
    refs |= {r.source_ref for r in s.eligibility.requirements} | {p.source_ref for p in s.eligibility.policies}
    refs |= {c.source_ref for c in s.chunks.values()}
    return refs


def build_authority(case: EvaluationCase, s: Scoped) -> support.FixtureSourceAuthority:
    authority = support.FixtureSourceAuthority()
    refs = scope_source_refs(s)
    for principal in case.initial_state.authority.principals:
        for ref in refs:
            authority.set(principal, ref, VersionStatus.CURRENT, AccessStatus.ALLOWED)
    apply_overrides(authority, case.initial_state.authority.overrides)
    return authority


def apply_overrides(authority: support.FixtureSourceAuthority, overrides: tuple[AuthorityOverride, ...]) -> None:
    for o in overrides:
        authority.set(o.principal_id, o.source_ref, o.version_status, o.access_status)


def build_review_store(s: Scoped, authority) -> InMemoryReviewService:
    principals, grants = {}, {}
    for p in s.principals:
        principals[p["credential"]] = AuthenticatedPrincipal(
            principal_id=p["principal"], kind=p["kind"], authenticated_by="mock-authenticator/0",
            authenticated_at=support.REVIEW_PRINCIPAL_AUTHENTICATED_AT)
        grants[p["principal"]] = tuple(ReviewerGrant.model_validate(g) for g in p["grants"])
    return InMemoryReviewService(
        authenticator=MockAuthenticator(principals), authorizer=MockAuthorizer(grants), authority=authority,
        context=s.context, recommendations=list(s.recommendations.values()), verifications=[],
        reason_vocabularies=s.reason_vocabularies)


# ---------------------------------------------------------------------------
# Step execution
# ---------------------------------------------------------------------------


def _snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()[:64]


def _validation(fn, *args) -> ObservedRecord:
    try:
        fn(*args)
    except ContractViolation as exc:
        return ObservedRecord(result=ExpectedResult.VIOLATION, violation_code=exc.code)
    return ObservedRecord(result=ExpectedResult.ACCEPTED)


BASIS = {
    "record_set_validation": ObservationBasis.REFERENCE_VALIDATOR,
    "context_validation": ObservationBasis.REFERENCE_VALIDATOR,
    "eligibility_support": ObservationBasis.REFERENCE_VALIDATOR,
    "recommendation_check": ObservationBasis.REFERENCE_VALIDATOR,
    "verification_acceptance": ObservationBasis.REFERENCE_VALIDATOR,
    "retrieval_admission": ObservationBasis.MOCK_AUTHORITY,
    "review_command": ObservationBasis.IN_MEMORY_DOUBLE,
}


def basis_of(step) -> ObservationBasis:
    if isinstance(step, VerificationTransitionStep):
        return ObservationBasis.IN_MEMORY_DOUBLE if step.via == "review_store" else ObservationBasis.REFERENCE_VALIDATOR
    return BASIS[step.operation]


@dataclass
class RunState:
    scope: Scoped
    authority: support.FixtureSourceAuthority
    store: InMemoryReviewService | None
    observed: dict[str, ObservedRecord] = field(default_factory=dict)


def execute(step, st: RunState) -> ObservedRecord:
    s = st.scope
    if isinstance(step, RecordSetValidationStep):
        return _validation(check_record_set, s.records)
    if isinstance(step, ContextValidationStep):
        return _validation(validate_recommendation_inputs, s.context)
    if isinstance(step, EligibilitySupportStep):
        result = s.results[step.eligibility_result_id]
        obs = _validation(check_eligibility_result, result, s.eligibility)
        rules = tuple(ExpectedRuleOutcome(rule_id=o.rule_id, result=o.result, reason_code=o.reason_code)
                      for o in result.rule_outcomes)
        return obs.model_copy(update={"decision": result.decision, "rule_outcomes": rules})
    if isinstance(step, RecommendationCheckStep):
        return _validation(check_recommendation, s.recommendations[step.recommendation_id], s.context)
    if isinstance(step, VerificationAcceptanceStep):
        return _validation(accept_verification, s.verifications[step.verification_id],
                           s.recommendations[step.recommendation_id], s.context)
    if isinstance(step, VerificationTransitionStep):
        ver = s.verifications[step.verification_id]
        if ver.recommendation_id != step.recommendation_id:
            raise HarnessError(f"{step.step_id}: verification is for another recommendation")
        if step.via == "review_store":
            return ObservedRecord(status_after=st.store.record_verification(ver).status)
        return ObservedRecord(status_after=apply_verification(s.recommendations[step.recommendation_id], ver, s.context).status)
    if isinstance(step, RetrievalAdmissionStep):
        request = RetrievalRequest(organization_id=step.organization_id, purpose=step.purpose, chunk_ids=step.chunk_ids)
        calls_before = len(st.authority.calls)
        chunk_store = support.FixtureChunkStore(s.chunk_store)
        outcome = admit_chunks(request, s.chunks, st.authority, chunk_store, step.principal_id, s.capabilities)
        return ObservedRecord(
            admitted_chunk_ids=tuple(a.chunk_id for a in outcome.admitted),
            denied=tuple(DeniedChunk(chunk_id=d.chunk_id, code=d.code) for d in outcome.denied),
            authority_calls=len(st.authority.calls) - calls_before,
            content_loads=len(chunk_store.loads))
    if isinstance(step, ReviewCommandStep):
        svc = st.store
        decisions, events, rejections = len(svc.decisions), len(svc.events), len(svc.rejection_log)
        outcome = svc.submit_review(step.credential, step.command)
        internal = svc.rejection_log[-1][0] if len(svc.rejection_log) > rejections else None
        return ObservedRecord(
            review_outcome=outcome.status, external_code=outcome.error, internal_code=internal,
            status_after=outcome.decision.recommendation_status_after if outcome.decision else None,
            decision_id=outcome.decision.id if outcome.decision else None,
            decisions_delta=len(svc.decisions) - decisions, events_delta=len(svc.events) - events)
    raise HarnessError(f"unsupported step {type(step).__name__}")


def matches(step, obs: ObservedRecord, st: RunState) -> bool:
    exp = step.expected
    if isinstance(step, (RecordSetValidationStep, ContextValidationStep, RecommendationCheckStep, VerificationAcceptanceStep)):
        return (obs.result, obs.violation_code) == (exp.result, exp.violation_code)
    if isinstance(step, EligibilitySupportStep):
        key = lambda r: r.rule_id  # noqa: E731
        return ((obs.result, obs.violation_code, obs.decision) == (exp.result, exp.violation_code, exp.decision)
                and sorted(obs.rule_outcomes, key=key) == sorted(exp.rule_outcomes, key=key))
    if isinstance(step, VerificationTransitionStep):
        return obs.status_after is exp.status_after
    if isinstance(step, RetrievalAdmissionStep):
        return (sorted(obs.admitted_chunk_ids) == sorted(exp.admitted_chunk_ids)
                and {(d.chunk_id, d.code) for d in obs.denied} == {(d.chunk_id, d.code) for d in exp.denied}
                and len(obs.denied) == len(exp.denied)
                and (obs.authority_calls, obs.content_loads) == (exp.authority_calls, exp.content_loads))
    if isinstance(step, ReviewCommandStep):
        same = True
        if exp.same_decision_as is not None:
            prior = st.observed.get(exp.same_decision_as)
            same = prior is not None and prior.decision_id is not None and prior.decision_id == obs.decision_id
        return (same and (obs.review_outcome, obs.external_code, obs.internal_code) == (exp.outcome, exp.external_code, exp.internal_code)
                and obs.status_after == exp.status_after
                and (obs.decisions_delta, obs.events_delta) == (exp.decisions_delta, exp.events_delta))
    raise HarnessError(f"unsupported step {type(step).__name__}")


def forbidden_effect(step, obs: ObservedRecord) -> bool:
    """Did the step produce the effect its safety expectation exists to prevent?"""
    exp = step.expected
    if isinstance(step, RetrievalAdmissionStep):
        return any(d.chunk_id in obs.admitted_chunk_ids for d in exp.denied)
    if isinstance(step, (RecordSetValidationStep, ContextValidationStep, RecommendationCheckStep, VerificationAcceptanceStep)):
        return exp.result is ExpectedResult.VIOLATION and obs.result is ExpectedResult.ACCEPTED
    if isinstance(step, VerificationTransitionStep):
        reviewable = (RecommendationStatus.READY_FOR_REVIEW, RecommendationStatus.APPROVED_FOR_FOLLOW_UP)
        return exp.status_after not in reviewable and obs.status_after in reviewable
    if isinstance(step, ReviewCommandStep):
        return exp.outcome is not OutcomeStatus.RECORDED and bool(obs.decisions_delta)
    return False


def safety_of(step, obs: ObservedRecord | None, errored: bool) -> tuple[SafetyObservation, ...]:
    out = []
    for exp in step.safety:
        if exp.disposition == "not_observable":
            disposition = SafetyDisposition.NOT_OBSERVABLE
        elif errored or obs is None:
            disposition = SafetyDisposition.NOT_EXERCISED
        elif forbidden_effect(step, obs):
            disposition = SafetyDisposition.UNBLOCKED_VIOLATION
        else:
            disposition = SafetyDisposition.ATTEMPT_BLOCKED
        out.append(SafetyObservation(category=exp.category, exposure_point=exp.exposure_point, disposition=disposition))
    return tuple(out)


@dataclass
class CaseRun:
    observation: CaseObservation
    observed: dict[str, ObservedRecord]
    scope: Scoped
    store: InMemoryReviewService | None


NOT_MEASURED_LATENCY = Measurement(status=MeasurementStatus.NOT_MEASURED, unit="milliseconds")
NO_INFERENCE_COST = Measurement(status=MeasurementStatus.NOT_APPLICABLE, unit="usd")


def run_case(case: EvaluationCase, doc: dict[str, Any], run_id: str = "evalrun_conformance_local",
             scope: Scoped | None = None, authority=None) -> CaseRun:
    s = scope if scope is not None else build_scope(case, doc)
    authority = authority if authority is not None else build_authority(case, s)
    store = build_review_store(s, authority) if case.initial_state.review_store == "empty" else None
    st = RunState(scope=s, authority=authority, store=store)
    status_by_step: dict[str, StepStatus] = {}
    halted = False
    steps: list[StepObservation] = []
    for step in case.steps:
        skip = halted or (step.role is StepRole.CONSEQUENCE and status_by_step.get(step.consequence_of) is not StepStatus.MATCHED)
        if skip:
            status_by_step[step.step_id] = StepStatus.NOT_EVALUATED
            steps.append(StepObservation(step_id=step.step_id, role=step.role, operation=step.operation,
                                         status=StepStatus.NOT_EVALUATED, basis=basis_of(step)))
            continue
        apply_overrides(authority, step.authority_delta)
        errored = False
        try:
            obs = execute(step, st)
            status = StepStatus.MATCHED if matches(step, obs, st) else StepStatus.MISMATCHED
        except (KeyError, HarnessError, ContractViolation) as exc:
            obs, status, errored = ObservedRecord(error_type=_snake(type(exc).__name__)), StepStatus.ERRORED, True
        st.observed[step.step_id] = obs
        status_by_step[step.step_id] = status
        steps.append(StepObservation(step_id=step.step_id, role=step.role, operation=step.operation, status=status,
                                     basis=basis_of(step), observed=obs, safety=safety_of(step, obs, errored)))
        if step.role in (StepRole.PREREQUISITE, StepRole.CONTROL) and status is not StepStatus.MATCHED:
            halted = True
    assertions_hold = None
    if case.assertions:
        assertions_hold = all(len(store.events) == a.equals for a in case.assertions) if not halted else False
    observation = CaseObservation(
        run_id=run_id, case_id=case.id, case_version=case.version, case_sha256=case_sha256(case), split=case.split,
        execution_status="executed", steps=tuple(steps), assertions_hold=assertions_hold,
        outcome=derive_case_outcome(steps, assertions_hold), latency=NOT_MEASURED_LATENCY, cost=NO_INFERENCE_COST)
    return CaseRun(observation=observation, observed=st.observed, scope=s, store=store)


def describe(run: CaseRun) -> str:
    """Human-readable mismatch report for test failure messages."""
    lines = [f"{run.observation.case_id}: {run.observation.outcome.value}"]
    for step in run.observation.steps:
        if step.status is not StepStatus.MATCHED:
            lines.append(f"  {step.step_id} [{step.role.value}/{step.operation.value}] {step.status.value}: "
                         f"{step.observed.model_dump(exclude_defaults=True) if step.observed else '-'}")
    return "\n".join(lines)
