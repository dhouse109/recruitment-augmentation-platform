"""Reviewer rubric, review items and adjudication records -- D-004.12 / ADR-0003 decision 8.

Contract v0.2 (partial, development, NOT frozen). Added in 0.2.0-dev.foundations.4;
adjudication integrity (F4 PR-B) in 0.2.0-dev.foundations.5.

Subjective expectations must be adjudicated by humans before any benchmark
performance is reported. These contracts define the *shape* of that process.
They adjudicate nothing, and no adjudication record is committed.

Owner decisions encoded here (``docs/evaluation/F4-definitions-decision-record.md``):

* B2 / E12 -- exactly two designated independent primary reviewers per rubric
  dimension; a direct final label when they agree; a distinct designated
  adjudicator only when they disagree; otherwise a counted ``disputed`` or
  ``unresolved`` result. No majority voting, no extra primaries.
* N1 / E7 -- ``third_reviewer`` is the only disagreement policy.
* E1-E3, E14 -- one record per *produced* output, attached through a stable
  review-item key that exists even when no output was produced.
* E10 -- N/A only for a reason the rubric grounds in a pinned expectation that
  the review item carries; omitted required information is scored, never N/A.
* E13 -- ``reportable`` is always ``False``: no caller-supplied metadata can make
  a record genuinely reportable until a trusted evaluation-record service exists.

What is caller-declared and therefore NOT established here: review-item
completeness, output slots and applicability expectations (``provenance:
caller_declared``); structural consistency with a pinned case identity does not
prove the expectations were derived from that case. ``RecordAttribution`` values,
reviewer roles and conflict registers are structural claims: a
``trusted_service_authenticated`` value written by a caller is not authentication,
a role assertion is not a role grant, and a register is not proof of
independence.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Iterable, Literal

from pydantic import AwareDatetime, Field, model_validator

from .evaluation import (
    AttestationBasis,
    Code,
    ConfigurationPin,
    EvaluationCaseId,
    EvaluationDatasetManifest,
    EvaluationRun,
    EvaluationRunId,
    MeasurementStatus,
    RecordAttribution,
    RecordId,
    Sha256,
    ShortText,
)
from .invariants import ContractViolation
from .models import _ID_BODY, ContractModel
from .promotion import DimensionReviewState, DistributionValue, MetricDefinition, UsefulnessCoverage
from .review import PrincipalId

RubricId = Annotated[str, Field(pattern=rf"^rubric_{_ID_BODY}$", max_length=64)]
AdjudicationId = Annotated[str, Field(pattern=rf"^adjudication_{_ID_BODY}$", max_length=64)]

#: Asserted roles required on reviewer attributions. Assertions are structural, not grants.
REVIEWER_ROLE = "evaluation_reviewer"
ADJUDICATOR_ROLE = "evaluation_adjudicator"


# ---------------------------------------------------------------------------
# Rubric
# ---------------------------------------------------------------------------


class ScaleAnchor(ContractModel):
    value: Annotated[int, Field(ge=0, le=10)]
    label: ShortText


class NotApplicableRule(ContractModel):
    """An allowed N/A reason, valid only when the review item carries ``requires_expectation`` (E10)."""

    reason: Code
    requires_expectation: Code


class RubricDimension(ContractModel):
    code: Code
    description: ShortText
    scale: Annotated[tuple[ScaleAnchor, ...], Field(min_length=2)]
    rationale_required_at_or_below: Annotated[int, Field(ge=0, le=10)] | None = None
    not_applicable_reasons: tuple[NotApplicableRule, ...] = ()  # empty: N/A is not permitted

    @model_validator(mode="after")
    def _scale(self) -> "RubricDimension":
        values = [a.value for a in self.scale]
        if values != sorted(set(values)):
            raise ValueError("scale anchors are unique and ascending")
        reasons = [r.reason for r in self.not_applicable_reasons]
        if len(reasons) != len(set(reasons)):
            raise ValueError("N/A reasons are unique per dimension")
        return self


class DisagreementPolicy(str, Enum):
    THIRD_REVIEWER = "third_reviewer"  # N1: the only policy; recorded discussion is not a resolution


class ReviewerRubric(ContractModel):
    """Versioned rubric. A draft rubric is a proposal until the owner approves it."""

    id: RubricId
    version: Annotated[int, Field(ge=1)]
    status: Literal["draft", "approved"]
    dimensions: Annotated[tuple[RubricDimension, ...], Field(min_length=1)]
    min_independent_reviewers: Literal[2]  # E12: exactly two designated primaries per dimension
    disagreement_policy: DisagreementPolicy

    @model_validator(mode="after")
    def _unique(self) -> "ReviewerRubric":
        codes = [d.code for d in self.dimensions]
        if len(codes) != len(set(codes)):
            raise ValueError("dimension codes are unique")
        return self

    def dimension(self, code: str) -> RubricDimension | None:
        return next((d for d in self.dimensions if d.code == code), None)


class RubricPin(ContractModel):
    rubric_id: RubricId
    version: Annotated[int, Field(ge=1)]


# ---------------------------------------------------------------------------
# Review items (caller-declared in this contract version)
# ---------------------------------------------------------------------------


class ReviewItemKey(ContractModel):
    """Stable identity of one expected output position, whether or not an output was produced.

    ``output_slot`` names a position fixed by the case (not by what a run produced),
    so that several outputs of one case and replicate stay distinct and baseline and
    candidate items align. ``replicate`` is identity only: replicate observations
    are not part of this contract version.
    """

    run_id: EvaluationRunId
    case_id: EvaluationCaseId
    case_version: Annotated[int, Field(ge=1)]
    case_sha256: Sha256
    replicate: Annotated[int, Field(ge=1)]
    output_slot: Code


class ProducedOutputRef(ContractModel):
    output_id: RecordId
    output_kind: Code


PresenceCategory = Literal["produced_expected", "produced_unexpected", "missing", "correctly_absent",
                           "generation_failed"]


class ReviewItem(ContractModel):
    """One review item. ``produced_output`` is required exactly when an output was produced.

    ``provenance`` can only be ``caller_declared``: item completeness, output slots
    and applicability expectations are not derived from pinned cases or trusted
    observations in this contract version.
    """

    key: ReviewItemKey
    expected_presence: Literal["expected", "not_expected"]
    output_status: Literal["produced", "absent", "generation_failed"]
    produced_output: ProducedOutputRef | None = None
    applicability_expectations: frozenset[Code] = frozenset()
    provenance: Literal["caller_declared"] = "caller_declared"

    @model_validator(mode="after")
    def _output(self) -> "ReviewItem":
        if (self.output_status == "produced") != (self.produced_output is not None):
            raise ValueError("a produced output reference is present exactly when an output was produced")
        return self

    @property
    def presence(self) -> PresenceCategory:
        if self.output_status == "generation_failed":
            return "generation_failed"
        if self.output_status == "produced":
            return "produced_expected" if self.expected_presence == "expected" else "produced_unexpected"
        return "missing" if self.expected_presence == "expected" else "correctly_absent"


def _index_items(items: Iterable[ReviewItem]) -> dict[ReviewItemKey, ReviewItem]:
    """Unique item keys, and no produced output counted through more than one slot of a run."""
    by_key: dict[ReviewItemKey, ReviewItem] = {}
    outputs: set[tuple[str, str]] = set()
    for item in items:
        if item.key in by_key:
            raise ContractViolation("duplicate_review_item", f"{item.key.case_id}/{item.key.output_slot} appears twice")
        by_key[item.key] = item
        if item.produced_output is not None:
            ref = (item.key.run_id, item.produced_output.output_id)
            if ref in outputs:
                raise ContractViolation("duplicate_produced_output",
                                        f"{item.produced_output.output_id} is referenced by more than one item")
            outputs.add(ref)
    return by_key


def check_review_items(items: Iterable[ReviewItem], run: EvaluationRun, manifest: EvaluationDatasetManifest) -> None:
    """Items are unique, belong to ``run``, name a case pinned by ``manifest`` and a replicate the run declared.

    This is structural consistency only: it does not show that the item set is
    complete or that slots and expectations were derived from the pinned case.
    """
    items = list(items)
    _index_items(items)
    pins = {p.case_id: p for p in manifest.case_pins}
    for item in items:
        key = item.key
        if key.run_id != run.id:
            raise ContractViolation("review_item_run_mismatch", f"{key.case_id}/{key.output_slot} is not from {run.id}")
        pin = pins.get(key.case_id)
        if pin is None or (pin.version, pin.sha256) != (key.case_version, key.case_sha256):
            raise ContractViolation("review_item_case_mismatch", f"{key.case_id} v{key.case_version} is not pinned")
        if key.replicate > run.replicates:
            raise ContractViolation("review_item_replicate_out_of_range",
                                    f"replicate {key.replicate} exceeds the run's {run.replicates}")


# ---------------------------------------------------------------------------
# Labels, per-dimension results and the adjudication record
# ---------------------------------------------------------------------------


class ReviewSubject(ContractModel):
    """The produced output an adjudication record judges."""

    item: ReviewItemKey
    output_id: RecordId


class ReviewRole(str, Enum):
    PRIMARY = "primary"
    ADJUDICATOR = "adjudicator"


_ASSERTED_ROLE = {ReviewRole.PRIMARY: REVIEWER_ROLE, ReviewRole.ADJUDICATOR: ADJUDICATOR_ROLE}


class RawLabel(ContractModel):
    """One reviewer's judgment on one dimension: a scale value, or N/A with a reason (never both)."""

    reviewer: RecordAttribution
    role: ReviewRole
    dimension: Code
    applicability: Literal["scored", "not_applicable"]
    value: Annotated[int, Field(ge=0, le=10)] | None = None
    not_applicable_reason: Code | None = None
    rationale: ShortText | None = None
    labeled_at: AwareDatetime

    @model_validator(mode="after")
    def _shape(self) -> "RawLabel":
        if self.reviewer.asserted_kind != "human":
            raise ValueError("raw labels are human judgments; a model or service cannot be a reviewer")
        if self.reviewer.asserted_role != _ASSERTED_ROLE[self.role]:
            raise ValueError(f"a {self.role.value} label asserts the role {_ASSERTED_ROLE[self.role]}")
        if self.applicability == "scored" and (self.value is None or self.not_applicable_reason is not None):
            raise ValueError("a scored label carries a value and no N/A reason")
        if self.applicability == "not_applicable" and (self.value is not None or self.not_applicable_reason is None):
            raise ValueError("an N/A label carries a reason and no value")
        if self.applicability == "not_applicable" and self.rationale is None:
            raise ValueError("an N/A label explains why")
        if self.role is ReviewRole.ADJUDICATOR and self.rationale is None:
            raise ValueError("an adjudicator's resolution is reasoned")
        return self


