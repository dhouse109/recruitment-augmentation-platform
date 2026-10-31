"""Opportunity, program and organization isolation (D-004.05, D-004.01)."""

import unittest

from rap_contracts.eligibility import EligibilityResult

from builders import (ANA, CY, DATA, OPS, ORG2, OTHER_PROGRAM, WEB, BETA_JOB, BETA_POLICY, World, outcome_map,
                      ref, run)
from rap_baseline import Assessed


def assessed(world, cand=ANA, opp=DATA, pin=None, **kw):
    out, auth = run(world, cand, opp, pin or ("policy_s1_pilot", 1), **kw)
    assert isinstance(out, Assessed), out
    return out, auth


class OpportunityIsolationTests(unittest.TestCase):
    def test_changing_another_opportunity_changes_nothing_here(self):
        base = {o: assessed(World(), ANA, o)[0].result.model_dump_json() for o in (DATA, WEB)}
        w = World()
        w.opportunity(OPS).update(status="closed", source_ref=ref("opportunity", "4103", "19"))
        for r in w.requirements:
            if r["opportunity_id"] == OPS:
                r["source_ref"] = ref("opportunity", "4103", "19")
                r["requirement"]["hours_per_week"] = 40
        w.add_skill_requirement(OPS, "web_content")
        for o in (DATA, WEB):
            with self.subTest(o):
                self.assertEqual(assessed(w, ANA, o)[0].result.model_dump_json(), base[o])

    def test_ineligible_for_one_opportunity_leaves_the_next_assessment_unchanged(self):
        fresh = assessed(World(), ANA, WEB)[0].result.model_dump_json()
        w = World()
        ops, _ = assessed(w, ANA, OPS)
        self.assertEqual(ops.result.decision.value, "ineligible")
        self.assertEqual(assessed(w, ANA, WEB)[0].result.model_dump_json(), fresh)

    def test_result_has_no_candidate_level_field(self):
        self.assertEqual(set(EligibilityResult.model_fields) & {"rejection", "rejected", "rank", "score", "candidate_status"},
                         set())


class ProgramIsolationTests(unittest.TestCase):
    def test_participation_in_another_program_does_not_satisfy_this_one(self):
        w = World()
        w.participations = [p for p in w.participations if p["id"] != "participation_s1_ana"]
        w.add_participation("participation_s1_ana_other", ANA, OTHER_PROGRAM, "confirmed", "6131", "61")
        out, auth = assessed(w)
        self.assertEqual(outcome_map(out.result)["S1-PROGRAM-002"][:2], ("unknown", "participation_not_recorded"))
        self.assertNotIn(ref("program_enrollment", "6131", "61")["entity"]["entity_id"],
                         {r.entity.entity_id for r in auth.calls})

    def test_status_in_another_program_is_ignored(self):
        w = World()
        w.add_participation("participation_s1_ana_other", ANA, OTHER_PROGRAM, "not_participating", "6132", "62")
        out, _ = assessed(w)
        self.assertEqual(outcome_map(out.result)["S1-PROGRAM-002"][:2], ("pass", "participation_confirmed"))


class OrganizationSeparationTests(unittest.TestCase):
    def test_other_organization_sources_are_never_selected_or_checked(self):
        _, auth = assessed(World())
        self.assertTrue(all(r.organization_id == "org_s1_alpha" for r in auth.calls))

    def test_other_organization_results_are_unaffected_by_this_organizations_changes(self):
        base = assessed(World(), CY, BETA_JOB, BETA_POLICY)[0].result.model_dump_json()
        w = World()
        w.claim("claim_s1_ana_hours")["value"] = {"kind": "availability", "hours_per_week": 1}
        w.opportunity(DATA)["status"] = "paused"
        out, auth = assessed(w, CY, BETA_JOB, BETA_POLICY)
        self.assertEqual(out.result.model_dump_json(), base)
        self.assertTrue(all(r.organization_id == ORG2 for r in auth.calls))


if __name__ == "__main__":
    unittest.main()
