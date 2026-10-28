"""Controlled candidate claims and authoritative program participation (D-004.10).

Claim vocabulary is versioned, organization-scoped data (not a hard-coded
enum). Claims hold controlled codes and small typed values only; candidate
free text stays in the authoritative source. Program participation is a
separate authoritative record, never a candidate claim.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
from typing import Annotated, Iterable, Literal, Mapping, Union

from pydantic import ConfigDict, Field, model_validator

from .evidence import EvidenceBasis, EvidenceId, EvidenceRecord, EvidenceSubject, EvidenceSubjectKind, resolve_evidence_ids
from .invariants import ContractRecordSet, ContractViolation
from .models import CandidateId, ComponentId, ContractModel, OrganizationId, ProgramId, _ID_BODY

ClaimId = Annotated[str, Field(pattern=rf"^claim_{_ID_BODY}$", max_length=64)]
VocabularyId = Annotated[str, Field(pattern=rf"^vocabulary_{_ID_BODY}$", max_length=64)]
ParticipationId = Annotated[str, Field(pattern=rf"^participation_{_ID_BODY}$", max_length=64)]
Code = Annotated[str, Field(pattern=r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$", max_length=48)]

#: Defense-in-depth screen for vocabulary codes. The primary guard is the
#: allowlist itself; this list is NOT exhaustive and does not make any
#: vocabulary fair or lawful. Tokens are matched against '_'-separated parts.
RESTRICTED_ATTRIBUTE_TOKENS: frozenset[str] = frozenset(
    {
        "accommodation", "address", "age", "birth", "birthdate", "caste", "citizenship", "criminal",
        "diagnosis", "disability", "disabled", "dob", "ethnic", "ethnicity", "family", "gender",
        "genetic", "graduation", "health", "immigration", "marital", "medical", "nationality",
        "orientation", "photo", "postal", "pregnancy", "pregnant", "pronoun", "pronouns", "race",
        "religion", "religious", "sex", "sexual", "union", "veteran", "zip", "zipcode",
    }
)


def restricted_tokens(code: str) -> set[str]:
    return set(code.split("_")) & RESTRICTED_ATTRIBUTE_TOKENS


class ClaimType(str, Enum):
    SKILL = "skill"
    EXPERIENCE = "experience"
    INTEREST = "interest"
    AVAILABILITY = "availability"
    WORK_PREFERENCE = "work_preference"


class ClaimVocabulary(ContractModel):
    """Versioned allowlist of claim subject codes for one organization."""

    id: VocabularyId
    organization_id: OrganizationId
    version: Annotated[int, Field(ge=1)]
    skills: frozenset[Code]
    experience_areas: frozenset[Code]
    interest_areas: frozenset[Code]
    work_preferences: frozenset[Code]

    @model_validator(mode="after")
    def _screen(self) -> "ClaimVocabulary":
        for name in ("skills", "experience_areas", "interest_areas", "work_preferences"):
            for code in getattr(self, name):
                hit = restricted_tokens(code)
                if hit:
                    raise ValueError(f"{name} code {code!r} uses restricted attribute terms {sorted(hit)}")
        return self

    def codes_for(self, claim_type: ClaimType) -> frozenset[str]:
        return {
            ClaimType.SKILL: self.skills,
            ClaimType.EXPERIENCE: self.experience_areas,
            ClaimType.INTEREST: self.interest_areas,
            ClaimType.WORK_PREFERENCE: self.work_preferences,
        }[claim_type]


class VocabularyPin(ContractModel):
    id: VocabularyId
    version: Annotated[int, Field(ge=1)]


# --- typed claim values (no free text) -------------------------------------


class SkillValue(ContractModel):
    kind: Literal["skill"]
    presence: Literal["has", "lacks"]


class ExperienceValue(ContractModel):
    kind: Literal["experience"]
    presence: Literal["has", "lacks"]
    duration_months: Annotated[int, Field(ge=0)] | None = None

    @model_validator(mode="after")
    def _duration(self) -> "ExperienceValue":
        if self.presence == "lacks" and self.duration_months is not None:
            raise ValueError("duration_months only applies when presence is 'has'")
        return self


class InterestValue(ContractModel):
    kind: Literal["interest"]
    stance: Literal["interested", "not_interested"]


class AvailabilityValue(ContractModel):
    """Declared whole hours per week.

    Bounded only by the hours in a week. This does NOT represent schedules,
    time windows, schedule compatibility, or accommodation needs.
    """

    kind: Literal["availability"]
    hours_per_week: Annotated[int, Field(ge=0, le=168)]


class WorkPreferenceValue(ContractModel):
    kind: Literal["work_preference"]
    stance: Literal["prefers", "does_not_prefer"]


ClaimValue = Annotated[
    Union[SkillValue, ExperienceValue, InterestValue, AvailabilityValue, WorkPreferenceValue],
    Field(discriminator="kind"),
]


def values_conflict(a: ClaimValue, b: ClaimValue) -> bool:
    """Deterministic conflict rule for two values of the same claim key.

    Different presence/stance/hours conflict. For experience, two 'has' values
    conflict only if both state different durations; an unstated duration is
    less specific, not contradictory.
    """
    if a.kind != b.kind:
        raise ValueError("values of different kinds are not comparable")
    if isinstance(a, ExperienceValue):
        if a.presence != b.presence:
            return True
        return a.duration_months is not None and b.duration_months is not None and a.duration_months != b.duration_months
    return a != b


class ClaimState(str, Enum):
    DECLARED = "declared"
    INFERRED = "inferred"
    UNKNOWN = "unknown"
    CONTESTED = "contested"


class ClaimAlternative(ContractModel):
    value: ClaimValue
    evidence_ids: Annotated[tuple[EvidenceId, ...], Field(min_length=1)]


class CandidateClaim(ContractModel):
    """One candidate fact in an explicit epistemic state.

    * declared  -- a value supported by >=1 source-backed evidence record.
    * inferred  -- a NON-AUTHORITATIVE proposal: value + producing component + input evidence.
    * unknown   -- no supported value. A value here is a fabrication and is rejected.
    * contested -- >=2 genuinely conflicting source-backed alternatives; no single value.
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        json_schema_extra={
            # Portable subset of the state rules. Cross-alternative conflict and
            # value-kind/claim_type agreement remain Python-only.
            "allOf": [
                {"if": {"properties": {"state": {"enum": ["declared", "inferred"]}}, "required": ["state"]},
                 "then": {"required": ["value", "evidence_ids"],
                          "properties": {"value": {"type": "object"}, "evidence_ids": {"minItems": 1},
                                         "alternatives": {"type": "null"}}}},
                {"if": {"properties": {"state": {"const": "inferred"}}, "required": ["state"]},
                 "then": {"required": ["inferred_by"], "properties": {"inferred_by": {"type": "string"}}},
                 "else": {"properties": {"inferred_by": {"type": "null"}}}},
                {"if": {"properties": {"state": {"const": "unknown"}}, "required": ["state"]},
                 "then": {"properties": {"value": {"type": "null"}, "alternatives": {"type": "null"}}}},
                {"if": {"properties": {"state": {"const": "contested"}}, "required": ["state"]},
                 "then": {"required": ["alternatives"],
                          "properties": {"value": {"type": "null"}, "alternatives": {"type": "array", "minItems": 2},
                                         "evidence_ids": {"maxItems": 0}}}},
                {"if": {"properties": {"claim_type": {"const": "availability"}}, "required": ["claim_type"]},
                 "then": {"properties": {"subject_code": {"type": "null"}}},
                 "else": {"required": ["subject_code"], "properties": {"subject_code": {"type": "string"}}}},
            ]
        },
    )

    id: ClaimId
    organization_id: OrganizationId
    candidate_id: CandidateId
    vocabulary: VocabularyPin
    claim_type: ClaimType
    subject_code: Code | None = None
    state: ClaimState
    value: ClaimValue | None = None
    alternatives: tuple[ClaimAlternative, ...] | None = None
    evidence_ids: tuple[EvidenceId, ...] = ()
    inferred_by: ComponentId | None = None

    @model_validator(mode="after")
    def _state_rules(self) -> "CandidateClaim":
        if (self.claim_type is ClaimType.AVAILABILITY) != (self.subject_code is None):
            raise ValueError("subject_code is required for coded claim types and forbidden for availability")
        st = self.state
        if st in (ClaimState.DECLARED, ClaimState.INFERRED):
            if self.value is None or self.alternatives is not None:
                raise ValueError(f"{st.value} claims require exactly one value and no alternatives")
            if not self.evidence_ids:
                raise ValueError(f"{st.value} claims require evidence")
            if self.value.kind != self.claim_type.value:
                raise ValueError("value kind must match claim_type")
        if st is ClaimState.INFERRED and self.inferred_by is None:
            raise ValueError("inferred claims must name the producing component (inferred_by)")
        if st is not ClaimState.INFERRED and self.inferred_by is not None:
            raise ValueError("inferred_by is only allowed on inferred claims")
        if st is ClaimState.UNKNOWN and (self.value is not None or self.alternatives is not None):
            raise ValueError("unknown claims cannot carry a value or alternatives")
        if st is ClaimState.CONTESTED:
            alts = self.alternatives or ()
            if self.value is not None or len(alts) < 2 or self.evidence_ids:
                raise ValueError("contested claims need >=2 alternatives (each with evidence) and no single value")
            if any(a.value.kind != self.claim_type.value for a in alts):
                raise ValueError("alternative value kinds must match claim_type")
            if not any(values_conflict(x.value, y.value) for i, x in enumerate(alts) for y in alts[i + 1:]):
                raise ValueError("contested alternatives must genuinely conflict; corroborating values are not contested")
        return self

    @property
    def key(self) -> tuple[str, str, str | None]:
        return (self.candidate_id, self.claim_type.value, self.subject_code)

    def all_evidence_ids(self) -> tuple[str, ...]:
        if self.alternatives:
            return tuple(e for alt in self.alternatives for e in alt.evidence_ids)
        return self.evidence_ids


