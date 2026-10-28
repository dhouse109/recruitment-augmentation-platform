"""D-004.04 -- recommendations, application lineage, verification and lifecycle.

Recommendations and verifications in the fixture are hand-authored labels.
These tests exercise contract validity, the substantive acceptance checks and
the transition table; they do not demonstrate a recommendation engine or verifier.
"""

import copy
import itertools
import unittest

from pydantic import ValidationError

import support
from rap_contracts.invariants import ContractViolation
from rap_contracts.recommendation import (
    HUMAN_TRIGGERS,
    PILOT_REVIEWABLE_CONTEXT_KINDS,
    TERMINAL_STATUSES,
    TRANSITIONS,
    Recommendation,
    RecommendationStatus,
    Trigger,
    VerificationResult,
    accept_verification,
    apply_verification,
    check_recommendation,
    next_status,
    recommendation_source_refs,
)


def rec_doc(rid="recommendation_a_data"):
    return copy.deepcopy(next(r for r in support.review_raw()["recommendations"] if r["id"] == rid))


def ver_doc(vid="verification_a_data_1"):
    return copy.deepcopy(next(v for v in support.review_raw()["verifications"] if v["id"] == vid))


def expect(test, code, fn, *args):
    with test.assertRaises(ContractViolation) as caught:
        fn(*args)
    test.assertEqual(caught.exception.code, code)


class RecommendationShapeTests(unittest.TestCase):
    def test_fixture_recommendations_valid(self):
        ctx = support.recommendation_context()
        for rec in support.review_models()[0]:
            with self.subTest(rec=rec.id):
                check_recommendation(rec, ctx)

    def test_no_placement_or_free_text_fields(self):
        base = rec_doc()
        for key in ("placement", "offer", "hire", "rejected", "rationale", "explanation", "score", "rank", "confidence"):
            with self.subTest(key=key), self.assertRaises(ValidationError):
                Recommendation.model_validate({**base, key: "x"})
        for status in ("placed", "hired", "rejected", "offered", "admitted"):
            with self.subTest(status=status), self.assertRaises(ValidationError):
                Recommendation.model_validate({**base, "status": status})

    def test_requires_context_claims_and_evidence(self):
        base = rec_doc()
        for label, payload in (("no context", {k: v for k, v in base.items() if k != "context"}),
                               ("no claims", {**base, "supporting_claim_ids": []}),
                               ("no evidence", {**base, "evidence_ids": []}),
                               ("duplicate evidence", {**base, "evidence_ids": base["evidence_ids"] + base["evidence_ids"][:1]})):
            with self.subTest(label), self.assertRaises(ValidationError):
                Recommendation.model_validate(payload)

    def test_unapproved_context_kinds_not_representable(self):
        self.assertEqual(PILOT_REVIEWABLE_CONTEXT_KINDS, frozenset({"application"}))
        base = rec_doc()
        for kind in ("discovery", "candidate_only", "opportunity_search"):
            with self.subTest(kind=kind), self.assertRaises(ValidationError):
                Recommendation.model_validate({**base, "context": {**base["context"], "kind": kind}})


