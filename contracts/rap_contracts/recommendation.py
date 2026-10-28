"""Recommendations, verification results and their lifecycle (D-004.04).

A Recommendation is a suggestion for human follow-up review, never a
placement, hiring, admission, offer or rejection. Verification is a set of
substantive, deterministic checks; a ``passed`` VerificationResult is only
accepted after this module recomputes those checks (``accept_verification``).
Neither a recommendation status nor a verification record authorizes a
human-review write: that requires the trusted reviewer boundary in ``review.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Annotated, Iterable, Literal, Mapping

from pydantic import AwareDatetime, ConfigDict, Field, model_validator

from .claims import ClaimState
from .eligibility import (
    ClaimIdRef,
    EligibilityContext,
    EligibilityDecision,
    EligibilityId,
    EligibilityResult,
    PolicyPin,
    RequirementId,
    eligibility_source_refs,
)
from .evidence import EvidenceId, EvidenceSubjectKind
from .invariants import ContractViolation
from .models import (
    AccessStatus,
    ApplicationId,
    ApplicationStatus,
    CandidateId,
    ComponentId,
    ContractModel,
    OpportunityId,
    OrganizationId,
    SourceCheckResult,
    SourceReference,
    VersionStatus,
    _ID_BODY,
)

RecommendationId = Annotated[str, Field(pattern=rf"^recommendation_{_ID_BODY}$", max_length=64)]
VerificationId = Annotated[str, Field(pattern=rf"^verification_{_ID_BODY}$", max_length=64)]

# ---------------------------------------------------------------------------
# Context binding (owner decision 1)
# ---------------------------------------------------------------------------


class ApplicationContext(ContractModel):
    """Binds a recommendation to one submitted application at an exact source version.

    This is the only context kind in this contract version. Other kinds (for
    example discovery without an application) are NOT representable; adding one
    requires explicit design and must also be added to the reviewable allowlist.
    """

    kind: Literal["application"]
    application_id: ApplicationId
    application_ref: SourceReference


#: Pilot gate: context kinds whose recommendations may enter human review.
PILOT_REVIEWABLE_CONTEXT_KINDS: frozenset[str] = frozenset({"application"})


# ---------------------------------------------------------------------------
# Recommendation lifecycle (owner decision 2)
# ---------------------------------------------------------------------------


class RecommendationStatus(str, Enum):
    PENDING_VERIFICATION = "pending_verification"
    READY_FOR_REVIEW = "ready_for_review"
    ESCALATED = "escalated"
    NEEDS_INFORMATION = "needs_information"
    APPROVED_FOR_FOLLOW_UP = "approved_for_follow_up"
    DISMISSED = "dismissed"
    OBSOLETE = "obsolete"


TERMINAL_STATUSES = frozenset(
    {RecommendationStatus.APPROVED_FOR_FOLLOW_UP, RecommendationStatus.DISMISSED, RecommendationStatus.OBSOLETE}
)


class Trigger(str, Enum):
    """What moves a recommendation. ``system`` triggers are not human review actions."""

    VERIFICATION_PASSED = "verification_passed"  # system
    VERIFICATION_NOT_PASSED = "verification_not_passed"  # system: failed / stale / unresolved
    SOURCES_CHANGED = "sources_changed"  # system
    APPROVE_FOR_FOLLOW_UP = "approve_for_follow_up"  # human
    REQUEST_INFORMATION = "request_information"  # human
    DISMISS_SUGGESTION = "dismiss_suggestion"  # human


HUMAN_TRIGGERS = frozenset({Trigger.APPROVE_FOR_FOLLOW_UP, Trigger.REQUEST_INFORMATION, Trigger.DISMISS_SUGGESTION})

S, T = RecommendationStatus, Trigger
#: The complete legal transition table. Anything absent is forbidden. Terminal
#: statuses have no outgoing transitions; reopening requires a future design.
TRANSITIONS: Mapping[tuple[RecommendationStatus, Trigger], RecommendationStatus] = {
    (S.PENDING_VERIFICATION, T.VERIFICATION_PASSED): S.READY_FOR_REVIEW,
    (S.PENDING_VERIFICATION, T.VERIFICATION_NOT_PASSED): S.ESCALATED,
    (S.PENDING_VERIFICATION, T.SOURCES_CHANGED): S.OBSOLETE,
    (S.READY_FOR_REVIEW, T.APPROVE_FOR_FOLLOW_UP): S.APPROVED_FOR_FOLLOW_UP,
    (S.READY_FOR_REVIEW, T.REQUEST_INFORMATION): S.NEEDS_INFORMATION,
    (S.READY_FOR_REVIEW, T.DISMISS_SUGGESTION): S.DISMISSED,
    (S.READY_FOR_REVIEW, T.SOURCES_CHANGED): S.OBSOLETE,
    (S.ESCALATED, T.REQUEST_INFORMATION): S.NEEDS_INFORMATION,
    (S.ESCALATED, T.DISMISS_SUGGESTION): S.DISMISSED,
    (S.ESCALATED, T.SOURCES_CHANGED): S.OBSOLETE,
    (S.NEEDS_INFORMATION, T.DISMISS_SUGGESTION): S.DISMISSED,
    (S.NEEDS_INFORMATION, T.SOURCES_CHANGED): S.OBSOLETE,
}
del S, T


def next_status(current: RecommendationStatus, trigger: Trigger) -> RecommendationStatus:
    try:
        return TRANSITIONS[(current, trigger)]
    except KeyError:
        raise ContractViolation(
            "forbidden_transition", f"{trigger.value} is not permitted from {current.value}"
        ) from None


class Recommendation(ContractModel):
    """A structured suggestion for coordinator follow-up review. No free-text rationale in this version."""

    id: RecommendationId
    organization_id: OrganizationId
    candidate_id: CandidateId
    opportunity_id: OpportunityId
    opportunity_ref: SourceReference
    context: ApplicationContext
    eligibility_result_id: EligibilityId
    policy: PolicyPin
    supporting_claim_ids: Annotated[tuple[ClaimIdRef, ...], Field(min_length=1)]
    evidence_ids: Annotated[tuple[EvidenceId, ...], Field(min_length=1)]
    requirement_ids: tuple[RequirementId, ...] = ()
    generated_by: ComponentId
    generated_at: AwareDatetime
    status: RecommendationStatus

    @model_validator(mode="after")
    def _consistency(self) -> "Recommendation":
        for ref, name in ((self.opportunity_ref, "opportunity_ref"), (self.policy.source_ref, "policy.source_ref"),
                          (self.context.application_ref, "context.application_ref")):
            if ref.organization_id != self.organization_id:
                raise ValueError(f"{name}.organization_id must equal organization_id")
        for name in ("supporting_claim_ids", "evidence_ids", "requirement_ids"):
            ids = getattr(self, name)
            if len(set(ids)) != len(ids):
                raise ValueError(f"{name} must be unique")
        return self


# ---------------------------------------------------------------------------
# Cross-record checks
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RecommendationContext:
    eligibility: EligibilityContext
    eligibility_results: Mapping[str, EligibilityResult]


def index_eligibility_results(results: Iterable[EligibilityResult]) -> dict[str, EligibilityResult]:
    index: dict[str, EligibilityResult] = {}
    for res in results:
        if res.id in index:
            raise ContractViolation("duplicate_id", f"duplicate eligibility id {res.id}")
        index[res.id] = res
    return index


def check_application_context(rec: Recommendation, ctx: RecommendationContext) -> None:
    """Pilot requirement: grounded in the candidate's own submitted application for this opportunity or its program."""
    if rec.context.kind not in PILOT_REVIEWABLE_CONTEXT_KINDS:
        raise ContractViolation("context_not_reviewable", f"{rec.context.kind} recommendations cannot enter review")
    records = ctx.eligibility.records
    app = next((a for a in records.applications if a.id == rec.context.application_id), None)
    if app is None:
        raise ContractViolation("invalid_application_context", f"{rec.id}: application not found")
    if app.candidate_id != rec.candidate_id or app.organization_id != rec.organization_id:
        raise ContractViolation("invalid_application_context", f"{rec.id}: application belongs to another candidate/org")
    if rec.context.application_ref != app.source_ref:
        raise ContractViolation("invalid_application_context", f"{rec.id}: application version is not the pinned one")
    if app.status is not ApplicationStatus.SUBMITTED:
        raise ContractViolation("invalid_application_context", f"{rec.id}: application is {app.status.value}, not submitted")
    opp = next(o for o in records.opportunities if o.id == rec.opportunity_id)
    targets_opportunity = app.target.opportunity_id == opp.id
    targets_program = app.target.program_id is not None and app.target.program_id == opp.program_id
    if not (targets_opportunity or targets_program):
        raise ContractViolation("invalid_application_context", f"{rec.id}: application does not target {opp.id} or its program")


