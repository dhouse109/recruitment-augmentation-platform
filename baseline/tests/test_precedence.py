"""SD-4 precedence and SD-5 citations (approved 2026-10-31), including several required codes,
mixed self-declared/verified evidence, losing-but-supportable alternatives, rejected
alternatives and contradictory records (refused, never an outcome).
"""

import unittest

from rap_contracts.eligibility import EligibilityResult, check_eligibility_result
from rap_contracts.invariants import ContractViolation

from builders import (ANA, BEN, DATA, HAS, LACKS, PILOT, WEB, StubAuthority, World, as_ref, hours, outcome_map, run)
from rap_baseline import Assessed, Refused, Stage

Q, V, P = "S1-SKILL-004", "S1-AVAIL-003", "S1-PROGRAM-002"
PY = ("claim_s1_ana_python_app", "claim_s1_ana_python_profile")
R_PY, R_SH, R_DA = "requirement_s1_data_python", "requirement_s1_data_spreadsheets", "requirement_s1_data_data_analysis"


def multi(w: World) -> World:
    w.add_skill_requirement(DATA, "spreadsheets")
    return w


def drop_python(w, cand=ANA):
    for c in [c for c in w.claims if c["candidate_id"] == cand and c.get("subject_code") == "python"]:
        w.remove_claim(c["id"])


def alternative(base: EligibilityResult, rule_id: str, **changes) -> EligibilityResult:
    doc = base.model_dump(mode="python")
    for o in doc["rule_outcomes"]:
        if o["rule_id"] == rule_id:
            o.update(changes)
    return EligibilityResult.model_validate(doc)


class Base(unittest.TestCase):
    def assess(self, world, cand=ANA, opp=DATA, authority=None):
        out, auth = run(world, cand, opp, PILOT, authority=authority)
        self.assertIsInstance(out, Assessed, str(out))
        self.ctx = world.build()[0]
        return out.result, auth

    def assertRule(self, result, rule_id, res, reason, claims=(), parts=(), reqs=()):
        self.assertEqual(outcome_map(result)[rule_id],
                         (res, reason, tuple(sorted(claims)), tuple(sorted(parts)), tuple(sorted(reqs))))

    def assertSupportable(self, alt):
        check_eligibility_result(alt, self.ctx)  # raises if not supportable

    def assertRejected(self, alt, code):
        with self.assertRaises(ContractViolation) as cm:
            check_eligibility_result(alt, self.ctx)
        self.assertEqual(cm.exception.code, code)


