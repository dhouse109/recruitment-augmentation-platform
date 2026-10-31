"""Every rule kind and every representable (kind, result, reason) is produced by the engine.

Each scenario is a new synthetic world mutation. A scenario only counts if the
engine returns ``Assessed``, which already means the unmodified wrapper and
``check_eligibility_result`` accepted the result (P10).
"""

import unittest

from rap_contracts.eligibility import REASON_CODES, PolicyRuleKind, RuleResult

from builders import (ANA, BEN, CY, DATA, HAS, LACKS, OPS, PILOT, WEB, BETA_JOB, BETA_POLICY, World, hours, outcome_map, run)
from rap_baseline import Assessed

PY_CLAIMS = ("claim_s1_ana_python_app", "claim_s1_ana_python_profile")


def set_status(opp_id, status):
    return lambda w: w.opportunity(opp_id).update(status=status)


def ana_participation(status):
    return lambda w: next(p for p in w.participations if p["id"] == "participation_s1_ana").update(status=status)


def drop_ana_participation(w):
    w.participations = [p for p in w.participations if p["id"] != "participation_s1_ana"]


def ana_hours(n):
    return lambda w: w.claim("claim_s1_ana_hours").update(value=hours(n))


def ben_hours_contested(w):
    w.remove_claim("claim_s1_ben_hours")
    w.add_statement(BEN, "evidence_s1_ben_hours_profile", "availability.weekly_hours")
    w.add_statement(BEN, "evidence_s1_ben_hours_app", "answers.weekly_hours", source="application")
    w.add_claim("claim_s1_ben_hours_contested", BEN, None, "contested", alternatives=[
        {"value": hours(10), "evidence_ids": ["evidence_s1_ben_hours_profile"]},
        {"value": hours(20), "evidence_ids": ["evidence_s1_ben_hours_app"]}])


def no_hours_requirement(opp):
    return lambda w: w.remove_requirement(f"requirement_s1_{opp.removeprefix('opportunity_s1_')}_hours")


def drop_ana_python(w):
    for cid in PY_CLAIMS:
        w.remove_claim(cid)


def ana_python_verified(w):
    w.add_verification(ANA, "evidence_s1_ana_python_verified", "9101", "assessments.python")
    w.add_claim("claim_s1_ana_python_verified", ANA, "python", "declared", HAS, ["evidence_s1_ana_python_verified"])


def ana_python_lacks(verified):
    def mutate(w):
        drop_ana_python(w)
        if verified:
            w.add_verification(ANA, "evidence_s1_ana_python_check", "9102", "assessments.python")
        else:
            w.add_statement(ANA, "evidence_s1_ana_python_check", "answers.python_screening", source="application")
        w.add_claim("claim_s1_ana_python_lacks", ANA, "python", "declared", LACKS, ["evidence_s1_ana_python_check"])
    return mutate


def ana_python_inferred(w):
    drop_ana_python(w)
    w.add_statement(ANA, "evidence_s1_ana_project", "answers.project", source="application")
    w.add_claim("claim_s1_ana_python_inferred", ANA, "python", "inferred", HAS, ["evidence_s1_ana_project"])


NOOP = lambda w: None  # noqa: E731
A, P, V, Q = "S1-ACTIVE-001", "S1-PROGRAM-002", "S1-AVAIL-003", "S1-SKILL-004"

