"""D-004.03 / .08 / .09 -- human review authority, idempotency, audit and structured reasons.

Every service test runs against tests/review_double.py, an in-memory TEST DOUBLE
with MOCK authentication, authorization and source authority. These tests show
contract semantics and check ordering only; they prove nothing about real
authentication, database transactions, concurrent idempotency-key uniqueness
or durable append-only storage.
"""

import copy
import dataclasses
import json
import unittest

from pydantic import ValidationError

import support
from rap_contracts.evidence import DenialCode, EvidenceRecord, RetrievalChunk, RetrievalRequest, admit_chunks, check_evidence_records, index_evidence
from rap_contracts.invariants import ContractViolation
from rap_contracts.models import AccessStatus, VersionStatus
from rap_contracts.recommendation import RecommendationStatus, VerificationResult, recommendation_source_refs
from rap_contracts.review import (
    AuditEvent,
    ExternalCode,
    HumanReviewCommand,
    OutcomeStatus,
    ReviewAction,
    ReviewCorrectionCommand,
    ReviewDecision,
    ReviewReasonVocabulary,
    index_reason_vocabularies,
    review_fingerprint,
)

COORD = "credential-demo-coordinator"
REC = "recommendation_a_data"
ESC = "recommendation_a_web"  # escalated: verification failed


def cmd(**kw):
    return support.review_command(**kw)


class Harness(unittest.TestCase):
    def setUp(self):
        self.svc = support.review_service()
        self.auth = self.svc.authority

    def assert_recorded(self, outcome, status_after):
        self.assertIs(outcome.status, OutcomeStatus.RECORDED, outcome)
        self.assertIs(outcome.decision.recommendation_status_after, status_after)
        return outcome.decision

    def assert_rejected(self, outcome, external):
        self.assertIs(outcome.status, OutcomeStatus.REJECTED)
        self.assertIs(outcome.error, external)
        self.assertIsNone(outcome.decision)

    def assert_no_effects(self, rec_id=REC, status=RecommendationStatus.READY_FOR_REVIEW):
        self.assertEqual(self.svc.events, [])
        self.assertEqual(self.svc.decisions, {})
        self.assertIs(self.svc.recommendations[rec_id].status, status)


class AuthorizedApprovalTests(Harness):
    def test_coordinator_approves_verified_eligible_recommendation(self):
        out = self.svc.submit_review(COORD, cmd())
        decision = self.assert_recorded(out, RecommendationStatus.APPROVED_FOR_FOLLOW_UP)
        self.assertEqual(decision.reviewer_principal_id, "principal_demo_coordinator")  # server-derived
        self.assertEqual(decision.reviewer_role, "program_coordinator")
        self.assertIsNone(decision.comment)  # routine approval needs no free text
        rec = self.svc.recommendations[REC]
        self.assertEqual(set(decision.rechecked_source_refs), set(recommendation_source_refs(rec, self.svc.context)))
        (event,) = self.svc.events
        self.assertEqual((event.decision_id, event.actor_principal_id, event.action.value, event.sequence),
                         (decision.id, "principal_demo_coordinator", "approve_for_follow_up", 1))
        self.assertEqual(event.application_ref, rec.context.application_ref)
        self.assertEqual(event.eligibility_result_id, "eligibility_a_data")
        self.assertIs(rec.status, RecommendationStatus.APPROVED_FOR_FOLLOW_UP)

    def test_live_recheck_runs_for_every_dependency_for_this_reviewer(self):
        self.svc.submit_review(COORD, cmd())
        rec = self.svc.recommendations[REC]
        self.assertEqual(set(self.auth.calls), set(recommendation_source_refs(rec, self.svc.context)))

    def test_org_wide_grant_may_approve(self):
        svc = support.review_service(authority=support.scenario_authority("principal_demo_org_lead"))
        self.assert_recorded(svc.submit_review("credential-demo-org-lead", cmd()), RecommendationStatus.APPROVED_FOR_FOLLOW_UP)

    def test_other_org_coordinator_approves_own_org(self):
        svc = support.review_service(authority=support.scenario_authority("principal_lantern_coordinator"))
        out = svc.submit_review("credential-lantern-coordinator",
                                cmd(recommendation_id="recommendation_c_job", vocabulary=("review_reasons_lantern", 1)))
        self.assert_recorded(out, RecommendationStatus.APPROVED_FOR_FOLLOW_UP)

    def test_action_vocabulary_is_follow_up_only(self):
        self.assertEqual({a.value for a in ReviewAction}, {"approve_for_follow_up", "request_information", "dismiss_suggestion"})
        for legacy in ("reject_suggestion", "reject_candidate", "place", "hire", "offer", "admit", "send_outreach"):
            with self.subTest(action=legacy), self.assertRaises(ValidationError):
                HumanReviewCommand.model_validate({**cmd().model_dump(mode="json"), "action": legacy})


