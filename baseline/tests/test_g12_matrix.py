"""PR-S2 case matrix (plan rev. 2.2 section 6): C01-C19, G12a-c, identity rows ID1-ID6, determinism.

Test-local synthetic records only (``g12_cases.py`` on ``builders.World``). Engine
outcomes for these cases were observed at the PR-S1 base ``dbeee9ab``; the literal
result ids below are pinned from that base and must not change (ID6, A4).
"""

import json
import os
import random
import subprocess
import sys
import unittest
from datetime import timedelta
from pathlib import Path

from builders import AS_OF, DATA, EASTERN, OTHER_PRINCIPAL, run
from g12_cases import ASSESSED, CASES, REFUSED
from rap_baseline import Assessed, explanation, findings
from rap_contracts.eligibility import EligibilityContext

Q, V, P = "S1-SKILL-004", "S1-AVAIL-003", "S1-PROGRAM-002"
TESTS = Path(__file__).resolve().parent

#: ID6: result ids observed at the PR-S1 base commit dbeee9ab for identical admitted inputs.
BASE_RESULT_IDS = {
    "C01": "eligibility_dff6ae4768403bd1ad48699dbbd2021a944b29c9",
    "C02": "eligibility_22ad16d8a805851d21265ee485166f2fb18ac4f9",
    "C03": "eligibility_1d165b23c3586d5f85315e2c3f7fedaa76eff44a",
    "C04": "eligibility_bf9db1592a33e19f031e1c4511d932a3affdaac4",
    "C05": "eligibility_6f0dd04857d1eea21d1735b930c69a781a52b036",
    "C06": "eligibility_aefaaf4ec477fe9b6b41e65b043ada65faa664be",
    "C07": "eligibility_6955ddc8cf6351d8d777b9957dcea8756603cca2",
    "C08": "eligibility_da20f29b8a7b744706482e444a564952e097424f",
    "C09": "eligibility_c5ae0517c203cafc995c651eb6755cf0bf5aff28",
    "C10": "eligibility_20ceff72c455c3092a98f2869c4fe46fc6181db9",
    "C11": "eligibility_91ddd461a48e66a8bb54d186837438ffb3bfb297",
    "C12": "eligibility_ec320e25c9e3d06f75652f35ee946e8fea8f127d",
    "C13": "eligibility_8a8d6b5d71d482bbdf68ee61a37160efc871edc4",
    "C14": "eligibility_351d44ae7f4feea446f773e6b437467943f46c12",
    "C18": "eligibility_01fdbf3574fc1c5ebe4444dd85c0a928a026bb2e",
}

S = "claim_s1_"


def assess_case(name, **kw):
    w, cand, ckw = CASES[name]()
    out, _ = run(w, cand, DATA, **{**ckw, **kw})
    return out


def subjects(out, rule_id=Q):
    """subject key -> (status, role, gap, {input_id: (role, standing, ((basis, relation, alt_index), ...))})."""
    rule = next(r for r in out.findings.content.rules if r.rule_id == rule_id)
    table = {}
    for s in rule.subjects:
        key = s.skill_code or s.kind
        table[key] = (s.subject_status, s.subject_role, s.information_gap,
                      {c.input_id.removeprefix(S): (c.role, c.rule_standing,
                                                    tuple((a.basis, a.relation, a.alternative_index) for a in c.evidence))
                       for c in s.contributions})
    return table


STMT, VER, AUTH = "candidate_statement", "independent_verification", "authority_record"
DI, NDI = "decision_input", "non_decision_input"