class ProgramParticipationStatus(str, Enum):
    CONFIRMED = "confirmed"
    NOT_PARTICIPATING = "not_participating"


class ProgramParticipation(ContractModel):
    """Authoritative participation record. Absence of a record means 'unknown'.

    Not a CandidateClaim: it has no inferred/declared state and must be backed
    by authority-record evidence from a declared participation authority.
    """

    id: ParticipationId
    organization_id: OrganizationId
    candidate_id: CandidateId
    program_id: ProgramId
    status: ProgramParticipationStatus
    evidence_ids: Annotated[tuple[EvidenceId, ...], Field(min_length=1)]


# ---------------------------------------------------------------------------
# Cross-record checks
# ---------------------------------------------------------------------------

CLAIM_EVIDENCE_BASES = frozenset({EvidenceBasis.CANDIDATE_STATEMENT, EvidenceBasis.INDEPENDENT_VERIFICATION})


@dataclass(frozen=True)
class ConflictGroup:
    key: tuple[str, str, str | None]
    claim_ids: tuple[str, ...]


def detect_conflicts(claims: Iterable[CandidateClaim]) -> list[ConflictGroup]:
    """Deterministic, sorted conflicts among DECLARED claims sharing a key.

    Inferred claims are excluded: an inference can neither create a conflict
    with nor override a source-backed fact.
    """
    by_key: dict[tuple, list[CandidateClaim]] = defaultdict(list)
    for claim in claims:
        if claim.state is ClaimState.DECLARED:
            by_key[claim.key].append(claim)
    groups = []
    for key in sorted(by_key, key=lambda k: (k[0], k[1], k[2] or "")):
        group = sorted(by_key[key], key=lambda c: c.id)
        if any(values_conflict(a.value, b.value) for i, a in enumerate(group) for b in group[i + 1:]):
            groups.append(ConflictGroup(key, tuple(c.id for c in group)))
    return groups


