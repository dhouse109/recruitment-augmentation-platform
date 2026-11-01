"""Phase 2, execution: the per-step workflow of plan section 2.1.

For each selected ``eligibility_support`` step (evidence tier T3):

1. the request is built from the admitted label KEY only (no label content);
2. ``rap_baseline.assess`` GENERATES a result from the admitted scope;
3. ``check_eligibility_result`` validates the GENERATED result against the full
   admitted scope (the step's own operation);
4. the generated result is compared with the step's PROPOSED expectation.

``Refused`` and ``Errored`` produce no result: the step is ``errored`` with
``engine_refused`` / ``engine_errored`` and the internal stage and code go to the
sidecar. g025's ``context_validation`` prerequisite runs on the reference
validator (basis ``reference_validator``, T2) over the same label-free admitted
context the engine receives. A match means agreement with a proposed,
unadjudicated label -- never reviewed correctness.

Any exception that is not an engine outcome is a runner failure (exit 4).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Callable, Mapping

from rap_baseline import Assessed, EligibilityRequest, Errored, Refused, assess
from rap_baseline.explanation import artifact_canonical as explanation_canonical
from rap_baseline.findings import artifact_canonical as findings_canonical
from rap_baseline.identity import canonical, utc_text
from rap_contracts.eligibility import EligibilityResult, check_eligibility_result
from rap_contracts.evaluation import (
    CaseObservation,
    CaseOutcome,
    EligibilitySupportStep,
    EvaluationCase,
    ExpectedResult,
    ExpectedRuleOutcome,
    Measurement,
    MeasurementStatus,
    ObservationBasis,
    ObservedRecord,
    StepObservation,
    StepRole,
    StepStatus,
    case_sha256,
    derive_case_outcome,
)
from rap_contracts.invariants import ContractViolation
from rap_contracts.recommendation import RecommendationContext, validate_recommendation_inputs

from . import RunnerFailure
from .authority import FixtureMockAuthority
from .scope import AdmittedScope, LabelKey

NOT_MEASURED_LATENCY = Measurement(status=MeasurementStatus.NOT_MEASURED, unit="milliseconds")
NO_INFERENCE_COST = Measurement(status=MeasurementStatus.NOT_APPLICABLE, unit="usd")

ENGINE_BASIS = ObservationBasis.DETERMINISTIC_BASELINE_EXECUTION
VALIDATOR_BASIS = ObservationBasis.REFERENCE_VALIDATOR

WORKFLOW = "assess(key) -> check_eligibility_result(generated) -> compare(proposed label)"


def result_json(result: EligibilityResult) -> str:
    """The generated result's exact bytes as stored in the sidecar (canonical JSON text)."""
    return canonical_json_text(result.model_dump(mode="json"))


