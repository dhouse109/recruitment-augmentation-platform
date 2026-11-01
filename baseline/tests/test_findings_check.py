"""L1 independent findings verification (PR-S2, P13): plan rev. 2.2 sections 4.6, 5 and 6.3.

N1-N4 exact SD-4/SD-5 precedence; N5-N6 provenance closure; N7 tamper resistance (A7);
N9-N10 trusted header; version pins; independence (A10). All injections use existing
patch points (``rules.evaluate``, ``engine.gate_refs``) or wrap the new producer.
"""

import ast
import dataclasses
import inspect
import unittest
from pathlib import Path
from unittest import mock

from builders import ANA, DATA, HAS, StubAuthority, World, as_ref, run
from g12_cases import CASES, R_PY, R_SH
from rap_baseline import Assessed, Errored, Stage, assess, engine, explanation, findings, findings_check, rules
from rap_contracts.models import SourceReference

Q = "S1-SKILL-004"
REAL_EVALUATE = rules.evaluate
REAL_BUILD = rules.build_findings
REAL_MAKE = engine.make_artifact
PACKAGE = Path(engine.__file__).resolve().parent


def run_case(name, **patches):
    """Assess a matrix case with ``rules`` attributes replaced (existing patch points only)."""
    w, cand, kw = CASES[name]()
    ctx, caps = w.build()
    with mock.patch.multiple(rules, **patches):
        return assess(w.request(cand, DATA), ctx, kw.get("authority") or StubAuthority(), caps)


def relabel(rule_id, **changes):
    def evaluate(d):
        return tuple(o.model_copy(update=changes) if o.rule_id == rule_id else o for o in REAL_EVALUATE(d))
    return evaluate


def assert_findings_error(test, out, subcode):
    test.assertIsInstance(out, Errored, str(out))
    test.assertEqual((out.stage, out.code), (Stage.FINDINGS, "findings_verification_failed"), out.detail)
    test.assertTrue(out.detail.startswith(subcode + ":"), out.detail)
    test.assertFalse(hasattr(out, "findings") or hasattr(out, "explanation"))


def all_verified_world():  # PR-S1 test_q3: every required code declared 'has' with verification evidence
    w = World()
    w.add_skill_requirement(DATA, "spreadsheets")
    w.add_verification(ANA, "evidence_s1_ana_python_verified", "9201", "assessments.python")
    w.add_claim("claim_s1_ana_python_verified", ANA, "python", "declared", HAS, ["evidence_s1_ana_python_verified"])
    w.add_statement(ANA, "evidence_s1_ana_sheets", "skills.spreadsheets")
    w.add_claim("claim_s1_ana_sheets", ANA, "spreadsheets", "declared", HAS, ["evidence_s1_ana_sheets"])
    w.add_verification(ANA, "evidence_s1_ana_sheets_verified", "9202", "assessments.spreadsheets")
    w.add_claim("claim_s1_ana_sheets_verified", ANA, "spreadsheets", "declared", HAS, ["evidence_s1_ana_sheets_verified"])
    return w


