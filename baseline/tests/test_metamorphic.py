"""Metamorphic properties of the deterministic rules."""

import unittest

from builders import ANA, BEN, DATA, HAS, LACKS, WEB, World, hours, outcome_map, run
from rap_baseline import Assessed, Refused, Stage

Q, V = "S1-SKILL-004", "S1-AVAIL-003"


def assessed(world, cand=ANA, opp=DATA):
    out, _ = run(world, cand, opp)
    assert isinstance(out, Assessed), out
    return out.result


def results_only(result):
    return {k: v[0] for k, v in outcome_map(result).items()}, result.decision


class MetamorphicTests(unittest.TestCase):
    def test_adding_inferred_claims_never_changes_any_result_or_decision(self):
        for cand in (ANA, BEN):
            for presence in (HAS, LACKS):
                with self.subTest(cand=cand, presence=presence["presence"]):
                    base = results_only(assessed(World(), cand))
                    w = World()
                    w.add_statement(cand, f"evidence_s1_{cand[13:]}_guess", "answers.guess", source="application")
                    w.add_claim(f"claim_s1_{cand[13:]}_python_guess", cand, "python", "inferred", presence,
                                [f"evidence_s1_{cand[13:]}_guess"])
                    w.add_claim(f"claim_s1_{cand[13:]}_hours_guess", cand, None, "inferred", hours(1),
                                [f"evidence_s1_{cand[13:]}_guess"])
                    self.assertEqual(results_only(assessed(w, cand)), base)

    def test_verifying_every_required_code_changes_only_the_reason_and_citations(self):
        base = outcome_map(assessed(World()))
        w = World()
        w.add_verification(ANA, "evidence_s1_ana_python_verified", "9601", "assessments.python")
        w.add_claim("claim_s1_ana_python_verified", ANA, "python", "declared", HAS, ["evidence_s1_ana_python_verified"])
        out = outcome_map(assessed(w))
        self.assertEqual(out[Q][:2], ("pass", "qualification_independently_verified"))
        self.assertLess(set(base[Q][2]), set(out[Q][2]))
        self.assertEqual({k: v for k, v in out.items() if k != Q}, {k: v for k, v in base.items() if k != Q})

    def test_availability_is_monotonic_in_declared_hours(self):
        previous = None
        for n in range(0, 25):
            w = World()
            w.claim("claim_s1_ana_hours")["value"] = hours(n)
            res = outcome_map(assessed(w))[V][0]
            self.assertEqual(res, "pass" if n >= 12 else "fail", n)
            if previous == "pass":
                self.assertEqual(res, "pass", "raising hours never turns pass into fail")
            previous = res

    def test_removing_all_mandatory_requirements_gives_no_mandatory_qualification(self):
        w = World()
        w.remove_requirement("requirement_s1_data_python")
        self.assertEqual(outcome_map(assessed(w))[Q], ("pass", "no_mandatory_qualification", (), (), ()))

    def test_adding_a_declared_contradiction_turns_pass_into_fail(self):
        w = World()
        for cid in ("claim_s1_ana_python_app", "claim_s1_ana_python_profile"):
            w.remove_claim(cid)
        w.add_statement(ANA, "evidence_s1_ana_python_no", "answers.python_screening", source="application")
        w.add_claim("claim_s1_ana_python_no", ANA, "python", "declared", LACKS, ["evidence_s1_ana_python_no"])
        self.assertEqual(outcome_map(assessed(w))[Q][:2], ("fail", "qualification_contradicted_by_declaration"))

    def test_requirement_code_outside_vocabulary_is_refused_before_authority(self):
        w = World()
        w.add_skill_requirement(WEB, "python")
        w.vocabularies[0]["skills"].remove("python")
        out, auth = run(w, ANA, WEB)
        self.assertIsInstance(out, Refused)
        self.assertEqual((out.stage, out.code, auth.calls), (Stage.STRUCTURE, "unsupported_claim_code", []))


if __name__ == "__main__":
    unittest.main()