class AuthorityTests(Harness):
    def _reject(self, credential, external, command=None):
        out = self.svc.submit_review(credential, command or cmd())
        self.assert_rejected(out, external)
        self.assert_no_effects()
        return out

    def test_unauthenticated(self):
        for credential in (None, "", "credential-unknown", 12345):
            with self.subTest(credential=credential):
                self._reject(credential, ExternalCode.UNAUTHENTICATED)

    def test_machine_origin_with_coordinator_grant_rejected(self):
        self._reject("credential-demo-pipeline", ExternalCode.NOT_PERMITTED)
        self.assertEqual(self.svc.rejection_log[-1][0], "machine_origin_forbidden")

    def test_wrong_role_and_wrong_program_and_wrong_org(self):
        for credential, internal in (("credential-demo-viewer", "role_not_permitted"),
                                     ("credential-demo-other-program", "scope_not_permitted"),
                                     ("credential-lantern-coordinator", "scope_not_permitted")):
            with self.subTest(credential=credential):
                self._reject(credential, ExternalCode.NOT_PERMITTED)
                self.assertEqual(self.svc.rejection_log[-1][0], internal)

    def test_client_supplied_identity_cannot_be_submitted(self):
        base = cmd().model_dump(mode="json")
        for key, value in (("reviewer_id", "principal_demo_coordinator"), ("actor_type", "human"),
                           ("role", "program_coordinator"), ("principal_id", "principal_demo_coordinator"),
                           ("organization_id", "org_demo_001"), ("authorized", True)):
            with self.subTest(key=key), self.assertRaises(ValidationError):
                HumanReviewCommand.model_validate({**base, key: value})

    def test_nonexistent_and_unauthorized_targets_are_indistinguishable(self):
        missing = self.svc.submit_review(COORD, cmd(recommendation_id="recommendation_does_not_exist"))
        foreign = self.svc.submit_review(COORD, cmd(recommendation_id="recommendation_c_job", key="key-demo-0000000002",
                                                    vocabulary=("review_reasons_lantern", 1)))
        self.assertEqual(missing.model_dump(), foreign.model_dump())
        self.assertIs(missing.error, ExternalCode.NOT_PERMITTED)


class VerificationGateTests(Harness):
    def test_escalated_recommendation_cannot_be_approved(self):
        self.assertIs(self.svc.recommendations[ESC].status, RecommendationStatus.ESCALATED)
        out = self.svc.submit_review(COORD, cmd(recommendation_id=ESC))
        self.assert_rejected(out, ExternalCode.INVALID_STATE)
        self.assert_no_effects(ESC, RecommendationStatus.ESCALATED)

    def test_stale_or_unresolved_verification_escalates(self):
        for outcome, mutate in (
            ("stale", lambda d: (d["source_checks"][0].update(version_status="superseded"),
                                 next(c for c in d["checks"] if c["code"] == "sources_current_and_allowed").update(status="fail"))),
            ("unresolved", lambda d: next(c for c in d["checks"] if c["code"] == "supporting_claims_declared").update(status="unresolved")),
        ):
            doc = support.review_raw()
            ver = next(v for v in doc["verifications"] if v["id"] == "verification_a_data_1")
            mutate(ver)
            ver["outcome"] = outcome
            with self.subTest(outcome=outcome):
                svc = support.review_service(doc)
                self.assertIs(svc.recommendations[REC].status, RecommendationStatus.ESCALATED)
                self.assert_rejected(svc.submit_review(COORD, cmd()), ExternalCode.INVALID_STATE)

    def test_command_must_reference_current_verification(self):
        out = self.svc.submit_review(COORD, cmd(verification_id="verification_a_data_9"))
        self.assert_rejected(out, ExternalCode.INVALID_COMMAND)
        self.assert_no_effects()


