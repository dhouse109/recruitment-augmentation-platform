"""Evaluation cases, dataset manifests, runs and observations -- D-004.12 / ADR-0003.

Contract v0.2 (partial, development, NOT frozen). Added in 0.2.0-dev.foundations.4.

These contracts describe *what* an evaluation case expects and *how* a run and
its observations must be recorded. They do not run anything, they do not
compute eligibility, and they establish no measured quality, latency, cost or
safety result. In particular:

* Expected labels in an ``EvaluationCase`` are authored, version-pinned
  statements. Observations never rewrite them.
* A ``fixture_conformance`` run (evidence tier T2) only shows that hand-written
  labels agree with the reference validators on synthetic data. It is not a
  deterministic baseline (T3) and not integrated safety evidence (T4).
* ``RecordAttribution`` fields are structural metadata. ``asserted_kind="human"``
  does not authenticate anyone; only a future trusted service can attest that.
* A manifest's custody and held-out integrity fields are declarations. The
  validators here enforce internal consistency only. A declared
  ``custodied_unexposed`` status is not proof of custody (see promotion.py).
* Exposure-log entries are records of known exposures. A file cannot prove the
  log is complete, append-only or durable.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Iterable, Literal, Union

from pydantic import AwareDatetime, ConfigDict, Field, model_validator

from .eligibility import EligibilityDecision, EligibilityId, RuleId, RuleResult
from .evidence import ChunkId, DenialCode, RetrievalPurpose
from .invariants import ContractViolation
from .models import (
    _ID_BODY,
    AccessStatus,
    CandidateId,
    ComponentId,
    ContractModel,
    OrganizationId,
    SourceReference,
    VersionStatus,
)
from .recommendation import RecommendationId, RecommendationStatus, VerificationId
from .review import DecisionId, ExternalCode, HumanReviewCommand, OutcomeStatus, PrincipalId, RoleLabel
from .source_checks import canonical_json_sha256

# ---------------------------------------------------------------------------
# Identifiers and small value types
# ---------------------------------------------------------------------------


def _eval_id(prefix: str, what: str) -> object:
    return Field(pattern=rf"^{prefix}_{_ID_BODY}$", max_length=64, description=f"Opaque synthetic {what} identifier.")


EvaluationCaseId = Annotated[str, _eval_id("evalcase", "evaluation case")]
DatasetManifestId = Annotated[str, _eval_id("evalset", "evaluation dataset manifest")]
EvaluationRunId = Annotated[str, _eval_id("evalrun", "evaluation run")]
DefinitionsId = Annotated[str, _eval_id("evaldefs", "evaluation definitions set")]
StepId = Annotated[str, Field(pattern=r"^s[0-9]{1,2}$")]
RecordId = Annotated[str, Field(pattern=r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$", max_length=64)]
Code = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
Sha256 = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
LegacyLabel = Annotated[str, Field(pattern=r"^EVAL-[GH][0-9]{3}$", description="Seed label in RAP-EVAL-001 v0.1.0.")]
DecisionRef = Annotated[str, Field(pattern=r"^D-00[1-4](\.(0[1-9]|1[0-2]))?$")]
PilotTestRef = Annotated[str, Field(pattern=r"^PILOT-T0[0-9]{2}$")]
MockCredential = Annotated[
    str, Field(pattern=r"^credential-[a-z0-9]+(-[a-z0-9]+)*$", max_length=64,
               description="Fictional mock credential for the in-memory review test double. Not a secret.")
]
ShortText = Annotated[str, Field(min_length=1, max_length=300, pattern=r"^[^\r\n]*$")]


def content_sha256(record: ContractModel) -> str:
    """``sha256-canonical-json/v1`` over the record's JSON form."""
    return canonical_json_sha256(record.model_dump(mode="json"))


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class Split(str, Enum):
    GOLDEN = "golden"
    HELD_OUT = "held_out"


class Custody(str, Enum):
    REPOSITORY_VISIBLE = "repository_visible"
    EXTERNAL_ACCESS_CONTROLLED = "external_access_controlled"


class HeldOutIntegrity(str, Enum):
    """Declared status. ``custodied_unexposed`` is a claim until a trusted custodian attests it."""

    NOT_APPLICABLE = "not_applicable"  # golden datasets
    NOMINAL_EXPOSED = "nominal_exposed"  # demonstration held-out; labels known to be exposed
    CUSTODIED_UNEXPOSED = "custodied_unexposed"  # declared external custody


class EvidenceTier(str, Enum):
    T1_SCHEMA_VALIDATION = "t1_schema_validation"
    T2_MOCK_OBSERVED = "t2_mock_observed"
    T3_OFFLINE_MEASURED = "t3_offline_measured"
    T4_INTEGRATED = "t4_integrated"


class ObservationBasis(str, Enum):
    SCHEMA_VALIDATION = "schema_validation"
    REFERENCE_VALIDATOR = "reference_validator"
    MOCK_AUTHORITY = "mock_authority"
    IN_MEMORY_DOUBLE = "in_memory_double"
    DETERMINISTIC_BASELINE_EXECUTION = "deterministic_baseline_execution"
    OFFLINE_MODEL_EXECUTION = "offline_model_execution"
    INTEGRATED_SERVICE = "integrated_service"
    LIVE_SYSTEM = "live_system"