def check_recommendation(rec: Recommendation, ctx: RecommendationContext) -> None:
    """Deterministic, substantive checks shared by validation and verification acceptance."""
    records = ctx.eligibility.records
    cand = next((c for c in records.candidates if c.id == rec.candidate_id), None)
    opp = next((o for o in records.opportunities if o.id == rec.opportunity_id), None)
    if cand is None or opp is None:
        raise ContractViolation("unknown_reference", f"{rec.id} references unknown candidate/opportunity")
    if not (cand.organization_id == opp.organization_id == rec.organization_id):
        raise ContractViolation("cross_org_reference", f"{rec.id} crosses organizations")
    if rec.opportunity_ref != opp.source_ref:
        raise ContractViolation("opportunity_version_mismatch", f"{rec.id} does not pin the opportunity's version")

    elig = ctx.eligibility_results.get(rec.eligibility_result_id)
    if elig is None:
        raise ContractViolation("unknown_reference", f"{rec.id} references unknown eligibility result")
    if (elig.candidate_id, elig.opportunity_id, elig.organization_id) != (rec.candidate_id, rec.opportunity_id, rec.organization_id):
        raise ContractViolation("eligibility_mismatch", f"{rec.id}: eligibility result is for another candidate/opportunity")
    if elig.decision is not EligibilityDecision.ELIGIBLE:
        raise ContractViolation("not_eligible", f"{rec.id}: eligibility decision is {elig.decision.value}")
    if elig.policy != rec.policy or elig.opportunity_ref != rec.opportunity_ref:
        raise ContractViolation("policy_version_mismatch", f"{rec.id}: policy/opportunity pins differ from the eligibility result")

    check_application_context(rec, ctx)

    claims = {c.id: c for c in ctx.eligibility.claims}
    evidence = ctx.eligibility.evidence
    cited = set(rec.evidence_ids)
    for cid in rec.supporting_claim_ids:
        claim = claims.get(cid)
        if claim is None or claim.candidate_id != rec.candidate_id or claim.organization_id != rec.organization_id:
            raise ContractViolation("invalid_citation", f"{rec.id} cites claim {cid} not about {rec.candidate_id}")
        if claim.state is not ClaimState.DECLARED:
            raise ContractViolation("non_authoritative_input", f"{rec.id}: {cid} is {claim.state.value}, not a source-backed fact")
        missing = set(claim.all_evidence_ids()) - cited
        if missing:
            raise ContractViolation("incomplete_citations", f"{rec.id}: evidence for {cid} not cited: {sorted(missing)}")
    for eid in rec.evidence_ids:
        ev = evidence.get(eid)
        if ev is None:
            raise ContractViolation("invalid_citation", f"{rec.id} cites missing evidence {eid}")
        if ev.organization_id != rec.organization_id:
            raise ContractViolation("cross_org_reference", f"{rec.id} cites evidence {eid} from another organization")
        allowed = {(EvidenceSubjectKind.CANDIDATE, rec.candidate_id), (EvidenceSubjectKind.OPPORTUNITY, rec.opportunity_id)}
        if (ev.subject.kind, ev.subject.id) not in allowed:
            raise ContractViolation("invalid_citation", f"{rec.id}: evidence {eid} is about {ev.subject.id}")
    reqs = {r.id: r for r in ctx.eligibility.requirements}
    for rid in rec.requirement_ids:
        req = reqs.get(rid)
        if req is None or req.opportunity_id != rec.opportunity_id:
            raise ContractViolation("invalid_citation", f"{rec.id} cites requirement {rid} not about {rec.opportunity_id}")