def canonical_json_text(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _wall() -> str:
    return utc_text(datetime.now(timezone.utc))


def validate_result(result: EligibilityResult, scope: AdmittedScope) -> tuple[ExpectedResult, str | None]:
    """Step 3: the contract validator on the GENERATED result, against the full admitted scope."""
    try:
        check_eligibility_result(result, scope.eligibility)
    except ContractViolation as exc:
        return ExpectedResult.VIOLATION, exc.code
    return ExpectedResult.ACCEPTED, None


def rule_view(result: EligibilityResult) -> tuple[ExpectedRuleOutcome, ...]:
    return tuple(ExpectedRuleOutcome(rule_id=o.rule_id, result=o.result, reason_code=o.reason_code)
                 for o in result.rule_outcomes)


def compare(step: EligibilitySupportStep, observed: ObservedRecord) -> bool:
    """Step 4: agreement with the step's proposed expectation (result, code, decision, sorted rule outcomes)."""
    exp = step.expected
    key = lambda r: r.rule_id  # noqa: E731
    return ((observed.result, observed.violation_code, observed.decision) == (exp.result, exp.violation_code, exp.decision)
            and sorted(observed.rule_outcomes, key=key) == sorted(exp.rule_outcomes, key=key))


@dataclass
class SidecarEntry:
    """One engine invocation, bound to (case, step). Runner-local; not a contract."""

    case_id: str
    step_id: str
    key: LabelKey
    principal_id: str
    as_of: datetime
    outcome: str  # assessed | refused | errored
    result: EligibilityResult | None = None
    provenance: dict | None = None
    findings: dict | None = None
    explanation: dict | None = None
    refusal: dict | None = None
    started_at: str = ""
    ended_at: str = ""

    def to_json(self) -> dict:
        r = self.result
        return {
            "case_id": self.case_id,
            "step_id": self.step_id,
            "evidence": {"tier": "T3", "basis": ENGINE_BASIS.value, "workflow": WORKFLOW,
                         "label_status": "proposed, not adjudicated: agreement is not reviewed correctness"},
            "label_key": self.key.canonical(),
            "request": {"principal_id": self.principal_id, "as_of": utc_text(self.as_of)},
            "outcome": self.outcome,
            "result_json": result_json(r) if r is not None else None,
            "result_id": r.id if r is not None else None,
            "input_fingerprint": self.provenance["input_fingerprint"] if self.provenance else None,
            "output_digest": self.provenance["output_digest"] if self.provenance else None,
            "provenance": self.provenance,
            "citations": ([{"rule_id": o.rule_id, "claim_ids": list(o.claim_ids),
                            "participation_ids": list(o.participation_ids), "requirement_ids": list(o.requirement_ids)}
                           for o in r.rule_outcomes] if r is not None else None),
            "citations_evaluated": False,
            "findings": self.findings,
            "explanation": self.explanation,
            "refusal": self.refusal,
            "wall_clock": {"started_at": self.started_at, "ended_at": self.ended_at},
        }


@dataclass
class CaseExecution:
    observation: CaseObservation
    entries: list[SidecarEntry]


def validate_context(scope: AdmittedScope) -> ObservedRecord:
    try:
        validate_recommendation_inputs(RecommendationContext(
            eligibility=scope.eligibility, eligibility_results=MappingProxyType({}), capabilities=scope.capabilities))
    except ContractViolation as exc:
        return ObservedRecord(result=ExpectedResult.VIOLATION, violation_code=exc.code)
    return ObservedRecord(result=ExpectedResult.ACCEPTED)


def _engine_step(case: EvaluationCase, step: EligibilitySupportStep, scope: AdmittedScope, key: LabelKey,
                 principal: str, as_of: datetime, authority: FixtureMockAuthority,
                 assess_fn: Callable) -> tuple[ObservedRecord, StepStatus, SidecarEntry]:
    request = EligibilityRequest(organization_id=key.organization_id, candidate_id=key.candidate_id,
                                 opportunity_id=key.opportunity_id, policy=key.policy, principal_id=principal, as_of=as_of)
    entry = SidecarEntry(case_id=case.id, step_id=step.step_id, key=key, principal_id=principal, as_of=as_of,
                         outcome="", started_at=_wall())
    outcome = assess_fn(request, scope.eligibility, authority, scope.capabilities)
    entry.ended_at = _wall()
    if isinstance(outcome, Assessed):
        result = outcome.result
        verdict, code = validate_result(result, scope)
        observed = ObservedRecord(eligibility_result_id=result.id, result=verdict, violation_code=code,
                                  decision=result.decision, rule_outcomes=rule_view(result))
        entry.outcome, entry.result = "assessed", result
        entry.provenance = outcome.provenance.canonical()
        entry.findings = {"findings_id": outcome.findings.findings_id, "content_digest": outcome.findings.content_digest,
                          "artifact": findings_canonical(outcome.findings)}
        entry.explanation = {"explanation_id": outcome.explanation.explanation_id,
                             "content_digest": outcome.explanation.explanation_content_digest,
                             "artifact": explanation_canonical(outcome.explanation)}
        return observed, (StepStatus.MATCHED if compare(step, observed) else StepStatus.MISMATCHED), entry
    if isinstance(outcome, (Refused, Errored)):
        kind = "refused" if isinstance(outcome, Refused) else "errored"
        entry.outcome = kind
        entry.refusal = {"stage": outcome.stage.value, "code": outcome.code, "authority_calls": outcome.authority_calls}
        return ObservedRecord(error_type=f"engine_{kind}"), StepStatus.ERRORED, entry
    raise RunnerFailure("unexpected_engine_outcome", type(outcome).__name__)


def execute_case(case: EvaluationCase, scope: AdmittedScope, keys: Mapping[tuple[str, str], LabelKey],
                 principal: str, as_of: datetime, run_id: str, assess_fn: Callable | None = None) -> CaseExecution:
    assess_fn = assess if assess_fn is None else assess_fn
    authority = FixtureMockAuthority([principal], scope.source_refs, as_of)
    authority.apply(case.initial_state.authority.overrides)
    steps: list[StepObservation] = []
    entries: list[SidecarEntry] = []
    halted = False
    for step in case.steps:
        basis = ENGINE_BASIS if step.operation == "eligibility_support" else VALIDATOR_BASIS
        if halted:
            steps.append(StepObservation(step_id=step.step_id, role=step.role, operation=step.operation,
                                         status=StepStatus.NOT_EVALUATED, basis=basis))
            continue
        authority.apply(step.authority_delta)
        if step.operation == "eligibility_support":
            observed, status, entry = _engine_step(case, step, scope, keys[(case.id, step.step_id)], principal, as_of,
                                                   authority, assess_fn)
            entries.append(entry)
        elif step.operation == "context_validation":
            observed = validate_context(scope)
            exp = step.expected
            status = (StepStatus.MATCHED if (observed.result, observed.violation_code) == (exp.result, exp.violation_code)
                      else StepStatus.MISMATCHED)
        else:
            raise RunnerFailure("unsupported_operation", f"{case.id}/{step.step_id}")
        steps.append(StepObservation(step_id=step.step_id, role=step.role, operation=step.operation, status=status,
                                     basis=basis, observed=observed))
        if step.role in (StepRole.PREREQUISITE, StepRole.CONTROL) and status is not StepStatus.MATCHED:
            halted = True
    observation = CaseObservation(
        run_id=run_id, case_id=case.id, case_version=case.version, case_sha256=case_sha256(case), split=case.split,
        execution_status="executed", steps=tuple(steps), assertions_hold=None,
        outcome=derive_case_outcome(steps, None), latency=NOT_MEASURED_LATENCY, cost=NO_INFERENCE_COST)
    return CaseExecution(observation=observation, entries=entries)


def not_run(case: EvaluationCase, run_id: str) -> CaseObservation:
    return CaseObservation(run_id=run_id, case_id=case.id, case_version=case.version, case_sha256=case_sha256(case),
                           split=case.split, execution_status="not_run", outcome=CaseOutcome.NOT_EVALUATED,
                           latency=NOT_MEASURED_LATENCY, cost=NO_INFERENCE_COST)


def check_in_run_consistency(entries: list[SidecarEntry]) -> int:
    """Invocations sharing a key (and principal, as_of) must produce byte-identical results. Returns distinct count."""
    seen: dict[tuple, tuple] = {}
    for e in entries:
        k = (e.key.assessment(), e.principal_id, utc_text(e.as_of))
        produced = (e.outcome, result_json(e.result) if e.result is not None else None,
                    canonical(e.refusal) if e.refusal else None)
        if k in seen and seen[k] != produced:
            raise RunnerFailure("in_run_inconsistency", f"{e.case_id}/{e.step_id}")
        seen.setdefault(k, produced)
    return len(seen)
