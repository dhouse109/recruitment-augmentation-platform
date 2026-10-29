"""Portable reference contracts -- Contract v0.2 foundations (partial, development).

Scope (PR #4): D-004.01 identity, D-004.02 profile/application/opportunity
separation, and the *representation* requirements of D-004.07 source versions.

These are Pydantic v2 reference contracts. They are not a selection of the
application runtime. They validate structure and single-record invariants only.
They do NOT authenticate anyone, check live Drupal permissions, enforce
persistence/uniqueness/retention, or prove that a source is current.
Cross-record rules live in ``invariants.py``; source-check policy lives in
``source_checks.py``.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal, Union

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

# Semver pre-release precedence: 0.2.0-dev.foundations < .foundations.2 < .foundations.3 < .foundations.4
# < .foundations.5 (".foundations.N" is kept deliberately: "0.2.0-dev.evaluation.1" would sort BELOW ".foundations.3").
# .foundations.5: F4 PR-B adjudication integrity (adjudication-record, reviewer-rubric, run-comparison bodies).
CONTRACT_VERSION = "0.2.0-dev.foundations.5"

# ---------------------------------------------------------------------------
# Identifiers
# ---------------------------------------------------------------------------
# Portable IDs are opaque, lowercase, typed-prefix tokens. The pattern blocks
# obvious personal-data shapes (``@``, ``.``, spaces, upper case) but cannot
# prove opacity: generating IDs that are not derived from personal information
# (name, email, username, Drupal uid) is an obligation of the ID issuer.

_ID_BODY = r"[a-z0-9]+(?:_[a-z0-9]+)*"


def _portable_id(prefix: str, what: str) -> object:
    return Field(
        pattern=rf"^{prefix}_{_ID_BODY}$",
        max_length=64,
        description=(
            f"Opaque portable {what} identifier. Independent of Drupal IDs and "
            "never derived from personal information."
        ),
    )


OrganizationId = Annotated[str, _portable_id("org", "organization")]
ProgramId = Annotated[str, _portable_id("program", "program")]
OpportunityId = Annotated[str, _portable_id("opportunity", "opportunity")]
CandidateId = Annotated[str, _portable_id("candidate", "organization-scoped candidate")]
ProfileId = Annotated[str, _portable_id("profile", "candidate profile")]
ApplicationId = Annotated[str, _portable_id("application", "application")]

EntityTypeLabel = Annotated[
    str,
    Field(
        pattern=r"^[a-z][a-z0-9_]{0,63}$",
        description="Source-side logical entity type label declared by the adapter. Not a Drupal schema commitment.",
    ),
]
SourceEntityId = Annotated[
    str,
    Field(
        pattern=r"^[A-Za-z0-9._-]{1,128}$",
        description="Identifier of the record in the source system. Source metadata only; never a portable ID.",
    ),
]
ComponentId = Annotated[
    str,
    Field(
        pattern=r"^[a-z0-9]+(?:[.-][a-z0-9]+)*/[0-9A-Za-z.+-]{1,64}$",
        description="Identifier of the adapter/authority component and its version, e.g. 'fixture-adapter/0.2.0-dev.foundations'.",
    ),
]


class ContractModel(BaseModel):
    """Base: unknown fields rejected; instances immutable after validation."""

    model_config = ConfigDict(extra="forbid", frozen=True)


# ---------------------------------------------------------------------------
# Source references and version semantics (D-004.07)
# ---------------------------------------------------------------------------


class SourceSystem(str, Enum):
    """Authoritative source. ``fixture`` is the offline test substitute only."""

    DRUPAL = "drupal"
    FIXTURE = "fixture"


class SourceEntityKey(ContractModel):
    """Unversioned locator of one authoritative source record."""

    source_system: SourceSystem
    entity_type: EntityTypeLabel
    entity_id: SourceEntityId


class NativeRevision(ContractModel):
    """A revision identifier issued natively by the source system.

    ``:`` is excluded from the pattern so a prefixed logical snapshot token
    (``sha256:...``) cannot be relabeled as a native revision.
    """

    kind: Literal["native_revision"]
    revision_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9._-]{1,128}$")]


class LogicalSnapshot(ContractModel):
    """A version token computed by an adapter when no native revision exists.

    Provenance: ``captured_by`` computed ``token`` with ``method`` over the
    authoritative record as read at ``captured_at``. A well-formed token proves
    neither currentness nor authorization; only the authority can confirm that
    a token still corresponds to the record and that the caller may read it.
    """

    kind: Literal["logical_snapshot"]
    method: Annotated[
        str,
        Field(
            pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*/v[1-9][0-9]*$",
            description="Snapshot method identifier, e.g. 'sha256-canonical-json/v1'. Open set; consumers accept only registered methods.",
        ),
    ]
    token: Annotated[
        str,
        Field(
            pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*:[A-Za-z0-9._~-]{8,256}$",
            description="'<scheme>:<value>' token. Method-specific format is checked against a snapshot-method registry.",
        ),
    ]
    captured_at: AwareDatetime
    captured_by: ComponentId


SourceVersion = Annotated[
    Union[NativeRevision, LogicalSnapshot],
    Field(discriminator="kind"),
]


class SourceReference(ContractModel):
    """An authoritative record at one honestly labeled version.

    Version currentness and access are deliberately NOT fields here: they are
    separate, live checks reported by ``SourceCheckResult``.
    """

    organization_id: OrganizationId
    entity: SourceEntityKey
    version: SourceVersion


class VersionStatus(str, Enum):
    CURRENT = "current"
    SUPERSEDED = "superseded"  # this version still exists and is retained; a newer one exists
    WITHDRAWN = "withdrawn"
    DELETED = "deleted"
    UNAVAILABLE = "unavailable"  # version not found / not retained / not resolvable


class AccessStatus(str, Enum):
    ALLOWED = "allowed"
    DENIED = "denied"


class SourceCheckResult(ContractModel):
    """Outcome of one live check of one SourceReference by the authority.

    Version status and access status are independent axes (D-004.07). In this
    PR the only producer is a mock fixture authority; a real result must come
    from live Drupal authority at the time of use.
    """

    source: SourceReference
    checked_at: AwareDatetime
    checked_by: ComponentId
    version_status: VersionStatus
    access_status: AccessStatus


# ---------------------------------------------------------------------------
# Organization-scoped records (D-004.01, D-004.02)
# ---------------------------------------------------------------------------


def _require_same_org(record_org: str, ref: SourceReference, field: str) -> None:
    if ref.organization_id != record_org:
        raise ValueError(f"{field}.organization_id must equal the record organization_id")


class Program(ContractModel):
    id: ProgramId
    organization_id: OrganizationId
    source_ref: SourceReference

    @model_validator(mode="after")
    def _scope(self) -> "Program":
        _require_same_org(self.organization_id, self.source_ref, "source_ref")
        return self


class OpportunityStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    CLOSED = "closed"


class Opportunity(ContractModel):
    """Minimal opportunity envelope. Qualifications/attributes are deferred (D-004.06/.10)."""

    id: OpportunityId
    organization_id: OrganizationId
    opportunity_type: Annotated[
        str,
        Field(
            pattern=r"^[a-z][a-z0-9_]{1,40}$",
            description="Open category label, e.g. 'internship', 'job', 'fellowship'. Not internship-specific.",
        ),
    ]
    status: OpportunityStatus
    program_id: ProgramId | None = None
    source_ref: SourceReference

    @model_validator(mode="after")
    def _scope(self) -> "Opportunity":
        _require_same_org(self.organization_id, self.source_ref, "source_ref")
        return self


class Candidate(ContractModel):
    """Stable, organization-scoped recruitment subject (D-004.01).

    ``identity_source`` locates the authenticating account (e.g. a Drupal user).
    The account is identity, not the candidate ID. One account maps to at most
    one Candidate per organization; that uniqueness is a cross-record rule
    (``invariants.check_identity_mappings``) and must be enforced by the
    authoritative store. ``identity_source`` is immutable through ordinary
    updates; merges/corrections require a separately designed audited process.
    """

    id: CandidateId
    organization_id: OrganizationId
    identity_source: SourceEntityKey


class CandidateProfile(ContractModel):
    """One version of an organization-scoped reusable candidate profile.

    Version envelope and metadata only. Claim vocabulary is deferred to the
    D-004.10 contract PR. Each instance pins exactly one profile version via
    ``source_ref``; multiple versions share ``id``, ``candidate_id`` and source entity.
    """

    id: ProfileId
    organization_id: OrganizationId
    candidate_id: CandidateId
    source_ref: SourceReference

    @model_validator(mode="after")
    def _scope(self) -> "CandidateProfile":
        _require_same_org(self.organization_id, self.source_ref, "source_ref")
        return self


class ApplicationStatus(str, Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    WITHDRAWN = "withdrawn"
    CLOSED = "closed"


class ApplicationTarget(ContractModel):
    """At least one of program or opportunity. Duplicate-application policy is OPEN."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        json_schema_extra={
            "anyOf": [
                {"required": ["program_id"], "properties": {"program_id": {"type": "string"}}},
                {"required": ["opportunity_id"], "properties": {"opportunity_id": {"type": "string"}}},
            ]
        },
    )

    program_id: ProgramId | None = None
    opportunity_id: OpportunityId | None = None

    @model_validator(mode="after")
    def _at_least_one(self) -> "ApplicationTarget":
        if self.program_id is None and self.opportunity_id is None:
            raise ValueError("an application target requires program_id and/or opportunity_id")
        return self