class CaseMatrixTests(unittest.TestCase):
    """Section 6.1: engine outcomes [observed at base] and expected findings."""

    def test_assessed_cases_carry_findings_and_explanation(self):
        for name in ASSESSED:
            with self.subTest(name):
                out = assess_case(name)
                self.assertIsInstance(out, Assessed, str(out))
                self.assertEqual(out.findings.result_id, out.result.id)
                self.assertEqual(out.explanation.findings_id, out.findings.findings_id)

    def test_refused_cases_carry_no_findings_or_explanation(self):
        for name, (stage, code) in REFUSED.items():
            with self.subTest(name):
                out = assess_case(name)
                self.assertNotIsInstance(out, Assessed)
                self.assertEqual((out.stage.value, out.code), (stage, code))
                self.assertFalse(hasattr(out, "findings") or hasattr(out, "explanation") or hasattr(out, "result"))
        self.assertEqual(assess_case("C19").authority_calls, 0)

    def test_c01_eligible(self):
        out = assess_case("C01")
        self.assertEqual(out.result.decision.value, "eligible")
        self.assertEqual(subjects(out), {"python": ("satisfied_declared", "decisive", None, {
            "ana_python_app": ("cited", DI, ((STMT, "support", None),)),
            "ana_python_profile": ("cited", DI, ((STMT, "support", None),))})})
        self.assertEqual(subjects(out, P)["program_participation"][3],
                         {"participation_s1_ana": ("cited", DI, ((AUTH, "authority_record", None),))})

    def test_c02_g12a_uncited_contradiction_is_material(self):
        out = assess_case("C02")
        self.assertEqual(subjects(out), {
            "spreadsheets": ("contradicted_verified", "decisive", None,
                             {"ana_sheets_lacks": ("cited", DI, ((VER, "support", None),))}),
            "python": ("contradicted_declared", "uncited_nonpass", None,
                       {"ana_python_lacks": ("uncited_material", DI, ((STMT, "support", None),))})})

    def test_c03_g12b_not_evidenced(self):
        out = assess_case("C03")
        self.assertEqual(subjects(out)["python"], ("not_evidenced", "uncited_nonpass", "no_source_backed_value", {}))

    def test_c04_g12b_contested_alternatives_attributed(self):
        out = assess_case("C04")
        self.assertEqual(subjects(out)["python"], ("contested", "uncited_nonpass", "conflicting_sources", {
            "ben_python": ("uncited_material", NDI, ((STMT, "alternative_support", 0), (STMT, "alternative_support", 1)))}))
        python = next(s for s in out.findings.content.rules[3].subjects if s.skill_code == "python")
        self.assertEqual([(a.alternative_index, a.reading) for a in python.contributions[0].evidence], [(0, "has"), (1, "lacks")])
        self.assertEqual(subjects(out, V)["weekly_hours"],
                         ("not_declared", "decisive", "no_source_backed_value", {"ben_hours": ("cited", NDI, ())}))

    def test_c05_g12b_only_inferred(self):
        out = assess_case("C05")
        self.assertEqual(subjects(out)["python"], ("only_inferred", "uncited_nonpass", "only_inferred_signal", {
            "ana_python_inferred": ("uncited_material", NDI, ((STMT, "inference_input", None),))}))
        con = next(s for s in out.findings.content.rules[3].subjects if s.skill_code == "python").contributions[0]
        self.assertEqual(con.inferred_by, "s1-synthetic-inference/1")

    def test_c06_g12c_same_code_statement_is_material(self):
        out = assess_case("C06")
        self.assertEqual(subjects(out), {"python": ("contradicted_verified", "decisive", None, {
            "ana_python_lacks_v": ("cited", DI, ((VER, "support", None),)),
            "ana_python_lacks": ("uncited_material", DI, ((STMT, "support", None),))})})

    def test_c07_one_claim_two_bases(self):
        out = assess_case("C07")
        self.assertEqual(subjects(out)["python"][3], {"ana_python_lacks": ("cited", DI, ((VER, "support", None),
                                                                                         (STMT, "support", None)))})

    def test_c08_inferred_has_is_context(self):
        out = assess_case("C08")
        self.assertEqual(subjects(out)["python"], ("contradicted_declared", "decisive", None, {
            "ana_python_lacks": ("cited", DI, ((STMT, "support", None),)),
            "ana_python_inferred": ("context", NDI, ((STMT, "inference_input", None),))}))

    def test_c09_g12a_and_g12c(self):
        out = assess_case("C09")
        self.assertEqual(subjects(out), {
            "spreadsheets": ("contradicted_verified", "decisive", None, {
                "ana_sheets_lacks": ("cited", DI, ((VER, "support", None),)),
                "ana_sheets_lacks_stmt": ("uncited_material", DI, ((STMT, "support", None),))}),
            "python": ("contradicted_declared", "uncited_nonpass", None, {
                "ana_python_lacks": ("uncited_material", DI, ((STMT, "support", None),))})})

    def test_c10_negative_control_has_no_uncited_material(self):
        out = assess_case("C10")
        roles = {c.role for r in out.findings.content.rules for s in r.subjects for c in s.contributions}
        subject_roles = {s.subject_role for r in out.findings.content.rules for s in r.subjects}
        self.assertNotIn("uncited_material", roles)
        self.assertEqual(subject_roles, {"decisive"})

    def test_c11_c12_needs_information(self):
        out = assess_case("C11")
        self.assertEqual(out.result.decision.value, "needs_information")
        self.assertEqual(subjects(out)["python"][:3], ("contested", "decisive", "conflicting_sources"))
        self.assertEqual(subjects(out)["python"][3]["ben_python"][:2], ("cited", NDI))
        out = assess_case("C12")
        self.assertEqual(subjects(out)["python"], ("only_inferred", "decisive", "only_inferred_signal", {
            "ana_python_inferred": ("cited", NDI, ((STMT, "inference_input", None),))}))

    def test_c13_verified_is_per_code(self):
        out = assess_case("C13")
        table = subjects(out)
        self.assertEqual((table["python"][0], table["spreadsheets"][0]), ("satisfied_verified", "satisfied_declared"))
        self.assertEqual({r for _, _, _, cons in table.values() for r, *_ in cons.values()}, {"cited"})

    def test_c14_unpublished_hours_is_an_opportunity_gap(self):
        out = assess_case("C14")
        self.assertEqual(subjects(out, V)["weekly_hours"], ("hours_not_published", "decisive",
                                                           "opportunity_requirement_unpublished",
                                                           {"ana_hours": ("context", DI, ((STMT, "support", None),))}))
        hours = out.findings.content.rules[2].subjects[0]
        self.assertIsNone(hours.requirement)

    def test_c18_participation_not_recorded(self):
        out = assess_case("C18")
        self.assertEqual(subjects(out, P)["program_participation"],
                         ("not_recorded", "decisive", "no_participation_record", {}))

    def test_g12_omissions_are_exactly_the_documented_ones(self):
        """Across the matrix, uncited material appears only in G12a-c cases (C02-C06, C09)."""
        g12 = {"C02", "C03", "C04", "C05", "C06", "C09"}
        for name in ASSESSED:
            with self.subTest(name):
                out = assess_case(name)
                nonpass = any(s.subject_role == "uncited_nonpass" for r in out.findings.content.rules for s in r.subjects)
                material = any(c.role == "uncited_material" for r in out.findings.content.rules for s in r.subjects
                               for c in s.contributions)
                self.assertEqual(nonpass or material, name in g12)


