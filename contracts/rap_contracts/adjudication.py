"""Reviewer rubric and adjudication records -- D-004.12 / ADR-0003 decision 8.

Contract v0.2 (partial, development, NOT frozen). Added in 0.2.0-dev.foundations.4.

Subjective expectations must be adjudicated by humans before any benchmark
performance is reported. These contracts define the *shape* of that record.
They do not adjudicate anything, and no adjudication record is committed in
this contract increment.

``RecordAttribution`` is structural metadata: ``asserted_kind="human"`` does
not authenticate a reviewer. ``reportable`` therefore requires the
``trusted_service_authenticated`` basis, which only a future trusted
evaluation-record service may issue (see ``promotion.EvaluationRecordService``).
Until that service exists, no adjudication is reportable.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, model_validator

from .evaluation import AttestationBasis, Code, EvaluationCaseId, RecordAttribution, ShortText
from .invariants import ContractViolation
from .models import _ID_BODY, ContractModel

RubricId = Annotated[str, Field(pattern=rf"^rubric_{_ID_BODY}$", max_length=64)]
AdjudicationId = Annotated[str, Field(pattern=rf"^adjudication_{_ID_BODY}$", max_length=64)]


class ScaleAnchor(ContractModel):
    value: Annotated[int, Field(ge=0, le=10)]
    label: ShortText


class RubricDimension(ContractModel):
    code: Code
    description: ShortText
    scale: Annotated[tuple[ScaleAnchor, ...], Field(min_length=2)]
    rationale_required_at_or_below: Annotated[int, Field(ge=0, le=10)] | None = None

    @model_validator(mode="after")
    def _scale(self) -> "RubricDimension":
        values = [a.value for a in self.scale]
        if values != sorted(set(values)):
            raise ValueError("scale anchors are unique and ascending")
        return self


class DisagreementPolicy(str, Enum):
    THIRD_REVIEWER = "third_reviewer"
    RECORDED_DISCUSSION = "recorded_discussion"


class ReviewerRubric(ContractModel):
    """Versioned rubric. A draft rubric is a proposal until the owner approves it."""

    id: RubricId
    version: Annotated[int, Field(ge=1)]
    status: Literal["draft", "approved"]
    dimensions: Annotated[tuple[RubricDimension, ...], Field(min_length=1)]
    min_independent_reviewers: Annotated[int, Field(ge=1)]
    disagreement_policy: DisagreementPolicy

    @model_validator(mode="after")
    def _unique(self) -> "ReviewerRubric":
        codes = [d.code for d in self.dimensions]
        if len(codes) != len(set(codes)):
            raise ValueError("dimension codes are unique")
        return self


class RubricPin(ContractModel):
    rubric_id: RubricId
    version: Annotated[int, Field(ge=1)]


class RawLabel(ContractModel):
    """One reviewer's independent judgment on one dimension."""

    reviewer: RecordAttribution
    dimension: Code
    value: Annotated[int, Field(ge=0, le=10)]
    rationale: ShortText | None = None
    labeled_at: AwareDatetime


class FinalLabel(ContractModel):
    dimension: Code
    value: Annotated[int, Field(ge=0, le=10)]


class AdjudicationStatus(str, Enum):
    ADJUDICATED = "adjudicated"
    DISPUTED = "disputed"
    UNRESOLVED = "unresolved"


class AdjudicationRecord(ContractModel):
    """Raw labels are retained; a correction is a new record that ``supersedes`` the prior one."""

    id: AdjudicationId
    case_id: EvaluationCaseId
    case_version: Annotated[int, Field(ge=1)]
    rubric: RubricPin
    raw_labels: Annotated[tuple[RawLabel, ...], Field(min_length=1)]
    status: AdjudicationStatus
    final_labels: tuple[FinalLabel, ...] = ()
    resolution_note: ShortText | None = None
    supersedes: AdjudicationId | None = None
    recorded_at: AwareDatetime
    recorded_by: RecordAttribution

    @model_validator(mode="after")
    def _consistency(self) -> "AdjudicationRecord":
        if any(label.reviewer.asserted_kind != "human" for label in self.raw_labels):
            raise ValueError("raw labels are human judgments; a model or service cannot be a reviewer")
        if self.recorded_by.asserted_kind != "human":
            raise ValueError("adjudication is recorded by a human")
        labeled = {label.dimension for label in self.raw_labels}
        seen = set()
        for label in self.raw_labels:
            key = (label.reviewer.principal_id, label.dimension)
            if key in seen:
                raise ValueError("one raw label per reviewer and dimension")
            seen.add(key)
        if self.status is AdjudicationStatus.ADJUDICATED:
            if {f.dimension for f in self.final_labels} != labeled or len(self.final_labels) != len(labeled):
                raise ValueError("an adjudicated record has exactly one final label per labeled dimension")
        elif self.final_labels:
            raise ValueError("disputed or unresolved records have no final labels")
        if self.status is not AdjudicationStatus.ADJUDICATED and self.resolution_note is None:
            raise ValueError("disputed or unresolved records explain why")
        if self.supersedes == self.id:
            raise ValueError("a record cannot supersede itself")
        return self

    @property
    def independent_reviewers(self) -> int:
        return len({label.reviewer.principal_id for label in self.raw_labels})

    @property
    def single_reviewer(self) -> bool:
        """No inter-rater agreement can be claimed for a single-reviewer record."""
        return self.independent_reviewers == 1


def check_adjudication(record: AdjudicationRecord, rubric: ReviewerRubric) -> None:
    """Labels conform to the pinned rubric's dimensions, scales and rationale rules."""
    if (record.rubric.rubric_id, record.rubric.version) != (rubric.id, rubric.version):
        raise ContractViolation("rubric_mismatch", f"{record.id} does not use {rubric.id} v{rubric.version}")
    dims = {d.code: d for d in rubric.dimensions}
    for label in (*record.raw_labels, *record.final_labels):
        dim = dims.get(label.dimension)
        if dim is None:
            raise ContractViolation("unknown_rubric_dimension", f"{label.dimension} is not in the rubric")
        if label.value not in {a.value for a in dim.scale}:
            raise ContractViolation("value_off_scale", f"{label.dimension}={label.value} is not a scale anchor")
    for label in record.raw_labels:
        threshold = dims[label.dimension].rationale_required_at_or_below
        if threshold is not None and label.value <= threshold and label.rationale is None:
            raise ContractViolation("rationale_required", f"{label.dimension}={label.value} needs a rationale")


def reportable(record: AdjudicationRecord, rubric: ReviewerRubric) -> bool:
    """May this record's final labels enter a reported metric?

    Requires an approved rubric, an adjudicated status, enough independent
    reviewers, and trusted attestation of every reviewer and of the recorder.
    Nothing in this contract increment can produce trusted attestation, so no
    adjudication is reportable yet.
    """
    check_adjudication(record, rubric)
    trusted = AttestationBasis.TRUSTED_SERVICE_AUTHENTICATED
    return (
        rubric.status == "approved"
        and record.status is AdjudicationStatus.ADJUDICATED
        and record.independent_reviewers >= rubric.min_independent_reviewers
        and record.recorded_by.attestation_basis is trusted
        and all(label.reviewer.attestation_basis is trusted for label in record.raw_labels)
    )