class Resolution(str, Enum):
    SCORED = "scored"
    NOT_APPLICABLE = "not_applicable"
    DISPUTED = "disputed"  # the two primaries disagree and no adjudicator label resolves it
    UNRESOLVED = "unresolved"  # a designated primary label is missing


class Derivation(str, Enum):
    UNANIMOUS = "unanimous"
    ADJUDICATOR_RESOLUTION = "adjudicator_resolution"
    NONE = "none"


class DimensionResult(ContractModel):
    """The derived result for one dimension. Recomputed from the raw labels, never trusted as declared."""

    dimension: Code
    resolution: Resolution
    value: Annotated[int, Field(ge=0, le=10)] | None = None
    not_applicable_reason: Code | None = None
    derivation: Derivation

    @model_validator(mode="after")
    def _shape(self) -> "DimensionResult":
        resolved = self.resolution in (Resolution.SCORED, Resolution.NOT_APPLICABLE)
        if resolved == (self.derivation is Derivation.NONE):
            raise ValueError("resolved results name their derivation; unresolved and disputed ones have none")
        if (self.resolution is Resolution.SCORED) != (self.value is not None):
            raise ValueError("only scored results carry a value")
        if (self.resolution is Resolution.NOT_APPLICABLE) != (self.not_applicable_reason is not None):
            raise ValueError("only N/A results carry an N/A reason")
        return self