class LiveRecheckTests(Harness):
    """Decision 4: approval revalidates everything at the write boundary (mock authority)."""

    def _deps(self):
        return recommendation_source_refs(self.svc.recommendations[REC], self.svc.context)

    def _by_type(self, entity_type):
        return next(r for r in self._deps() if r.entity.entity_type == entity_type)

    def _expect_stale(self, internal):
        out = self.svc.submit_review(COORD, cmd())
        self.assert_rejected(out, ExternalCode.REVIEW_STALE)
        self.assertEqual(self.svc.rejection_log[-1][0], internal)
        self.assert_no_effects()

    def test_source_changes_and_revocations_after_verification_block_approval(self):
        cases = [
            ("opportunity", VersionStatus.SUPERSEDED, AccessStatus.ALLOWED, "source_not_current"),
            ("candidate_profile", VersionStatus.SUPERSEDED, AccessStatus.ALLOWED, "source_not_current"),
            ("candidate_profile", VersionStatus.CURRENT, AccessStatus.DENIED, "source_access_denied"),
            ("policy_set", VersionStatus.SUPERSEDED, AccessStatus.ALLOWED, "source_not_current"),
            ("application", VersionStatus.WITHDRAWN, AccessStatus.ALLOWED, "source_withdrawn"),
            ("program_enrollment", VersionStatus.UNAVAILABLE, AccessStatus.ALLOWED, "source_unavailable"),
            ("opportunity", VersionStatus.DELETED, AccessStatus.ALLOWED, "source_deleted"),
        ]
        for entity_type, version, access, internal in cases:
            with self.subTest(entity_type=entity_type, internal=internal):
                self.setUp()
                self.auth.set(support.COORDINATOR, self._by_type(entity_type), version, access)
                self._expect_stale(internal)

    def test_authority_error_blocks_approval(self):
        self.auth.raise_error = True
        self._expect_stale("source_check_error")

    def test_withdrawn_application_in_records_blocks_approval(self):
        from rap_contracts.models import Application

        ctx = self.svc.context
        apps = [a if a.id != "application_demo_a_data" else Application.model_validate(
            {**a.model_dump(mode="json"), "status": "withdrawn"}) for a in ctx.eligibility.records.applications]
        records = dataclasses.replace(ctx.eligibility.records, applications=tuple(apps))
        self.svc.context = dataclasses.replace(ctx, eligibility=dataclasses.replace(ctx.eligibility, records=records))
        self._expect_stale("invalid_application_context")

    def test_eligibility_changed_before_review_blocks_approval(self):
        ctx = self.svc.context
        results = dict(ctx.eligibility_results)
        del results["eligibility_a_data"]
        self.svc.context = dataclasses.replace(ctx, eligibility_results=results)
        self._expect_stale("unknown_reference")


