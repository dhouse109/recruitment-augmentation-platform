"""Cross-record invariants for the v0.2 foundations contracts.

These are pure functions over in-memory records. They state the rules an
authoritative store must enforce; they do not enforce them in any database,
under concurrency, or against live Drupal state.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable, Mapping

from .models import (
    Application,
    ApplicationStatus,
    Candidate,
    CandidateProfile,
    Opportunity,
    Program,
    SourceReference,
    SourceSystem,
    SourceSystemCapabilities,
)


class ContractViolation(ValueError):
    """A named, testable invariant failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"[{code}] {message}")
        self.code = code


# ---------------------------------------------------------------------------
# D-004.01 identity
# ---------------------------------------------------------------------------


def check_identity_mappings(candidates: Iterable[Candidate]) -> None:
    """One account -> at most one Candidate per organization; candidate IDs never reused."""
    seen_ids: dict[str, Candidate] = {}
    seen_identity: dict[tuple[str, object], Candidate] = {}
    for cand in candidates:
        prior = seen_ids.get(cand.id)
        if prior is not None:
            if prior.organization_id != cand.organization_id:
                raise ContractViolation(
                    "candidate_id_reused",
                    f"{cand.id} is used in {prior.organization_id} and {cand.organization_id}; "
                    "organization-scoped identities must be distinct",
                )
            raise ContractViolation("duplicate_candidate_id", f"{cand.id} appears more than once")
        seen_ids[cand.id] = cand
        key = (cand.organization_id, cand.identity_source)
        other = seen_identity.get(key)
        if other is not None:
            raise ContractViolation(
                "identity_conflict",
                f"account {cand.identity_source.entity_id} maps to both {other.id} and {cand.id} "
                f"in {cand.organization_id}",
            )
        seen_identity[key] = cand


def check_identity_source(
    candidate: Candidate, capabilities: Mapping[SourceSystem, SourceSystemCapabilities]
) -> None:
    """The identity source must be a declared account/identity entity type."""
    caps = capabilities.get(candidate.identity_source.source_system)
    if caps is None:
        raise ContractViolation("unknown_source_system", f"no capabilities declared for {candidate.identity_source.source_system.value}")
    if candidate.identity_source.entity_type not in caps.identity_entity_types:
        raise ContractViolation(
            "invalid_identity_source",
            f"{candidate.identity_source.entity_type} is not a declared identity entity type",
        )


def check_candidate_update(previous: Candidate, proposed: Candidate) -> None:
    """Ordinary updates cannot change identity, scope, or the identity mapping."""
    if proposed.id != previous.id:
        raise ContractViolation("candidate_immutable_field", "id cannot change")
    if proposed.organization_id != previous.organization_id:
        raise ContractViolation("candidate_immutable_field", "organization_id cannot change")
    if proposed.identity_source != previous.identity_source:
        raise ContractViolation(
            "identity_immutable",
            "identity_source cannot change through an ordinary update; merges/corrections need a separate audited process",
        )


# ---------------------------------------------------------------------------
# D-004.02 profile / application separation and lifecycle
# ---------------------------------------------------------------------------

ALLOWED_APPLICATION_TRANSITIONS: Mapping[ApplicationStatus, frozenset[ApplicationStatus]] = {
    ApplicationStatus.DRAFT: frozenset({ApplicationStatus.SUBMITTED, ApplicationStatus.WITHDRAWN}),
    ApplicationStatus.SUBMITTED: frozenset({ApplicationStatus.WITHDRAWN, ApplicationStatus.CLOSED}),
    # Terminal in v0.2 foundations. Reopen/amend are UNSUPPORTED (not permanently
    # prohibited); adding them requires explicit contract review.
    ApplicationStatus.WITHDRAWN: frozenset(),
    ApplicationStatus.CLOSED: frozenset(),
}


def check_application_transition(current: ApplicationStatus, target: ApplicationStatus) -> None:
    if current is target:
        return  # re-projection without a status change
    if target not in ALLOWED_APPLICATION_TRANSITIONS[current]:
        raise ContractViolation(
            "forbidden_transition", f"application status {current.value} -> {target.value} is not supported"
        )


def check_application_update(previous: Application, proposed: Application) -> None:
    """A later projection of the same application may not rewrite history."""
    for name in ("id", "organization_id", "candidate_id", "target"):
        if getattr(proposed, name) != getattr(previous, name):
            raise ContractViolation("application_immutable_field", f"{name} cannot change")
    if proposed.source_ref.entity != previous.source_ref.entity:
        raise ContractViolation("application_source_entity_changed", "source entity cannot change")
    check_application_transition(previous.status, proposed.status)
    if previous.submission is not None:
        if proposed.submission != previous.submission:
            raise ContractViolation(
                "submission_rewrite", "a recorded submission snapshot cannot be changed or removed"
            )
    elif proposed.submission is not None and not (
        previous.status is ApplicationStatus.DRAFT and proposed.status is ApplicationStatus.SUBMITTED
    ):
        raise ContractViolation(
            "submission_without_submit", "a submission snapshot may only be added by draft -> submitted"
        )