def check_claims(
    claims: Iterable[CandidateClaim],
    evidence: Mapping[str, EvidenceRecord],
    vocabularies: Iterable[ClaimVocabulary],
    records: ContractRecordSet,
) -> None:
    claims = list(claims)
    vocab_index = {(v.id, v.version): v for v in vocabularies}
    candidates = {c.id: c for c in records.candidates}
    seen = set()
    for claim in claims:
        if claim.id in seen:
            raise ContractViolation("duplicate_id", f"duplicate claim id {claim.id}")
        seen.add(claim.id)
        cand = candidates.get(claim.candidate_id)
        if cand is None:
            raise ContractViolation("unknown_reference", f"claim {claim.id} references unknown candidate")
        if cand.organization_id != claim.organization_id:
            raise ContractViolation("cross_org_reference", f"claim {claim.id} crosses organizations")
        vocab = vocab_index.get((claim.vocabulary.id, claim.vocabulary.version))
        if vocab is None:
            raise ContractViolation("unknown_vocabulary", f"claim {claim.id} pins an unknown vocabulary version")
        if vocab.organization_id != claim.organization_id:
            raise ContractViolation("cross_org_reference", f"claim {claim.id} uses another organization's vocabulary")
        if claim.subject_code is not None and claim.subject_code not in vocab.codes_for(claim.claim_type):
            raise ContractViolation("unsupported_claim_code", f"{claim.subject_code} is not in {vocab.id} v{vocab.version}")
        subject = EvidenceSubject(kind=EvidenceSubjectKind.CANDIDATE, id=claim.candidate_id)
        for ev in resolve_evidence_ids(claim.all_evidence_ids(), evidence, claim.organization_id, subject):
            if ev.basis not in CLAIM_EVIDENCE_BASES:
                raise ContractViolation("evidence_provenance", f"claim {claim.id}: {ev.basis.value} cannot back a candidate claim")

    by_key: dict[tuple, list[CandidateClaim]] = defaultdict(list)
    for claim in claims:
        if claim.state is not ClaimState.INFERRED:
            by_key[claim.key].append(claim)
    for key, group in by_key.items():
        states = {c.state for c in group}
        if ClaimState.CONTESTED in states and len(group) > 1:
            raise ContractViolation("contested_not_exclusive", f"{key}: a contested claim must be the only non-inferred claim")
        if ClaimState.UNKNOWN in states and len(states) > 1:
            raise ContractViolation("unknown_conflicts_with_value", f"{key}: unknown cannot coexist with a declared value")
    conflicts = detect_conflicts(claims)
    if conflicts:
        raise ContractViolation(
            "unresolved_conflict",
            f"{conflicts[0].key}: declared claims {list(conflicts[0].claim_ids)} conflict; represent as one contested claim",
        )


