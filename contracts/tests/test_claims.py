"""D-004.10 -- controlled candidate claims, epistemic states, conflicts, participation."""

import copy
import json
import re
import unittest

from pydantic import ValidationError

import support
from rap_contracts.claims import (
    RESTRICTED_ATTRIBUTE_TOKENS,
    CandidateClaim,
    ClaimVocabulary,
    ProgramParticipation,
    check_claim_update,
    check_claims,
    check_participations,
    detect_conflicts,
)
from rap_contracts.evidence import RetrievalRequest, check_evidence_records
from rap_contracts.invariants import ContractViolation
from rap_contracts.models import SourceSystemCapabilities


def claim_doc(claim_id):
    return copy.deepcopy(next(c for c in support.ext_raw()["claims"] if c["id"] == claim_id))


def check_with(doc):
    ctx = support.ext_context(doc)
    check_claims(ctx.claims, ctx.evidence, ctx.vocabularies, ctx.records)


def expect_violation(test, code, fn, *args):
    with test.assertRaises(ContractViolation) as ctx:
        fn(*args)
    test.assertEqual(ctx.exception.code, code)


class ClaimStateTests(unittest.TestCase):
    def test_fixture_claims_cover_all_types_and_states(self):
        claims = support.ext_context().claims
        self.assertEqual({c.claim_type.value for c in claims},
                         {"skill", "experience", "interest", "availability", "work_preference"})
        self.assertEqual({c.state.value for c in claims}, {"declared", "inferred", "unknown", "contested"})
        check_with(support.ext_raw())

    def test_unknown_with_fabricated_value_rejected(self):
        bad = claim_doc("claim_b_availability")
        bad["value"] = {"kind": "availability", "hours_per_week": 15}
        with self.assertRaises(ValidationError):
            CandidateClaim.model_validate(bad)

    def test_declared_and_inferred_require_evidence(self):
        for cid in ("claim_a_availability", "claim_e_python_inferred"):
            bad = claim_doc(cid)
            bad["evidence_ids"] = []
            with self.subTest(cid), self.assertRaises(ValidationError):
                CandidateClaim.model_validate(bad)

    def test_inferred_requires_producer_and_only_inferred_may_name_one(self):
        bad = claim_doc("claim_e_python_inferred")
        del bad["inferred_by"]
        with self.assertRaises(ValidationError):
            CandidateClaim.model_validate(bad)
        bad = claim_doc("claim_a_python_profile")
        bad["inferred_by"] = "synthetic-inference-label/0"
        with self.assertRaises(ValidationError):
            CandidateClaim.model_validate(bad)

    def test_contested_rules(self):
        base = claim_doc("claim_b_python")
        corroborating = copy.deepcopy(base)
        corroborating["alternatives"][1]["value"] = {"kind": "skill", "presence": "has"}
        single = {**copy.deepcopy(base), "alternatives": base["alternatives"][:1]}
        with_value = {**copy.deepcopy(base), "value": {"kind": "skill", "presence": "has"}}
        no_alt_evidence = copy.deepcopy(base)
        no_alt_evidence["alternatives"][0]["evidence_ids"] = []
        for label, payload in (("corroborating values are not a conflict", corroborating), ("single alternative", single),
                               ("single value", with_value), ("alternative without evidence", no_alt_evidence)):
            with self.subTest(label), self.assertRaises(ValidationError):
                CandidateClaim.model_validate(payload)

    def test_value_kind_and_subject_code_must_match_type(self):
        bad = claim_doc("claim_a_python_profile")
        bad["value"] = {"kind": "availability", "hours_per_week": 10}
        with self.assertRaises(ValidationError):
            CandidateClaim.model_validate(bad)
        bad = claim_doc("claim_a_availability")
        bad["subject_code"] = "python"
        with self.assertRaises(ValidationError):
            CandidateClaim.model_validate(bad)

    def test_availability_bounds(self):
        base = claim_doc("claim_a_availability")
        for hours, ok in ((0, True), (168, True), (169, False), (-1, False), (12.5, False)):
            with self.subTest(hours=hours):
                payload = {**base, "value": {"kind": "availability", "hours_per_week": hours}}
                if ok:
                    CandidateClaim.model_validate(payload)
                else:
                    with self.assertRaises(ValidationError):
                        CandidateClaim.model_validate(payload)


