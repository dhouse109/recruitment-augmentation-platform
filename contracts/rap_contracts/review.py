"""Human review authority, structured reasons, idempotency and audit (D-004.03, .08, .09).

Layering (owner engineering decision 2):

* **Contracts** -- client commands (no identity fields), trusted principal and
  grant shapes, reason vocabulary, ReviewDecision, AuditEvent, ReviewOutcome.
* **Pure evaluation** -- ``evaluate_review`` / ``evaluate_correction`` decide a
  command given already-resolved inputs. No I/O, no storage, no clocks.
* **Boundary protocols** -- ``Authenticator``, ``Authorizer`` and
  ``ReviewWriteService`` describe the future authoritative Drupal service. The
  only implementation in this repository is an in-memory TEST DOUBLE
  (``tests/review_double.py``), which proves nothing about transactions,
  concurrency, authentication or durable append-only storage.

Approval for follow-up authorizes investigation or outreach planning only. No
action here represents placement, hiring, admission, an offer or rejection, and
no action sends communications.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Annotated, Iterable, Literal, Mapping, Protocol

from pydantic import AwareDatetime, ConfigDict, Field, model_validator

from .claims import RESTRICTED_ATTRIBUTE_TOKENS, restricted_tokens
from .eligibility import EligibilityId, PolicyPin
from .invariants import ContractViolation
from .models import (
    ComponentId,
    ContractModel,
    OrganizationId,
    ProgramId,
    SourceCheckResult,
    SourceReference,
    _ID_BODY,
)
from .recommendation import (
    Recommendation,
    RecommendationContext,
    RecommendationId,
    RecommendationStatus,
    Trigger,
    VerificationId,
    VerificationResult,
    accept_verification,
    check_recommendation,
    next_status,
    recommendation_source_refs,
)
from .source_checks import SourceAuthority, checked, require_current_and_allowed

PrincipalId = Annotated[str, Field(pattern=rf"^principal_{_ID_BODY}$", max_length=64)]
DecisionId = Annotated[str, Field(pattern=rf"^review_decision_{_ID_BODY}$", max_length=80)]
AuditEventId = Annotated[str, Field(pattern=rf"^audit_event_{_ID_BODY}$", max_length=80)]
ReasonVocabularyId = Annotated[str, Field(pattern=rf"^review_reasons_{_ID_BODY}$", max_length=64)]
ReasonCode = Annotated[str, Field(pattern=r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$", max_length=64)]
IdempotencyKey = Annotated[
    str, Field(pattern=r"^[A-Za-z0-9_-]{16,128}$", description="Client-generated opaque request identity.")
]
FreeText = Annotated[
    str,
    Field(
        min_length=1,
        max_length=2000,
        pattern=r"^[^\x00-\x08\x0b\x0c\x0e-\x1f\x7f]+$",
        description="Reviewer-authored text. Stored only on ReviewDecision; never in audit events, evidence, chunks, claims or prompts.",
    ),
]
RoleLabel = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")]

#: The only role that may record review actions in this contract version.
REVIEW_ROLE = "program_coordinator"


class ReviewAction(str, Enum):
    """ADR-0004 vocabulary. The legacy ``reject_suggestion`` is intentionally absent."""

    APPROVE_FOR_FOLLOW_UP = "approve_for_follow_up"
    REQUEST_INFORMATION = "request_information"
    DISMISS_SUGGESTION = "dismiss_suggestion"


ACTION_TRIGGERS = {
    ReviewAction.APPROVE_FOR_FOLLOW_UP: Trigger.APPROVE_FOR_FOLLOW_UP,
    ReviewAction.REQUEST_INFORMATION: Trigger.REQUEST_INFORMATION,
    ReviewAction.DISMISS_SUGGESTION: Trigger.DISMISS_SUGGESTION,
}

# ---------------------------------------------------------------------------
# Structured reasons (D-004.09)
# ---------------------------------------------------------------------------

#: Defense-in-depth screen for reason codes and free text. Not exhaustive.
ACCUSATORY_TOKENS: frozenset[str] = frozenset(
    {"cheat", "cheated", "cheating", "dishonest", "fake", "faked", "fraud", "fraudulent", "liar", "lied", "lying",
     "scam", "suspicious", "untrustworthy"}
)
_EMAIL = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+")
_PHONE = re.compile(r"(?:\+?\d[\s().-]*){7,}")


class CommentRule(str, Enum):
    FORBIDDEN = "forbidden"
    OPTIONAL = "optional"
    REQUIRED = "required"


class ReasonDefinition(ContractModel):
    code: ReasonCode
    actions: Annotated[frozenset[ReviewAction], Field(min_length=1)]
    comment: CommentRule


class ReviewReasonVocabulary(ContractModel):
    """Versioned, organization-scoped allowlist of review reason codes."""

    id: ReasonVocabularyId
    organization_id: OrganizationId
    version: Annotated[int, Field(ge=1)]
    reasons: Annotated[tuple[ReasonDefinition, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def _consistency(self) -> "ReviewReasonVocabulary":
        codes = [r.code for r in self.reasons]
        if len(set(codes)) != len(codes):
            raise ValueError("reason codes must be unique within a vocabulary version")
        for code in codes:
            hit = restricted_tokens(code) | (set(code.split("_")) & ACCUSATORY_TOKENS)
            if hit:
                raise ValueError(f"reason code {code!r} uses restricted or accusatory terms {sorted(hit)}")
        if any(ReviewAction.DISMISS_SUGGESTION in r.actions and r.comment is not CommentRule.REQUIRED for r in self.reasons):
            raise ValueError("every dismissal reason must require an explanatory comment")
        return self

    def get(self, code: str) -> ReasonDefinition | None:
        return next((r for r in self.reasons if r.code == code), None)


class ReasonPin(ContractModel):
    vocabulary_id: ReasonVocabularyId
    vocabulary_version: Annotated[int, Field(ge=1)]
    code: ReasonCode


def index_reason_vocabularies(vocabularies: Iterable[ReviewReasonVocabulary]) -> dict[tuple[str, int], ReviewReasonVocabulary]:
    index: dict[tuple[str, int], ReviewReasonVocabulary] = {}
    for vocab in vocabularies:
        pin = (vocab.id, vocab.version)
        prior = index.get(pin)
        if prior is not None and prior != vocab:
            raise ContractViolation("vocabulary_version_conflict", f"{vocab.id} v{vocab.version} has two different definitions")
        index[pin] = vocab
    return index


# ---------------------------------------------------------------------------
# Client commands: no reviewer id, role or actor_type fields (extra=forbid)
# ---------------------------------------------------------------------------


class HumanReviewCommand(ContractModel):
    idempotency_key: IdempotencyKey
    recommendation_id: RecommendationId
    verification_id: VerificationId
    action: ReviewAction
    reason: ReasonPin
    comment: FreeText | None = None


class ReviewCorrectionCommand(ContractModel):
    """Amends the reason/comment of a prior decision. Cannot change or reverse the action."""

    idempotency_key: IdempotencyKey
    corrects_decision_id: DecisionId
    reason: ReasonPin
    comment: FreeText | None = None
    correction_note: FreeText


# ---------------------------------------------------------------------------
# Trusted, server-derived identity (never deserialized from a client payload)
# ---------------------------------------------------------------------------


class AuthenticatedPrincipal(ContractModel):
    principal_id: PrincipalId
    kind: Literal["human", "service"]
    authenticated_by: ComponentId
    authenticated_at: AwareDatetime


class ReviewerGrant(ContractModel):
    """A server-side authorization grant. ``program_id=None`` means organization-wide."""

    organization_id: OrganizationId
    program_id: ProgramId | None = None
    role: RoleLabel


class Authenticator(Protocol):
    def authenticate(self, credential: object) -> AuthenticatedPrincipal | None: ...


class Authorizer(Protocol):
    def grants_for(self, principal: AuthenticatedPrincipal) -> tuple[ReviewerGrant, ...]: ...


# ---------------------------------------------------------------------------
# Persisted outputs
# ---------------------------------------------------------------------------


class ReviewDecision(ContractModel):
    """Authoritative-to-be review record. Reviewer fields are written from trusted context only."""

    model_config = ConfigDict(extra="forbid", frozen=True, json_schema_extra={"allOf": [
        {"if": {"properties": {"corrects_decision_id": {"type": "string"}}, "required": ["corrects_decision_id"]},
         "then": {"required": ["correction_note"], "properties": {"correction_note": {"type": "string"}}}},
        {"if": {"properties": {"correction_note": {"type": "string"}}, "required": ["correction_note"]},
         "then": {"required": ["corrects_decision_id"], "properties": {"corrects_decision_id": {"type": "string"}}}},
    ]})

    id: DecisionId
    organization_id: OrganizationId
    recommendation_id: RecommendationId
    verification_id: VerificationId
    action: ReviewAction
    reason: ReasonPin
    comment: FreeText | None = None
    reviewer_principal_id: PrincipalId
    reviewer_role: RoleLabel
    decided_at: AwareDatetime
    idempotency_key: IdempotencyKey
    payload_fingerprint: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    rechecked_source_refs: tuple[SourceReference, ...] = ()
    recommendation_status_after: RecommendationStatus
    corrects_decision_id: DecisionId | None = None
    correction_note: FreeText | None = None

    @model_validator(mode="after")
    def _consistency(self) -> "ReviewDecision":
        if (self.corrects_decision_id is None) != (self.correction_note is None):
            raise ValueError("corrections require both corrects_decision_id and correction_note")
        if self.action is ReviewAction.APPROVE_FOR_FOLLOW_UP and self.corrects_decision_id is None and not self.rechecked_source_refs:
            raise ValueError("an approval must record the source versions rechecked at the write boundary")
        if any(r.organization_id != self.organization_id for r in self.rechecked_source_refs):
            raise ValueError("rechecked sources must be in the decision's organization")
        return self


class AuditEventType(str, Enum):
    REVIEW_DECISION_RECORDED = "review_decision_recorded"
    REVIEW_DECISION_CORRECTED = "review_decision_corrected"


class AuditEvent(ContractModel):
    """Append-only lineage record. Carries codes and references, never free text."""

    model_config = ConfigDict(extra="forbid", frozen=True, json_schema_extra={"allOf": [{
        "if": {"properties": {"event_type": {"const": "review_decision_corrected"}}, "required": ["event_type"]},
        "then": {"required": ["corrects_decision_id", "prior_event_id"],
                 "properties": {"corrects_decision_id": {"type": "string"}, "prior_event_id": {"type": "string"}}},
        "else": {"properties": {"corrects_decision_id": {"type": "null"}, "prior_event_id": {"type": "null"}}},
    }]})

    id: AuditEventId
    organization_id: OrganizationId
    sequence: Annotated[int, Field(ge=1)]
    event_type: AuditEventType
    occurred_at: AwareDatetime
    actor_principal_id: PrincipalId
    actor_kind: Literal["human"]
    actor_role: RoleLabel
    action: ReviewAction
    reason: ReasonPin
    decision_id: DecisionId
    recommendation_id: RecommendationId
    verification_id: VerificationId
    eligibility_result_id: EligibilityId
    policy: PolicyPin
    application_ref: SourceReference
    opportunity_ref: SourceReference
    rechecked_source_refs: tuple[SourceReference, ...] = ()
    recommendation_status_after: RecommendationStatus
    corrects_decision_id: DecisionId | None = None
    prior_event_id: AuditEventId | None = None

    @model_validator(mode="after")
    def _lineage(self) -> "AuditEvent":
        corrected = self.event_type is AuditEventType.REVIEW_DECISION_CORRECTED
        if corrected != (self.corrects_decision_id is not None) or corrected != (self.prior_event_id is not None):
            raise ValueError("correction events (and only they) reference the corrected decision and prior event")
        return self


class ExternalCode(str, Enum):
    """Caller-visible rejection codes. Nonexistent and unauthorized targets are indistinguishable."""

    UNAUTHENTICATED = "unauthenticated"
    NOT_PERMITTED = "not_permitted"
    INVALID_COMMAND = "invalid_command"
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"
    INVALID_STATE = "invalid_state"
    REVIEW_STALE = "review_stale"


class OutcomeStatus(str, Enum):
    RECORDED = "recorded"  # a new decision and event were committed
    REPLAYED = "replayed"  # same key + same semantic payload: prior result, no new effects
    REJECTED = "rejected"


class ReviewOutcome(ContractModel):
    model_config = ConfigDict(extra="forbid", frozen=True, json_schema_extra={"allOf": [{
        "if": {"properties": {"status": {"const": "rejected"}}, "required": ["status"]},
        "then": {"required": ["error"], "properties": {"error": {"type": "string"}, "decision": {"type": "null"},
                                                        "audit_event_ids": {"maxItems": 0}}},
        "else": {"required": ["decision", "audit_event_ids"],
                 "properties": {"decision": {"type": "object"}, "error": {"type": "null"}, "audit_event_ids": {"minItems": 1}}},
    }]})

    status: OutcomeStatus
    decision: ReviewDecision | None = None
    audit_event_ids: tuple[AuditEventId, ...] = ()
    error: ExternalCode | None = None

    @model_validator(mode="after")
    def _consistency(self) -> "ReviewOutcome":
        rejected = self.status is OutcomeStatus.REJECTED
        if rejected != (self.error is not None) or rejected == (self.decision is not None):
            raise ValueError("rejected outcomes carry an error and no decision; others carry a decision and no error")
        if not rejected and not self.audit_event_ids:
            raise ValueError("recorded/replayed outcomes reference their audit events")
        if rejected and self.audit_event_ids:
            raise ValueError("rejected outcomes have no audit events")
        return self


class ReviewWriteService(Protocol):
    """Interface for the future authoritative Drupal review-write service.

    Required of a real implementation (NOT demonstrated here): authentication
    from the Drupal session; authorization from Drupal permissions; one atomic
    transaction for decision + event + recommendation status + idempotency
    record; a database-enforced unique idempotency key safe under concurrency;
    durable append-only event storage; and retention per a future policy.
    """

    def submit_review(self, credential: object, command: HumanReviewCommand) -> ReviewOutcome: ...

    def submit_correction(self, credential: object, command: ReviewCorrectionCommand) -> ReviewOutcome: ...


# ---------------------------------------------------------------------------
# Pure evaluation
# ---------------------------------------------------------------------------


class ReviewRejected(ContractViolation):
    """Internal reason (``code``) plus the caller-visible ``external`` code."""

    def __init__(self, code: str, external: ExternalCode, message: str) -> None:
        super().__init__(code, message)
        self.external = external


def check_reviewer_authority(
    principal: AuthenticatedPrincipal | None,
    grants: Iterable[ReviewerGrant],
    organization_id: str,
    program_id: str | None,
) -> ReviewerGrant:
    """Server-side authority check. Client-supplied identity never reaches this function."""
    if principal is None:
        raise ReviewRejected("unauthenticated", ExternalCode.UNAUTHENTICATED, "no authenticated principal")
    if principal.kind != "human":
        raise ReviewRejected("machine_origin_forbidden", ExternalCode.NOT_PERMITTED, "only a human may record review actions")
    grants = list(grants)
    in_org = [g for g in grants if g.organization_id == organization_id]
    covering = [g for g in in_org if g.program_id is None or g.program_id == program_id]
    for grant in covering:
        if grant.role == REVIEW_ROLE:
            return grant
    if covering:
        raise ReviewRejected("role_not_permitted", ExternalCode.NOT_PERMITTED, "grant does not carry the coordinator role")
    raise ReviewRejected("scope_not_permitted", ExternalCode.NOT_PERMITTED, "no grant covers this organization/program")


def screen_free_text(text: str, field: str) -> None:
    """Defense-in-depth only: cannot detect every accusation or sensitive detail."""
    tokens = set(re.findall(r"[a-z]+", text.lower()))
    hits = (tokens & RESTRICTED_ATTRIBUTE_TOKENS) | (tokens & ACCUSATORY_TOKENS)
    if hits:
        raise ReviewRejected("comment_rejected", ExternalCode.INVALID_COMMAND,
                             f"{field} contains restricted or accusatory terms {sorted(hits)}")
    if _EMAIL.search(text) or _PHONE.search(text):
        raise ReviewRejected("comment_rejected", ExternalCode.INVALID_COMMAND, f"{field} contains contact details")


def check_reason(
    reason: ReasonPin,
    action: ReviewAction,
    comment: str | None,
    vocabularies: Mapping[tuple[str, int], ReviewReasonVocabulary],
    organization_id: str,
) -> ReasonDefinition:
    vocab = vocabularies.get((reason.vocabulary_id, reason.vocabulary_version))
    if vocab is None or vocab.organization_id != organization_id:
        raise ReviewRejected("unknown_reason_vocabulary", ExternalCode.INVALID_COMMAND, "reason vocabulary not available")
    definition = vocab.get(reason.code)
    if definition is None:
        raise ReviewRejected("unknown_reason_code", ExternalCode.INVALID_COMMAND, f"{reason.code} is not in the vocabulary")
    if action not in definition.actions:
        raise ReviewRejected("reason_not_for_action", ExternalCode.INVALID_COMMAND, f"{reason.code} is not valid for {action.value}")
    if definition.comment is CommentRule.REQUIRED and comment is None:
        raise ReviewRejected("comment_required", ExternalCode.INVALID_COMMAND, f"{reason.code} requires an explanation")
    if definition.comment is CommentRule.FORBIDDEN and comment is not None:
        raise ReviewRejected("comment_forbidden", ExternalCode.INVALID_COMMAND, f"{reason.code} does not accept a comment")
    if comment is not None:
        screen_free_text(comment, "comment")
    return definition


def _fingerprint(payload: dict) -> str:
    data = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(data.encode("utf-8")).hexdigest()


def review_fingerprint(command: HumanReviewCommand, principal: AuthenticatedPrincipal, rec: Recommendation) -> str:
    """Semantic identity of a review command (transport fields and the key itself excluded)."""
    return _fingerprint({
        "kind": "review",
        "command": command.model_dump(mode="json", exclude={"idempotency_key"}),
        "reviewer_principal_id": principal.principal_id,
        "organization_id": rec.organization_id,
        "pins": {
            "eligibility_result_id": rec.eligibility_result_id,
            "policy": rec.policy.model_dump(mode="json"),
            "application_ref": rec.context.application_ref.model_dump(mode="json"),
            "opportunity_ref": rec.opportunity_ref.model_dump(mode="json"),
        },
    })


def correction_fingerprint(command: ReviewCorrectionCommand, principal: AuthenticatedPrincipal, prior: ReviewDecision) -> str:
    return _fingerprint({
        "kind": "correction",
        "command": command.model_dump(mode="json", exclude={"idempotency_key"}),
        "reviewer_principal_id": principal.principal_id,
        "organization_id": prior.organization_id,
        "corrected_fingerprint": prior.payload_fingerprint,
    })


def check_replay(stored_fingerprint: str, fingerprint: str) -> None:
    if stored_fingerprint != fingerprint:
        raise ReviewRejected("idempotency_conflict", ExternalCode.IDEMPOTENCY_CONFLICT,
                             "idempotency key reused with a different semantic payload or reviewer")


def approval_dependencies(rec: Recommendation, context: RecommendationContext) -> list[SourceReference]:
    """Dependencies to recheck for approval; an unresolvable dependency blocks the write (fail closed)."""
    try:
        return recommendation_source_refs(rec, context)
    except ContractViolation as exc:
        raise ReviewRejected(exc.code, ExternalCode.REVIEW_STALE, str(exc)) from None


def collect_live_checks(
    refs: Iterable[SourceReference], authority: SourceAuthority, principal_id: str
) -> dict[SourceReference, SourceCheckResult | ContractViolation]:
    """Boundary helper (performs authority calls): one live check per dependency for the reviewer."""
    out: dict[SourceReference, SourceCheckResult | ContractViolation] = {}
    for ref in refs:
        try:
            out[ref] = checked(authority, principal_id, ref)
        except ContractViolation as exc:
            out[ref] = exc
    return out


@dataclass(frozen=True)
class ReviewPlan:
    """Effects a write service must commit atomically. Produced by pure evaluation."""

    decision: ReviewDecision
    event: AuditEvent
    recommendation: Recommendation


def _event(event_id, sequence, decision, rec, principal, grant, event_type, prior_event_id=None) -> AuditEvent:
    return AuditEvent(
        id=event_id, organization_id=rec.organization_id, sequence=sequence, event_type=event_type,
        occurred_at=decision.decided_at, actor_principal_id=principal.principal_id, actor_kind="human",
        actor_role=grant.role, action=decision.action, reason=decision.reason, decision_id=decision.id,
        recommendation_id=rec.id, verification_id=decision.verification_id,
        eligibility_result_id=rec.eligibility_result_id, policy=rec.policy,
        application_ref=rec.context.application_ref, opportunity_ref=rec.opportunity_ref,
        rechecked_source_refs=decision.rechecked_source_refs,
        recommendation_status_after=decision.recommendation_status_after,
        corrects_decision_id=decision.corrects_decision_id, prior_event_id=prior_event_id,
    )


def evaluate_review(
    *,
    command: HumanReviewCommand,
    principal: AuthenticatedPrincipal,
    grant: ReviewerGrant,
    recommendation: Recommendation,
    latest_verification: VerificationResult | None,
    context: RecommendationContext,
    reason_vocabularies: Mapping[tuple[str, int], ReviewReasonVocabulary],
    live_checks: Mapping[SourceReference, SourceCheckResult | ContractViolation] | None,
    fingerprint: str,
    decision_id: str,
    event_id: str,
    sequence: int,
    now,
) -> ReviewPlan:
    """Decide a new (non-replay) review command whose reviewer authority is already established.

    Order: transition legality -> reason/comment -> verification currency ->
    (approve only) verification acceptance, recommendation checks, live
    recheck of every dependency for this reviewer.
    """
    rec = recommendation
    trigger = ACTION_TRIGGERS[command.action]
    try:
        new_status = next_status(rec.status, trigger)
    except ContractViolation as exc:
        raise ReviewRejected(exc.code, ExternalCode.INVALID_STATE, str(exc)) from None
    check_reason(command.reason, command.action, command.comment, reason_vocabularies, rec.organization_id)
    if latest_verification is None or command.verification_id != latest_verification.id:
        raise ReviewRejected("verification_mismatch", ExternalCode.INVALID_COMMAND,
                             "command does not reference the recommendation's current verification")

    rechecked: tuple[SourceReference, ...] = ()
    if command.action is ReviewAction.APPROVE_FOR_FOLLOW_UP:
        try:
            accept_verification(latest_verification, rec, context)  # recomputes check_recommendation
            check_recommendation(rec, context)
        except ContractViolation as exc:
            raise ReviewRejected(exc.code, ExternalCode.REVIEW_STALE, str(exc)) from None
        deps = approval_dependencies(rec, context)
        if live_checks is None or set(deps) - set(live_checks):
            raise ReviewRejected("live_recheck_incomplete", ExternalCode.REVIEW_STALE, "every dependency must be rechecked live")
        for ref in deps:
            result = live_checks[ref]
            if isinstance(result, ContractViolation):
                raise ReviewRejected(result.code, ExternalCode.REVIEW_STALE, str(result))
            try:
                require_current_and_allowed(result)
            except ContractViolation as exc:
                raise ReviewRejected(exc.code, ExternalCode.REVIEW_STALE, str(exc)) from None
        rechecked = tuple(deps)

    decision = ReviewDecision(
        id=decision_id, organization_id=rec.organization_id, recommendation_id=rec.id,
        verification_id=command.verification_id, action=command.action, reason=command.reason,
        comment=command.comment, reviewer_principal_id=principal.principal_id, reviewer_role=grant.role,
        decided_at=now, idempotency_key=command.idempotency_key, payload_fingerprint=fingerprint,
        rechecked_source_refs=rechecked, recommendation_status_after=new_status,
    )
    event = _event(event_id, sequence, decision, rec, principal, grant, AuditEventType.REVIEW_DECISION_RECORDED)
    return ReviewPlan(decision, event, rec.model_copy(update={"status": new_status}))


def evaluate_correction(
    *,
    command: ReviewCorrectionCommand,
    principal: AuthenticatedPrincipal,
    grant: ReviewerGrant,
    prior: ReviewDecision,
    prior_event: AuditEvent,
    prior_superseded: bool,
    recommendation: Recommendation,
    reason_vocabularies: Mapping[tuple[str, int], ReviewReasonVocabulary],
    fingerprint: str,
    decision_id: str,
    event_id: str,
    sequence: int,
    now,
) -> ReviewPlan:
    """Amend reason/comment as a NEW linked decision. Action and recommendation status are unchanged."""
    if prior_superseded:
        raise ReviewRejected("correction_target_superseded", ExternalCode.INVALID_STATE,
                             "correct the latest decision in the chain")
    if prior_event.decision_id != prior.id:
        raise ReviewRejected("lineage_mismatch", ExternalCode.INVALID_STATE, "prior event does not belong to the decision")
    check_reason(command.reason, prior.action, command.comment, reason_vocabularies, prior.organization_id)
    screen_free_text(command.correction_note, "correction_note")
    decision = ReviewDecision(
        id=decision_id, organization_id=prior.organization_id, recommendation_id=prior.recommendation_id,
        verification_id=prior.verification_id, action=prior.action, reason=command.reason,
        comment=command.comment, reviewer_principal_id=principal.principal_id, reviewer_role=grant.role,
        decided_at=now, idempotency_key=command.idempotency_key, payload_fingerprint=fingerprint,
        recommendation_status_after=prior.recommendation_status_after,
        corrects_decision_id=prior.id, correction_note=command.correction_note,
    )
    event = _event(event_id, sequence, decision, recommendation, principal, grant,
                   AuditEventType.REVIEW_DECISION_CORRECTED, prior_event_id=prior_event.id)
    return ReviewPlan(decision, event, recommendation)
