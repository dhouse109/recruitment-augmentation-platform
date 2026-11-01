"""P14 deterministic explanation (PR-S2): template coverage, time slot, escaping, wording (A14).

The sweep below builds test-local synthetic worlds that, together with the C01-C19
matrix, reach every mapped template key; every other key combination must be listed
in ``UNREACHABLE``. Test-local synthetic records only.
"""

import dataclasses
import re
import unittest

from builders import ANA, BEN, DATA, HAS, LACKS, OPS, WEB, World, hours, run
from g12_cases import CASES, drop, py_lacks_stmt, sh_lacks_stmt, two_codes
from rap_baseline import Assessed, explanation
from rap_baseline.explanation import KEY_SPACE, SLOT, TEMPLATES, UNREACHABLE, ExplanationMismatch, build_explanation

FORBIDDEN = re.compile(r"\b(reject\w*|hir(e|ed|es|ing)|offer\w*|placement\w*|placed|scor(e|ed|es|ing)|rank\w*|"
                       r"disqualif\w*|unqualified|unsuitable|candidate-level)\b|not qualified", re.IGNORECASE)


def sweep_worlds():
    """(label, world, candidate, opportunity) scenarios that reach the keys the C01-C19 matrix does not."""
    out = []
    w = World(); w.opportunity(DATA)["status"] = "closed"; out.append(("closed", w, ANA, DATA))
    out.append(("paused", World(), ANA, OPS))
    out.append(("no_qualification", World(), ANA, WEB))
    w = World(); w.participations[0]["status"] = "not_participating"; out.append(("not_participating", w, ANA, DATA))
    w = World(); w.claim("claim_s1_ana_hours")["value"] = hours(5); out.append(("below", w, ANA, DATA))
    w = World(); w.remove_claim("claim_s1_ana_hours")
    w.add_statement(ANA, "evidence_s1_ana_hours_app", "answers.weekly_hours", source="application")
    w.add_claim("claim_s1_ana_hours_contested", ANA, None, "contested", alternatives=[
        {"value": hours(20), "evidence_ids": ["evidence_s1_ana_hours"]},
        {"value": hours(4), "evidence_ids": ["evidence_s1_ana_hours_app"]}])
    out.append(("hours_contested", w, ANA, DATA))
    w = World(); drop(w, "python"); out.append(("not_evidenced_decisive", w, ANA, DATA))
    w = two_codes(); sh_lacks_stmt(w); out.append(("uncited_satisfied_declared", w, ANA, DATA))
    w = two_codes(); sh_lacks_stmt(w)
    w.add_verification(ANA, "evidence_s1_ana_python_verified", "9201", "assessments.python")
    w.add_claim("claim_s1_ana_python_verified", ANA, "python", "declared", HAS, ["evidence_s1_ana_python_verified"])
    out.append(("uncited_satisfied_verified", w, ANA, DATA))
    w = World(); drop(w, "python", BEN)  # Ben's existing profile statement is reused as one alternative
    w.add_verification(BEN, "evidence_s1_ben_python_check", "9301", "assessments.python")
    w.add_claim("claim_s1_ben_python", BEN, "python", "contested", alternatives=[
        {"value": HAS, "evidence_ids": ["evidence_s1_ben_python_profile"]},
        {"value": LACKS, "evidence_ids": ["evidence_s1_ben_python_check"]}])
    out.append(("contested_with_verification", w, BEN, DATA))
    w = World(); drop(w, "python")
    w.add_verification(ANA, "evidence_s1_ana_python_signal", "9205", "assessments.python_signal")
    w.add_claim("claim_s1_ana_python_inferred", ANA, "python", "inferred", HAS, ["evidence_s1_ana_python_signal"])
    out.append(("inferred_from_verification", w, ANA, DATA))
    w = World(); py_lacks_stmt(w); out.append(("refused_conflict", w, ANA, DATA))
    return out


def all_outcomes():
    outs = []
    for name, fn in CASES.items():
        w, cand, kw = fn()
        outs.append((name, run(w, cand, DATA, **kw)[0]))
    for label, w, cand, opp in sweep_worlds():
        outs.append((label, run(w, cand, opp)[0]))
    return outs


class TemplateCoverageTests(unittest.TestCase):
    def test_each_key_family_is_partitioned_into_templates_and_unreachable(self):
        for family, space in KEY_SPACE.items():
            with self.subTest(family):
                space = set(space)
                mapped = {k for k in TEMPLATES if k.startswith(family + "/")}
                unreachable = {k for k in UNREACHABLE if k.startswith(family + "/")}
                self.assertEqual(mapped & unreachable, set())
                self.assertEqual(mapped | unreachable, space)
        self.assertLessEqual(UNREACHABLE, set().union(*map(set, KEY_SPACE.values())))

    def test_planned_counts(self):
        mapped = {f: len([k for k in TEMPLATES if k.startswith(f + "/")]) for f in KEY_SPACE}
        self.assertEqual(mapped, {"subject": 25, "contribution": 7, "attribution": 7, "gap": 5})
        self.assertNotIn("subject/qualification/contradicted_verified/uncited_nonpass", TEMPLATES)

    def test_every_mapped_template_is_reached_and_no_template_is_unused(self):
        used = set()
        for name, out in all_outcomes():
            if isinstance(out, Assessed):
                used |= {s.key for s in out.explanation.content.statements}
                used |= {f"limitation/{x}" for x in out.explanation.content.limitations}
        used.add("section/limitations")
        self.assertEqual(set(TEMPLATES) - used, set())
        self.assertEqual(used - set(TEMPLATES), set())

    def test_unreachable_key_is_rejected(self):
        out = run(*CASES["C02"]()[:2], DATA)[0]
        c = out.findings.content
        bad = dataclasses.replace(c, rules=tuple(
            dataclasses.replace(r, subjects=tuple(dataclasses.replace(s, subject_role="uncited_nonpass")
                                                  if s.subject_status == "contradicted_verified" else s
                                                  for s in r.subjects)) for r in c.rules))
        with self.assertRaises(ExplanationMismatch):
            build_explanation(dataclasses.replace(out.findings, content=bad))