class AllowlistAndSensitiveFieldTests(unittest.TestCase):
    SENSITIVE_KEYS = ("gender", "age", "date_of_birth", "disability", "accommodation", "medical_note", "ethnicity",
                      "religion", "postal_code", "graduation_year", "marital_status", "citizenship", "photo_url")

    def test_unsupported_claim_types_and_extra_fields_rejected(self):
        base = claim_doc("claim_a_python_profile")
        for key in self.SENSITIVE_KEYS:
            with self.subTest(claim_type=key), self.assertRaises(ValidationError):
                CandidateClaim.model_validate({**base, "claim_type": key})
            with self.subTest(extra_field=key), self.assertRaises(ValidationError):
                CandidateClaim.model_validate({**base, key: "synthetic"})
        with self.assertRaises(ValidationError):  # free text cannot ride along in a value
            CandidateClaim.model_validate({**base, "value": {"kind": "skill", "presence": "has", "note": "x"}})

    def test_code_outside_vocabulary_rejected(self):
        doc = support.ext_raw()
        claim = next(c for c in doc["claims"] if c["id"] == "claim_a_python_profile")
        claim["subject_code"] = "rust"
        expect_violation(self, "unsupported_claim_code", check_with, doc)

    def test_vocabulary_screens_restricted_terms(self):
        base = support.ext_raw()["vocabularies"][0]
        for code in ("disability_status", "age_band", "accommodation_needed", "zip_code", "graduation_year",
                     "native_gender_pref", "veteran"):
            with self.subTest(code=code), self.assertRaises(ValidationError):
                ClaimVocabulary.model_validate({**base, "skills": base["skills"] + [code]})

    def test_wrong_or_foreign_vocabulary_rejected(self):
        doc = support.ext_raw()
        next(c for c in doc["claims"] if c["id"] == "claim_a_python_profile")["vocabulary"]["version"] = 2
        expect_violation(self, "unknown_vocabulary", check_with, doc)
        doc = support.ext_raw()
        next(c for c in doc["claims"] if c["id"] == "claim_a_python_profile")["vocabulary"] = {"id": "vocabulary_lantern", "version": 1}
        expect_violation(self, "cross_org_reference", check_with, doc)

    def test_retrieval_request_cannot_carry_sensitive_fields(self):
        base = support.ext_raw()["retrieval_requests"][0]
        for key in ("fields", "gender", "accommodation", "include_medical"):
            with self.subTest(key), self.assertRaises(ValidationError):
                RetrievalRequest.model_validate({**base, key: ["synthetic"]})

    def test_sensitive_context_case_stores_nothing_sensitive(self):
        """Candidate E: the sensitive source answer is not represented anywhere matching or prompts can reach."""
        doc = support.ext_raw()
        e_claims = [c for c in doc["claims"] if c["candidate_id"] == "candidate_demo_e"]
        avail = next(c for c in e_claims if c["claim_type"] == "availability")
        self.assertEqual(avail["state"], "unknown")
        self.assertNotIn("value", avail)
        self.assertNotIn("evidence_ids", avail)
        reachable = {k: doc[k] for k in ("claims", "evidence", "chunks", "chunk_store", "vocabularies",
                                         "requirements", "eligibility_results", "retrieval_requests")}
        tokens = set(re.findall(r"[a-z]+", json.dumps(reachable).lower()))
        self.assertEqual(tokens & RESTRICTED_ATTRIBUTE_TOKENS, set())
        self.assertFalse(any(c["field_path"].startswith("availability") for c in doc["chunks"]
                             if c["source_ref"]["entity"]["entity_id"] == "7006"))