class EscalationPathTests(Harness):
    def test_request_information_on_escalated_without_freshness_or_side_effects(self):
        claims_before = [c.model_dump() for c in self.svc.context.eligibility.claims]
        out = self.svc.submit_review(COORD, cmd(recommendation_id=ESC, action="request_information",
                                                code="verification_issue_followup"))
        decision = self.assert_recorded(out, RecommendationStatus.NEEDS_INFORMATION)
        self.assertEqual(decision.rechecked_source_refs, ())
        self.assertEqual(self.auth.calls, [])  # no source content read, nothing exposed
        self.assertEqual([c.model_dump() for c in self.svc.context.eligibility.claims], claims_before)
        self.assertFalse(set(out.model_dump()) - {"status", "decision", "audit_event_ids", "error"})

    def test_dismissal_allowed_even_when_sources_are_stale_or_withdrawn(self):
        for ref in recommendation_source_refs(self.svc.recommendations[ESC], self.svc.context):
            self.auth.set(support.COORDINATOR, ref, VersionStatus.WITHDRAWN, AccessStatus.DENIED)
        out = self.svc.submit_review(COORD, cmd(recommendation_id=ESC, action="dismiss_suggestion",
                                                code="verification_failed", comment="Suggestion relied on a citation that did not resolve."))
        self.assert_recorded(out, RecommendationStatus.DISMISSED)

    def test_needs_information_then_dismiss(self):
        self.svc.submit_review(COORD, cmd(action="request_information", code="availability_details_needed"))
        out = self.svc.submit_review(COORD, cmd(action="dismiss_suggestion", code="opportunity_no_longer_suitable",
                                                comment="Posting scope changed before follow-up.", key="key-demo-0000000002"))
        self.assert_recorded(out, RecommendationStatus.DISMISSED)
        self.assertEqual([e.sequence for e in self.svc.events], [1, 2])

    def test_unauthorized_escalation_rejected(self):
        for credential in ("credential-demo-other-program", "credential-demo-viewer", "credential-demo-pipeline", None):
            with self.subTest(credential=credential):
                out = self.svc.submit_review(credential, cmd(recommendation_id=ESC, action="request_information",
                                                             code="verification_issue_followup"))
                self.assertIs(out.status, OutcomeStatus.REJECTED)
                self.assert_no_effects(ESC, RecommendationStatus.ESCALATED)


class TerminalStateTests(Harness):
    def test_terminal_recommendations_cannot_be_reopened_or_re_reviewed(self):
        self.svc.submit_review(COORD, cmd())
        for i, (action, code, comment) in enumerate((
            ("approve_for_follow_up", "meets_published_criteria", None),
            ("request_information", "availability_details_needed", None),
            ("dismiss_suggestion", "duplicate_suggestion", "Duplicate of an earlier suggestion."),
        )):
            with self.subTest(action=action):
                out = self.svc.submit_review(COORD, cmd(action=action, code=code, comment=comment, key=f"key-demo-terminal-{i:04d}"))
                self.assert_rejected(out, ExternalCode.INVALID_STATE)
        self.assertEqual(len(self.svc.events), 1)
        self.assertIs(self.svc.recommendations[REC].status, RecommendationStatus.APPROVED_FOR_FOLLOW_UP)

    def test_dismissed_cannot_be_approved(self):
        self.svc.submit_review(COORD, cmd(action="dismiss_suggestion", code="duplicate_suggestion", comment="Duplicate entry."))
        self.assert_rejected(self.svc.submit_review(COORD, cmd(key="key-demo-0000000002")), ExternalCode.INVALID_STATE)