def _same_judgment(a: RawLabel, b: RawLabel) -> bool:
    return (a.applicability, a.value, a.not_applicable_reason) == (b.applicability, b.value, b.not_applicable_reason)


def _resolved_from(dimension: str, label: RawLabel, derivation: Derivation) -> DimensionResult:
    if label.applicability == "scored":
        return DimensionResult(dimension=dimension, resolution=Resolution.SCORED, value=label.value, derivation=derivation)
    return DimensionResult(dimension=dimension, resolution=Resolution.NOT_APPLICABLE,
                           not_applicable_reason=label.not_applicable_reason, derivation=derivation)


def derive_dimension_result(dimension: str, labels: Iterable[RawLabel], primaries: tuple[str, str]) -> DimensionResult:
    """B2 / E4 / E5 / E12. Unanimous primaries resolve directly (N/A requires the same reason); a
    disagreement is resolved only by the adjudicator's own label; a missing primary leaves it unresolved.

    Raises ``ValueError`` for an adjudicator label that resolves nothing (an unauthorized resolution).
    """
    labels = [label for label in labels if label.dimension == dimension]
    primary = {label.reviewer.principal_id: label for label in labels if label.role is ReviewRole.PRIMARY}
    adjudicator = [label for label in labels if label.role is ReviewRole.ADJUDICATOR]
    if set(primary) != set(primaries):
        if adjudicator:
            raise ValueError(f"{dimension}: an adjudicator cannot resolve a dimension missing a primary label")
        return DimensionResult(dimension=dimension, resolution=Resolution.UNRESOLVED, derivation=Derivation.NONE)
    first, second = primary[primaries[0]], primary[primaries[1]]
    if _same_judgment(first, second):
        if adjudicator:
            raise ValueError(f"{dimension}: an adjudicator label is not permitted when the primaries agree")
        return _resolved_from(dimension, first, Derivation.UNANIMOUS)
    if adjudicator:
        return _resolved_from(dimension, adjudicator[0], Derivation.ADJUDICATOR_RESOLUTION)
    return DimensionResult(dimension=dimension, resolution=Resolution.DISPUTED, derivation=Derivation.NONE)