class QualificationPrecedenceTests(Base):
    def test_q1_two_codes_both_declared(self):
        w = multi(World())
        w.add_statement(ANA, "evidence_s1_ana_sheets", "skills.spreadsheets")
        w.add_claim("claim_s1_ana_sheets", ANA, "spreadsheets", "declared", HAS, ["evidence_s1_ana_sheets"])
        res, _ = self.assess(w)
        self.assertRule(res, Q, "pass", "qualification_declared", PY + ("claim_s1_ana_sheets",), (), (R_PY, R_SH))
        self.assertRejected(alternative(res, Q, claim_ids=PY, requirement_ids=(R_PY,)), "unsupported_outcome")

    def _mixed(self, verify_sheets: bool):
        w = multi(World())
        w.add_verification(ANA, "evidence_s1_ana_python_verified", "9201", "assessments.python")
        w.add_claim("claim_s1_ana_python_verified", ANA, "python", "declared", HAS, ["evidence_s1_ana_python_verified"])
        w.add_statement(ANA, "evidence_s1_ana_sheets", "skills.spreadsheets")
        w.add_claim("claim_s1_ana_sheets", ANA, "spreadsheets", "declared", HAS, ["evidence_s1_ana_sheets"])
        if verify_sheets:
            w.add_verification(ANA, "evidence_s1_ana_sheets_verified", "9202", "assessments.spreadsheets")
            w.add_claim("claim_s1_ana_sheets_verified", ANA, "spreadsheets", "declared", HAS, ["evidence_s1_ana_sheets_verified"])
        return w

    def test_q2_one_code_statement_only_gives_declared(self):
        res, _ = self.assess(self._mixed(False))
        cited = PY + ("claim_s1_ana_python_verified", "claim_s1_ana_sheets")
        self.assertRule(res, Q, "pass", "qualification_declared", cited, (), (R_PY, R_SH))
        self.assertRejected(alternative(res, Q, reason_code="qualification_independently_verified"), "unsupported_outcome")

    def test_q3_every_code_verified_gives_verified_and_declared_loses(self):
        res, _ = self.assess(self._mixed(True))
        cited = PY + ("claim_s1_ana_python_verified", "claim_s1_ana_sheets", "claim_s1_ana_sheets_verified")
        self.assertRule(res, Q, "pass", "qualification_independently_verified", cited, (), (R_PY, R_SH))
        self.assertSupportable(alternative(res, Q, reason_code="qualification_declared"))

    def _mixed_lacks(self):
        w = multi(World())
        drop_python(w)
        w.add_statement(ANA, "evidence_s1_ana_python_screen", "answers.python_screening", source="application")
        w.add_claim("claim_s1_ana_python_lacks", ANA, "python", "declared", LACKS, ["evidence_s1_ana_python_screen"])
        w.add_verification(ANA, "evidence_s1_ana_sheets_check", "9203", "assessments.spreadsheets")
        w.add_claim("claim_s1_ana_sheets_lacks", ANA, "spreadsheets", "declared", LACKS, ["evidence_s1_ana_sheets_check"])
        return w

    def test_q4_mixed_basis_contradiction_cites_verification_subset_only(self):
        """SD-18 / G12: the declaration-backed contradiction on python is deliberately uncited."""
        res, _ = self.assess(self._mixed_lacks())
        self.assertRule(res, Q, "fail", "qualification_contradicted_by_verification", ("claim_s1_ana_sheets_lacks",), (), (R_SH,))
        self.assertSupportable(alternative(res, Q, reason_code="qualification_contradicted_by_declaration",
                                           claim_ids=("claim_s1_ana_python_lacks",), requirement_ids=(R_PY,)))
        both = ("claim_s1_ana_python_lacks", "claim_s1_ana_sheets_lacks")
        for code in ("qualification_contradicted_by_verification", "qualification_contradicted_by_declaration"):
            self.assertRejected(alternative(res, Q, reason_code=code, claim_ids=both, requirement_ids=(R_PY, R_SH)),
                                "unsupported_outcome")

    def test_q5_contradiction_beats_contested_and_cites_only_the_contradiction(self):
        w = multi(World())
        w.add_statement(BEN, "evidence_s1_ben_sheets", "skills.spreadsheets")
        w.add_claim("claim_s1_ben_sheets", BEN, "spreadsheets", "declared", LACKS, ["evidence_s1_ben_sheets"])
        res, _ = self.assess(w, BEN)
        self.assertRule(res, Q, "fail", "qualification_contradicted_by_declaration", ("claim_s1_ben_sheets",), (), (R_SH,))
        self.assertRejected(alternative(res, Q, claim_ids=("claim_s1_ben_python", "claim_s1_ben_sheets"),
                                        requirement_ids=(R_PY, R_SH)), "non_authoritative_input")

    def _undetermined(self, with_contested: bool):
        w = multi(World())
        drop_python(w)
        w.add_statement(ANA, "evidence_s1_ana_project", "answers.project", source="application")
        w.add_claim("claim_s1_ana_python_inferred", ANA, "python", "inferred", HAS, ["evidence_s1_ana_project"])
        if with_contested:
            w.add_skill_requirement(DATA, "data_analysis")
            w.add_statement(ANA, "evidence_s1_ana_da_profile", "skills.data_analysis")
            w.add_statement(ANA, "evidence_s1_ana_da_app", "answers.data_analysis", source="application")
            w.add_claim("claim_s1_ana_da", ANA, "data_analysis", "contested", alternatives=[
                {"value": HAS, "evidence_ids": ["evidence_s1_ana_da_profile"]},
                {"value": LACKS, "evidence_ids": ["evidence_s1_ana_da_app"]}])
        return w

    def test_q6_contested_wins_and_every_undetermined_code_is_cited(self):
        res, _ = self.assess(self._undetermined(True))
        cited = ("claim_s1_ana_da", "claim_s1_ana_python_inferred")
        self.assertRule(res, Q, "unknown", "qualification_contested", cited, (), (R_DA, R_PY, R_SH))
        self.assertSupportable(alternative(res, Q, reason_code="qualification_only_inferred"))
        self.assertRejected(alternative(res, Q, reason_code="qualification_not_evidenced"), "unsupported_outcome")

    def test_q7_inferred_only_beats_not_evidenced(self):
        res, _ = self.assess(self._undetermined(False))
        self.assertRule(res, Q, "unknown", "qualification_only_inferred", ("claim_s1_ana_python_inferred",), (), (R_PY, R_SH))
        self.assertSupportable(alternative(res, Q, reason_code="qualification_not_evidenced"))

    def test_q8_not_evidenced_cites_only_the_undetermined_requirement(self):
        res, _ = self.assess(multi(World()))
        self.assertRule(res, Q, "unknown", "qualification_not_evidenced", (), (), (R_SH,))
        self.assertRejected(alternative(res, Q, claim_ids=PY, requirement_ids=(R_PY, R_SH)), "unsupported_outcome")

    def test_q9_inferred_lacks_never_overrides_declared_has(self):
        w = World()
        w.add_statement(ANA, "evidence_s1_ana_project", "answers.project", source="application")
        w.add_claim("claim_s1_ana_python_inferred_lacks", ANA, "python", "inferred", LACKS, ["evidence_s1_ana_project"])
        res, _ = self.assess(w)
        self.assertRule(res, Q, "pass", "qualification_declared", PY, (), (R_PY,))