class ExactPrecedenceTests(unittest.TestCase):
    """N1-N4 (I7): supportable but precedence- or citation-incorrect results are rejected."""

    def test_n1_mixed_basis_relabelled_by_declaration(self):
        out = run_case("C02", evaluate=relabel(Q, reason_code="qualification_contradicted_by_declaration",
                                               claim_ids=("claim_s1_ana_python_lacks",), requirement_ids=(R_PY,)))
        assert_findings_error(self, out, "precedence_mismatch")

    def test_n2_all_verified_relabelled_declared(self):
        w = all_verified_world()
        ctx, caps = w.build()
        base = assess(w.request(), ctx, StubAuthority(), caps)
        self.assertEqual(next(o for o in base.result.rule_outcomes if o.rule_id == Q).reason_code,
                         "qualification_independently_verified")
        with mock.patch.object(rules, "evaluate", relabel(Q, reason_code="qualification_declared")):
            out = assess(w.request(), ctx, StubAuthority(), caps)
        assert_findings_error(self, out, "precedence_mismatch")

    def test_n3_pass_citing_a_subset_of_declared_claims(self):
        out = run_case("C01", evaluate=relabel(Q, claim_ids=("claim_s1_ana_python_app",)))
        assert_findings_error(self, out, "citation_mismatch")

    def test_n3b_fail_citing_the_uncited_contradiction_too(self):
        """G12c: citing both lacks claims under by_verification is unsupported (P10), not a findings issue."""
        out = run_case("C06", evaluate=relabel(Q, claim_ids=("claim_s1_ana_python_lacks", "claim_s1_ana_python_lacks_v")))
        self.assertEqual((out.stage, out.code), (Stage.POST_CHECK, "post_check_failed"))

    def test_n4_contested_claim_cited_in_a_fail_is_rejected_at_p10(self):
        out = run_case("C04", evaluate=relabel(Q, claim_ids=("claim_s1_ben_python", "claim_s1_ben_sheets"),
                                               requirement_ids=(R_PY, R_SH)))
        self.assertIsInstance(out, Errored)
        self.assertEqual((out.stage, out.code), (Stage.POST_CHECK, "post_check_failed"))
        self.assertIn("non_authoritative_input", out.detail)

    def test_supportable_alternatives_pass_the_contract_post_check(self):
        """The N1-N3 injections are supportable: only L1 (not P10) rejects them."""
        from rap_contracts.eligibility import check_eligibility_result
        for name, change in (("C02", dict(reason_code="qualification_contradicted_by_declaration",
                                          claim_ids=("claim_s1_ana_python_lacks",), requirement_ids=(R_PY,))),
                             ("C01", dict(claim_ids=("claim_s1_ana_python_app",)))):
            with self.subTest(name):
                w, cand, _ = CASES[name]()
                out, _ = run(w, cand, DATA)
                alt = out.result.model_copy(update={"rule_outcomes": tuple(
                    o.model_copy(update=change) if o.rule_id == Q else o for o in out.result.rule_outcomes)})
                check_eligibility_result(alt, w.build()[0])


class ProvenanceClosureTests(unittest.TestCase):
    """N5-N6 (I10): findings references must EQUAL the gated set."""

    def gate_patched(self, transform):
        w, cand, _ = CASES["C02"]()
        ctx, caps = w.build()
        real = engine.gate_refs
        with mock.patch.object(engine, "gate_refs", lambda p, t: transform(real(p, t), w)):
            return assess(w.request(cand, DATA), ctx, StubAuthority(), caps)

    def test_n5_uncited_input_source_not_gated(self):
        def drop(refs, w):
            target = as_ref(w.evidence_record("evidence_s1_ana_python_screen")["source_ref"])
            self.assertIn(target, refs)
            return tuple(r for r in refs if r != target)
        assert_findings_error(self, self.gate_patched(drop), "provenance_mismatch")

    def test_n6_extra_admitted_source(self):
        def add(refs, w):
            extra = as_ref(w.evidence_record("evidence_s1_ana_remote")["source_ref"])
            self.assertNotIn(extra, refs)
            return refs + (extra,)
        assert_findings_error(self, self.gate_patched(add), "provenance_mismatch")


def edit_subject(content, rule_id, pick, fn):
    rules_ = []
    for r in content.rules:
        if r.rule_id == rule_id:
            r = dataclasses.replace(r, subjects=tuple(fn(s) if pick(s) else s for s in r.subjects))
        rules_.append(r)
    return dataclasses.replace(content, rules=tuple(rules_))


def edit_contribution(content, rule_id, input_id, fn):
    return edit_subject(content, rule_id, lambda s: any(c.input_id == input_id for c in s.contributions),
                        lambda s: dataclasses.replace(s, contributions=tuple(
                            fn(c) if c.input_id == input_id else c for c in s.contributions)))


def edit_attribution(content, rule_id, input_id, fn):
    return edit_contribution(content, rule_id, input_id,
                             lambda c: dataclasses.replace(c, evidence=tuple(fn(a) for a in c.evidence)))


py = lambda s: s.skill_code == "python"  # noqa: E731
OTHER_REF = SourceReference.model_validate({
    "organization_id": "org_s1_alpha", "entity": {"source_system": "fixture", "entity_type": "application",
                                                  "entity_id": "7101"},
    "version": {"kind": "native_revision", "revision_id": "70"}})