class IdempotencyTests(Harness):
    def test_same_key_same_payload_replays_without_effects(self):
        first = self.svc.submit_review(COORD, cmd())
        calls_after_first = len(self.auth.calls)
        replay = self.svc.submit_review(COORD, cmd())
        self.assertIs(replay.status, OutcomeStatus.REPLAYED)
        self.assertEqual(replay.decision, first.decision)
        self.assertEqual(replay.audit_event_ids, first.audit_event_ids)
        self.assertEqual((len(self.svc.events), len(self.svc.decisions)), (1, 1))
        self.assertEqual(len(self.auth.calls), calls_after_first)  # committed action not re-executed
        self.assertEqual(self.svc.replay_log, [("key-demo-0000000001", "principal_demo_coordinator")])

    def test_replay_requires_current_authentication_and_authorization(self):
        self.svc.submit_review(COORD, cmd())
        self.assert_rejected(self.svc.submit_review("credential-unknown", cmd()), ExternalCode.UNAUTHENTICATED)
        self.svc.authorizer.grants["principal_demo_coordinator"] = ()  # permission revoked after commit
        self.assert_rejected(self.svc.submit_review(COORD, cmd()), ExternalCode.NOT_PERMITTED)
        self.assertEqual(self.svc.replay_log, [])
        self.assertEqual(len(self.svc.events), 1)

    def test_conflicting_payload_reuse_fails_and_prior_is_intact(self):
        first = self.svc.submit_review(COORD, cmd(action="request_information", code="availability_details_needed"))
        for label, conflicting in (
            ("different reason", cmd(action="request_information", code="qualification_evidence_needed")),
            ("different comment", cmd(action="request_information", code="availability_details_needed", comment="Need weekly hours.")),
            ("different action", cmd()),
        ):
            with self.subTest(label):
                self.assert_rejected(self.svc.submit_review(COORD, conflicting), ExternalCode.IDEMPOTENCY_CONFLICT)
        self.assertEqual(list(self.svc.decisions.values()), [first.decision])
        self.assertEqual(len(self.svc.events), 1)

    def test_different_reviewer_cannot_replay_or_reuse_key(self):
        self.svc.submit_review(COORD, cmd(action="request_information", code="availability_details_needed"))
        out = self.svc.submit_review("credential-demo-coordinator-two",
                                     cmd(action="request_information", code="availability_details_needed"))
        self.assert_rejected(out, ExternalCode.IDEMPOTENCY_CONFLICT)
        self.assertEqual(self.svc.replay_log, [])

    def test_rejected_commands_do_not_consume_the_key(self):
        bad = cmd(action="dismiss_suggestion", code="duplicate_suggestion")  # missing required comment
        self.assert_rejected(self.svc.submit_review(COORD, bad), ExternalCode.INVALID_COMMAND)
        good = cmd(action="dismiss_suggestion", code="duplicate_suggestion", comment="Duplicate entry.")
        self.assert_recorded(self.svc.submit_review(COORD, good), RecommendationStatus.DISMISSED)

    def test_fingerprint_binds_vocabulary_version_pins_and_reviewer(self):
        rec = self.svc.recommendations[REC]
        principal = self.svc.authenticator.principals[COORD]
        other = self.svc.authenticator.principals["credential-demo-coordinator-two"]
        base = review_fingerprint(cmd(), principal, rec)
        self.assertEqual(base, review_fingerprint(cmd(key="key-demo-9999999999"), principal, rec))  # key excluded
        self.assertNotEqual(base, review_fingerprint(cmd(vocabulary=("review_reasons_demo", 2)), principal, rec))
        self.assertNotEqual(base, review_fingerprint(cmd(), other, rec))
        moved = rec.model_copy(update={"eligibility_result_id": "eligibility_a_web"})
        self.assertNotEqual(base, review_fingerprint(cmd(), principal, moved))


