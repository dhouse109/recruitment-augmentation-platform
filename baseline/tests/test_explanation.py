"""P14 deterministic explanation (PR-S2): template coverage, time slot, escaping, wording (A14).

The sweep below builds test-local synthetic worlds that, together with the C01-C19
matrix, reach every mapped template key; every other key combination must be listed
in ``UNREACHABLE``. Test-local synthetic records only.
"""

import dataclasses
import re
import unittest
from unittest import mock

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
        try:
            ea = build_explanation(dataclasses.replace(out.findings, content=edit(out.findings.content)))
        except Exception as exc:  # a source string interpreted as template text breaks rendering
            self.fail(f"a hostile field path changed rendering: {exc!r}")
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


# --- review repair R2: one-to-one completeness of explanation statements ----------------------------

_REF = re.compile(r"^rule:(?P<rule>[^/]+)(?:/subject:(?P<kind>[a-z_]+):(?P<anchor>[^/]+)"
                  r"(?:/(?:(?P<gap>gap)|input:(?P<input>[^/]+)(?:/evidence:(?P<evidence>[^#/]+)(?:#alt(?P<alt>\d+))?)?))?)?$")


def findings_elements(fa):
    """The test's own enumeration of verified finding elements (independent of explanation.py)."""
    out = []
    for r in fa.content.rules:
        out.append(("rule", r.rule_id, f"rule/{r.result}"))
        for s in r.subjects:
            anchor = s.requirement.requirement_id if s.requirement else (s.program_id or "-")
            out.append(("subject", r.rule_id, s.kind, anchor, f"subject/{s.kind}/{s.subject_status}/{s.subject_role}"))
            if s.information_gap:
                out.append(("gap", r.rule_id, s.kind, anchor, f"gap/{s.information_gap}"))
            for c in s.contributions:
                out.append(("contribution", r.rule_id, s.kind, anchor, c.input_id, f"contribution/{c.role}/{c.rule_standing}"))
                for a in c.evidence:
                    out.append(("attribution", r.rule_id, s.kind, anchor, c.input_id, a.evidence_id, a.alternative_index,
                                f"attribution/{a.relation}/{a.basis}", a.field_path))
    return out


def statement_elements(ea):
    """Parse explanation statements back into finding elements (references and identifying params)."""
    out = []
    for st in ea.content.statements:
        if st.ref == "decision":
            continue
        m = _REF.match(st.ref)
        assert m, st.ref
        p = dict(st.params)
        if m["evidence"]:
            alt = None if m["alt"] is None else int(m["alt"])
            assert p["evidence_id"] == m["evidence"] and p.get("alternative_index") == alt, st.ref
            out.append(("attribution", m["rule"], m["kind"], m["anchor"], m["input"], m["evidence"], alt, st.key,
                        p["field_path"]))
        elif m["input"]:
            assert p["input_id"] == m["input"], st.ref
            out.append(("contribution", m["rule"], m["kind"], m["anchor"], m["input"], st.key))
        elif m["gap"]:
            out.append(("gap", m["rule"], m["kind"], m["anchor"], st.key))
        elif m["kind"]:
            assert m["anchor"] in (p.get("requirement_id"), p.get("program_id"), "-"), st.ref
            out.append(("subject", m["rule"], m["kind"], m["anchor"], st.key))
        else:
            assert p["rule_id"] == m["rule"], st.ref
            out.append(("rule", m["rule"], st.key))
    return out


def assert_complete(test, out):
    expected = findings_elements(out.findings)
    got = statement_elements(out.explanation)
    test.assertEqual(len(expected), len(set(expected)))
    test.assertEqual(got, expected)
    test.assertEqual(sum(1 for st in out.explanation.content.statements if st.ref == "decision"), 1)
    lines = out.explanation.rendered_text.splitlines()
    test.assertEqual(len(lines), len(out.explanation.content.statements) + 1 + len(out.explanation.content.limitations))
    for line, st in zip(lines, out.explanation.content.statements):
        ident = dict(st.params).get("evidence_id") or dict(st.params).get("input_id") or dict(st.params).get("requirement_id")
        if ident:
            test.assertIn(f'"{ident}"', line, st.ref)