class ApplicationLineageTests(unittest.TestCase):
    """Decision 1: grounded in the candidate's own submitted application at its exact version."""

    def _check(self, rec, ctx=None):
        check_recommendation(Recommendation.model_validate(rec), ctx or support.recommendation_context())

    def test_program_level_application_supports_other_program_opportunity(self):
        self._check(rec_doc("recommendation_a_web"))  # application targets program_demo_001; web is in it

    def test_withdrawn_draft_or_other_candidates_application_rejected(self):
        cases = {"withdrawn (B, other candidate)": "application_demo_b_data",
                 "draft (B, other candidate)": "application_demo_b_program",
                 "other candidate's submitted application": "application_demo_d_data"}
        apps = {a["id"]: a for a in support.raw()["applications"] + support.ext_raw()["additional_records"]["applications"]}
        for label, app_id in cases.items():
            rec = rec_doc()
            rec["context"].update(application_id=app_id, application_ref=apps[app_id]["source_ref"])
            with self.subTest(label):
                expect(self, "invalid_application_context", self._check, rec)

    def _with_application(self, app_id, **changes):
        import dataclasses

        from rap_contracts.models import Application

        ctx = support.recommendation_context()
        apps = list(ctx.eligibility.records.applications)
        idx = next(i for i, a in enumerate(apps) if a.id == app_id)
        payload = {**apps[idx].model_dump(mode="json"), **changes}
        apps[idx] = Application.model_validate({k: v for k, v in payload.items() if v is not None})
        records = dataclasses.replace(ctx.eligibility.records, applications=tuple(apps))
        return dataclasses.replace(ctx, eligibility=dataclasses.replace(ctx.eligibility, records=records))

    def test_own_withdrawn_closed_or_draft_application_rejected(self):
        for status, changes in (("withdrawn", {}), ("closed", {}), ("draft", {"submission": None})):
            ctx = self._with_application("application_demo_a_data", status=status, **changes)
            with self.subTest(status=status):
                expect(self, "invalid_application_context", self._check, rec_doc(), ctx)

    def test_pinned_application_version_must_match(self):
        rec = rec_doc()
        rec["context"]["application_ref"]["version"]["revision_id"] = "712"
        expect(self, "invalid_application_context", self._check, rec)

    def test_job_application_supports_its_own_opportunity(self):
        self._check(rec_doc("recommendation_c_job"))  # application targets the job (no program)

    def test_application_targeting_single_opportunity_cannot_support_another(self):
        from rap_contracts.recommendation import check_application_context

        ctx = support.recommendation_context()
        rec = Recommendation.model_validate(rec_doc("recommendation_c_job"))
        other = rec.model_copy(update={"opportunity_id": "opportunity_demo_data"})
        expect(self, "invalid_application_context", check_application_context, other, ctx)


class RecommendationGroundingTests(unittest.TestCase):
    def _expect(self, rec, code):
        expect(self, code, check_recommendation, Recommendation.model_validate(rec), support.recommendation_context())

    def test_must_rest_on_eligible_result(self):
        rec = rec_doc()
        rec.update(opportunity_id="opportunity_demo_ops", eligibility_result_id="eligibility_a_ops")
        rec["opportunity_ref"] = next(r for r in support.ext_raw()["eligibility_results"] if r["id"] == "eligibility_a_ops")["opportunity_ref"]
        rec["requirement_ids"], rec["evidence_ids"] = [], ["evidence_a_profile_python", "evidence_a_app_python", "evidence_a_profile_hours"]
        self._expect(rec, "not_eligible")

    def test_eligibility_for_other_pair_rejected(self):
        rec = rec_doc()
        rec["eligibility_result_id"] = "eligibility_b_data"
        self._expect(rec, "eligibility_mismatch")

    def test_policy_pin_must_match_eligibility(self):
        rec = rec_doc()
        rec["policy"]["version"] = 2
        self._expect(rec, "policy_version_mismatch")
        rec = rec_doc()
        rec["opportunity_ref"]["version"]["revision_id"] = "40"
        self._expect(rec, "opportunity_version_mismatch")

    def test_supporting_claims_must_be_declared_and_fully_cited(self):
        rec = rec_doc()
        rec["supporting_claim_ids"].append("claim_e_python_inferred")
        self._expect(rec, "invalid_citation")  # E's claim, not A's
        rec = rec_doc()
        rec["evidence_ids"].remove("evidence_a_app_python")
        self._expect(rec, "incomplete_citations")

    def test_inferred_or_contested_claim_cannot_support(self):
        doc = support.ext_raw()
        inferred = copy.deepcopy(next(c for c in doc["claims"] if c["id"] == "claim_e_python_inferred"))
        inferred.update(id="claim_a_python_inferred", candidate_id="candidate_demo_a", evidence_ids=["evidence_a_profile_python"])
        doc["claims"].append(inferred)
        rec = Recommendation.model_validate({**rec_doc(), "supporting_claim_ids": ["claim_a_python_inferred"]})
        expect(self, "non_authoritative_input", check_recommendation, rec, support.recommendation_context(doc))

    def test_evidence_must_be_about_candidate_or_opportunity_in_scope(self):
        rec = rec_doc()
        rec["evidence_ids"].append("evidence_d_profile_hours")
        self._expect(rec, "invalid_citation")
        rec = rec_doc()
        rec["evidence_ids"].append("evidence_missing")
        self._expect(rec, "invalid_citation")
        rec = rec_doc()
        rec["evidence_ids"].append("evidence_c_profile_hours")
        self._expect(rec, "cross_org_reference")

    def test_published_requirements_and_opportunity_evidence_may_be_cited(self):
        rec = Recommendation.model_validate(rec_doc())
        self.assertIn("evidence_data_posting", rec.evidence_ids)  # opportunity-subject evidence (partial O5)
        check_recommendation(rec, support.recommendation_context())
        bad = rec_doc()
        bad["requirement_ids"].append("requirement_web_hours")
        self._expect(bad, "invalid_citation")

    def test_cross_org_record_rejected(self):
        rec = rec_doc()
        rec["organization_id"] = "org_demo_002"
        with self.assertRaises(ValidationError):  # pinned refs are in org_demo_001
            Recommendation.model_validate(rec)

    def test_dependencies_cover_application_policy_and_evidence(self):
        rec = Recommendation.model_validate(rec_doc())
        refs = recommendation_source_refs(rec, support.recommendation_context())
        self.assertEqual({r.entity.entity_type for r in refs},
                         {"application", "opportunity", "policy_set", "candidate_profile", "program_enrollment"})
        self.assertEqual(len(refs), len(set(refs)))


