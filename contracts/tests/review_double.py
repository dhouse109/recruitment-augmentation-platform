"""In-memory TEST DOUBLE of the review-write service boundary.

This is test scaffolding, not a reference implementation. Dicts and lists are
not transactions, the single-threaded flow proves nothing about concurrent
idempotency-key uniqueness, nothing is durable, and mock credentials are not
authentication. It exists only to exercise the portable contracts and the pure
evaluation functions in the order a real Drupal service must apply them:

authenticate -> resolve target -> authorize (human, role, org/program scope) ->
idempotency (replay / conflict) -> pure evaluation (+ live recheck for
approval) -> commit decision + event + status + idempotency record together.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from rap_contracts.recommendation import (
    Recommendation,
    RecommendationContext,
    VerificationResult,
    apply_verification,
)
from rap_contracts.review import (
    AuthenticatedPrincipal,
    ExternalCode,
    HumanReviewCommand,
    OutcomeStatus,
    ReviewAction,
    ReviewCorrectionCommand,
    ReviewerGrant,
    ReviewOutcome,
    ReviewRejected,
    approval_dependencies,
    check_replay,
    check_reviewer_authority,
    collect_live_checks,
    correction_fingerprint,
    evaluate_correction,
    evaluate_review,
    index_reason_vocabularies,
    review_fingerprint,
)

T0 = datetime(2026, 10, 28, 14, 0, tzinfo=timezone.utc)


class MockAuthenticator:
    """MOCK: maps fictional credential strings to principals. Not authentication."""

    def __init__(self, principals: dict[str, AuthenticatedPrincipal]) -> None:
        self.principals = principals

    def authenticate(self, credential: object) -> AuthenticatedPrincipal | None:
        return self.principals.get(credential) if isinstance(credential, str) else None


class MockAuthorizer:
    def __init__(self, grants: dict[str, tuple[ReviewerGrant, ...]]) -> None:
        self.grants = grants

    def grants_for(self, principal: AuthenticatedPrincipal) -> tuple[ReviewerGrant, ...]:
        return self.grants.get(principal.principal_id, ())


class InMemoryReviewService:
    def __init__(self, *, authenticator, authorizer, authority, context: RecommendationContext,
                 recommendations, verifications, reason_vocabularies) -> None:
        self.authenticator, self.authorizer, self.authority, self.context = authenticator, authorizer, authority, context
        self.recommendations: dict[str, Recommendation] = {r.id: r for r in recommendations}
        self.latest_verification: dict[str, VerificationResult] = {}
        self.vocabularies = index_reason_vocabularies(reason_vocabularies)
        self.decisions: dict = {}          # insert-only
        self.events: list = []             # append-only
        self.event_for_decision: dict = {}
        self.superseded: set[str] = set()
        self.idempotency: dict[str, tuple[str, ReviewOutcome]] = {}
        self.replay_log: list[tuple[str, str]] = []      # internal: (key, principal) replays, no effects
        self.rejection_log: list[tuple[str, str]] = []   # internal: (internal code, external code)
        self._tick = 0
        for v in verifications:
            self.record_verification(v)

    # -- system path (not a human review action) ---------------------------
    def record_verification(self, verification: VerificationResult) -> Recommendation:
        rec = self.recommendations[verification.recommendation_id]
        updated = apply_verification(rec, verification, self.context)
        self.latest_verification[rec.id] = verification
        self.recommendations[rec.id] = updated
        return updated

    # -- helpers -------------------------------------------------------------
    def _now(self):
        self._tick += 1
        return T0 + timedelta(minutes=self._tick)

    def _program_of(self, rec: Recommendation):
        return next(o.program_id for o in self.context.eligibility.records.opportunities if o.id == rec.opportunity_id)

    def _reject(self, exc: ReviewRejected) -> ReviewOutcome:
        self.rejection_log.append((exc.code, exc.external.value))
        return ReviewOutcome(status=OutcomeStatus.REJECTED, error=exc.external)

    def _authorize(self, principal, rec):
        if principal is not None and principal.kind == "human" and rec is None:
            raise ReviewRejected("unknown_target", ExternalCode.NOT_PERMITTED, "target not available")
        if rec is None:
            check_reviewer_authority(principal, (), "org_none", None)  # raises unauthenticated / machine origin
            raise ReviewRejected("unknown_target", ExternalCode.NOT_PERMITTED, "target not available")
        grants = self.authorizer.grants_for(principal) if principal is not None else ()
        return check_reviewer_authority(principal, grants, rec.organization_id, self._program_of(rec))

    def _replay_or_none(self, key, fingerprint, principal):
        stored = self.idempotency.get(key)
        if stored is None:
            return None
        check_replay(stored[0], fingerprint)
        self.replay_log.append((key, principal.principal_id))
        prior = stored[1]
        return ReviewOutcome(status=OutcomeStatus.REPLAYED, decision=prior.decision, audit_event_ids=prior.audit_event_ids)

    def _commit(self, key, fingerprint, plan) -> ReviewOutcome:
        outcome = ReviewOutcome(status=OutcomeStatus.RECORDED, decision=plan.decision, audit_event_ids=(plan.event.id,))
        self.decisions[plan.decision.id] = plan.decision
        self.events.append(plan.event)
        self.event_for_decision[plan.decision.id] = plan.event
        self.recommendations[plan.recommendation.id] = plan.recommendation
        self.idempotency[key] = (fingerprint, outcome)
        return outcome

    def _ids(self):
        n = len(self.events) + 1
        return f"review_decision_{n:04d}", f"audit_event_{n:04d}", n

    # -- ReviewWriteService --------------------------------------------------
    def submit_review(self, credential: object, command: HumanReviewCommand) -> ReviewOutcome:
        try:
            principal = self.authenticator.authenticate(credential)
            rec = self.recommendations.get(command.recommendation_id)
            grant = self._authorize(principal, rec)
            fingerprint = review_fingerprint(command, principal, rec)
            replay = self._replay_or_none(command.idempotency_key, fingerprint, principal)
            if replay is not None:
                return replay
            live = None
            if command.action is ReviewAction.APPROVE_FOR_FOLLOW_UP:
                live = collect_live_checks(approval_dependencies(rec, self.context), self.authority, principal.principal_id)
            decision_id, event_id, seq = self._ids()
            plan = evaluate_review(
                command=command, principal=principal, grant=grant, recommendation=rec,
                latest_verification=self.latest_verification.get(rec.id), context=self.context,
                reason_vocabularies=self.vocabularies, live_checks=live, fingerprint=fingerprint,
                decision_id=decision_id, event_id=event_id, sequence=seq, now=self._now())
            return self._commit(command.idempotency_key, fingerprint, plan)
        except ReviewRejected as exc:
            return self._reject(exc)

    def submit_correction(self, credential: object, command: ReviewCorrectionCommand) -> ReviewOutcome:
        try:
            principal = self.authenticator.authenticate(credential)
            prior = self.decisions.get(command.corrects_decision_id)
            rec = self.recommendations.get(prior.recommendation_id) if prior is not None else None
            grant = self._authorize(principal, rec)
            fingerprint = correction_fingerprint(command, principal, prior)
            replay = self._replay_or_none(command.idempotency_key, fingerprint, principal)
            if replay is not None:
                return replay
            decision_id, event_id, seq = self._ids()
            plan = evaluate_correction(
                command=command, principal=principal, grant=grant, prior=prior,
                prior_event=self.event_for_decision[prior.id], prior_superseded=prior.id in self.superseded,
                recommendation=rec, reason_vocabularies=self.vocabularies, fingerprint=fingerprint,
                decision_id=decision_id, event_id=event_id, sequence=seq, now=self._now())
            outcome = self._commit(command.idempotency_key, fingerprint, plan)
            self.superseded.add(prior.id)
            return outcome
        except ReviewRejected as exc:
            return self._reject(exc)