BASIS_TIER: dict[ObservationBasis, EvidenceTier] = {
    ObservationBasis.SCHEMA_VALIDATION: EvidenceTier.T1_SCHEMA_VALIDATION,
    ObservationBasis.REFERENCE_VALIDATOR: EvidenceTier.T2_MOCK_OBSERVED,
    ObservationBasis.MOCK_AUTHORITY: EvidenceTier.T2_MOCK_OBSERVED,
    ObservationBasis.IN_MEMORY_DOUBLE: EvidenceTier.T2_MOCK_OBSERVED,
    ObservationBasis.DETERMINISTIC_BASELINE_EXECUTION: EvidenceTier.T3_OFFLINE_MEASURED,
    ObservationBasis.OFFLINE_MODEL_EXECUTION: EvidenceTier.T3_OFFLINE_MEASURED,
    ObservationBasis.INTEGRATED_SERVICE: EvidenceTier.T4_INTEGRATED,
    ObservationBasis.LIVE_SYSTEM: EvidenceTier.T4_INTEGRATED,
}


class Operation(str, Enum):
    RECORD_SET_VALIDATION = "record_set_validation"
    CONTEXT_VALIDATION = "context_validation"
    ELIGIBILITY_SUPPORT = "eligibility_support"
    RECOMMENDATION_CHECK = "recommendation_check"
    VERIFICATION_ACCEPTANCE = "verification_acceptance"
    VERIFICATION_TRANSITION = "verification_transition"
    RETRIEVAL_ADMISSION = "retrieval_admission"
    REVIEW_COMMAND = "review_command"


class StepRole(str, Enum):
    PREREQUISITE = "prerequisite"
    CONTROL = "control"
    TARGET = "target"
    CONSEQUENCE = "consequence"


class LabelClass(str, Enum):
    OBJECTIVE_RULE_DERIVED = "objective_rule_derived"
    SUBJECTIVE = "subjective"


class LabelReviewStatus(str, Enum):
    PROPOSED = "proposed"
    OWNER_REVIEWED = "owner_reviewed"
    ADJUDICATED = "adjudicated"


class CaseAdjudicationStatus(str, Enum):
    NOT_ADJUDICATED = "not_adjudicated"
    ADJUDICATED = "adjudicated"
    DISPUTED = "disputed"
    UNRESOLVED = "unresolved"


class SafetyCategory(str, Enum):
    CROSS_ORG_ACCESS = "cross_org_access"
    UNAUTHORIZED_SOURCE_ACCESS = "unauthorized_source_access"
    STALE_OR_WITHDRAWN_SOURCE = "stale_or_withdrawn_source"
    HARD_ELIGIBILITY_VIOLATION = "hard_eligibility_violation"
    CRITICAL_UNSUPPORTED_CLAIM = "critical_unsupported_claim"
    UNAUTHORIZED_REVIEW_WRITE = "unauthorized_review_write"
    PROHIBITED_REVIEW_TRANSITION = "prohibited_review_transition"
    SOURCE_CONTENT_INTEGRITY = "source_content_integrity"
    PROMPT_INJECTION_COMPLIANCE = "prompt_injection_compliance"


class ExposurePoint(str, Enum):
    MODEL_CONTEXT = "model_context"
    REVIEWER_DISPLAY = "reviewer_display"
    RECOMMENDATION_OUTPUT = "recommendation_output"
    REVIEW_WRITE = "review_write"
    RECORD_LINKAGE = "record_linkage"


class SafetyDisposition(str, Enum):
    ATTEMPT_BLOCKED = "attempt_blocked"  # exercised and stopped before the exposure point
    UNBLOCKED_VIOLATION = "unblocked_violation"  # the forbidden effect was observed
    NOT_EXERCISED = "not_exercised"  # the attempt did not happen (coverage failure, not a pass)
    NOT_OBSERVABLE = "not_observable"  # the harness cannot see the exposure point


# ---------------------------------------------------------------------------
# Attribution (structural metadata only)
# ---------------------------------------------------------------------------


class AttestationBasis(str, Enum):
    """How the attribution was established. Only a future trusted service may issue the last value."""

    UNVERIFIED_METADATA = "unverified_metadata"
    MOCK_AUTHENTICATED = "mock_authenticated"
    TRUSTED_SERVICE_AUTHENTICATED = "trusted_service_authenticated"


class RecordAttribution(ContractModel):
    """Who a record says acted. ``asserted_*`` fields are claims, not authentication or authorization.

    A Pydantic model cannot verify ``attestation_basis``. A value of
    ``trusted_service_authenticated`` is meaningful only when written by the
    future evaluation-record service (``promotion.EvaluationRecordService``),
    which must authenticate the principal and check an explicit role grant.
    """

    principal_id: PrincipalId
    asserted_kind: Literal["human", "service"]
    asserted_role: RoleLabel | None = None
    attestation_basis: AttestationBasis


# ---------------------------------------------------------------------------
# Expectations
# ---------------------------------------------------------------------------


class ExpectedResult(str, Enum):
    ACCEPTED = "accepted"
    VIOLATION = "violation"


class ValidationExpectation(ContractModel):
    """Outcome of a validator that either returns or raises a named ``ContractViolation``."""

    result: ExpectedResult
    violation_code: Code | None = None

    @model_validator(mode="after")
    def _code(self) -> "ValidationExpectation":
        if (self.result is ExpectedResult.VIOLATION) != (self.violation_code is not None):
            raise ValueError("violation_code is required for, and only for, an expected violation")
        return self


class ExpectedRuleOutcome(ContractModel):
    rule_id: RuleId
    result: RuleResult
    reason_code: Code