class EvidenceProvenanceTests(unittest.TestCase):
    def test_claim_citing_missing_or_other_candidates_evidence_rejected(self):
        doc = support.ext_raw()
        next(c for c in doc["claims"] if c["id"] == "claim_a_availability")["evidence_ids"] = ["evidence_missing"]
        expect_violation(self, "invalid_citation", check_with, doc)
        doc = support.ext_raw()
        next(c for c in doc["claims"] if c["id"] == "claim_a_availability")["evidence_ids"] = ["evidence_d_profile_hours"]
        expect_violation(self, "invalid_citation", check_with, doc)

    def test_claim_cannot_rest_on_authority_record(self):
        doc = support.ext_raw()
        next(c for c in doc["claims"] if c["id"] == "claim_a_availability")["evidence_ids"] = ["evidence_a_enrollment"]
        expect_violation(self, "evidence_provenance", check_with, doc)

    def _evidence_check(self, doc, caps=None):
        ctx = support.ext_context(doc)
        check_evidence_records(ctx.evidence, ctx.records, caps or support.ext_capabilities())

    def test_candidate_statement_must_come_from_own_profile_or_application(self):
        doc = support.ext_raw()
        ev = next(e for e in doc["evidence"] if e["id"] == "evidence_a_profile_hours")
        ev["source_ref"] = copy.deepcopy(next(e for e in doc["evidence"] if e["id"] == "evidence_d_profile_hours")["source_ref"])
        expect_violation(self, "evidence_provenance", self._evidence_check, doc)

    def test_cross_org_evidence_rejected(self):
        doc = support.ext_raw()
        ev = next(e for e in doc["evidence"] if e["id"] == "evidence_c_profile_hours")
        ev["subject"]["id"] = "candidate_demo_a"
        expect_violation(self, "cross_org_reference", self._evidence_check, doc)

    def test_verification_sources_fail_closed_until_explicitly_authorized(self):
        doc = support.ext_raw()
        doc["evidence"].append({"id": "evidence_a_credential", "organization_id": "org_demo_001",
                                "subject": {"kind": "candidate", "id": "candidate_demo_a"},
                                "basis": "independent_verification",
                                "source_ref": {"organization_id": "org_demo_001",
                                               "entity": {"source_system": "fixture", "entity_type": "credential_check", "entity_id": "9901"},
                                               "version": {"kind": "native_revision", "revision_id": "1"}},
                                "field_path": "result"})
        caps_doc = support.ext_raw()["capabilities"][0]
        caps_doc["native_revision_entity_types"].append("credential_check")
        undeclared = {c.source_system: c for c in [SourceSystemCapabilities.model_validate(caps_doc)]}
        expect_violation(self, "unauthorized_verification_source", self._evidence_check, doc, undeclared)
        caps_doc["verification_entity_types"] = ["credential_check"]
        declared = {c.source_system: c for c in [SourceSystemCapabilities.model_validate(caps_doc)]}
        self._evidence_check(doc, declared)  # same org, provenance and version checks still apply

    def test_verification_source_cannot_be_an_identity_type(self):
        caps_doc = support.ext_raw()["capabilities"][0]
        caps_doc["verification_entity_types"] = ["user"]
        with self.assertRaises(ValidationError):
            SourceSystemCapabilities.model_validate(caps_doc)