TAMPERS = {
    "status": ("C02", lambda c: edit_subject(c, Q, py, lambda s: dataclasses.replace(s, subject_status="not_evidenced"))),
    "subject_role": ("C02", lambda c: edit_subject(c, Q, py, lambda s: dataclasses.replace(s, subject_role="decisive"))),
    "unreachable_role": ("C02", lambda c: edit_subject(c, Q, lambda s: s.skill_code == "spreadsheets",
                                                       lambda s: dataclasses.replace(s, subject_role="uncited_nonpass"))),
    "contribution_role": ("C06", lambda c: edit_contribution(c, Q, "claim_s1_ana_python_lacks",
                                                             lambda x: dataclasses.replace(x, role="context"))),
    "rule_standing": ("C04", lambda c: edit_contribution(c, Q, "claim_s1_ben_python",
                                                         lambda x: dataclasses.replace(x, rule_standing="decision_input"))),
    "claim_state": ("C05", lambda c: edit_contribution(c, Q, "claim_s1_ana_python_inferred",
                                                       lambda x: dataclasses.replace(x, claim_state="declared"))),
    "relation": ("C05", lambda c: edit_attribution(c, Q, "claim_s1_ana_python_inferred",
                                                   lambda a: dataclasses.replace(a, relation="support"))),
    "gap": ("C04", lambda c: edit_subject(c, Q, py, lambda s: dataclasses.replace(s, information_gap="opportunity_requirement_unpublished"))),
    "basis": ("C06", lambda c: edit_attribution(c, Q, "claim_s1_ana_python_lacks",
                                                lambda a: dataclasses.replace(a, basis="independent_verification"))),
    "source_ref": ("C06", lambda c: edit_attribution(c, Q, "claim_s1_ana_python_lacks",
                                                     lambda a: dataclasses.replace(a, source_ref=OTHER_REF))),
    "field_path": ("C06", lambda c: edit_attribution(c, Q, "claim_s1_ana_python_lacks",
                                                     lambda a: dataclasses.replace(a, field_path="answers.other"))),
    "alternative_index": ("C04", lambda c: edit_attribution(c, Q, "claim_s1_ben_python",
                                                            lambda a: dataclasses.replace(a, alternative_index=0))),
    "alternative_reading": ("C04", lambda c: edit_attribution(c, Q, "claim_s1_ben_python",
                                                              lambda a: dataclasses.replace(a, reading="has"))),
    "dropped_material_input": ("C02", lambda c: edit_subject(c, Q, py, lambda s: dataclasses.replace(s, contributions=()))),
    "dropped_subject": ("C02", lambda c: dataclasses.replace(c, rules=tuple(
        dataclasses.replace(r, subjects=tuple(s for s in r.subjects if not py(s))) if r.rule_id == Q else r
        for r in c.rules))),
    "foreign_input_id": ("C01", lambda c: edit_contribution(c, "S1-AVAIL-003", "claim_s1_ana_hours",
                                                            lambda x: dataclasses.replace(x, input_id="claim_s1_ben_hours"))),
    "unknown_input_id": ("C01", lambda c: edit_contribution(c, "S1-AVAIL-003", "claim_s1_ana_hours",
                                                            lambda x: dataclasses.replace(x, input_id="claim_s1_nobody"))),
    "organization": ("C01", lambda c: dataclasses.replace(c, organization_id="org_s1_beta")),
    "declared_hours": ("C01", lambda c: edit_subject(c, "S1-AVAIL-003", lambda s: True,
                                                     lambda s: dataclasses.replace(s, declared_hours=40))),
    "rule_result": ("C02", lambda c: dataclasses.replace(c, rules=tuple(
        dataclasses.replace(r, result="unknown") if r.rule_id == Q else r for r in c.rules))),
    "decision": ("C02", lambda c: dataclasses.replace(c, decision="needs_information")),
}


class TamperTests(unittest.TestCase):
    """N7 / A7: any tampered field class in the produced findings yields Errored(FINDINGS)."""

    def test_every_field_class(self):
        for label, (case, fn) in TAMPERS.items():
            with self.subTest(label):
                out = run_case(case, build_findings=lambda d, o, fn=fn: fn(REAL_BUILD(d, o)))
                self.assertIsInstance(out, Errored, f"{label}: {out}")
                self.assertEqual((out.stage, out.code), (Stage.FINDINGS, "findings_verification_failed"), out.detail)