class EligibilitySupportExpectation(ValidationExpectation):
    """Expected validator result plus the label's decision and EVERY rule outcome (rule-level labels)."""

    decision: EligibilityDecision
    rule_outcomes: Annotated[tuple[ExpectedRuleOutcome, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def _rules(self) -> "EligibilitySupportExpectation":
        ids = [r.rule_id for r in self.rule_outcomes]
        if len(ids) != len(set(ids)):
            raise ValueError("each rule appears once")
        return self


class TransitionExpectation(ContractModel):
    status_after: RecommendationStatus


class DeniedChunk(ContractModel):
    chunk_id: ChunkId
    code: DenialCode


class RetrievalExpectation(ContractModel):
    """Internal admission outcome. Denial codes are internal; callers never see them."""

    admitted_chunk_ids: tuple[ChunkId, ...] = ()
    denied: tuple[DeniedChunk, ...] = ()
    authority_calls: Annotated[int, Field(ge=0)]
    content_loads: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def _disjoint(self) -> "RetrievalExpectation":
        denied = [d.chunk_id for d in self.denied]
        if set(denied) & set(self.admitted_chunk_ids) or len(denied) != len(set(denied)):
            raise ValueError("a chunk is either admitted or denied once")
        return self


class ReviewExpectation(ContractModel):
    outcome: OutcomeStatus
    external_code: ExternalCode | None = None
    internal_code: Code | None = None
    status_after: RecommendationStatus | None = None
    decisions_delta: Annotated[int, Field(ge=0, le=1)]
    events_delta: Annotated[int, Field(ge=0, le=1)]
    same_decision_as: StepId | None = None

    @model_validator(mode="after")
    def _shape(self) -> "ReviewExpectation":
        if self.outcome is OutcomeStatus.REJECTED:
            if self.external_code is None or self.internal_code is None:
                raise ValueError("a rejection expectation names both the external and internal code")
            if self.decisions_delta or self.events_delta or self.status_after or self.same_decision_as:
                raise ValueError("a rejection writes nothing")
        else:
            if self.external_code is not None or self.internal_code is not None:
                raise ValueError("only rejections carry error codes")
        if self.outcome is OutcomeStatus.RECORDED and (self.decisions_delta, self.events_delta) != (1, 1):
            raise ValueError("a recorded outcome adds exactly one decision and one event")
        if self.outcome is OutcomeStatus.REPLAYED:
            if (self.decisions_delta, self.events_delta) != (0, 0) or self.same_decision_as is None:
                raise ValueError("a replay adds nothing and returns the decision of a named earlier step")
        return self


class SafetyExpectation(ContractModel):
    category: SafetyCategory
    exposure_point: ExposurePoint
    disposition: Literal["attempt_blocked", "not_observable"]


# ---------------------------------------------------------------------------
# Steps (discriminated by ``operation``)
# ---------------------------------------------------------------------------


class AuthorityOverride(ContractModel):
    """Declared MOCK authority answer for one (principal, exact source version)."""

    principal_id: PrincipalId
    source_ref: SourceReference
    version_status: VersionStatus
    access_status: AccessStatus


class _StepBase(ContractModel):
    step_id: StepId
    role: StepRole
    consequence_of: StepId | None = None
    state_from: tuple[StepId, ...] = ()
    authority_delta: tuple[AuthorityOverride, ...] = ()
    safety: tuple[SafetyExpectation, ...] = ()

    @model_validator(mode="after")
    def _role(self) -> "_StepBase":
        if (self.role is StepRole.CONSEQUENCE) != (self.consequence_of is not None):
            raise ValueError("consequence_of is required for, and only for, consequence steps")
        if self.safety and self.role not in (StepRole.TARGET, StepRole.CONSEQUENCE):
            raise ValueError("safety expectations belong on target or consequence steps")
        return self


class RecordSetValidationStep(_StepBase):
    """``invariants.check_record_set`` over the case's scoped records."""

    operation: Literal["record_set_validation"]
    expected: ValidationExpectation


class ContextValidationStep(_StepBase):
    """``recommendation.validate_recommendation_inputs`` over the case's scoped context."""

    operation: Literal["context_validation"]
    expected: ValidationExpectation


class EligibilitySupportStep(_StepBase):
    """``eligibility.check_eligibility_result`` on one assessment key, compared with the expected label.

    The step names a hand-written expected result (``eligibility_result_id``); its key is the label's
    organization, candidate, opportunity and policy pin. The observation basis says what was checked.
    At T2 (``reference_validator``) the validator checks the hand-written result itself; no engine runs.
    At T3 (``deterministic_baseline_execution``) the deterministic baseline first generates a result for
    the label's key, the same validator then checks that generated result, and its decision and rule
    outcomes are compared with the label; the observation names the generated result
    (``ObservedRecord.eligibility_result_id``). Agreement with a label is not reviewed correctness.
    """

    operation: Literal["eligibility_support"]
    eligibility_result_id: EligibilityId
    expected: EligibilitySupportExpectation


class RecommendationCheckStep(_StepBase):
    """``recommendation.check_recommendation``."""

    operation: Literal["recommendation_check"]
    recommendation_id: RecommendationId
    expected: ValidationExpectation


class VerificationAcceptanceStep(_StepBase):
    """``recommendation.accept_verification`` (recomputes substance; raises a named violation)."""

    operation: Literal["verification_acceptance"]
    verification_id: VerificationId
    recommendation_id: RecommendationId
    expected: ValidationExpectation


class VerificationTransitionStep(_StepBase):
    """``recommendation.apply_verification``; via ``review_store`` it is applied inside the case's review double."""

    operation: Literal["verification_transition"]
    verification_id: VerificationId
    recommendation_id: RecommendationId
    via: Literal["detached", "review_store"]
    expected: TransitionExpectation


class RetrievalAdmissionStep(_StepBase):
    """``evidence.admit_chunks`` against the MOCK authority and chunk store."""

    operation: Literal["retrieval_admission"]
    organization_id: OrganizationId
    purpose: RetrievalPurpose
    chunk_ids: Annotated[tuple[ChunkId, ...], Field(min_length=1)]
    principal_id: PrincipalId
    expected: RetrievalExpectation


class ReviewCommandStep(_StepBase):
    """``submit_review`` on the case's in-memory review TEST DOUBLE."""

    operation: Literal["review_command"]
    credential: MockCredential | None = None
    command: HumanReviewCommand
    expected: ReviewExpectation


CaseStep = Annotated[
    Union[
        RecordSetValidationStep,
        ContextValidationStep,
        EligibilitySupportStep,
        RecommendationCheckStep,
        VerificationAcceptanceStep,
        VerificationTransitionStep,
        RetrievalAdmissionStep,
        ReviewCommandStep,
    ],
    Field(discriminator="operation"),
]


def _touches_review_store(step: object) -> bool:
    return isinstance(step, ReviewCommandStep) or (
        isinstance(step, VerificationTransitionStep) and step.via == "review_store"
    )


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------


class LabelProvenance(ContractModel):
    origin: Literal["seed_proposal", "new_case"]
    origin_ref: ShortText
    authored_by: ComponentId
    review_status: LabelReviewStatus


class CaseScope(ContractModel):
    """Declared dependencies.

    The context contains the shared base records plus every candidate-scoped
    record owned by ``candidates`` in the pinned base fixture layers, plus the
    case-file records named in ``include_records``. Nothing else is loaded.
    """

    candidates: Annotated[tuple[CandidateId, ...], Field(min_length=1)]
    include_records: tuple[RecordId, ...] = ()

    @model_validator(mode="after")
    def _unique(self) -> "CaseScope":
        if len(set(self.candidates)) != len(self.candidates) or len(set(self.include_records)) != len(self.include_records):
            raise ValueError("scope entries must be unique")
        return self


class AuthorityState(ContractModel):
    """MOCK authority baseline: every source version in scope is current and allowed for ``principals``,
    except the declared ``overrides``. Any other (principal, version) pair fails closed."""

    baseline: Literal["scope_sources_current_and_allowed"]
    principals: Annotated[tuple[PrincipalId, ...], Field(min_length=1)]
    overrides: tuple[AuthorityOverride, ...] = ()


class InitialState(ContractModel):
    authority: AuthorityState
    review_store: Literal["none", "empty"] = "none"


class AuditEventTotalAssertion(ContractModel):
    kind: Literal["audit_event_total"]
    equals: Annotated[int, Field(ge=0)]


class EvaluationCase(ContractModel):
    """One versioned synthetic case: declared scope, initial state, ordered steps and expectations."""

    id: EvaluationCaseId
    version: Annotated[int, Field(ge=1)]
    legacy_label: LegacyLabel | None = None
    split: Split
    title: ShortText
    decision_refs: Annotated[tuple[DecisionRef, ...], Field(min_length=1)]
    pilot_test_refs: tuple[PilotTestRef, ...] = ()
    label_class: LabelClass
    provenance: LabelProvenance
    adjudication_status: CaseAdjudicationStatus
    scope: CaseScope
    initial_state: InitialState
    steps: Annotated[tuple[CaseStep, ...], Field(min_length=1)]
    assertions: tuple[AuditEventTotalAssertion, ...] = ()

    @model_validator(mode="after")
    def _grammar(self) -> "EvaluationCase":
        seen: dict[str, object] = {}
        store_steps: list[str] = []
        for step in self.steps:
            if step.step_id in seen:
                raise ValueError(f"duplicate step id {step.step_id}")
            if step.consequence_of is not None:
                target = seen.get(step.consequence_of)
                if target is None or target.role is not StepRole.TARGET:
                    raise ValueError(f"{step.step_id}: consequence_of must name an earlier target step")
            for ref in step.state_from:
                if ref not in seen:
                    raise ValueError(f"{step.step_id}: state_from must reference earlier steps")
            if _touches_review_store(step):
                if self.initial_state.review_store != "empty":
                    raise ValueError(f"{step.step_id}: review-store steps require initial_state.review_store='empty'")
                if isinstance(step, ReviewCommandStep) and set(store_steps) - set(step.state_from):
                    raise ValueError(f"{step.step_id}: state_from must list every earlier review-store step (no implicit state)")
            if isinstance(step, ReviewCommandStep) and step.expected.same_decision_as is not None:
                ref = step.expected.same_decision_as
                if not isinstance(seen.get(ref), ReviewCommandStep) or ref not in step.state_from:
                    raise ValueError(f"{step.step_id}: same_decision_as must name an earlier review step in state_from")
            seen[step.step_id] = step
            if _touches_review_store(step):
                store_steps.append(step.step_id)
        if not any(s.role is StepRole.TARGET for s in self.steps):
            raise ValueError("a case has at least one target step")
        if self.assertions and self.initial_state.review_store != "empty":
            raise ValueError("audit-event assertions require a review store")
        if (self.provenance.review_status is LabelReviewStatus.ADJUDICATED) != (
            self.adjudication_status is CaseAdjudicationStatus.ADJUDICATED
        ):
            raise ValueError("a label is 'adjudicated' only with a matching adjudication status")
        if self.legacy_label is not None and self.legacy_label[5] != ("G" if self.split is Split.GOLDEN else "H"):
            raise ValueError("legacy label prefix must match the split")
        return self


def case_sha256(case: EvaluationCase) -> str:
    return content_sha256(case)


# ---------------------------------------------------------------------------
# Dataset manifests
# ---------------------------------------------------------------------------


class FixtureLayerPin(ContractModel):
    name: Annotated[str, Field(pattern=r"^[a-z0-9.-]+\.json$")]
    sha256: Sha256


class CasePin(ContractModel):
    case_id: EvaluationCaseId
    version: Annotated[int, Field(ge=1)]
    sha256: Sha256


class ExposureEntry(ContractModel):
    """A recorded known exposure. Not proof that the log is complete or durable."""

    recorded_at: AwareDatetime
    kind: Literal["published_in_repository", "visible_to_ai_session", "uploaded_to_project_knowledge", "other"]
    description: ShortText
    recorded_by: RecordAttribution


class EvaluationDatasetManifest(ContractModel):
    """Versioned split manifest.

    ``repository_visible`` manifests pin each case by content hash. Externally
    custodied manifests carry only salted commitments: no case IDs, labels or
    scenario details, and never the salt.
    """

    id: DatasetManifestId
    version: Annotated[int, Field(ge=1)]
    split: Split
    custody: Custody
    held_out_integrity: HeldOutIntegrity
    contract_version: Annotated[str, Field(pattern=r"^0\.2\.0-dev\.[a-z]+\.[0-9]+$")]
    data_policy: Literal["synthetic_only"]
    fixture_layers: tuple[FixtureLayerPin, ...] = ()
    case_records_sha256: Sha256 | None = None
    case_pins: tuple[CasePin, ...] = ()
    commitments: tuple[Sha256, ...] = ()
    exposure_log: tuple[ExposureEntry, ...] = ()

    @model_validator(mode="after")
    def _custody(self) -> "EvaluationDatasetManifest":
        if self.split is Split.GOLDEN:
            if self.held_out_integrity is not HeldOutIntegrity.NOT_APPLICABLE or self.custody is not Custody.REPOSITORY_VISIBLE:
                raise ValueError("golden datasets are repository-visible and have no held-out integrity status")
        elif self.held_out_integrity is HeldOutIntegrity.NOT_APPLICABLE:
            raise ValueError("held-out datasets declare an integrity status")
        if self.custody is Custody.REPOSITORY_VISIBLE:
            if self.held_out_integrity is HeldOutIntegrity.CUSTODIED_UNEXPOSED:
                raise ValueError("a repository-visible dataset cannot be declared custodied and unexposed")
            if not self.case_pins or self.commitments:
                raise ValueError("repository-visible manifests pin cases, not commitments")
        else:
            if self.case_pins or self.case_records_sha256 is not None or not self.commitments:
                raise ValueError("externally custodied manifests carry only commitments")
        if self.held_out_integrity is HeldOutIntegrity.NOMINAL_EXPOSED and not self.exposure_log:
            raise ValueError("a nominal held-out dataset records its known exposures")
        ids = [p.case_id for p in self.case_pins]
        if len(ids) != len(set(ids)) or len(self.commitments) != len(set(self.commitments)):
            raise ValueError("case pins and commitments are unique")
        return self


def manifest_root(manifest: EvaluationDatasetManifest) -> str:
    """Content root over the manifest's identity and its case pins or commitments."""
    return canonical_json_sha256({
        "id": manifest.id,
        "version": manifest.version,
        "split": manifest.split.value,
        "fixture_layers": [p.model_dump(mode="json") for p in manifest.fixture_layers],
        "case_records_sha256": manifest.case_records_sha256,
        "case_pins": [p.model_dump(mode="json") for p in manifest.case_pins],
        "commitments": list(manifest.commitments),
    })


class ManifestPin(ContractModel):
    id: DatasetManifestId
    version: Annotated[int, Field(ge=1)]
    split: Split
    root: Sha256


def pin_manifest(manifest: EvaluationDatasetManifest) -> ManifestPin:
    return ManifestPin(id=manifest.id, version=manifest.version, split=manifest.split, root=manifest_root(manifest))


def check_manifest_cases(manifest: EvaluationDatasetManifest, cases: Iterable[EvaluationCase]) -> None:
    """The supplied cases are exactly the pinned ones, unmodified, and in the manifest's split."""
    cases = list(cases)
    pinned = {p.case_id: p for p in manifest.case_pins}
    if {c.id for c in cases} != set(pinned) or len(cases) != len(pinned):
        raise ContractViolation("manifest_case_set_mismatch", f"{manifest.id}: case set differs from the pinned set")
    for case in cases:
        pin = pinned[case.id]
        if case.split is not manifest.split:
            raise ContractViolation("manifest_split_mismatch", f"{case.id} is not in split {manifest.split.value}")
        if case.version != pin.version or case_sha256(case) != pin.sha256:
            raise ContractViolation("manifest_case_modified", f"{case.id} does not match its pinned content")


def check_partition(golden: Iterable[EvaluationCase], held_out: Iterable[EvaluationCase]) -> None:
    """Split-leakage check over declared scopes (fixture ownership is checked by the harness tests)."""
    golden, held_out = list(golden), list(held_out)
    if any(c.split is not Split.GOLDEN for c in golden) or any(c.split is not Split.HELD_OUT for c in held_out):
        raise ContractViolation("partition_split_mismatch", "cases supplied under the wrong split")
    if {c.id for c in golden} & {c.id for c in held_out}:
        raise ContractViolation("partition_case_overlap", "a case id appears in both splits")
    g_cands = {x for c in golden for x in c.scope.candidates}
    h_cands = {x for c in held_out for x in c.scope.candidates}
    if g_cands & h_cands:
        raise ContractViolation("partition_scope_overlap", f"candidates in both splits: {sorted(g_cands & h_cands)}")
    g_recs = {x for c in golden for x in c.scope.include_records}
    h_recs = {x for c in held_out for x in c.scope.include_records}
    if g_recs & h_recs:
        raise ContractViolation("partition_record_overlap", f"case records in both splits: {sorted(g_recs & h_recs)}")


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------


class RunKind(str, Enum):
    FIXTURE_CONFORMANCE = "fixture_conformance"  # T2: labels vs reference validators; not a baseline
    DETERMINISTIC_BASELINE = "deterministic_baseline"  # T3: future Slice 0 engine output
    SINGLE_MODEL = "single_model"  # T3: future offline model run
    MULTI_AGENT = "multi_agent"  # T3: future offline multi-agent run


RUN_KIND_TIER: dict[RunKind, EvidenceTier] = {
    RunKind.FIXTURE_CONFORMANCE: EvidenceTier.T2_MOCK_OBSERVED,
    RunKind.DETERMINISTIC_BASELINE: EvidenceTier.T3_OFFLINE_MEASURED,
    RunKind.SINGLE_MODEL: EvidenceTier.T3_OFFLINE_MEASURED,
    RunKind.MULTI_AGENT: EvidenceTier.T3_OFFLINE_MEASURED,
}


class RunPurpose(str, Enum):
    REGRESSION = "regression"
    TUNING = "tuning"
    MODEL_SELECTION = "model_selection"
    PROMOTION_ASSESSMENT = "promotion_assessment"


class OptionalPin(ContractModel):
    status: Literal["pinned", "not_applicable"]
    value: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/+-]{0,127}$")] | None = None

    @model_validator(mode="after")
    def _value(self) -> "OptionalPin":
        if (self.status == "pinned") != (self.value is not None):
            raise ValueError("a value is present only when pinned")
        return self


NOT_APPLICABLE = OptionalPin(status="not_applicable")


class CodeRevision(ContractModel):
    status: Literal["recorded", "unavailable"]
    commit: Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")] | None = None
    dirty: bool | None = None

    @model_validator(mode="after")
    def _recorded(self) -> "CodeRevision":
        if (self.status == "recorded") != (self.commit is not None and self.dirty is not None):
            raise ValueError("commit and dirty flag are present only when recorded")
        return self


class MeasurementStatus(str, Enum):
    OBSERVED = "observed"
    NOT_RUN = "not_run"
    NOT_MEASURED = "not_measured"
    NOT_APPLICABLE = "not_applicable"
    ERRORED = "errored"


class Measurement(ContractModel):
    """A value exists only when it was observed. No fabricated zeros."""

    status: MeasurementStatus
    unit: Literal["milliseconds", "usd", "count"]
    value: Annotated[float, Field(ge=0)] | None = None

    @model_validator(mode="after")
    def _value(self) -> "Measurement":
        if (self.status is MeasurementStatus.OBSERVED) != (self.value is not None):
            raise ValueError("a value is present if and only if the status is 'observed'")
        return self


class DefinitionsPin(ContractModel):
    id: DefinitionsId
    version: Annotated[int, Field(ge=1)]


class Component(str, Enum):
    """Generating components a strategy contains. Determines which outcome metrics can apply."""

    ELIGIBILITY = "eligibility"
    RECOMMENDATION = "recommendation"
    VERIFIER = "verifier"
    RETRIEVAL = "retrieval"
    MODEL = "model"


class StrategyPin(ContractModel):
    """Versioned identity of the implementation strategy under evaluation (not its run kind)."""

    id: Code
    version: Annotated[int, Field(ge=1)]
    components: frozenset[Component] = frozenset()


class ConfigurationPin(ContractModel):
    """Stable identity of a system configuration. ``fingerprint`` is recomputed, never trusted as declared."""

    id: Code
    fingerprint_version: Literal[1]
    fingerprint: Sha256


def fingerprint_configuration(
    *, run_kind: "RunKind", strategy: StrategyPin, code_revision: CodeRevision, contract_version: str,
    retrieval_index: OptionalPin, prompt: OptionalPin, model: OptionalPin, judge: OptionalPin,
) -> str:
    """``sha256-canonical-json/v1`` over the configuration-defining fields (fingerprint version 1).

    Included: run kind, strategy (id, version, sorted components), recorded clean
    code commit, contract version, and the retrieval-index, prompt, model and
    judge pins. Excluded (execution conditions, checked separately by
    ``promotion.check_comparable_runs``): source authority, replicate count,
    timestamps, purpose, manifests, metric definitions and safety policy.
    """
    if code_revision.status != "recorded" or code_revision.dirty:
        raise ContractViolation("configuration_requires_clean_revision", "a configuration needs a recorded, clean commit")
    return canonical_json_sha256({
        "fingerprint_version": 1,
        "run_kind": run_kind.value,
        "strategy": {"id": strategy.id, "version": strategy.version,
                     "components": sorted(c.value for c in strategy.components)},
        "code_commit": code_revision.commit,
        "contract_version": contract_version,
        "retrieval_index": retrieval_index.model_dump(mode="json"),
        "prompt": prompt.model_dump(mode="json"),
        "model": model.model_dump(mode="json"),
        "judge": judge.model_dump(mode="json"),
    })


def configuration_fingerprint(run: "EvaluationRun") -> str:
    return fingerprint_configuration(
        run_kind=run.run_kind, strategy=run.strategy, code_revision=run.code_revision,
        contract_version=run.contract_version, retrieval_index=run.retrieval_index, prompt=run.prompt,
        model=run.model, judge=run.judge)


class EvaluationRun(ContractModel):
    id: EvaluationRunId
    run_kind: RunKind
    purpose: RunPurpose
    manifests: Annotated[tuple[ManifestPin, ...], Field(min_length=1)]
    definitions: DefinitionsPin
    safety_policy: DefinitionsPin
    contract_version: Annotated[str, Field(pattern=r"^0\.2\.0-dev\.[a-z]+\.[0-9]+$")]
    code_revision: CodeRevision
    strategy: StrategyPin
    configuration: ConfigurationPin | None = None
    source_authority: Literal["fixture_mock", "drupal"]
    retrieval_index: OptionalPin
    prompt: OptionalPin
    model: OptionalPin
    judge: OptionalPin
    replicates: Annotated[int, Field(ge=1)]
    started_at: AwareDatetime
    completed_at: AwareDatetime | None = None
    status: Literal["completed", "partial", "failed", "aborted"]
    errors: tuple[Code, ...] = ()
    latency: Measurement
    cost: Measurement
    executed_by: ComponentId

    @model_validator(mode="after")
    def _pins(self) -> "EvaluationRun":
        no_model = self.run_kind in (RunKind.FIXTURE_CONFORMANCE, RunKind.DETERMINISTIC_BASELINE)
        model_pins = (self.prompt, self.model, self.judge)
        if no_model and any(p.status == "pinned" for p in model_pins):
            raise ValueError("no-model runs pin no prompt, model or judge")
        if not no_model and (self.prompt.status != "pinned" or self.model.status != "pinned"):
            raise ValueError("model runs pin their prompt and model")
        if no_model and self.cost.status is MeasurementStatus.OBSERVED:
            raise ValueError("no-model runs have no inference cost to observe")
        if self.run_kind is RunKind.FIXTURE_CONFORMANCE:
            if self.purpose is not RunPurpose.REGRESSION or self.source_authority != "fixture_mock":
                raise ValueError("fixture-conformance runs are regression runs against the fixture mock only")
        if self.purpose in (RunPurpose.TUNING, RunPurpose.MODEL_SELECTION) and any(m.split is Split.HELD_OUT for m in self.manifests):
            raise ValueError("tuning and model-selection runs may not reference held-out manifests")
        if self.purpose is RunPurpose.PROMOTION_ASSESSMENT:
            if self.code_revision.status != "recorded" or self.code_revision.dirty or self.status != "completed":
                raise ValueError("promotion-assessment runs are completed runs of a recorded, clean code revision")
        if len({m.id for m in self.manifests}) != len(self.manifests):
            raise ValueError("each manifest is pinned once")
        if self.completed_at is not None and self.completed_at < self.started_at:
            raise ValueError("completed_at precedes started_at")
        if (self.status == "completed") != (self.completed_at is not None):
            raise ValueError("completed_at is present only for completed runs")
        components = self.strategy.components
        if self.run_kind is RunKind.FIXTURE_CONFORMANCE:
            if components or self.configuration is not None:
                raise ValueError("fixture-conformance runs declare no generating components and no configuration")
        else:
            if not components:
                raise ValueError("generating runs declare their strategy components")
            if (Component.MODEL in components) != (not no_model):
                raise ValueError("model runs, and only model runs, include the model component")
            if self.configuration is None:
                raise ValueError("generating runs carry a configuration pin")
        if self.configuration is not None:
            try:
                expected = configuration_fingerprint(self)
            except ContractViolation as exc:
                raise ValueError(str(exc)) from None
            if self.configuration.fingerprint != expected:
                raise ValueError("configuration fingerprint does not match the run's own configuration fields")
        return self

    @property
    def evidence_tier(self) -> EvidenceTier:
        return RUN_KIND_TIER[self.run_kind]


# ---------------------------------------------------------------------------
# Observations
# ---------------------------------------------------------------------------


class StepStatus(str, Enum):
    MATCHED = "matched"
    MISMATCHED = "mismatched"
    NOT_EVALUATED = "not_evaluated"
    ERRORED = "errored"


class ObservedRecord(ContractModel):
    """What a step produced, as codes and identifiers only. Never source or chunk text.

    ``eligibility_result_id`` names the result a T3 ``deterministic_baseline_execution`` eligibility
    step generated and checked. Its presence is a structural rule (see ``StepObservation``); it does not
    prove that the result exists, was generated by a real execution, or matches this observation.
    """

    eligibility_result_id: EligibilityId | None = None
    result: ExpectedResult | None = None
    violation_code: Code | None = None
    decision: EligibilityDecision | None = None
    rule_outcomes: tuple[ExpectedRuleOutcome, ...] = ()
    status_after: RecommendationStatus | None = None
    admitted_chunk_ids: tuple[ChunkId, ...] = ()
    denied: tuple[DeniedChunk, ...] = ()
    authority_calls: Annotated[int, Field(ge=0)] | None = None
    content_loads: Annotated[int, Field(ge=0)] | None = None
    review_outcome: OutcomeStatus | None = None
    external_code: ExternalCode | None = None
    internal_code: Code | None = None
    decision_id: DecisionId | None = None
    decisions_delta: Annotated[int, Field(ge=0)] | None = None
    events_delta: Annotated[int, Field(ge=0)] | None = None
    error_type: Code | None = None


class SafetyObservation(ContractModel):
    category: SafetyCategory
    exposure_point: ExposurePoint
    disposition: SafetyDisposition


#: Portable subset of the generated-result binding rule (V5). Python enforces the same rule (V1, V2, V4).
_BINDING_SCHEMA = {
    "allOf": [{
        "if": {
            "properties": {"operation": {"const": "eligibility_support"},
                           "basis": {"const": "deterministic_baseline_execution"},
                           "status": {"enum": ["matched", "mismatched"]}},
            "required": ["operation", "basis", "status"],
        },
        "then": {
            "required": ["observed"],
            "properties": {"observed": {"type": "object", "required": ["eligibility_result_id"],
                                        "properties": {"eligibility_result_id": {"type": "string"}}}},
        },
        "else": {
            "properties": {"observed": {"anyOf": [
                {"type": "null"},
                {"properties": {"eligibility_result_id": {"type": "null"}}},
            ]}},
        },
    }],
}


class StepObservation(ContractModel):
    """One observed case step.

    Generated-result binding (0.2.0-dev.foundations.6), a STRUCTURAL rule only:

    * V1 -- an evaluated (``matched`` or ``mismatched``) ``eligibility_support`` step at basis
      ``deterministic_baseline_execution`` names the generated result in ``observed.eligibility_result_id``;
    * V2 -- an ``errored`` step at that basis names none (no result was generated);
    * V4 -- every other operation and every other basis, including other T3 bases such as
      ``offline_model_execution``, names none, so T2 reference-validator observations are unchanged;
    * V3 (unchanged) -- a ``not_evaluated`` step has no observation at all;
    * V5 -- V1, V2 and V4 are also expressed in the JSON Schema.

    Validation cannot see the case step, the label or any generated result. It therefore does NOT prove
    that the named result exists, was produced by a genuine engine execution, differs from the label, or
    produced this observation. That binding is the producer's obligation: the offline runner must
    cross-check each id against the engine-returned result, recompute its identity from the inputs and
    provenance, and must not trust a declared value.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, json_schema_extra=_BINDING_SCHEMA)

    step_id: StepId
    role: StepRole
    operation: Operation
    status: StepStatus
    basis: ObservationBasis
    observed: ObservedRecord | None = None
    safety: tuple[SafetyObservation, ...] = ()

    @model_validator(mode="after")
    def _evaluated(self) -> "StepObservation":
        if (self.status is StepStatus.NOT_EVALUATED) != (self.observed is None):
            raise ValueError("only not-evaluated steps lack an observation")
        if self.status is StepStatus.NOT_EVALUATED and self.safety:
            raise ValueError("a step that was not evaluated has no safety observation")
        generated = self.observed.eligibility_result_id if self.observed is not None else None
        bound = (self.operation is Operation.ELIGIBILITY_SUPPORT
                 and self.basis is ObservationBasis.DETERMINISTIC_BASELINE_EXECUTION)
        if bound and self.status in (StepStatus.MATCHED, StepStatus.MISMATCHED):
            if generated is None:
                raise ValueError("an evaluated deterministic-baseline eligibility step names its generated result")
        elif generated is not None:
            raise ValueError("eligibility_result_id is only for evaluated deterministic-baseline eligibility steps")
        return self


class CaseOutcome(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    INCONCLUSIVE = "inconclusive"
    NOT_EVALUATED = "not_evaluated"


def derive_case_outcome(steps: Iterable[StepObservation], assertions_hold: bool | None) -> CaseOutcome:
    """Prerequisite/control problems make a case inconclusive; target/consequence problems make it fail."""
    steps = list(steps)
    if any(s.role in (StepRole.PREREQUISITE, StepRole.CONTROL) and s.status is not StepStatus.MATCHED for s in steps):
        return CaseOutcome.INCONCLUSIVE
    if any(s.role in (StepRole.TARGET, StepRole.CONSEQUENCE) and s.status in (StepStatus.MISMATCHED, StepStatus.ERRORED)
           for s in steps):
        return CaseOutcome.FAIL
    if any(s.role is StepRole.TARGET and s.status is StepStatus.NOT_EVALUATED for s in steps):
        return CaseOutcome.INCONCLUSIVE
    if any(s.role is StepRole.CONSEQUENCE and s.status is StepStatus.NOT_EVALUATED for s in steps):
        return CaseOutcome.INCONCLUSIVE
    if assertions_hold is False:
        return CaseOutcome.FAIL
    return CaseOutcome.PASS


class CaseObservation(ContractModel):
    """Internal evaluation artifact. Holds internal denial/violation codes: never shown to callers or reviewers."""

    visibility: Literal["internal_only"] = "internal_only"
    run_id: EvaluationRunId
    case_id: EvaluationCaseId
    case_version: Annotated[int, Field(ge=1)]
    case_sha256: Sha256
    split: Split
    execution_status: Literal["executed", "not_run", "errored"]
    steps: tuple[StepObservation, ...] = ()
    assertions_hold: bool | None = None
    outcome: CaseOutcome
    latency: Measurement
    cost: Measurement

    @model_validator(mode="after")
    def _outcome(self) -> "CaseObservation":
        if self.execution_status == "executed":
            if not self.steps:
                raise ValueError("an executed case records its steps")
            if self.outcome is not derive_case_outcome(self.steps, self.assertions_hold):
                raise ValueError(f"outcome must be {derive_case_outcome(self.steps, self.assertions_hold).value}")
        else:
            if self.steps or self.assertions_hold is not None or self.outcome is not CaseOutcome.NOT_EVALUATED:
                raise ValueError("a case that did not execute has no steps and is not evaluated")
        ids = [s.step_id for s in self.steps]
        if len(ids) != len(set(ids)):
            raise ValueError("step observations are unique")
        return self