class TransitionTests(unittest.TestCase):
    ALLOWED = {
        ("pending_verification", "verification_passed"): "ready_for_review",
        ("pending_verification", "verification_not_passed"): "escalated",
        ("pending_verification", "sources_changed"): "obsolete",
        ("ready_for_review", "approve_for_follow_up"): "approved_for_follow_up",
        ("ready_for_review", "request_information"): "needs_information",
        ("ready_for_review", "dismiss_suggestion"): "dismissed",
        ("ready_for_review", "sources_changed"): "obsolete",
        ("escalated", "request_information"): "needs_information",
        ("escalated", "dismiss_suggestion"): "dismissed",
        ("escalated", "sources_changed"): "obsolete",
        ("needs_information", "dismiss_suggestion"): "dismissed",
        ("needs_information", "sources_changed"): "obsolete",
    }

    def test_exhaustive_transition_matrix(self):
        self.assertEqual({(s.value, t.value): v.value for (s, t), v in TRANSITIONS.items()}, self.ALLOWED)
        for status, trigger in itertools.product(RecommendationStatus, Trigger):
            with self.subTest(status=status.value, trigger=trigger.value):
                key = (status.value, trigger.value)
                if key in self.ALLOWED:
                    self.assertEqual(next_status(status, trigger).value, self.ALLOWED[key])
                else:
                    expect(self, "forbidden_transition", next_status, status, trigger)

    def test_terminal_statuses_cannot_reopen(self):
        self.assertEqual({s.value for s in TERMINAL_STATUSES}, {"approved_for_follow_up", "dismissed", "obsolete"})
        for status in TERMINAL_STATUSES:
            for trigger in Trigger:
                with self.subTest(status=status.value, trigger=trigger.value):
                    expect(self, "forbidden_transition", next_status, status, trigger)

    def test_approval_only_from_ready_for_review(self):
        sources = {s for (s, t) in TRANSITIONS if t is Trigger.APPROVE_FOR_FOLLOW_UP}
        self.assertEqual(sources, {RecommendationStatus.READY_FOR_REVIEW})

    def test_no_human_trigger_reaches_ready_for_review(self):
        for (_, trigger), target in TRANSITIONS.items():
            if target is RecommendationStatus.READY_FOR_REVIEW:
                self.assertNotIn(trigger, HUMAN_TRIGGERS)