def check_profile_revision(previous: CandidateProfile, proposed: CandidateProfile) -> None:
    """Two versions of one logical profile share identity, owner, scope and source entity."""
    for name in ("id", "candidate_id", "organization_id"):
        if getattr(proposed, name) != getattr(previous, name):
            raise ContractViolation("profile_immutable_field", f"{name} cannot change across profile versions")
    if proposed.source_ref.entity != previous.source_ref.entity:
        raise ContractViolation("profile_source_entity_changed", "profile versions must share one source entity")


def application_submission_ref(application: Application) -> SourceReference:
    """Full reference to the application's own source entity at its submitted version."""
    if application.submission is None:
        raise ContractViolation("no_submission", f"{application.id} has no submission snapshot")
    return SourceReference(
        organization_id=application.organization_id,
        entity=application.source_ref.entity,
        version=application.submission.application_version,
    )


# ---------------------------------------------------------------------------
# Record set: cross-object scope and reference checks
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ContractRecordSet:
    candidates: tuple[Candidate, ...] = ()
    profiles: tuple[CandidateProfile, ...] = ()  # may contain several versions per profile id
    programs: tuple[Program, ...] = ()
    opportunities: tuple[Opportunity, ...] = ()
    applications: tuple[Application, ...] = ()


def _unique(records: Iterable, kind: str) -> dict[str, object]:
    index: dict[str, object] = {}
    for rec in records:
        if rec.id in index:
            raise ContractViolation("duplicate_id", f"duplicate {kind} id {rec.id}")
        index[rec.id] = rec
    return index


def _same_org(owner_org: str, other_org: str, what: str) -> None:
    if owner_org != other_org:
        raise ContractViolation("cross_org_reference", f"{what} crosses from {owner_org} to {other_org}")


def all_source_refs(records: ContractRecordSet) -> list[SourceReference]:
    refs: list[SourceReference] = []
    refs += [p.source_ref for p in records.profiles]
    refs += [p.source_ref for p in records.programs]
    refs += [o.source_ref for o in records.opportunities]
    for app in records.applications:
        refs.append(app.source_ref)
        if app.submission is not None:
            refs.append(app.submission.profile_ref)
            refs.append(application_submission_ref(app))
    return refs


def check_record_set(records: ContractRecordSet) -> None:
    """Organization scope, referential integrity and profile-version coherence.

    Version-kind checks against adapter capabilities are in
    ``source_checks.check_version_kind`` / ``check_record_set_versions``.
    """
    check_identity_mappings(records.candidates)
    candidates = {c.id: c for c in records.candidates}
    programs = _unique(records.programs, "program")
    opportunities = _unique(records.opportunities, "opportunity")
    _unique(records.applications, "application")

    profile_versions: dict[str, list[CandidateProfile]] = defaultdict(list)
    for prof in records.profiles:
        cand = candidates.get(prof.candidate_id)
        if cand is None:
            raise ContractViolation("unknown_reference", f"profile {prof.id} references unknown candidate")
        _same_org(prof.organization_id, cand.organization_id, f"profile {prof.id} -> candidate {cand.id}")
        if profile_versions[prof.id]:
            check_profile_revision(profile_versions[prof.id][0], prof)
            if any(v.source_ref.version == prof.source_ref.version for v in profile_versions[prof.id]):
                raise ContractViolation("duplicate_profile_version", f"profile {prof.id} version listed twice")
        profile_versions[prof.id].append(prof)

    for opp in opportunities.values():
        if opp.program_id is not None:
            prog = programs.get(opp.program_id)
            if prog is None:
                raise ContractViolation("unknown_reference", f"opportunity {opp.id} references unknown program")
            _same_org(opp.organization_id, prog.organization_id, f"opportunity {opp.id} -> program {prog.id}")

    for app in records.applications:
        cand = candidates.get(app.candidate_id)
        if cand is None:
            raise ContractViolation("unknown_reference", f"application {app.id} references unknown candidate")
        _same_org(app.organization_id, cand.organization_id, f"application {app.id} -> candidate")
        prog = opp = None
        if app.target.program_id is not None:
            prog = programs.get(app.target.program_id)
            if prog is None:
                raise ContractViolation("unknown_reference", f"application {app.id} targets unknown program")
            _same_org(app.organization_id, prog.organization_id, f"application {app.id} -> program")
        if app.target.opportunity_id is not None:
            opp = opportunities.get(app.target.opportunity_id)
            if opp is None:
                raise ContractViolation("unknown_reference", f"application {app.id} targets unknown opportunity")
            _same_org(app.organization_id, opp.organization_id, f"application {app.id} -> opportunity")
        if prog is not None and opp is not None and opp.program_id != prog.id:
            raise ContractViolation(
                "target_program_mismatch", f"application {app.id}: opportunity is not in the targeted program"
            )
        sub = app.submission
        if sub is not None:
            versions = profile_versions.get(sub.profile_id)
            if not versions:
                raise ContractViolation("unknown_reference", f"application {app.id} pins unknown profile")
            if versions[0].candidate_id != app.candidate_id:
                raise ContractViolation(
                    "submission_profile_mismatch", f"application {app.id} pins another candidate's profile"
                )
            if sub.profile_ref.entity != versions[0].source_ref.entity:
                raise ContractViolation(
                    "submission_profile_mismatch",
                    f"application {app.id} profile_ref does not locate profile {sub.profile_id}",
                )