class ReasonTests(Harness):
    def _invalid(self, internal, **kw):
        out = self.svc.submit_review(COORD, cmd(**kw))
        self.assert_rejected(out, ExternalCode.INVALID_COMMAND)
        self.assertEqual(self.svc.rejection_log[-1][0], internal)
        self.assert_no_effects()

    def test_unknown_code_vocabulary_and_foreign_vocabulary(self):
        self._invalid("unknown_reason_code", code="ai_suggested_strong_fit")
        self._invalid("unknown_reason_vocabulary", vocabulary=("review_reasons_demo", 2))
        self._invalid("unknown_reason_vocabulary", vocabulary=("review_reasons_lantern", 1))

    def test_reason_must_fit_action(self):
        self._invalid("reason_not_for_action", code="duplicate_suggestion")

    def test_conditional_comments(self):
        self._invalid("comment_required", code="coordinator_exception")
        self._invalid("comment_required", action="dismiss_suggestion", code="duplicate_suggestion")
        self._invalid("comment_required", action="request_information", code="other_information_needed")
        self._invalid("comment_forbidden", code="checklist_complete", comment="All good.")
        out = self.svc.submit_review(COORD, cmd(code="coordinator_exception",
                                                comment="Approved for an introductory call despite a late submission."))
        self.assert_recorded(out, RecommendationStatus.APPROVED_FOR_FOLLOW_UP)

    def test_comment_screen_rejects_sensitive_accusatory_and_contact_text(self):
        for text in ("Has a disability so may need changes.", "Looks like a fake profile.", "Candidate lied about hours.",
                     "Email them at someone@example.org", "Call 555 010 9999 tomorrow", "Their age seems relevant."):
            with self.subTest(text=text):
                self._invalid("comment_rejected", code="coordinator_exception", comment=text)

    def test_comment_shape(self):
        base = cmd().model_dump(mode="json")
        for bad in ("", "x" * 2001, "line\x00break"):
            with self.subTest(length=len(bad)), self.assertRaises(ValidationError):
                HumanReviewCommand.model_validate({**base, "comment": bad})

    def test_vocabulary_rules(self):
        base = copy.deepcopy(support.review_raw()["reason_vocabularies"][0])
        optional_dismissal = copy.deepcopy(base)
        optional_dismissal["reasons"].append({"code": "quick_dismissal", "actions": ["dismiss_suggestion"], "comment": "optional"})
        accusatory = copy.deepcopy(base)
        accusatory["reasons"].append({"code": "suspected_fraud", "actions": ["dismiss_suggestion"], "comment": "required"})
        sensitive = copy.deepcopy(base)
        sensitive["reasons"].append({"code": "accommodation_needed", "actions": ["request_information"], "comment": "optional"})
        duplicate = copy.deepcopy(base)
        duplicate["reasons"].append(copy.deepcopy(base["reasons"][0]))
        legacy = copy.deepcopy(base)
        legacy["reasons"][0]["actions"] = ["reject_suggestion"]
        for label, payload in (("optional dismissal comment", optional_dismissal), ("accusatory code", accusatory),
                               ("sensitive code", sensitive), ("duplicate code", duplicate), ("legacy action", legacy)):
            with self.subTest(label), self.assertRaises(ValidationError):
                ReviewReasonVocabulary.model_validate(payload)

    def test_vocabulary_version_conflict(self):
        base = support.review_raw()["reason_vocabularies"][0]
        vocab = ReviewReasonVocabulary.model_validate(base)
        changed = ReviewReasonVocabulary.model_validate({**base, "reasons": base["reasons"][:3]})
        self.assertEqual(index_reason_vocabularies([vocab, vocab]), {(vocab.id, vocab.version): vocab})
        with self.assertRaises(ContractViolation) as caught:
            index_reason_vocabularies([vocab, changed])
        self.assertEqual(caught.exception.code, "vocabulary_version_conflict")
        doc = support.review_raw()
        doc["reason_vocabularies"].append({**copy.deepcopy(base), "reasons": base["reasons"][:3]})
        with self.assertRaises(ContractViolation):
            support.review_service(doc)