class AvailabilityAndParticipationPrecedenceTests(Base):
    def test_v1_unpublished_hours_beats_not_declared(self):
        w = World()
        w.remove_requirement("requirement_s1_web_hours")
        res, _ = self.assess(w, BEN, WEB)
        self.assertRule(res, V, "unknown", "required_hours_not_published")
        self.assertSupportable(alternative(res, V, reason_code="availability_not_declared", claim_ids=("claim_s1_ben_hours",)))

    def test_v2_contested_beats_not_declared(self):
        w = World()
        w.remove_claim("claim_s1_ben_hours")
        w.add_statement(BEN, "evidence_s1_ben_hours_profile", "availability.weekly_hours")
        w.add_statement(BEN, "evidence_s1_ben_hours_app", "answers.weekly_hours", source="application")
        w.add_claim("claim_s1_ben_hours_c", BEN, None, "contested", alternatives=[
            {"value": hours(10), "evidence_ids": ["evidence_s1_ben_hours_profile"]},
            {"value": hours(20), "evidence_ids": ["evidence_s1_ben_hours_app"]}])
        res, _ = self.assess(w, BEN)
        self.assertRule(res, V, "unknown", "availability_contested", ("claim_s1_ben_hours_c",))
        self.assertSupportable(alternative(res, V, reason_code="availability_not_declared", claim_ids=()))

    def test_v3_inferred_hours_cited_under_not_declared_and_never_decisive(self):
        w = World()
        w.add_statement(BEN, "evidence_s1_ben_project", "answers.project", source="application")
        w.add_claim("claim_s1_ben_hours_inferred", BEN, None, "inferred", hours(40), ["evidence_s1_ben_project"])
        res, _ = self.assess(w, BEN)
        self.assertRule(res, V, "unknown", "availability_not_declared", ("claim_s1_ben_hours", "claim_s1_ben_hours_inferred"))
        self.assertRejected(alternative(res, V, result="pass", reason_code="availability_meets_required_hours",
                                        claim_ids=("claim_s1_ben_hours_inferred",),
                                        requirement_ids=("requirement_s1_data_hours",)), "non_authoritative_input")

    def test_corroborating_declared_hours_are_all_cited(self):
        w = World()
        w.add_statement(ANA, "evidence_s1_ana_hours_app", "answers.weekly_hours", source="application")
        w.add_claim("claim_s1_ana_hours_app", ANA, None, "declared", hours(20), ["evidence_s1_ana_hours_app"])
        res, _ = self.assess(w)
        self.assertRule(res, V, "pass", "availability_meets_required_hours", ("claim_s1_ana_hours", "claim_s1_ana_hours_app"),
                        (), ("requirement_s1_data_hours",))

    def test_p1_corroborating_participation_records_are_all_cited(self):
        w = World()
        w.add_participation("participation_s1_ana_second", ANA, "program_s1_pathways", "confirmed", "6111", "41")
        res, _ = self.assess(w)
        self.assertRule(res, P, "pass", "participation_confirmed", (), ("participation_s1_ana", "participation_s1_ana_second"))