#: name -> (mutation, candidate, opportunity, policy, rule id, expected outcome, decision)
SCENARIOS = {
    "active_pass": (NOOP, ANA, DATA, PILOT, A, ("pass", "opportunity_active", (), (), ()), "eligible"),
    "active_paused": (NOOP, ANA, OPS, PILOT, A, ("fail", "opportunity_paused", (), (), ()), "ineligible"),
    "active_closed": (set_status(OPS, "closed"), ANA, OPS, PILOT, A, ("fail", "opportunity_closed", (), (), ()), "ineligible"),
    "program_confirmed": (NOOP, ANA, DATA, PILOT, P, ("pass", "participation_confirmed", (), ("participation_s1_ana",), ()), "eligible"),
    "program_not_participating": (ana_participation("not_participating"), ANA, DATA, PILOT, P,
                                  ("fail", "participation_not_participating", (), ("participation_s1_ana",), ()), "ineligible"),
    "program_not_recorded": (drop_ana_participation, ANA, DATA, PILOT, P,
                             ("unknown", "participation_not_recorded", (), (), ()), "needs_information"),
    "hours_meet": (NOOP, ANA, DATA, PILOT, V, ("pass", "availability_meets_required_hours", ("claim_s1_ana_hours",), (),
                                               ("requirement_s1_data_hours",)), "eligible"),
    "hours_meet_exactly": (ana_hours(12), ANA, DATA, PILOT, V, ("pass", "availability_meets_required_hours",
                                                                ("claim_s1_ana_hours",), (), ("requirement_s1_data_hours",)), "eligible"),
    "hours_below": (ana_hours(11), ANA, DATA, PILOT, V, ("fail", "availability_below_required_hours", ("claim_s1_ana_hours",),
                                                         (), ("requirement_s1_data_hours",)), "ineligible"),
    "hours_not_declared": (NOOP, BEN, DATA, PILOT, V, ("unknown", "availability_not_declared", ("claim_s1_ben_hours",), (), ()),
                           "needs_information"),
    "hours_contested": (ben_hours_contested, BEN, DATA, PILOT, V,
                        ("unknown", "availability_contested", ("claim_s1_ben_hours_contested",), (), ()), "needs_information"),
    "hours_not_published": (no_hours_requirement(WEB), ANA, WEB, PILOT, V,
                            ("unknown", "required_hours_not_published", (), (), ()), "needs_information"),
    "skill_declared": (NOOP, ANA, DATA, PILOT, Q, ("pass", "qualification_declared", PY_CLAIMS, (), ("requirement_s1_data_python",)),
                       "eligible"),
    "skill_verified": (ana_python_verified, ANA, DATA, PILOT, Q,
                       ("pass", "qualification_independently_verified", PY_CLAIMS[:1] + PY_CLAIMS[1:] + ("claim_s1_ana_python_verified",),
                        (), ("requirement_s1_data_python",)), "eligible"),
    "skill_none_required": (NOOP, ANA, WEB, PILOT, Q, ("pass", "no_mandatory_qualification", (), (), ()), "eligible"),
    "skill_contradicted_declaration": (ana_python_lacks(False), ANA, DATA, PILOT, Q,
                                       ("fail", "qualification_contradicted_by_declaration", ("claim_s1_ana_python_lacks",), (),
                                        ("requirement_s1_data_python",)), "ineligible"),
    "skill_contradicted_verification": (ana_python_lacks(True), ANA, DATA, PILOT, Q,
                                        ("fail", "qualification_contradicted_by_verification", ("claim_s1_ana_python_lacks",), (),
                                         ("requirement_s1_data_python",)), "ineligible"),
    "skill_contested": (NOOP, BEN, DATA, PILOT, Q, ("unknown", "qualification_contested", ("claim_s1_ben_python",), (),
                                                    ("requirement_s1_data_python",)), "needs_information"),
    "skill_only_inferred": (ana_python_inferred, ANA, DATA, PILOT, Q,
                            ("unknown", "qualification_only_inferred", ("claim_s1_ana_python_inferred",), (),
                             ("requirement_s1_data_python",)), "needs_information"),
    "skill_not_evidenced": (drop_ana_python, ANA, DATA, PILOT, Q,
                            ("unknown", "qualification_not_evidenced", (), (), ("requirement_s1_data_python",)), "needs_information"),
    "portable_job_policy": (NOOP, CY, BETA_JOB, BETA_POLICY, "S1B-AVAIL-002",
                            ("pass", "availability_meets_required_hours", ("claim_s1_cy_hours",), (), ("requirement_s1_beta_job_hours",)),
                            "eligible"),
}

KIND_OF = {A: PolicyRuleKind.OPPORTUNITY_STATUS_ACTIVE, P: PolicyRuleKind.PROGRAM_PARTICIPATION_CONFIRMED,
           V: PolicyRuleKind.AVAILABILITY_MEETS_REQUIRED_HOURS, Q: PolicyRuleKind.MANDATORY_QUALIFICATION_EVIDENCED,
           "S1B-AVAIL-002": PolicyRuleKind.AVAILABILITY_MEETS_REQUIRED_HOURS}


class RuleScenarioTests(unittest.TestCase):
    def test_each_scenario(self):
        for name, (mutate, cand, opp, pin, rule_id, expected, decision) in SCENARIOS.items():
            with self.subTest(name):
                world = World()
                mutate(world)
                out, _ = run(world, cand, opp, pin)
                self.assertIsInstance(out, Assessed, f"{name}: {out}")
                got = outcome_map(out.result)[rule_id]
                self.assertEqual(got[:2], expected[:2])
                self.assertEqual(got[2:], tuple(tuple(sorted(x)) for x in expected[2:]))
                self.assertEqual(out.result.decision.value, decision)

    def test_every_representable_reason_code_is_covered(self):
        covered = {(KIND_OF[s[4]], RuleResult(s[5][0]), s[5][1]) for s in SCENARIOS.values()}
        representable = {(kind, res, code) for kind, by_res in REASON_CODES.items() for res, codes in by_res.items()
                         for code in codes}
        self.assertEqual(representable - covered, set(), "uncovered (kind, result, reason) combinations")
        self.assertEqual(len(representable), 19)

    def test_active_rule_has_no_unknown_reason_per_o1(self):
        self.assertEqual(REASON_CODES[PolicyRuleKind.OPPORTUNITY_STATUS_ACTIVE][RuleResult.UNKNOWN], frozenset())

    def test_outcomes_follow_policy_rule_order_and_citations_are_sorted(self):
        out, _ = run(World(), ANA, DATA)
        self.assertEqual([o.rule_id for o in out.result.rule_outcomes], [A, P, V, Q])
        for o in out.result.rule_outcomes:
            for ids in (o.claim_ids, o.participation_ids, o.requirement_ids):
                self.assertEqual(list(ids), sorted(ids))


if __name__ == "__main__":
    unittest.main()