class ConflictTests(unittest.TestCase):
    def _add(self, doc, **claim):
        doc["claims"].append(claim)
        return doc

    def test_corroborating_declared_claims_allowed(self):
        ctx = support.ext_context()
        a_python = [c for c in ctx.claims if c.key == ("candidate_demo_a", "skill", "python")]
        self.assertEqual(len(a_python), 2)
        self.assertEqual(detect_conflicts(ctx.claims), [])

    def test_conflicting_declared_claims_must_be_contested(self):
        doc = support.ext_raw()
        extra = claim_doc("claim_a_python_application")
        extra.update(id="claim_a_python_conflict", value={"kind": "skill", "presence": "lacks"})
        doc["claims"].append(extra)
        expect_violation(self, "unresolved_conflict", check_with, doc)
        groups = detect_conflicts(support.ext_context(doc).claims)
        self.assertEqual([g.claim_ids for g in groups],
                         [("claim_a_python_application", "claim_a_python_conflict", "claim_a_python_profile")])

    def test_conflicting_availability_detected(self):
        doc = support.ext_raw()
        extra = claim_doc("claim_a_availability")
        extra.update(id="claim_a_availability_app", value={"kind": "availability", "hours_per_week": 6},
                     evidence_ids=["evidence_a_app_python"])
        doc["claims"].append(extra)
        expect_violation(self, "unresolved_conflict", check_with, doc)

    def test_experience_duration_conflict_is_deterministic(self):
        def exp(months, presence="has"):
            v = {"kind": "experience", "presence": presence}
            if months is not None:
                v["duration_months"] = months
            return v
        from rap_contracts.claims import ExperienceValue, values_conflict
        cases = [((6, 6), False), ((6, None), False), ((6, 12), True), ((None, None), False)]
        for (a, b), conflict in cases:
            with self.subTest(a=a, b=b):
                self.assertIs(values_conflict(ExperienceValue.model_validate(exp(a)), ExperienceValue.model_validate(exp(b))), conflict)
        self.assertTrue(values_conflict(ExperienceValue.model_validate(exp(None)), ExperienceValue.model_validate(exp(None, "lacks"))))

    def test_inference_never_conflicts_with_or_overrides_a_fact(self):
        doc = support.ext_raw()
        inferred = claim_doc("claim_e_python_inferred")
        inferred.update(id="claim_d_python_inferred", candidate_id="candidate_demo_d", evidence_ids=["evidence_d_app_screening"])
        doc["claims"].append(inferred)  # inferred 'has' alongside declared 'lacks'
        check_with(doc)
        self.assertEqual(detect_conflicts(support.ext_context(doc).claims), [])

    def test_contested_or_unknown_cannot_coexist_with_declared_value(self):
        doc = support.ext_raw()
        extra = claim_doc("claim_b_python")
        extra.update(id="claim_b_python_declared", state="declared", value={"kind": "skill", "presence": "has"},
                     evidence_ids=["evidence_b_profile_python"])
        del extra["alternatives"]
        doc["claims"].append(extra)
        expect_violation(self, "contested_not_exclusive", check_with, doc)
        doc = support.ext_raw()
        extra = claim_doc("claim_a_availability")
        extra.update(id="claim_a_availability_unknown", state="unknown")
        del extra["value"], extra["evidence_ids"]
        doc["claims"].append(extra)
        expect_violation(self, "unknown_conflicts_with_value", check_with, doc)


class InferredPromotionTests(unittest.TestCase):
    def setUp(self):
        self.inferred = CandidateClaim.model_validate(claim_doc("claim_e_python_inferred"))

    def test_inferred_cannot_be_relabeled(self):
        base = claim_doc("claim_e_python_inferred")
        del base["inferred_by"]
        promoted = CandidateClaim.model_validate({**base, "state": "declared"})
        expect_violation(self, "inferred_promotion", check_claim_update, self.inferred, promoted)
        unknown = {k: v for k, v in base.items() if k not in ("value", "evidence_ids")}
        expect_violation(self, "inferred_promotion", check_claim_update, self.inferred,
                         CandidateClaim.model_validate({**unknown, "state": "unknown"}))

    def test_inference_cannot_overwrite_a_declared_claim(self):
        declared = CandidateClaim.model_validate(claim_doc("claim_d_python"))
        overwritten = CandidateClaim.model_validate({**claim_doc("claim_d_python"), "state": "inferred",
                                                     "value": {"kind": "skill", "presence": "has"},
                                                     "inferred_by": "synthetic-inference-label/0"})
        expect_violation(self, "inferred_overwrite", check_claim_update, declared, overwritten)

    def test_identity_fields_immutable(self):
        moved = CandidateClaim.model_validate({**claim_doc("claim_e_python_inferred"), "subject_code": "web_content"})
        expect_violation(self, "claim_immutable_field", check_claim_update, self.inferred, moved)

    def test_inferred_reupdate_allowed(self):
        check_claim_update(self.inferred, CandidateClaim.model_validate(claim_doc("claim_e_python_inferred")))