class IdentityTests(unittest.TestCase):
    """Section 6.2: ID1-ID6, and I11a/I11b (content vs artifact)."""

    def test_id1_rerun_is_byte_identical(self):
        a, b = assess_case("C02"), assess_case("C02")
        self.assertEqual(a.result.model_dump_json(), b.result.model_dump_json())
        self.assertEqual(findings.artifact_canonical(a.findings), findings.artifact_canonical(b.findings))
        self.assertEqual(explanation.artifact_canonical(a.explanation), explanation.artifact_canonical(b.explanation))

    def test_id2_as_of_changes_ids_and_rendered_time_only(self):
        a, b = assess_case("C02"), assess_case("C02", as_of=AS_OF + timedelta(hours=1))
        self.assertEqual(a.provenance.input_fingerprint, b.provenance.input_fingerprint)
        self.assertEqual(a.provenance.output_digest, b.provenance.output_digest)
        self.assertNotEqual(a.result.id, b.result.id)
        self.assertEqual(a.findings.content, b.findings.content)
        self.assertEqual(a.findings.content_digest, b.findings.content_digest)
        self.assertNotEqual(a.findings.findings_id, b.findings.findings_id)
        self.assertEqual(a.explanation.content, b.explanation.content)
        self.assertEqual(a.explanation.explanation_content_digest, b.explanation.explanation_content_digest)
        self.assertNotEqual(a.explanation.explanation_id, b.explanation.explanation_id)
        self.assertNotEqual(a.explanation.rendered_text, b.explanation.rendered_text)
        self.assertNotEqual(a.explanation.rendered_text_digest, b.explanation.rendered_text_digest)
        self.assertEqual(a.explanation.rendered_text.replace("2026-11-02T15:00:00Z", "T"),
                         b.explanation.rendered_text.replace("2026-11-02T16:00:00Z", "T"))

    def test_id3_equivalent_timezone_is_byte_identical(self):
        a, b = assess_case("C02"), assess_case("C02", as_of=AS_OF.astimezone(EASTERN))
        self.assertEqual(a.result.model_dump_json(), b.result.model_dump_json())
        self.assertEqual(findings.artifact_canonical(a.findings), findings.artifact_canonical(b.findings))
        self.assertEqual(explanation.artifact_canonical(a.explanation), explanation.artifact_canonical(b.explanation))

    def test_id4_principal_is_not_identity(self):
        a, b = assess_case("C02"), assess_case("C02", principal=OTHER_PRINCIPAL)
        self.assertEqual(a.result.model_dump_json(), b.result.model_dump_json())
        self.assertEqual(findings.artifact_canonical(a.findings), findings.artifact_canonical(b.findings))
        self.assertEqual(explanation.artifact_canonical(a.explanation), explanation.artifact_canonical(b.explanation))
        self.assertNotEqual(a.provenance.principal_id, b.provenance.principal_id)

    def test_id5_equal_outcomes_with_different_inputs_have_different_findings(self):
        outs = {n: assess_case(n) for n in ("C02", "C03", "C09")}
        self.assertEqual(len({o.result.rule_outcomes for o in outs.values()}), 1)
        self.assertEqual(len({o.provenance.output_digest for o in outs.values()}), 1)
        self.assertEqual(len({o.provenance.input_fingerprint for o in outs.values()}), 3)
        self.assertEqual(len({o.result.id for o in outs.values()}), 3)
        self.assertEqual(len({o.findings.content_digest for o in outs.values()}), 3)
        self.assertEqual(len({o.explanation.explanation_content_digest for o in outs.values()}), 3)
        self.assertEqual(len({o.explanation.rendered_text for o in outs.values()}), 3)

    def test_id6_result_ids_pinned_to_the_pr_s1_base(self):
        for name, rid in BASE_RESULT_IDS.items():
            with self.subTest(name):
                self.assertEqual(assess_case(name).result.id, rid)

    def test_content_excludes_time_and_assessment_ids(self):
        out = assess_case("C02")
        plain = json.dumps(findings.content_canonical(out.findings.content))
        for forbidden in (out.result.id, out.provenance.input_fingerprint, out.provenance.output_digest, "2026-11-02T15"):
            self.assertNotIn(forbidden, plain)
        body = out.explanation.content.rendered_body
        self.assertNotIn("2026-11-02T15", body)
        self.assertEqual(body.count(explanation.SLOT), 1)
        self.assertEqual(out.explanation.rendered_text, body.replace(explanation.SLOT, "2026-11-02T15:00:00Z"))