class ContradictoryRecordTests(unittest.TestCase):
    """Contradictory authoritative or declared records are refused, never turned into an outcome."""

    def refused(self, world, cand=ANA, opp=DATA, stage=Stage.CONTEXT):
        out, auth = run(world, cand, opp)
        self.assertIsInstance(out, Refused, str(out))
        self.assertEqual(out.stage, stage)
        return out, auth

    def test_participation_conflict(self):
        w = World()
        w.add_participation("participation_s1_ana_conflict", ANA, "program_s1_pathways", "not_participating", "6112", "42")
        out, auth = self.refused(w)
        self.assertEqual(out.code, "participation_conflict")
        self.assertTrue(auth.calls, "contradiction detected only after the gate")

    def test_uncontested_has_and_lacks(self):
        w = World()
        w.add_statement(ANA, "evidence_s1_ana_python_screen", "answers.python_screening", source="application")
        w.add_claim("claim_s1_ana_python_lacks", ANA, "python", "declared", LACKS, ["evidence_s1_ana_python_screen"])
        self.assertEqual(self.refused(w)[0].code, "unresolved_conflict")

    def test_conflicting_declared_hours(self):
        w = World()
        w.add_statement(ANA, "evidence_s1_ana_hours_app", "answers.weekly_hours", source="application")
        w.add_claim("claim_s1_ana_hours_app", ANA, None, "declared", hours(5), ["evidence_s1_ana_hours_app"])
        self.assertEqual(self.refused(w)[0].code, "unresolved_conflict")

    def test_contested_alongside_declared(self):
        w = World()
        w.add_statement(ANA, "evidence_s1_ana_alt1", "skills.python_alt")
        w.add_statement(ANA, "evidence_s1_ana_alt2", "answers.python_alt", source="application")
        w.add_claim("claim_s1_ana_python_c", ANA, "python", "contested", alternatives=[
            {"value": HAS, "evidence_ids": ["evidence_s1_ana_alt1"]}, {"value": LACKS, "evidence_ids": ["evidence_s1_ana_alt2"]}])
        self.assertEqual(self.refused(w)[0].code, "contested_not_exclusive")

    def test_unknown_alongside_declared(self):
        w = World()
        w.add_claim("claim_s1_ana_hours_unknown", ANA, None, "unknown")
        self.assertEqual(self.refused(w)[0].code, "unknown_conflicts_with_value")

    def test_two_published_hours_requirements(self):
        w = World()
        w.add_hours_requirement(DATA, 30, "requirement_s1_data_hours_second")
        out, auth = self.refused(w, stage=Stage.STRUCTURE)
        self.assertEqual(out.code, "requirement_conflict")
        self.assertEqual(auth.calls, [])

    def test_two_definitions_of_one_policy_pin(self):
        w = World()
        w.policies.append({**w.policy(), "rules": w.policy()["rules"][:1]})
        out, auth = self.refused(w, stage=Stage.REFERENCE)
        self.assertEqual(out.code, "policy_version_conflict")
        self.assertEqual(auth.calls, [])


class VerifiedVersusDeclaredTests(unittest.TestCase):
    """SD-19: a verified 'lacks' conflicting with a self-declared 'has' yields needs_information only as one
    contested claim that preserves both sources; it is never silently resolved."""

    def world(self):
        w = World()
        drop_python(w)
        w.add_statement(ANA, "evidence_s1_ana_python_says", "skills.python")
        w.add_verification(ANA, "evidence_s1_ana_python_check", "9301", "assessments.python")
        return w

    def test_preserved_as_contested_gives_needs_information_and_gates_both_sources(self):
        w = self.world()
        w.add_claim("claim_s1_ana_python_c", ANA, "python", "contested", alternatives=[
            {"value": HAS, "evidence_ids": ["evidence_s1_ana_python_says"]},
            {"value": LACKS, "evidence_ids": ["evidence_s1_ana_python_check"]}])
        out, auth = run(w)
        self.assertIsInstance(out, Assessed)
        self.assertEqual(outcome_map(out.result)[Q][:3], ("unknown", "qualification_contested", ("claim_s1_ana_python_c",)))
        self.assertEqual(out.result.decision.value, "needs_information")
        for eid in ("evidence_s1_ana_python_says", "evidence_s1_ana_python_check"):
            self.assertIn(as_ref(w.evidence_record(eid)["source_ref"]), out.provenance.gated_refs)

    def test_revoking_either_alternative_refuses_rather_than_resolving(self):
        for eid in ("evidence_s1_ana_python_says", "evidence_s1_ana_python_check"):
            with self.subTest(eid):
                w = self.world()
                w.add_claim("claim_s1_ana_python_c", ANA, "python", "contested", alternatives=[
                    {"value": HAS, "evidence_ids": ["evidence_s1_ana_python_says"]},
                    {"value": LACKS, "evidence_ids": ["evidence_s1_ana_python_check"]}])
                auth = StubAuthority()
                auth.deny(w.evidence_record(eid)["source_ref"])
                out, _ = run(w, authority=auth)
                self.assertIsInstance(out, Refused)
                self.assertEqual((out.stage, out.code), (Stage.SOURCE_GATE, "source_access_denied"))

    def test_delivered_as_two_declared_claims_is_refused(self):
        w = self.world()
        w.add_claim("claim_s1_ana_python_says", ANA, "python", "declared", HAS, ["evidence_s1_ana_python_says"])
        w.add_claim("claim_s1_ana_python_check", ANA, "python", "declared", LACKS, ["evidence_s1_ana_python_check"])
        out, _ = run(w)
        self.assertIsInstance(out, Refused)
        self.assertEqual((out.stage, out.code), (Stage.CONTEXT, "unresolved_conflict"))


if __name__ == "__main__":
    unittest.main()
