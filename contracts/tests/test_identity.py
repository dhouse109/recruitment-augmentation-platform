"""D-004.01 -- identity, subject and organization scope."""

import unittest

from pydantic import ValidationError

import support
from rap_contracts.invariants import (
    ContractRecordSet,
    ContractViolation,
    check_candidate_update,
    check_identity_mappings,
    check_identity_source,
    check_record_set,
)
from rap_contracts.models import Application, Candidate, CandidateProfile


class IdentityMappingTests(unittest.TestCase):
    def test_fixture_identities_are_valid(self):
        recs = support.records()
        check_identity_mappings(recs.candidates)
        caps = support.capabilities()
        for cand in recs.candidates:
            check_identity_source(cand, caps)

    def test_same_account_gets_distinct_candidates_in_two_orgs(self):
        recs = support.records()
        a = support.by_id(recs.candidates, "candidate_demo_a")
        c = support.by_id(recs.candidates, "candidate_demo_c")
        self.assertEqual(a.identity_source, c.identity_source)
        self.assertNotEqual(a.organization_id, c.organization_id)
        self.assertNotEqual(a.id, c.id)
        check_identity_mappings([a, c])

    def test_second_candidate_for_same_account_in_same_org_rejected(self):
        dup = support.raw_record("candidates", "candidate_demo_b")
        dup["identity_source"]["entity_id"] = "9001"  # account already mapped to candidate_demo_a
        cands = list(support.records().candidates) + [Candidate.model_validate({**dup, "id": "candidate_demo_x"})]
        with self.assertRaises(ContractViolation) as ctx:
            check_identity_mappings(cands)
        self.assertEqual(ctx.exception.code, "identity_conflict")

    def test_candidate_id_reused_across_orgs_rejected(self):
        reused = support.raw_record("candidates", "candidate_demo_c")
        reused["id"] = "candidate_demo_a"
        cands = [support.by_id(support.records().candidates, "candidate_demo_a"), Candidate.model_validate(reused)]
        with self.assertRaises(ContractViolation) as ctx:
            check_identity_mappings(cands)
        self.assertEqual(ctx.exception.code, "candidate_id_reused")

    def test_identity_source_must_be_declared_identity_type(self):
        bad = support.raw_record("candidates", "candidate_demo_a")
        bad["identity_source"]["entity_type"] = "candidate_profile"
        with self.assertRaises(ContractViolation) as ctx:
            check_identity_source(Candidate.model_validate(bad), support.capabilities())
        self.assertEqual(ctx.exception.code, "invalid_identity_source")


class IdentityImmutabilityTests(unittest.TestCase):
    def setUp(self):
        self.cand = support.by_id(support.records().candidates, "candidate_demo_a")

    def test_reprojection_with_same_identity_allowed(self):
        check_candidate_update(self.cand, Candidate.model_validate(self.cand.model_dump()))

    def test_identity_source_change_rejected(self):
        changed = self.cand.model_dump()
        changed["identity_source"]["entity_id"] = "9999"
        with self.assertRaises(ContractViolation) as ctx:
            check_candidate_update(self.cand, Candidate.model_validate(changed))
        self.assertEqual(ctx.exception.code, "identity_immutable")

    def test_organization_change_rejected(self):
        changed = {**self.cand.model_dump(), "organization_id": "org_demo_002"}
        with self.assertRaises(ContractViolation) as ctx:
            check_candidate_update(self.cand, Candidate.model_validate(changed))
        self.assertEqual(ctx.exception.code, "candidate_immutable_field")

    def test_attribute_assignment_blocked(self):
        with self.assertRaises(ValidationError):
            self.cand.identity_source = self.cand.identity_source  # frozen model


class PortableIdTests(unittest.TestCase):
    def test_personal_data_shaped_and_mistyped_ids_rejected(self):
        base = support.raw_record("candidates", "candidate_demo_a")
        for bad_id in (
            "candidate_jane.doe@example.org",
            "candidate_Demo_A",
            "candidate demo a",
            "user_9001",  # account/source id is not a candidate id
            "9001",
            "candidate_",
            "candidate_" + "x" * 60,
        ):
            with self.subTest(bad_id=bad_id), self.assertRaises(ValidationError):
                Candidate.model_validate({**base, "id": bad_id})

    def test_unknown_fields_rejected(self):
        base = support.raw_record("candidates", "candidate_demo_a")
        with self.assertRaises(ValidationError):
            Candidate.model_validate({**base, "email": "synthetic@example.invalid"})


class CrossOrganizationReferenceTests(unittest.TestCase):
    """Cross-org *reference* rejection. Cross-org *match* rejection is deferred to the matching PR."""

    def test_fixture_record_set_is_consistent(self):
        check_record_set(support.records())

    def _with(self, **changes):
        recs = support.records()
        return ContractRecordSet(**{**recs.__dict__, **changes})

    def test_profile_for_candidate_in_other_org_rejected(self):
        bad = support.raw_record("profiles", "profile_demo_c")
        bad["id"] = "profile_demo_cross"
        bad["candidate_id"] = "candidate_demo_a"
        recs = self._with(profiles=support.records().profiles + (CandidateProfile.model_validate(bad),))
        with self.assertRaises(ContractViolation) as ctx:
            check_record_set(recs)
        self.assertEqual(ctx.exception.code, "cross_org_reference")

    def test_application_targeting_other_org_opportunity_rejected(self):
        bad = support.raw_record("applications", "application_demo_b_program")
        bad["id"] = "application_demo_b_cross"
        bad["target"] = {"opportunity_id": "opportunity_demo_job"}  # org_demo_002
        recs = self._with(applications=support.records().applications + (Application.model_validate(bad),))
        with self.assertRaises(ContractViolation) as ctx:
            check_record_set(recs)
        self.assertEqual(ctx.exception.code, "cross_org_reference")

    def test_application_for_candidate_in_other_org_rejected(self):
        bad = support.raw_record("applications", "application_demo_b_program")
        bad["id"] = "application_demo_c_cross"
        bad["candidate_id"] = "candidate_demo_c"  # org_demo_002 candidate in org_demo_001 application
        recs = self._with(applications=support.records().applications + (Application.model_validate(bad),))
        with self.assertRaises(ContractViolation) as ctx:
            check_record_set(recs)
        self.assertEqual(ctx.exception.code, "cross_org_reference")

    def test_record_source_ref_in_other_org_rejected_at_model_level(self):
        bad = support.raw_record("profiles", "profile_demo_a")
        bad["source_ref"]["organization_id"] = "org_demo_002"
        with self.assertRaises(ValidationError):
            CandidateProfile.model_validate(bad)


if __name__ == "__main__":
    unittest.main()