class AdjudicationStatus(str, Enum):
    ADJUDICATED = "adjudicated"  # every dimension resolved (scored or N/A)
    DISPUTED = "disputed"  # at least one dimension disputed
    UNRESOLVED = "unresolved"  # otherwise, at least one dimension unresolved


def derive_status(results: Iterable[DimensionResult]) -> AdjudicationStatus:
    resolutions = {r.resolution for r in results}
    if Resolution.DISPUTED in resolutions:
        return AdjudicationStatus.DISPUTED
    if Resolution.UNRESOLVED in resolutions:
        return AdjudicationStatus.UNRESOLVED
    return AdjudicationStatus.ADJUDICATED


class AdjudicationRecord(ContractModel):
    """Adjudication of one produced output. Raw labels are retained; results and status are recomputed.

    ``primary_reviewers`` and ``adjudicator`` are designations recorded with the
    record. They are structural claims: whether those principals hold the asserted
    roles, are independent of the configuration and labels, and are who they claim
    to be can only be established by a future trusted evaluation-record service.
    """

    id: AdjudicationId
    subject: ReviewSubject
    rubric: RubricPin
    primary_reviewers: Annotated[tuple[PrincipalId, ...], Field(min_length=2, max_length=2)]
    adjudicator: PrincipalId | None = None
    raw_labels: Annotated[tuple[RawLabel, ...], Field(min_length=1)]
    dimension_results: Annotated[tuple[DimensionResult, ...], Field(min_length=1)]
    status: AdjudicationStatus
    resolution_note: ShortText | None = None
    supersedes: AdjudicationId | None = None
    recorded_at: AwareDatetime
    recorded_by: RecordAttribution

    @model_validator(mode="after")
    def _consistency(self) -> "AdjudicationRecord":
        first, second = self.primary_reviewers
        if first == second:
            raise ValueError("the two designated primary reviewers are distinct")
        if self.adjudicator is not None and self.adjudicator in self.primary_reviewers:
            raise ValueError("the adjudicator is distinct from both primary reviewers")
        if self.recorded_by.asserted_kind != "human":
            raise ValueError("adjudication is recorded by a human")
        seen = set()
        for label in self.raw_labels:
            pid = label.reviewer.principal_id
            if label.role is ReviewRole.PRIMARY and pid not in self.primary_reviewers:
                raise ValueError(f"{pid} is not a designated primary reviewer (no extra primaries, no majority)")
            if label.role is ReviewRole.ADJUDICATOR and pid != self.adjudicator:
                raise ValueError(f"{pid} is not the designated adjudicator")
            if (pid, label.dimension) in seen:
                raise ValueError("one raw label per reviewer and dimension")
            seen.add((pid, label.dimension))
        results = {r.dimension: r for r in self.dimension_results}
        if len(results) != len(self.dimension_results):
            raise ValueError("one result per dimension")
        if {label.dimension for label in self.raw_labels} - set(results):
            raise ValueError("every labelled dimension has a result")
        for dimension, declared in results.items():
            derived = derive_dimension_result(dimension, self.raw_labels, (first, second))
            if declared != derived:
                raise ValueError(f"{dimension}: the declared result does not follow from the raw labels")
        if self.status is not derive_status(self.dimension_results):
            raise ValueError(f"status must be {derive_status(self.dimension_results).value}")
        if self.status is not AdjudicationStatus.ADJUDICATED and self.resolution_note is None:
            raise ValueError("disputed or unresolved records explain why")
        if self.supersedes == self.id:
            raise ValueError("a record cannot supersede itself")
        return self

    @property
    def labelling_principals(self) -> frozenset[str]:
        return frozenset(label.reviewer.principal_id for label in self.raw_labels)