class SubmissionSnapshot(ContractModel):
    """Immutable record of what was submitted, by version pointer (no copied claim values).

    ``profile_ref`` pins the exact historical profile version.
    ``application_version`` is the version of the *application's own* source
    entity (``Application.source_ref.entity``) as of submission. It is stored as
    a bare version rather than a full reference so the application never needs
    to embed a reference to a record that contains itself; the adapter assembles
    this snapshot from authoritative state after the submission is persisted.
    """

    submitted_at: AwareDatetime
    profile_id: ProfileId
    profile_ref: SourceReference
    application_version: SourceVersion


class Application(ContractModel):
    """One independent submission to a program and/or opportunity (D-004.02)."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        json_schema_extra={
            "allOf": [
                {
                    "if": {"properties": {"status": {"const": "draft"}}, "required": ["status"]},
                    "then": {"properties": {"submission": {"type": "null"}}},
                },
                {
                    "if": {"properties": {"status": {"enum": ["submitted", "closed"]}}, "required": ["status"]},
                    "then": {"required": ["submission"], "properties": {"submission": {"type": "object"}}},
                },
            ]
        },
    )

    id: ApplicationId
    organization_id: OrganizationId
    candidate_id: CandidateId
    target: ApplicationTarget
    status: ApplicationStatus
    source_ref: SourceReference
    submission: SubmissionSnapshot | None = None

    @model_validator(mode="after")
    def _consistency(self) -> "Application":
        _require_same_org(self.organization_id, self.source_ref, "source_ref")
        sub = self.submission
        if self.status is ApplicationStatus.DRAFT and sub is not None:
            raise ValueError("a draft application cannot carry a submission snapshot")
        if self.status in (ApplicationStatus.SUBMITTED, ApplicationStatus.CLOSED) and sub is None:
            raise ValueError(f"a {self.status.value} application requires a submission snapshot")
        if sub is not None:
            _require_same_org(self.organization_id, sub.profile_ref, "submission.profile_ref")
            if sub.application_version.kind != self.source_ref.version.kind:
                raise ValueError(
                    "submission.application_version kind must match source_ref.version kind (same source entity)"
                )
        return self


class SourceSystemCapabilities(ContractModel):
    """Adapter-declared versioning capabilities for one source system.

    Declares which entity types carry native revisions and which require
    logical snapshots, so version kinds are checked against declared facts
    rather than hard-coded Drupal entity knowledge. Not exported as a portable
    schema in this PR (adapter configuration).
    """

    source_system: SourceSystem
    declared_by: ComponentId
    identity_entity_types: frozenset[EntityTypeLabel]
    native_revision_entity_types: frozenset[EntityTypeLabel]
    logical_snapshot_entity_types: frozenset[EntityTypeLabel]
    snapshot_methods: frozenset[str]
    # Added in 0.2.0-dev.foundations.2 (optional; defaults keep PR #4 declarations valid).
    participation_authority_entity_types: frozenset[EntityTypeLabel] = frozenset()
    """Entity types authoritative for program participation (staff/system records)."""
    verification_entity_types: frozenset[EntityTypeLabel] = frozenset()
    """Explicitly authorized independent verification sources. Empty = none authorized (fail closed)."""

    @model_validator(mode="after")
    def _coherent(self) -> "SourceSystemCapabilities":
        overlap = self.native_revision_entity_types & self.logical_snapshot_entity_types
        if overlap:
            raise ValueError(f"entity types cannot declare both version kinds: {sorted(overlap)}")
        declared = self.native_revision_entity_types | self.logical_snapshot_entity_types
        if not self.identity_entity_types <= declared:
            raise ValueError("identity entity types must declare a version kind")
        if self.logical_snapshot_entity_types and not self.snapshot_methods:
            raise ValueError("logical snapshot entity types require at least one snapshot method")
        for name in ("participation_authority_entity_types", "verification_entity_types"):
            role_types = getattr(self, name)
            if not role_types <= declared:
                raise ValueError(f"{name} must declare a version kind")
            if role_types & self.identity_entity_types:
                raise ValueError(f"{name} cannot include identity entity types")
        return self