class ExplanationCompletenessTests(unittest.TestCase):
    """Every rule, subject, applicable gap, contribution and evidence attribution of the verified findings is
    represented exactly once, in order, with the correct reference -- and omissions are detected."""

    def test_one_to_one_coverage_of_verified_findings(self):
        n = 0
        for name, out in all_outcomes():
            if isinstance(out, Assessed):
                with self.subTest(name):
                    assert_complete(self, out)
                    n += 1
        self.assertGreaterEqual(n, 25)

    def test_c06_g12c_is_fully_represented(self):
        out = run(*CASES["C06"]()[:2], DATA)[0]
        assert_complete(self, out)
        base = "rule:S1-SKILL-004/subject:qualification:requirement_s1_data_python"
        pairs = [(st.key, st.ref) for st in out.explanation.content.statements if st.ref.startswith(base)]
        self.assertEqual(pairs, [
            ("subject/qualification/contradicted_verified/decisive", base),
            ("contribution/uncited_material/decision_input", base + "/input:claim_s1_ana_python_lacks"),
            ("attribution/support/candidate_statement",
             base + "/input:claim_s1_ana_python_lacks/evidence:evidence_s1_ana_python_screen"),
            ("contribution/cited/decision_input", base + "/input:claim_s1_ana_python_lacks_v"),
            ("attribution/support/independent_verification",
             base + "/input:claim_s1_ana_python_lacks_v/evidence:evidence_s1_ana_py_check"),
        ])
        text = out.explanation.rendered_text
        self.assertIn('Material decision input not cited by the eligibility result: "claim_s1_ana_python_lacks"', text)
        self.assertIn('Evidence "evidence_s1_ana_python_screen": self-declared (candidate statement)', text)
        self.assertIn('Cited decision input "claim_s1_ana_python_lacks_v"', text)

    def test_contested_alternatives_and_gaps_are_represented(self):  # C04: G12b contested with a gap
        out = run(*CASES["C04"]()[:2], DATA)[0]
        refs = {st.ref for st in out.explanation.content.statements}
        base = "rule:S1-SKILL-004/subject:qualification:requirement_s1_data_python"
        self.assertLessEqual({base + "/gap", base + "/input:claim_s1_ben_python/evidence:evidence_s1_ben_python_profile#alt0",
                              base + "/input:claim_s1_ben_python/evidence:evidence_s1_ben_python_app#alt1"}, refs)

    def test_checker_is_discriminating(self):
        """The test-side comparison itself detects an omitted element (bypassing the runtime self-check)."""
        out = run(*CASES["C06"]()[:2], DATA)[0]
        trimmed = tuple(st for st in out.explanation.content.statements
                        if "/input:claim_s1_ana_python_lacks" not in st.ref or "_lacks_v" in st.ref)
        forged = dataclasses.replace(out, explanation=dataclasses.replace(
            out.explanation, content=dataclasses.replace(out.explanation.content, statements=trimmed)))
        with self.assertRaises(AssertionError):
            assert_complete(self, forged)

    def omitting(self, case, drop):
        real = explanation._statements

        def statements(fa):
            return [(d, st) for d, st in real(fa) if not drop(st)]
        w, cand, kw = CASES[case]()
        ctx, caps = w.build()
        from builders import StubAuthority
        from rap_baseline import Errored, Stage, assess
        with mock.patch.object(explanation, "_statements", statements):
            out = assess(w.request(cand, DATA), ctx, StubAuthority(), caps)
        self.assertIsInstance(out, Errored, str(out))
        self.assertEqual((out.stage, out.code), (Stage.EXPLANATION, "explanation_verification_failed"))
        self.assertFalse(hasattr(out, "explanation"))
        return out

    def test_omitted_uncited_material_is_errored(self):  # G12c: the statement-backed claim and its evidence
        out = self.omitting("C06", lambda st: "/input:claim_s1_ana_python_lacks" in st.ref and "_lacks_v" not in st.ref)
        self.assertIn("statements for", out.detail)

    def test_omitted_gap_is_errored(self):
        self.omitting("C04", lambda st: st.ref.endswith("/gap"))

    def test_omitted_attribution_is_errored(self):
        self.omitting("C07", lambda st: st.ref.endswith("/evidence:evidence_s1_ana_python_screen"))

    def test_omitted_rule_is_errored(self):
        self.omitting("C01", lambda st: st.ref == "rule:S1-ACTIVE-001")

    def test_wrong_reference_is_errored(self):
        real = explanation._statements

        def statements(fa):
            return [(d, dataclasses.replace(st, ref=st.ref.replace("claim_s1_ana_python_lacks", "claim_s1_ana_hours")))
                    for d, st in real(fa)]
        out = run(*CASES["C06"]()[:2], DATA)[0]
        with mock.patch.object(explanation, "_statements", statements):
            with self.assertRaises(ExplanationMismatch):
                build_explanation(out.findings)

    def test_missing_rendered_line_is_errored(self):
        out = run(*CASES["C06"]()[:2], DATA)[0]
        ea = out.explanation
        lines = ea.content.rendered_body.split("\n")
        body = "\n".join(lines[:3] + lines[4:])
        with self.assertRaises(ExplanationMismatch):
            explanation._verify(dataclasses.replace(ea, content=dataclasses.replace(ea.content, rendered_body=body)),
                                out.findings)