def check_adjudication(record: AdjudicationRecord, rubric: ReviewerRubric) -> None:
    """The record uses the pinned rubric, covers every rubric dimension, and respects its scales,
    N/A reasons and rationale rules."""
    if (record.rubric.rubric_id, record.rubric.version) != (rubric.id, rubric.version):
        raise ContractViolation("rubric_mismatch", f"{record.id} does not use {rubric.id} v{rubric.version}")
    dims = {d.code: d for d in rubric.dimensions}
    for label in record.raw_labels:
        if label.dimension not in dims:
            raise ContractViolation("unknown_rubric_dimension", f"{label.dimension} is not in the rubric")
    if {r.dimension for r in record.dimension_results} != set(dims):
        raise ContractViolation("rubric_dimension_coverage", f"{record.id} must have one result per rubric dimension")
    for item in (*record.raw_labels, *record.dimension_results):
        dim = dims[item.dimension]
        if item.value is not None and item.value not in {a.value for a in dim.scale}:
            raise ContractViolation("value_off_scale", f"{item.dimension}={item.value} is not a scale anchor")
        if item.not_applicable_reason is not None and item.not_applicable_reason not in {
                r.reason for r in dim.not_applicable_reasons}:
            raise ContractViolation("not_applicable_reason_not_allowed",
                                    f"{item.dimension} does not allow N/A for {item.not_applicable_reason}")
    for label in record.raw_labels:
        threshold = dims[label.dimension].rationale_required_at_or_below
        if label.value is not None and threshold is not None and label.value <= threshold and label.rationale is None:
            raise ContractViolation("rationale_required", f"{label.dimension}={label.value} needs a rationale")