class CorrectionTests(Harness):
    def setUp(self):
        super().setUp()
        self.first = self.svc.submit_review(COORD, cmd()).decision
        self.snapshot = (copy.deepcopy(self.svc.decisions[self.first.id].model_dump()), self.svc.events[0].model_dump())

    def correction(self, key="key-demo-correction-01", decision_id=None, code="coordinator_exception",
                   comment="Approved for an introductory call; reason recorded incorrectly.", note="Reason code corrected."):
        payload = {"idempotency_key": key, "corrects_decision_id": decision_id or self.first.id,
                   "reason": {"vocabulary_id": "review_reasons_demo", "vocabulary_version": 1, "code": code},
                   "correction_note": note}
        if comment is not None:
            payload["comment"] = comment
        return ReviewCorrectionCommand.model_validate(payload)

    def test_correction_is_a_new_linked_decision_and_event(self):
        out = self.svc.submit_correction(COORD, self.correction())
        self.assertIs(out.status, OutcomeStatus.RECORDED)
        new = out.decision
        self.assertEqual((new.corrects_decision_id, new.action, new.recommendation_status_after),
                         (self.first.id, ReviewAction.APPROVE_FOR_FOLLOW_UP, RecommendationStatus.APPROVED_FOR_FOLLOW_UP))
        self.assertNotEqual(new.id, self.first.id)
        first_event, second_event = self.svc.events
        self.assertEqual((second_event.event_type.value, second_event.corrects_decision_id, second_event.prior_event_id),
                         ("review_decision_corrected", self.first.id, first_event.id))
        self.assertEqual((self.svc.decisions[self.first.id].model_dump(), first_event.model_dump()), self.snapshot)
        self.assertIs(self.svc.recommendations[REC].status, RecommendationStatus.APPROVED_FOR_FOLLOW_UP)

    def test_correction_cannot_change_or_reverse_the_action(self):
        base = self.correction().model_dump(mode="json")
        for key, value in (("action", "dismiss_suggestion"), ("recommendation_status_after", "dismissed"), ("revoke", True)):
            with self.subTest(key=key), self.assertRaises(ValidationError):
                ReviewCorrectionCommand.model_validate({**base, key: value})
        out = self.svc.submit_correction(COORD, self.correction(code="duplicate_suggestion"))  # dismissal reason
        self.assert_rejected(out, ExternalCode.INVALID_COMMAND)

    def test_correction_requires_note_and_screens_text(self):
        base = self.correction().model_dump(mode="json")
        with self.assertRaises(ValidationError):
            ReviewCorrectionCommand.model_validate({k: v for k, v in base.items() if k != "correction_note"})
        out = self.svc.submit_correction(COORD, self.correction(note="Candidate was dishonest earlier."))
        self.assert_rejected(out, ExternalCode.INVALID_COMMAND)

    def test_only_latest_decision_in_chain_can_be_corrected(self):
        second = self.svc.submit_correction(COORD, self.correction()).decision
        stale = self.svc.submit_correction(COORD, self.correction(key="key-demo-correction-02"))
        self.assert_rejected(stale, ExternalCode.INVALID_STATE)
        third = self.svc.submit_correction(COORD, self.correction(key="key-demo-correction-03", decision_id=second.id,
                                                                  code="meets_published_criteria", comment=None))
        self.assertIs(third.status, OutcomeStatus.RECORDED)
        self.assertEqual([e.sequence for e in self.svc.events], [1, 2, 3])

    def test_correction_authority_and_idempotency(self):
        self.assert_rejected(self.svc.submit_correction("credential-demo-other-program", self.correction()), ExternalCode.NOT_PERMITTED)
        self.assert_rejected(self.svc.submit_correction("credential-demo-pipeline", self.correction()), ExternalCode.NOT_PERMITTED)
        self.assert_rejected(self.svc.submit_correction(COORD, self.correction(decision_id="review_decision_9999")),
                             ExternalCode.NOT_PERMITTED)
        first = self.svc.submit_correction(COORD, self.correction())
        replay = self.svc.submit_correction(COORD, self.correction())
        self.assertIs(replay.status, OutcomeStatus.REPLAYED)
        self.assertEqual(replay.decision, first.decision)
        self.assert_rejected(self.svc.submit_correction(COORD, self.correction(note="Different note.")),
                             ExternalCode.IDEMPOTENCY_CONFLICT)
        self.assert_rejected(self.svc.submit_review(COORD, cmd(key="key-demo-correction-01")), ExternalCode.IDEMPOTENCY_CONFLICT)
        self.assertEqual(len(self.svc.events), 2)