class ParticipationTests(unittest.TestCase):
    def _check(self, doc):
        ctx = support.ext_context(doc)
        check_participations(ctx.participations, ctx.evidence, ctx.records)

    def test_fixture_participations_valid(self):
        self._check(support.ext_raw())

    def test_participation_is_not_a_claim_type(self):
        with self.assertRaises(ValidationError):
            CandidateClaim.model_validate({**claim_doc("claim_a_python_profile"), "claim_type": "program_participation"})
        with self.assertRaises(ValidationError):
            ProgramParticipation.model_validate({**support.ext_raw()["participations"][0], "state": "inferred"})

    def test_participation_requires_authority_record_evidence(self):
        doc = support.ext_raw()
        doc["participations"][0]["evidence_ids"] = ["evidence_a_profile_hours"]  # candidate statement
        expect_violation(self, "evidence_provenance", self._check, doc)

    def test_candidate_authority_evidence_must_be_declared_participation_authority(self):
        doc = support.ext_raw()
        ev = next(e for e in doc["evidence"] if e["id"] == "evidence_a_enrollment")
        ev["source_ref"] = copy.deepcopy(next(e for e in doc["evidence"] if e["id"] == "evidence_a_profile_hours")["source_ref"])
        ctx = support.ext_context(doc)
        expect_violation(self, "evidence_provenance", check_evidence_records, ctx.evidence, ctx.records,
                         support.ext_capabilities())

    def test_conflicting_participation_records_rejected(self):
        doc = support.ext_raw()
        doc["participations"].append({**doc["participations"][0], "id": "participation_a_conflict", "status": "not_participating"})
        expect_violation(self, "participation_conflict", self._check, doc)
        doc = support.ext_raw()
        doc["participations"].append({**doc["participations"][0], "id": "participation_a_again"})
        self._check(doc)  # corroborating authoritative records are allowed


if __name__ == "__main__":
    unittest.main()


class VocabularyVersionIntegrityTests(unittest.TestCase):
    """R2: one (vocabulary id, version) identifies exactly one definition."""

    def _conflicting(self, **changes):
        doc = support.ext_raw()
        doc["vocabularies"].append({**copy.deepcopy(doc["vocabularies"][0]), **changes})
        return doc

    def test_conflicting_definition_rejected_by_claim_checks(self):
        doc = self._conflicting(skills=["data_analysis", "python", "spreadsheets", "web_content", "rust"])
        expect_violation(self, "vocabulary_version_conflict", check_with, doc)

    def test_conflict_detected_regardless_of_order(self):
        doc = self._conflicting(skills=["python"])
        doc["vocabularies"].reverse()
        expect_violation(self, "vocabulary_version_conflict", check_with, doc)

    def test_conflicting_definition_rejected_by_requirement_checks(self):
        from rap_contracts.eligibility import check_requirements

        doc = self._conflicting(skills=["python"])
        expect_violation(self, "vocabulary_version_conflict", check_requirements,
                         support.ext_context(doc), support.ext_capabilities())

    def test_same_id_and_version_in_another_org_rejected(self):
        doc = self._conflicting(organization_id="org_demo_002")
        expect_violation(self, "vocabulary_version_conflict", check_with, doc)

    def test_identical_duplicate_and_new_version_allowed(self):
        check_with(self._conflicting())  # byte-identical re-delivery of the same version
        check_with(self._conflicting(version=2, skills=["python"]))  # a new version may differ

    def test_standalone_index_reports_conflict(self):
        from rap_contracts.claims import index_vocabularies

        vocab = ClaimVocabulary.model_validate(support.ext_raw()["vocabularies"][0])
        changed = ClaimVocabulary.model_validate({**support.ext_raw()["vocabularies"][0], "interest_areas": ["data"]})
        self.assertEqual(index_vocabularies([vocab, vocab]), {(vocab.id, vocab.version): vocab})
        expect_violation(self, "vocabulary_version_conflict", index_vocabularies, [vocab, changed])