class VerificationTests(unittest.TestCase):
    def setUp(self):
        self.ctx = support.recommendation_context()
        self.rec = Recommendation.model_validate(rec_doc())

    def test_outcome_derivation(self):
        base = ver_doc()
        cases = {
            ("evidence_citations_resolve", "fail"): "failed",
            ("supporting_claims_declared", "unresolved"): "unresolved",
        }
        for (code, status), outcome in cases.items():
            doc = copy.deepcopy(base)
            next(c for c in doc["checks"] if c["code"] == code)["status"] = status
            with self.subTest(code=code):
                with self.assertRaises(ValidationError):  # still labelled passed
                    VerificationResult.model_validate(doc)
                self.assertEqual(VerificationResult.model_validate({**doc, "outcome": outcome}).outcome.value, outcome)

    def test_stale_source_forces_stale_outcome(self):
        doc = ver_doc()
        doc["source_checks"][0]["version_status"] = "superseded"
        with self.assertRaises(ValidationError):  # sources check still says pass
            VerificationResult.model_validate(doc)
        next(c for c in doc["checks"] if c["code"] == "sources_current_and_allowed")["status"] = "fail"
        with self.assertRaises(ValidationError):  # outcome still passed
            VerificationResult.model_validate(doc)
        self.assertEqual(VerificationResult.model_validate({**doc, "outcome": "stale"}).outcome.value, "stale")

    def test_scores_agreement_and_missing_checks_rejected(self):
        base = ver_doc()
        for key in ("confidence", "score", "model_agreement", "reviewer_id", "approved"):
            with self.subTest(key=key), self.assertRaises(ValidationError):
                VerificationResult.model_validate({**base, key: 0.99})
        with self.assertRaises(ValidationError):
            VerificationResult.model_validate({**base, "checks": base["checks"][:-1]})
        with self.assertRaises(ValidationError):
            VerificationResult.model_validate({**base, "checks": base["checks"] + base["checks"][:1]})

    def test_passed_verification_accepted_only_after_recompute(self):
        accept_verification(VerificationResult.model_validate(ver_doc()), self.rec, self.ctx)
        # A verifier claiming 'passed' is not proof: break the recommendation and the claim no longer holds.
        broken = self.rec.model_copy(update={"evidence_ids": tuple(e for e in self.rec.evidence_ids if e != "evidence_a_app_python")})
        doc = ver_doc()
        doc["source_checks"] = [sc for sc in doc["source_checks"]]
        expect(self, "incomplete_citations", accept_verification, VerificationResult.model_validate(doc), broken, self.ctx)

    def test_same_component_is_not_independent(self):
        doc = ver_doc()
        doc["verified_by"] = self.rec.generated_by
        expect(self, "verification_not_independent", accept_verification, VerificationResult.model_validate(doc), self.rec, self.ctx)

    def test_source_coverage_must_be_exact(self):
        doc = ver_doc()
        doc["source_checks"] = doc["source_checks"][:-1]
        expect(self, "verification_incomplete", accept_verification, VerificationResult.model_validate(doc), self.rec, self.ctx)
        doc = ver_doc()
        extra = copy.deepcopy(doc["source_checks"][0])
        extra["source"]["entity"]["entity_id"] = "9999"
        doc["source_checks"].append(extra)
        expect(self, "verification_incomplete", accept_verification, VerificationResult.model_validate(doc), self.rec, self.ctx)

    def test_verification_for_other_recommendation_rejected(self):
        expect(self, "verification_mismatch", accept_verification,
               VerificationResult.model_validate(ver_doc("verification_c_job_1")), self.rec, self.ctx)

    def test_not_passed_outcomes_escalate_never_ready(self):
        base = ver_doc()
        variants = {}
        failed = copy.deepcopy(base)
        next(c for c in failed["checks"] if c["code"] == "eligibility_supports_recommendation")["status"] = "fail"
        variants["failed"] = {**failed, "outcome": "failed"}
        unresolved = copy.deepcopy(base)
        next(c for c in unresolved["checks"] if c["code"] == "policy_pin_matches")["status"] = "unresolved"
        variants["unresolved"] = {**unresolved, "outcome": "unresolved"}
        stale = copy.deepcopy(base)
        stale["source_checks"][1]["access_status"] = "denied"
        next(c for c in stale["checks"] if c["code"] == "sources_current_and_allowed")["status"] = "fail"
        variants["stale"] = {**stale, "outcome": "stale"}
        for outcome, payload in variants.items():
            with self.subTest(outcome=outcome):
                updated = apply_verification(self.rec, VerificationResult.model_validate(payload), self.ctx)
                self.assertIs(updated.status, RecommendationStatus.ESCALATED)
        self.assertIs(apply_verification(self.rec, VerificationResult.model_validate(base), self.ctx).status,
                      RecommendationStatus.READY_FOR_REVIEW)

    def test_verification_cannot_move_a_reviewed_recommendation(self):
        ready = self.rec.model_copy(update={"status": RecommendationStatus.READY_FOR_REVIEW})
        expect(self, "forbidden_transition", apply_verification, ready, VerificationResult.model_validate(ver_doc()), self.ctx)

    def test_verification_is_not_authorization(self):
        fields = set(VerificationResult.model_fields)
        self.assertFalse(fields & {"reviewer_id", "reviewer_principal_id", "approved", "authorized", "decision"})


if __name__ == "__main__":
    unittest.main()