def check_record_attachment(record: AdjudicationRecord, items: Iterable[ReviewItem], rubric: ReviewerRubric) -> None:
    """The record judges an actually produced output of a known item, and every N/A is grounded in an
    expectation the item carries (E10). Item expectations are caller-declared in this version."""
    by_key = _index_items(items)
    item = by_key.get(record.subject.item)
    if item is None:
        raise ContractViolation("record_item_missing", f"{record.id} names an item that is not in the review set")
    if item.output_status != "produced":
        raise ContractViolation("record_attached_to_absent_output", f"{record.id} judges an item with no produced output")
    if item.produced_output.output_id != record.subject.output_id:
        raise ContractViolation("record_output_mismatch", f"{record.id} names another output than the item produced")
    rules = {(d.code, r.reason): r.requires_expectation for d in rubric.dimensions for r in d.not_applicable_reasons}
    for entry in (*record.raw_labels, *record.dimension_results):
        if entry.not_applicable_reason is None:
            continue
        required = rules.get((entry.dimension, entry.not_applicable_reason))
        if required is None or required not in item.applicability_expectations:
            raise ContractViolation("not_applicable_unsupported_by_expectation",
                                    f"{entry.dimension}: N/A needs the pinned expectation {required}")


# ---------------------------------------------------------------------------
# Conflicts and reportability (structural only; E13)
# ---------------------------------------------------------------------------


class ConflictReason(str, Enum):
    CONFIGURATION_AUTHORSHIP = "configuration_authorship"
    CONFIGURATION_TUNING = "configuration_tuning"
    REFERENCE_LABEL_AUTHORSHIP = "reference_label_authorship"


class ReviewerConflict(ContractModel):
    principal_id: PrincipalId
    reason: ConflictReason


class ReviewerConflictRegister(ContractModel):
    """Conflicts of interest for one configuration and case (owner B2 qualification). Caller-supplied
    and not exported: a register's ``basis`` and ``coverage`` are claims that only a future trusted
    service can make true. Separate account identifiers never prove independence."""

    configuration: ConfigurationPin
    case_id: EvaluationCaseId
    case_version: Annotated[int, Field(ge=1)]
    coverage: Literal["complete_for_scope", "partial"]
    basis: Literal["unverified_declaration", "trusted_service_attested"]
    conflicts: tuple[ReviewerConflict, ...] = ()


class ReportabilityAssessment(ContractModel):
    """Structural eligibility is separate from genuine reporting authority.

    ``genuinely_reportable`` can only be ``False`` in this contract version: no
    caller-crafted attribution, role, register or rubric can make a record
    genuinely reportable until a trusted evaluation-record service exists.
    """

    record_id: AdjudicationId
    structurally_eligible: bool
    structural_reasons: tuple[Code, ...] = ()
    genuinely_reportable: Literal[False] = False
    authority_reasons: Annotated[tuple[Code, ...], Field(min_length=1)] = ("no_trusted_evaluation_record_service",)

    @model_validator(mode="after")
    def _consistent(self) -> "ReportabilityAssessment":
        if self.structurally_eligible == bool(self.structural_reasons):
            raise ValueError("structurally eligible exactly when there is no structural reason against it")
        return self


_TRUSTED = AttestationBasis.TRUSTED_SERVICE_AUTHENTICATED


def assess_reportability(record: AdjudicationRecord, rubric: ReviewerRubric, items: Iterable[ReviewItem],
                         run: EvaluationRun, register: ReviewerConflictRegister | None = None) -> ReportabilityAssessment:
    """Structural assessment only. Raises when records contradict each other; otherwise lists the
    structural reasons a record could not be reported, and always withholds genuine reportability."""
    check_adjudication(record, rubric)
    check_record_attachment(record, items, rubric)
    if record.subject.item.run_id != run.id:
        raise ContractViolation("record_run_mismatch", f"{record.id} judges an output of another run")
    reasons: list[str] = []
    if rubric.status != "approved":
        reasons.append("rubric_not_approved")
    if any(label.reviewer.attestation_basis is not _TRUSTED for label in record.raw_labels):
        reasons.append("role_not_authenticated")
    if record.recorded_by.attestation_basis is not _TRUSTED:
        reasons.append("recorder_not_authenticated")
    if register is None:
        reasons.append("conflict_register_missing")
    else:
        item = record.subject.item
        if (register.configuration != run.configuration
                or (register.case_id, register.case_version) != (item.case_id, item.case_version)):
            reasons.append("conflict_register_scope_mismatch")
        if register.coverage != "complete_for_scope":
            reasons.append("conflict_register_incomplete")
        if register.basis != "trusted_service_attested":
            reasons.append("conflict_register_untrusted")
        if {c.principal_id for c in register.conflicts} & record.labelling_principals:
            reasons.append("conflicted_reviewer")
    return ReportabilityAssessment(record_id=record.id, structurally_eligible=not reasons,
                                   structural_reasons=tuple(reasons))


