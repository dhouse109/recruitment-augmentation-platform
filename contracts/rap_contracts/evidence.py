"""Evidence records, derived retrieval chunks and fail-closed admission (D-004.11).

Reuses ``SourceReference`` / ``SourceCheckResult`` and the PR #4 source-check
gates. What this module does NOT do: authenticate principals, query Drupal,
maintain an index, embed, rank, or assemble prompts. ``SourceAuthority`` and
``ChunkContentStore`` are protocols; in this PR they are implemented only by
in-memory test mocks.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import Enum
from typing import Annotated, Iterable, Literal, Mapping, Protocol

from pydantic import Field, model_validator

from .invariants import ContractRecordSet, ContractViolation
from .models import (
    ComponentId,
    ContractModel,
    OrganizationId,
    SourceReference,
    SourceSystem,
    SourceSystemCapabilities,
    _ID_BODY,
)
from .source_checks import (
    DEFAULT_SNAPSHOT_METHODS,
    SnapshotMethodRegistry,
    SourceAuthority,
    check_version_kind,
    checked,
    require_current_and_allowed,
)

EvidenceId = Annotated[str, Field(pattern=rf"^evidence_{_ID_BODY}$", max_length=64)]
ChunkId = Annotated[str, Field(pattern=rf"^chunk_{_ID_BODY}$", max_length=64)]
FieldPath = Annotated[
    str,
    Field(
        pattern=r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)*$",
        max_length=128,
        description="Location of the supporting field inside the source record, e.g. 'answers.screening_python'.",
    ),
]
ContentHash = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]


def content_sha256(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# EvidenceRecord
# ---------------------------------------------------------------------------


class EvidenceBasis(str, Enum):
    """Why this source supports a fact. Preserves declared vs verified (D-004.10, owner refinement A/2)."""

    CANDIDATE_STATEMENT = "candidate_statement"  # the candidate's own profile/application
    AUTHORITY_RECORD = "authority_record"  # staff/system record: participation, published opportunity data
    INDEPENDENT_VERIFICATION = "independent_verification"  # explicitly authorized verification source


class EvidenceSubjectKind(str, Enum):
    CANDIDATE = "candidate"
    OPPORTUNITY = "opportunity"


class EvidenceSubject(ContractModel):
    kind: EvidenceSubjectKind
    id: Annotated[str, Field(pattern=rf"^(candidate|opportunity)_{_ID_BODY}$", max_length=64)]

    @model_validator(mode="after")
    def _prefix(self) -> "EvidenceSubject":
        if not self.id.startswith(f"{self.kind.value}_"):
            raise ValueError("subject id prefix must match subject kind")
        return self


class EvidenceRecord(ContractModel):
    """Attributable pointer to one field of one exact authoritative source version.

    Carries no copied text. Content is resolved, when permitted, from the
    authority; a valid EvidenceRecord is not proof that it may be read.
    """

    id: EvidenceId
    organization_id: OrganizationId
    subject: EvidenceSubject
    basis: EvidenceBasis
    source_ref: SourceReference
    field_path: FieldPath

    @model_validator(mode="after")
    def _consistency(self) -> "EvidenceRecord":
        if self.source_ref.organization_id != self.organization_id:
            raise ValueError("source_ref.organization_id must equal organization_id")
        if self.basis is not EvidenceBasis.AUTHORITY_RECORD and self.subject.kind is not EvidenceSubjectKind.CANDIDATE:
            raise ValueError(f"{self.basis.value} evidence must have a candidate subject")
        return self


def index_evidence(records: Iterable[EvidenceRecord]) -> dict[str, EvidenceRecord]:
    index: dict[str, EvidenceRecord] = {}
    for rec in records:
        if rec.id in index:
            raise ContractViolation("duplicate_id", f"duplicate evidence id {rec.id}")
        index[rec.id] = rec
    return index


def check_evidence_records(
    evidence: Mapping[str, EvidenceRecord],
    records: ContractRecordSet,
    capabilities: Mapping[SourceSystem, SourceSystemCapabilities],
    methods: SnapshotMethodRegistry = DEFAULT_SNAPSHOT_METHODS,
) -> None:
    """Provenance rules per basis; organization scope; version kind.

    * candidate_statement -> the subject candidate's own profile/application source entity.
    * independent_verification -> an entity type the adapter explicitly declares as a
      verification source (none by default: fail closed).
    * authority_record about a candidate -> a declared participation-authority entity type.
    * authority_record about an opportunity -> that opportunity's own source entity.
    """
    candidates = {c.id: c for c in records.candidates}
    opportunities = {o.id: o for o in records.opportunities}
    statement_entities: dict[str, set] = {}
    for prof in records.profiles:
        statement_entities.setdefault(prof.candidate_id, set()).add(prof.source_ref.entity)
    for app in records.applications:
        statement_entities.setdefault(app.candidate_id, set()).add(app.source_ref.entity)

    for ev in evidence.values():
        check_version_kind(ev.source_ref, capabilities, methods)
        caps = capabilities[ev.source_ref.entity.source_system]
        subject_org = None
        if ev.subject.kind is EvidenceSubjectKind.CANDIDATE:
            cand = candidates.get(ev.subject.id)
            subject_org = cand.organization_id if cand else None
        else:
            opp = opportunities.get(ev.subject.id)
            subject_org = opp.organization_id if opp else None
        if subject_org is None:
            raise ContractViolation("unknown_reference", f"evidence {ev.id} subject {ev.subject.id} not found")
        if subject_org != ev.organization_id:
            raise ContractViolation("cross_org_reference", f"evidence {ev.id} subject is in another organization")
        entity = ev.source_ref.entity
        if ev.basis is EvidenceBasis.CANDIDATE_STATEMENT:
            if entity not in statement_entities.get(ev.subject.id, set()):
                raise ContractViolation(
                    "evidence_provenance",
                    f"evidence {ev.id}: candidate statements must come from the candidate's own profile/application",
                )
        elif ev.basis is EvidenceBasis.INDEPENDENT_VERIFICATION:
            if entity.entity_type not in caps.verification_entity_types:
                raise ContractViolation(
                    "unauthorized_verification_source",
                    f"evidence {ev.id}: {entity.entity_type} is not a declared verification source",
                )
        elif ev.subject.kind is EvidenceSubjectKind.CANDIDATE:
            if entity.entity_type not in caps.participation_authority_entity_types:
                raise ContractViolation(
                    "evidence_provenance",
                    f"evidence {ev.id}: candidate authority records must come from a declared participation authority",
                )
        else:
            if entity != opportunities[ev.subject.id].source_ref.entity:
                raise ContractViolation(
                    "evidence_provenance", f"evidence {ev.id}: opportunity evidence must come from the opportunity source"
                )


def resolve_evidence_ids(
    evidence_ids: Iterable[str],
    evidence: Mapping[str, EvidenceRecord],
    organization_id: str,
    subject: EvidenceSubject,
) -> list[EvidenceRecord]:
    """Citation check: every id exists, is in scope, and is about the stated subject."""
    resolved = []
    for eid in evidence_ids:
        ev = evidence.get(eid)
        if ev is None:
            raise ContractViolation("invalid_citation", f"evidence {eid} does not exist")
        if ev.organization_id != organization_id:
            raise ContractViolation("cross_org_reference", f"evidence {eid} is in another organization")
        if ev.subject != subject:
            raise ContractViolation("invalid_citation", f"evidence {eid} is not about {subject.id}")
        resolved.append(ev)
    return resolved


# ---------------------------------------------------------------------------
# Derived retrieval projection
# ---------------------------------------------------------------------------


class RetrievalChunk(ContractModel):
    """Derived, disposable projection of one exact source version. Never authoritative.

    ``access_scope_hint`` is an advisory pre-filter label written by the indexer.
    It is NEVER used to authorize admission; only the live authority decides.
    """

    id: ChunkId
    organization_id: OrganizationId
    source_ref: SourceReference
    field_path: FieldPath
    index_version: ComponentId
    text_pointer: Annotated[
        str,
        Field(
            pattern=r"^[A-Za-z0-9._~-]+(/[A-Za-z0-9._~-]+)*$",
            max_length=256,
            description="Opaque key into a controlled derived store. Not a URL: no scheme, host or ':'.",
        ),
    ]
    content_hash: ContentHash
    access_scope_hint: Annotated[
        str,
        Field(
            pattern=r"^[a-z][a-z0-9_]{0,63}$",
            description="Advisory indexer label. Not authorization; ignored by admission.",
        ),
    ]

    @model_validator(mode="after")
    def _scope(self) -> "RetrievalChunk":
        if self.source_ref.organization_id != self.organization_id:
            raise ValueError("source_ref.organization_id must equal organization_id")
        return self


class RetrievalPurpose(str, Enum):
    MODEL_CONTEXT = "model_context"
    REVIEWER_DISPLAY = "reviewer_display"


class RetrievalRequest(ContractModel):
    """Caller request for derived content. Contains no principal: identity is server-derived."""

    organization_id: OrganizationId
    purpose: RetrievalPurpose
    chunk_ids: Annotated[tuple[ChunkId, ...], Field(min_length=1, max_length=100)]

    @model_validator(mode="after")
    def _unique(self) -> "RetrievalRequest":
        if len(set(self.chunk_ids)) != len(self.chunk_ids):
            raise ValueError("chunk_ids must be unique")
        return self


class AdmittedChunk(ContractModel):
    """Content cleared for this request. ``text`` is untrusted data, never instructions."""

    chunk_id: ChunkId
    source_ref: SourceReference
    field_path: FieldPath
    trust: Literal["untrusted_data"] = "untrusted_data"
    text: str


class RetrievalResponse(ContractModel):
    """Externally observable result.

    Every requested chunk that is not admitted is listed in ``unavailable_chunk_ids``
    with no reason. Nonexistent, cross-organization, unauthorized, stale,
    withdrawn, deleted and integrity-failed chunks are indistinguishable here.
    """

    organization_id: OrganizationId
    admitted: tuple[AdmittedChunk, ...]
    unavailable_chunk_ids: tuple[ChunkId, ...]


class DenialCode(str, Enum):
    """Internal-only denial reasons (logs/audit). Never returned to the caller."""

    UNKNOWN_CHUNK = "unknown_chunk"
    CROSS_ORG = "cross_org"
    INVALID_SOURCE_VERSION = "invalid_source_version"
    SOURCE_CHECK_FAILED = "source_check_failed"
    ACCESS_DENIED = "access_denied"
    NOT_CURRENT = "not_current"
    WITHDRAWN = "withdrawn"
    DELETED = "deleted"
    UNAVAILABLE = "unavailable"
    CONTENT_UNAVAILABLE = "content_unavailable"
    CONTENT_INTEGRITY = "content_integrity"


_VIOLATION_TO_DENIAL = {
    "source_access_denied": DenialCode.ACCESS_DENIED,
    "source_not_current": DenialCode.NOT_CURRENT,
    "source_withdrawn": DenialCode.WITHDRAWN,
    "source_deleted": DenialCode.DELETED,
    "source_unavailable": DenialCode.UNAVAILABLE,
}


@dataclass(frozen=True)
class InternalDenial:
    chunk_id: str
    code: DenialCode


@dataclass(frozen=True)
class AdmissionOutcome:
    """Internal result. Use ``external_response`` for anything returned to a caller."""

    request: RetrievalRequest
    admitted: tuple[AdmittedChunk, ...]
    denied: tuple[InternalDenial, ...]

    def external_response(self) -> RetrievalResponse:
        return RetrievalResponse(
            organization_id=self.request.organization_id,
            admitted=self.admitted,
            unavailable_chunk_ids=tuple(sorted(d.chunk_id for d in self.denied)),
        )


class ChunkContentStore(Protocol):
    """Controlled derived store. Called only after a chunk is authorized."""

    def load(self, text_pointer: str) -> str: ...


def admit_chunks(
    request: RetrievalRequest,
    index: Mapping[str, RetrievalChunk],
    authority: SourceAuthority,
    store: ChunkContentStore,
    principal_id: str,
    capabilities: Mapping[SourceSystem, SourceSystemCapabilities],
    methods: SnapshotMethodRegistry = DEFAULT_SNAPSHOT_METHODS,
) -> AdmissionOutcome:
    """Per-chunk fail-closed admission.

    Order per requested id: index lookup -> organization scope -> version kind ->
    live authority check (current AND allowed) -> load text -> content hash.
    No authority call is made for unknown or cross-organization ids, and no
    text is loaded for any chunk that fails a check before loading.
    ``chunk.access_scope_hint`` is never consulted.
    """
    admitted: list[AdmittedChunk] = []
    denied: list[InternalDenial] = []
    for chunk_id in request.chunk_ids:
        chunk = index.get(chunk_id)
        if chunk is None:
            denied.append(InternalDenial(chunk_id, DenialCode.UNKNOWN_CHUNK))
            continue
        if chunk.organization_id != request.organization_id or chunk.source_ref.organization_id != request.organization_id:
            denied.append(InternalDenial(chunk_id, DenialCode.CROSS_ORG))
            continue
        try:
            check_version_kind(chunk.source_ref, capabilities, methods)
        except ContractViolation:
            denied.append(InternalDenial(chunk_id, DenialCode.INVALID_SOURCE_VERSION))
            continue
        try:
            require_current_and_allowed(checked(authority, principal_id, chunk.source_ref))
        except ContractViolation as exc:
            denied.append(InternalDenial(chunk_id, _VIOLATION_TO_DENIAL.get(exc.code, DenialCode.SOURCE_CHECK_FAILED)))
            continue
        try:
            text = store.load(chunk.text_pointer)
        except Exception:
            denied.append(InternalDenial(chunk_id, DenialCode.CONTENT_UNAVAILABLE))
            continue
        if not isinstance(text, str) or content_sha256(text) != chunk.content_hash:
            denied.append(InternalDenial(chunk_id, DenialCode.CONTENT_INTEGRITY))
            continue  # loaded text is discarded, never exposed
        admitted.append(
            AdmittedChunk(chunk_id=chunk.id, source_ref=chunk.source_ref, field_path=chunk.field_path, text=text)
        )
    return AdmissionOutcome(request=request, admitted=tuple(admitted), denied=tuple(denied))


def require_sources_admissible(
    refs: Iterable[SourceReference],
    authority: SourceAuthority,
    principal_id: str,
    capabilities: Mapping[SourceSystem, SourceSystemCapabilities],
    methods: SnapshotMethodRegistry = DEFAULT_SNAPSHOT_METHODS,
) -> None:
    """Gate before eligibility processing (owner refinement B).

    Raises on the first revoked, unavailable, withdrawn, deleted, stale or
    failed source check. Integrity/authorization failures are never converted
    into an ordinary ``unknown`` rule outcome.
    """
    seen = set()
    for ref in refs:
        if ref in seen:
            continue
        seen.add(ref)
        check_version_kind(ref, capabilities, methods)
        require_current_and_allowed(checked(authority, principal_id, ref))