def check_claim_update(previous: CandidateClaim, proposed: CandidateClaim) -> None:
    """Identity is fixed; an inferred claim can never be relabeled into an authoritative state.

    A source-backed fact may only arise as a separate claim with its own
    candidate-statement or verification evidence (a future reviewed workflow).
    """
    for name in ("id", "organization_id", "candidate_id", "claim_type", "subject_code"):
        if getattr(proposed, name) != getattr(previous, name):
            raise ContractViolation("claim_immutable_field", f"{name} cannot change")
    if previous.state is ClaimState.INFERRED and proposed.state is not ClaimState.INFERRED:
        raise ContractViolation("inferred_promotion", "an inferred claim cannot become declared, unknown or contested")
    if previous.state is not ClaimState.INFERRED and proposed.state is ClaimState.INFERRED:
        raise ContractViolation("inferred_overwrite", "an inference cannot overwrite a source-backed claim")


def check_participations(
    participations: Iterable[ProgramParticipation],
    evidence: Mapping[str, EvidenceRecord],
    records: ContractRecordSet,
) -> None:
    candidates = {c.id: c for c in records.candidates}
    programs = {p.id: p for p in records.programs}
    status_by_key: dict[tuple, set] = defaultdict(set)
    seen = set()
    for part in participations:
        if part.id in seen:
            raise ContractViolation("duplicate_id", f"duplicate participation id {part.id}")
        seen.add(part.id)
        cand, prog = candidates.get(part.candidate_id), programs.get(part.program_id)
        if cand is None or prog is None:
            raise ContractViolation("unknown_reference", f"participation {part.id} references unknown records")
        if not (cand.organization_id == prog.organization_id == part.organization_id):
            raise ContractViolation("cross_org_reference", f"participation {part.id} crosses organizations")
        subject = EvidenceSubject(kind=EvidenceSubjectKind.CANDIDATE, id=part.candidate_id)
        for ev in resolve_evidence_ids(part.evidence_ids, evidence, part.organization_id, subject):
            if ev.basis is not EvidenceBasis.AUTHORITY_RECORD:
                raise ContractViolation(
                    "evidence_provenance", f"participation {part.id} requires authority-record evidence, not {ev.basis.value}"
                )
        status_by_key[(part.candidate_id, part.program_id)].add(part.status)
    for key, statuses in status_by_key.items():
        if len(statuses) > 1:
            raise ContractViolation("participation_conflict", f"{key}: conflicting authoritative participation records")