def reportable(record: AdjudicationRecord, rubric: ReviewerRubric, items: Iterable[ReviewItem], run: EvaluationRun,
               register: ReviewerConflictRegister | None = None) -> bool:
    """May this record's resolved labels enter a reported metric? Always ``False`` in this contract
    version (E13), whatever trusted-looking metadata the caller supplies."""
    return assess_reportability(record, rubric, items, run, register).genuinely_reportable


# ---------------------------------------------------------------------------
# Usefulness distribution (diagnostic coverage; never a measurement here)
# ---------------------------------------------------------------------------


def derive_usefulness_distribution(definition: MetricDefinition, items: Iterable[ReviewItem],
                                   records: Iterable[AdjudicationRecord], rubric: ReviewerRubric, run: EvaluationRun,
                                   registers: Iterable[ReviewerConflictRegister] = ()) -> DistributionValue:
    """Count every review item and every reviewed output; never impute a score.

    Returns ``not_measured`` with fully populated diagnostic coverage: no record
    is genuinely reportable until a trusted evaluation-record service exists, so
    no usefulness measurement can be derived here (F4 E9 qualification).
    The item list is caller-declared; its completeness is not established.
    """
    if definition.unit != "ordinal_distribution":
        raise ContractViolation("metric_kind_mismatch", f"{definition.id} is not an ordinal-distribution metric")
    items = list(items)
    by_key = _index_items(items)
    if any(item.key.run_id != run.id for item in items):
        raise ContractViolation("review_item_run_mismatch", "review items belong to another run")
    registers = list(registers)
    by_subject: dict[ReviewItemKey, AdjudicationRecord] = {}
    for record in records:
        if record.subject.item in by_subject:
            raise ContractViolation("duplicate_adjudication", f"{record.id} judges an output that is already adjudicated")
        by_subject[record.subject.item] = record
    # genuinely_reportable stays 0: ReportabilityAssessment cannot express genuine reportability (E13).
    states = {"genuinely_reportable": 0, "structurally_eligible_only": 0, "structurally_ineligible": 0}
    dims = {d.code: {"scored": 0, "not_applicable": 0, "disputed": 0, "unresolved": 0} for d in rubric.dimensions}
    for record in by_subject.values():
        key = record.subject.item
        register = next((r for r in registers if (r.case_id, r.case_version) == (key.case_id, key.case_version)), None)
        assessment = assess_reportability(record, rubric, items, run, register)
        states["structurally_eligible_only" if assessment.structurally_eligible else "structurally_ineligible"] += 1
        for result in record.dimension_results:
            dims[result.dimension][result.resolution.value] += 1
    presence = {p: 0 for p in ("produced_expected", "produced_unexpected", "missing", "correctly_absent",
                               "generation_failed")}
    for item in by_key.values():
        presence[item.presence] += 1
    reviewed = len(by_subject)
    coverage = UsefulnessCoverage(
        items_total=len(by_key), **presence, reviewed=reviewed,
        unreviewed=presence["produced_expected"] + presence["produced_unexpected"] - reviewed, **states,
        dimension_states=tuple(DimensionReviewState(dimension=code, **counts) for code, counts in dims.items()))
    return DistributionValue(metric_id=definition.id, metric_version=definition.version,
                             status=MeasurementStatus.NOT_MEASURED, coverage=coverage)