class TrustedHeaderTests(unittest.TestCase):
    """N9-N10: header values are recomputed, never taken from the artifact or from engine names."""

    def make_patched(self, name, **changes):
        def make(content, result, provenance, policy):
            return dataclasses.replace(REAL_MAKE(content, result, provenance, policy), **changes)
        w, cand, kw = CASES[name]()
        ctx, caps = w.build()
        with mock.patch.object(engine, "make_artifact", make):
            return assess(w.request(cand, DATA), ctx, StubAuthority(), caps)

    def test_n9_forged_fingerprint_and_digest_with_self_consistent_ids(self):
        forged = "sha256:" + "0" * 64
        out = self.make_patched("C02", input_fingerprint=forged, output_digest=forged)
        assert_findings_error(self, out, "header_mismatch")

    def test_header_fields_individually(self):
        good = run(*CASES["C02"]()[:2], DATA)[0]
        for field, value in (("result_id", "eligibility_" + "1" * 40), ("as_of", good.result.evaluated_at.replace(year=2030)),
                             ("findings_id", "findings_" + "2" * 40), ("content_digest", "sha256:" + "3" * 64),
                             ("produced_by", "rap-baseline.findings/9.9.9")):
            with self.subTest(field):
                assert_findings_error(self, self.make_patched("C02", **{field: value}), "header_mismatch")

    def test_n10_wrong_provenance_values(self):
        for name in ("output_digest", "input_fingerprint"):
            with self.subTest(name):
                w, cand, _ = CASES["C02"]()
                ctx, caps = w.build()
                with mock.patch.object(engine, name, lambda x: "sha256:" + "f" * 64):
                    out = assess(w.request(cand, DATA), ctx, StubAuthority(), caps)
                assert_findings_error(self, out, "header_mismatch")


class VersionPinTests(unittest.TestCase):
    """A13: byte determinism holds only under the pinned versions; anything else is Errored, never silent."""

    def test_unpinned_versions_are_errored(self):
        w, cand, _ = CASES["C02"]()
        ctx, caps = w.build()
        for target, attr, stage in ((rules, "FINDINGS_POLICY_VERSION", Stage.FINDINGS),
                                    (findings, "FINDINGS_PRODUCER", Stage.FINDINGS),
                                    (explanation, "TEMPLATES_VERSION", Stage.EXPLANATION),
                                    (explanation, "EXPLANATION_PRODUCER", Stage.EXPLANATION)):
            with self.subTest(attr):
                with mock.patch.object(target, attr, "changed/2"):
                    out = assess(w.request(cand, DATA), ctx, StubAuthority(), caps)
                self.assertIsInstance(out, Errored, str(out))
                self.assertEqual(out.stage, stage)


class IndependenceTests(unittest.TestCase):
    """A10: L1 imports no producer or engine module and makes no authority call; P12-P14 make none either."""

    def test_l1_imports(self):
        tree = ast.parse((PACKAGE / "findings_check.py").read_text(encoding="utf-8"))
        relative = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom):
                if n.level:
                    relative |= {n.module} if n.module else {a.name for a in n.names}
                else:
                    self.assertTrue(n.module == "__future__" or n.module == "typing" or n.module.startswith("rap_contracts."),
                                    n.module)
            elif isinstance(n, ast.Import):
                self.assertEqual({a.name for a in n.names} - {"dataclasses"}, set())
        self.assertEqual(relative, {"identity", "findings"})

    def test_l1_signature_takes_no_authority_or_supplied_context(self):
        self.assertEqual(list(inspect.signature(findings_check.verify_findings).parameters),
                         ["fa", "result", "projected", "prov", "engine_identity"])

    def test_no_authority_call_after_p11(self):
        w, cand, _ = CASES["C04"]()
        ctx, caps = w.build()
        auth = StubAuthority()
        counts = []

        def spy(fn):
            def wrapper(*a, **k):
                counts.append(len(auth.calls))
                out = fn(*a, **k)
                counts.append(len(auth.calls))
                return out
            return wrapper

        with mock.patch.object(rules, "build_findings", spy(REAL_BUILD)), \
                mock.patch.object(engine, "verify_findings", spy(engine.verify_findings)), \
                mock.patch.object(engine, "build_explanation", spy(engine.build_explanation)):
            out = assess(w.request(cand, DATA), ctx, auth, caps)
        self.assertIsInstance(out, Assessed)
        self.assertEqual(len(counts), 6)
        self.assertEqual(len(set(counts)), 1)
        self.assertEqual(counts[0], len(auth.calls))

    def test_l1_rejects_a_foreign_engine_identity(self):
        w, cand, _ = CASES["C01"]()
        ctx, caps = w.build()
        changed = engine.ENGINE.__class__(**{**engine.ENGINE.__dict__, "evaluated_by": "other/1"})
        with mock.patch.object(engine, "verify_findings",
                               lambda fa, r, p, prov, e: findings_check.verify_findings(fa, r, p, prov, changed)):
            out = assess(w.request(cand, DATA), ctx, StubAuthority(), caps)
        assert_findings_error(self, out, "header_mismatch")

if __name__ == "__main__":
    unittest.main()