# --- review repair R3: exact typed parameter integrity --------------------------------------------


def set_param(st, name, value):
    params = dict(st.params)
    params[name] = value
    return dataclasses.replace(st, params=tuple(sorted(params.items())))


class ParameterIntegrityTests(unittest.TestCase):
    """Keys and references stay correct; only a factual parameter changes. Each must be Errored(EXPLANATION)."""

    def substituted(self, case, ref_suffix, name, value, key_prefix=None):
        real = explanation._statements
        hits = []

        def statements(fa):
            out = []
            for depth, st in real(fa):
                if st.ref.endswith(ref_suffix) and (key_prefix is None or st.key.startswith(key_prefix)):
                    hits.append(st.ref)
                    st = set_param(st, name, value)
                out.append((depth, st))
            return out
        w, cand, kw = CASES[case]()
        ctx, caps = w.build()
        from builders import StubAuthority
        from rap_baseline import Errored, Stage, assess
        with mock.patch.object(explanation, "_statements", statements):
            out = assess(w.request(cand, DATA), ctx, StubAuthority(), caps)
        self.assertEqual(len(hits), 1, hits)
        self.assertIsInstance(out, Errored, str(out))
        self.assertEqual((out.stage, out.code), (Stage.EXPLANATION, "explanation_verification_failed"))
        self.assertIn("parameters differ", out.detail)
        self.assertFalse(hasattr(out, "explanation"))

    def test_substituted_source_locator(self):  # G12c: the uncited statement's evidence points elsewhere
        self.substituted("C06", "/evidence:evidence_s1_ana_python_screen", "source",
                         "fixture/skill_assessment/9204@rev:1")

    def test_substituted_opportunity_locator(self):
        self.substituted("C01", "subject:opportunity_status:-", "opportunity_ref", "fixture/opportunity/4101@rev:10")

    def test_changed_claim_reading(self):
        self.substituted("C01", "/input:claim_s1_ana_python_app", "reading", "lacks")

    def test_changed_declared_hours(self):
        self.substituted("C01", "subject:weekly_hours:requirement_s1_data_hours", "declared_hours", 40)

    def test_changed_required_hours(self):
        self.substituted("C01", "subject:weekly_hours:requirement_s1_data_hours", "required_hours", 8)

    def test_changed_contribution_hours(self):
        self.substituted("C01", "/input:claim_s1_ana_hours", "reading_hours", 21)

    def test_changed_contested_alternative_reading(self):
        self.substituted("C04", "/evidence:evidence_s1_ben_python_app#alt1", "reading", "has")

    def test_changed_inferred_producer(self):
        self.substituted("C05", "/input:claim_s1_ana_python_inferred", "inferred_by", "other-inference/9")

    def test_changed_rule_version(self):
        self.substituted("C01", "rule:S1-SKILL-004", "rule_version", 2, key_prefix="rule/")

    def test_changed_policy_version(self):
        self.substituted("C01", "decision", "policy_version", 2)

    def test_changed_field_path_and_claim_state(self):
        self.substituted("C06", "/evidence:evidence_s1_ana_python_screen", "field_path", "answers.other")
        self.substituted("C05", "/input:claim_s1_ana_python_inferred", "claim_state", "declared")

    def test_type_substitution_is_detected(self):  # "20" is not 20
        self.substituted("C01", "subject:weekly_hours:requirement_s1_data_hours", "declared_hours", "20")

    def test_equal_but_differently_typed_value_is_detected(self):
        """True == 1 in Python and renders as "1": only the typed comparison distinguishes it."""
        self.substituted("C04", "/evidence:evidence_s1_ben_python_app#alt1", "alternative_index", True)

    def test_extra_parameter_is_detected(self):
        self.substituted("C02", "/input:claim_s1_ana_python_lacks", "reading_hours", 5)

    def test_locator_derivations_agree(self):
        """The verifier's independent locator equals the renderer's for both version kinds."""
        from builders import snapshot
        from rap_contracts.models import SourceReference
        out = run(*CASES["C01"]()[:2], DATA)[0]
        refs = [out.findings.content.opportunity_ref, SourceReference.model_validate(snapshot("program", "3101", "1"))]
        for ref in refs:
            self.assertEqual(explanation._locator(ref), explanation._source(ref))

    def test_expected_index_does_not_call_the_producer(self):
        out = run(*CASES["C06"]()[:2], DATA)[0]
        with mock.patch.object(explanation, "_statements", side_effect=AssertionError("producer called")):
            explanation._completeness(out.explanation, out.findings)


if __name__ == "__main__":
    unittest.main()