class SlotAndEscapingTests(unittest.TestCase):
    def test_body_has_exactly_one_slot_and_text_is_its_substitution(self):
        for name, out in all_outcomes():
            if isinstance(out, Assessed):
                with self.subTest(name):
                    body = out.explanation.content.rendered_body
                    self.assertEqual(body.count(SLOT), 1)
                    self.assertNotIn(SLOT, out.explanation.rendered_text)
                    self.assertEqual(out.explanation.rendered_text, body.replace(SLOT, "2026-11-02T15:00:00Z"))

    def test_source_strings_are_data_not_templates(self):
        out = run(*CASES["C06"]()[:2], DATA)[0]
        hostile = "{evidence_id}{0}" + SLOT + "<script>&amp;"

        def edit(c):
            return dataclasses.replace(c, rules=tuple(dataclasses.replace(r, subjects=tuple(
                dataclasses.replace(s, contributions=tuple(dataclasses.replace(con, evidence=tuple(
                    dataclasses.replace(a, field_path=hostile) for a in con.evidence)) for con in s.contributions))
                for s in r.subjects)) for r in c.rules))
        ea = build_explanation(dataclasses.replace(out.findings, content=edit(out.findings.content)))
        self.assertEqual(ea.content.rendered_body.count(SLOT), 1)
        self.assertIn('"{evidence_id}{0}\\u27e6as_of\\u27e7\\u003cscript\\u003e\\u0026amp;"', ea.rendered_text)
        self.assertNotIn("<script>", ea.rendered_text)

    def test_tampered_artifact_text_fails_self_check(self):
        out = run(*CASES["C01"]()[:2], DATA)[0]
        ea = out.explanation
        for change in ({"rendered_text": ea.rendered_text + " "},
                       {"content": dataclasses.replace(ea.content, rendered_body=ea.content.rendered_body + SLOT)},
                       {"explanation_content_digest": "sha256:" + "0" * 64}):
            with self.subTest(list(change)):
                with self.assertRaises(ExplanationMismatch):
                    explanation._verify(dataclasses.replace(ea, **change), out.findings)


class WordingTests(unittest.TestCase):
    def test_no_forbidden_vocabulary_in_templates_or_renders(self):
        for key, text in TEMPLATES.items():
            self.assertIsNone(FORBIDDEN.search(text), key)
        for name, out in all_outcomes():
            if isinstance(out, Assessed):
                with self.subTest(name):
                    self.assertIsNone(FORBIDDEN.search(out.explanation.rendered_text))

    def test_scope_sentence_and_limitations_always_present(self):
        for name, out in all_outcomes():
            if isinstance(out, Assessed):
                with self.subTest(name):
                    text = out.explanation.rendered_text
                    self.assertIn("This assessment covers this opportunity under this policy version only.", text)
                    self.assertEqual(out.explanation.content.limitations[:5], explanation.MANDATORY_LIMITATIONS)
                    self.assertIn("not authorized for reviewer presentation", text)

    def test_contested_gap_assigns_no_responsibility(self):
        text = run(*CASES["C04"]()[:2], DATA)[0].explanation.rendered_text
        self.assertIn("no party is identified as responsible", text)
        for phrase in ("should", "must provide", "please", "correct the", "fault"):
            self.assertNotIn(phrase, text.lower())

    def test_unpublished_hours_asks_nothing_of_the_candidate(self):
        text = run(*CASES["C14"]()[:2], DATA)[0].explanation.rendered_text
        self.assertIn("the opportunity has not published this requirement", text)

    def test_declared_only_code_is_never_called_verified(self):
        out = run(*CASES["C13"]()[:2], DATA)[0]
        lines = [l for l in out.explanation.rendered_text.splitlines() if '"spreadsheets"' in l]
        self.assertTrue(lines)
        self.assertTrue(all("none is recorded as independently verified" in l for l in lines))

    def test_g12_uncited_material_is_rendered(self):
        text = run(*CASES["C02"]()[:2], DATA)[0].explanation.rendered_text
        self.assertIn('Also material, not cited by the eligibility result: Mandatory qualification "python"', text)
        self.assertIn('Material decision input not cited by the eligibility result: "claim_s1_ana_python_lacks"', text)

    def test_skill_codes_only_no_vocabulary_labels(self):  # O3: vocabularies are not gated
        text = run(*CASES["C01"]()[:2], DATA)[0].explanation.rendered_text
        self.assertNotIn("vocabulary_s1", text)


if __name__ == "__main__":
    unittest.main()