class AuditAndCommentIsolationTests(Harness):
    def test_audit_events_carry_no_free_text(self):
        comment = "Approved for an introductory call despite a late submission."
        self.svc.submit_review(COORD, cmd(code="coordinator_exception", comment=comment))
        dumped = json.dumps([e.model_dump(mode="json") for e in self.svc.events])
        self.assertNotIn("introductory", dumped)
        self.assertFalse({"comment", "correction_note"} & set(AuditEvent.model_fields))
        with self.assertRaises(ValidationError):
            AuditEvent.model_validate({**self.svc.events[0].model_dump(mode="json"), "comment": comment})

    def test_audit_event_lineage_rules(self):
        self.svc.submit_review(COORD, cmd())
        base = self.svc.events[0].model_dump(mode="json")
        for label, payload in (("recorded with prior event", {**base, "prior_event_id": "audit_event_0009"}),
                               ("corrected without lineage", {**base, "event_type": "review_decision_corrected"}),
                               ("machine actor", {**base, "actor_kind": "service"})):
            with self.subTest(label), self.assertRaises(ValidationError):
                AuditEvent.model_validate(payload)

    def test_approval_decision_must_record_rechecked_sources(self):
        self.svc.submit_review(COORD, cmd())
        decision = next(iter(self.svc.decisions.values())).model_dump(mode="json")
        with self.assertRaises(ValidationError):
            ReviewDecision.model_validate({**decision, "rechecked_source_refs": []})

    def test_review_content_never_becomes_evidence_or_retrieval_context(self):
        ref = {"organization_id": "org_demo_001",
               "entity": {"source_system": "fixture", "entity_type": "review_decision", "entity_id": "0001"},
               "version": {"kind": "native_revision", "revision_id": "1"}}
        caps_doc = support.ext_raw()["capabilities"][0]
        caps_doc["native_revision_entity_types"].append("review_decision")
        from rap_contracts.models import SourceSystemCapabilities
        caps = {c.source_system: c for c in [SourceSystemCapabilities.model_validate(caps_doc)]}
        ctx = support.ext_context()
        ev = EvidenceRecord.model_validate({"id": "evidence_review_comment", "organization_id": "org_demo_001",
                                            "subject": {"kind": "candidate", "id": "candidate_demo_a"},
                                            "basis": "candidate_statement", "source_ref": ref, "field_path": "comment"})
        with self.assertRaises(ContractViolation) as caught:
            check_evidence_records({**ctx.evidence, **index_evidence([ev])}, ctx.records, caps)
        self.assertEqual(caught.exception.code, "review_content_not_evidence")
        chunk = RetrievalChunk.model_validate({**support.ext_raw()["chunks"][0], "id": "chunk_review_comment", "source_ref": ref})
        authority = support.scenario_authority()
        authority.set(support.COORDINATOR, chunk.source_ref, VersionStatus.CURRENT, AccessStatus.ALLOWED)
        store = support.FixtureChunkStore()
        outcome = admit_chunks(RetrievalRequest(organization_id="org_demo_001", purpose="model_context",
                                                chunk_ids=("chunk_review_comment",)),
                               {chunk.id: chunk}, authority, store, support.COORDINATOR, caps)
        self.assertEqual([d.code for d in outcome.denied], [DenialCode.REVIEW_CONTENT])
        self.assertEqual((store.loads, authority.calls), ([], []))


class SchemaRoundTripTests(Harness):
    def test_outcome_and_decision_round_trip(self):
        out = self.svc.submit_review(COORD, cmd())
        from rap_contracts.review import ReviewOutcome
        self.assertEqual(ReviewOutcome.model_validate(out.model_dump(mode="json")), out)
        bad = {**out.model_dump(mode="json"), "error": "not_permitted"}
        with self.assertRaises(ValidationError):
            ReviewOutcome.model_validate(bad)
        verification = self.svc.latest_verification[REC]
        self.assertIsInstance(verification, VerificationResult)


if __name__ == "__main__":
    unittest.main()