def recommendation_source_refs(rec: Recommendation, ctx: RecommendationContext) -> list[SourceReference]:
    """Every exact source version the recommendation depends on (deduplicated, stable order).

    Fails closed with ``unknown_reference`` if any referenced record is missing.
    """
    reqs = {r.id: r for r in ctx.eligibility.requirements}
    try:
        elig = ctx.eligibility_results[rec.eligibility_result_id]
        refs = [rec.context.application_ref, rec.opportunity_ref, rec.policy.source_ref]
        refs += eligibility_source_refs(elig, ctx.eligibility)
        refs += [ctx.eligibility.evidence[e].source_ref for e in rec.evidence_ids]
        refs += [reqs[r].source_ref for r in rec.requirement_ids]
    except KeyError as exc:
        raise ContractViolation("unknown_reference", f"{rec.id}: dependency {exc} not found") from None
    seen, ordered = set(), []
    for ref in refs:
        if ref not in seen:
            seen.add(ref)
            ordered.append(ref)
    return ordered


# ---------------------------------------------------------------------------
# Verification (owner decision 3)
# ---------------------------------------------------------------------------


class VerificationOutcome(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    STALE = "stale"
    UNRESOLVED = "unresolved"


class CheckStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    UNRESOLVED = "unresolved"


class VerificationCheckCode(str, Enum):
    EVIDENCE_CITATIONS_RESOLVE = "evidence_citations_resolve"
    SUPPORTING_CLAIMS_DECLARED = "supporting_claims_declared"
    ELIGIBILITY_SUPPORTS_RECOMMENDATION = "eligibility_supports_recommendation"
    POLICY_PIN_MATCHES = "policy_pin_matches"
    ORGANIZATION_SCOPE_CONSISTENT = "organization_scope_consistent"
    APPLICATION_CONTEXT_VALID = "application_context_valid"
    SOURCES_CURRENT_AND_ALLOWED = "sources_current_and_allowed"


class VerificationCheck(ContractModel):
    code: VerificationCheckCode
    status: CheckStatus


def derive_outcome(checks: Iterable[VerificationCheck]) -> VerificationOutcome:
    statuses = {c.code: c.status for c in checks}
    substantive = {k: v for k, v in statuses.items() if k is not VerificationCheckCode.SOURCES_CURRENT_AND_ALLOWED}
    if CheckStatus.FAIL in substantive.values():
        return VerificationOutcome.FAILED
    if statuses.get(VerificationCheckCode.SOURCES_CURRENT_AND_ALLOWED) is CheckStatus.FAIL:
        return VerificationOutcome.STALE
    if CheckStatus.UNRESOLVED in statuses.values():
        return VerificationOutcome.UNRESOLVED
    return VerificationOutcome.PASSED


class VerificationResult(ContractModel):
    """Record of substantive checks. Not a score, not model agreement, not authorization."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: VerificationId
    organization_id: OrganizationId
    recommendation_id: RecommendationId
    outcome: VerificationOutcome
    checks: Annotated[tuple[VerificationCheck, ...], Field(min_length=len(VerificationCheckCode))]
    source_checks: Annotated[tuple[SourceCheckResult, ...], Field(min_length=1)]
    verified_by: ComponentId
    verified_at: AwareDatetime

    @model_validator(mode="after")
    def _consistency(self) -> "VerificationResult":
        codes = [c.code for c in self.checks]
        if sorted(codes, key=lambda c: c.value) != sorted(VerificationCheckCode, key=lambda c: c.value):
            raise ValueError("every verification check code must appear exactly once")
        sources_ok = all(sc.version_status is VersionStatus.CURRENT and sc.access_status is AccessStatus.ALLOWED
                         for sc in self.source_checks)
        reported = next(c.status for c in self.checks if c.code is VerificationCheckCode.SOURCES_CURRENT_AND_ALLOWED)
        if (reported is CheckStatus.PASS) != sources_ok:
            raise ValueError("sources_current_and_allowed must reflect the recorded source checks")
        if self.outcome is not derive_outcome(self.checks):
            raise ValueError(f"outcome must be {derive_outcome(self.checks).value} given the checks")
        if any(sc.source.organization_id != self.organization_id for sc in self.source_checks):
            raise ValueError("source checks must be in the verification's organization")
        return self


def accept_verification(verification: VerificationResult, rec: Recommendation, ctx: RecommendationContext) -> None:
    """Accept a verification as grounds for ``ready_for_review`` only after recomputing its substance.

    Raises unless: it is for this recommendation and organization; the verifier
    is not the generating component (necessary, not sufficient); its source
    checks cover exactly the recommendation's dependencies; it is ``passed``;
    and the deterministic recommendation checks pass now.
    """
    if verification.recommendation_id != rec.id or verification.organization_id != rec.organization_id:
        raise ContractViolation("verification_mismatch", "verification is for another recommendation")
    if verification.verified_by == rec.generated_by:
        raise ContractViolation("verification_not_independent", "the generating component cannot verify its own output")
    expected = set(recommendation_source_refs(rec, ctx))
    checked = [sc.source for sc in verification.source_checks]
    if set(checked) != expected or len(checked) != len(expected):
        raise ContractViolation("verification_incomplete", "source checks do not cover exactly the recommendation's dependencies")
    if verification.outcome is not VerificationOutcome.PASSED:
        raise ContractViolation("verification_not_passed", f"verification is {verification.outcome.value}")
    check_recommendation(rec, ctx)  # recompute; a verifier's own report is not proof


def apply_verification(rec: Recommendation, verification: VerificationResult, ctx: RecommendationContext) -> Recommendation:
    """System transition from pending_verification. Anything not acceptable escalates; nothing else reaches ready_for_review."""
    if verification.recommendation_id != rec.id:
        raise ContractViolation("verification_mismatch", "verification is for another recommendation")
    try:
        accept_verification(verification, rec, ctx)
        trigger = Trigger.VERIFICATION_PASSED
    except ContractViolation:
        trigger = Trigger.VERIFICATION_NOT_PASSED
    return rec.model_copy(update={"status": next_status(rec.status, trigger)})