class DeterminismTests(unittest.TestCase):
    def test_shuffled_inputs_give_identical_artifacts(self):
        for name in ("C02", "C04", "C09", "C13"):
            with self.subTest(name):
                base = assess_case(name)
                w, cand, kw = CASES[name]()
                rng = random.Random(7)
                for coll in ("claims", "evidence", "requirements", "participations", "applications", "candidates",
                             "opportunities", "programs", "profiles", "vocabularies", "policies"):
                    rng.shuffle(getattr(w, coll))
                out, _ = run(w, cand, DATA, **kw)
                self.assertEqual(findings.artifact_canonical(out.findings), findings.artifact_canonical(base.findings))
                self.assertEqual(explanation.artifact_canonical(out.explanation),
                                 explanation.artifact_canonical(base.explanation))

    def test_hash_seed_independence_across_processes(self):
        dump = TESTS / "tools" / "dump_scenarios.py"
        root = TESTS.parents[1]
        outputs = []
        for seed in ("0", "1", "2"):
            env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"} | {"PYTHONHASHSEED": seed}
            proc = subprocess.run([sys.executable, "-I", str(dump), "--code-root", str(root), "--artifacts"],
                                  capture_output=True, text=True, env=env, check=True)
            outputs.append(proc.stdout)
        self.assertTrue(outputs[0])
        self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(outputs[0], outputs[2])

    def test_eligibility_context_unchanged(self):  # PR-S2 adds no context field (labels/results cannot be passed)
        self.assertEqual(sorted(EligibilityContext.__dataclass_fields__),
                         ["claims", "evidence", "participations", "policies", "records", "requirements", "vocabularies"])

if __name__ == "__main__":
    unittest.main()
