"""The engine computes outcomes; it never receives or reads hand-written expected labels.

Review repair R1 (2026-10-31): PR-S1 development tests make NO contact with any
contract fixture file -- golden or nominal held-out. Label-blindness is shown
with synthetic, test-local hand-written labels built on the PR-S1 world. Two
guards enforce the separation: a static scan of everything under ``baseline/``
and a runtime spy on ``open`` while every synthetic scenario runs.
"""

import ast
import builtins
import dataclasses
import inspect
import re
import unittest
from pathlib import Path
from unittest import mock

from rap_contracts.eligibility import EligibilityContext, EligibilityResult, check_eligibility_result

from builders import ANA, AS_OF, BEN, DATA, OPS, PILOT, StubAuthority, World, run
from rap_baseline import Assessed, EligibilityRequest, assess

BASELINE = Path(__file__).resolve().parents[1]
PACKAGE = BASELINE / "rap_baseline"
FORBIDDEN_MODULES = ("rap_contracts.evaluation", "rap_contracts.promotion", "rap_contracts.adjudication",
                     "eval_harness", "review_double", "support", "builders")
HELD_OUT_PATTERNS = [
    re.compile(r"candidate_demo_[def]\b"),
    re.compile(r"\b(?:claim|evidence|participation|eligibility|profile|application|recommendation|verification|chunk)_(?:demo_)?[def]_"),
    re.compile(r"evalcase_h\d"),
    re.compile("EVAL-" + "H" + r"\d{3}"),
    re.compile("nominal" + "-held-out-v0"),
]
#: Any reference to the contract fixture directory or a fixture file name.
FIXTURE_PATTERNS = [re.compile("fix" + r"tures\b"), re.compile(r"-v0\.2\.0-dev" + r"\.json"), re.compile("json" + r"\.load\(")]

# --- synthetic hand-written labels (test-local; never seen by the engine) -----

PILOT_POLICY_REF = {"organization_id": "org_s1_alpha", "entity": {"source_system": "fixture", "entity_type": "policy_set",
                                                                  "entity_id": "8101"},
                    "version": {"kind": "native_revision", "revision_id": "81"}}


def label(label_id, cand, opp, opp_entity, opp_rev, decision, outcomes):
    """A hand-written expected label for the synthetic world, shaped like a fixture expectation."""
    return {"id": label_id, "organization_id": "org_s1_alpha", "candidate_id": cand, "opportunity_id": opp,
            "opportunity_ref": {"organization_id": "org_s1_alpha", "entity": {"source_system": "fixture",
                                "entity_type": "opportunity", "entity_id": opp_entity},
                                "version": {"kind": "native_revision", "revision_id": opp_rev}},
            "policy": {"policy_set_id": "policy_s1_pilot", "version": 1, "source_ref": PILOT_POLICY_REF},
            "rule_outcomes": [dict(zip(("rule_id", "rule_version", "rule_kind", "result", "reason_code", "claim_ids",
                                        "participation_ids", "requirement_ids"), o)) for o in outcomes],
            "decision": decision, "evaluated_at": "2026-11-01T00:00:00Z", "evaluated_by": "s1-hand-written-label/1"}


def synthetic_labels():
    A, P, V, Q = ("S1-ACTIVE-001", 1, "opportunity_status_active"), ("S1-PROGRAM-002", 1, "program_participation_confirmed"), \
        ("S1-AVAIL-003", 1, "availability_meets_required_hours"), ("S1-SKILL-004", 1, "mandatory_qualification_evidenced")
    return [
        label("eligibility_s1_label_ana_data", ANA, DATA, "4101", "11", "eligible", [
            A + ("pass", "opportunity_active", [], [], []),
            P + ("pass", "participation_confirmed", [], ["participation_s1_ana"], []),
            V + ("pass", "availability_meets_required_hours", ["claim_s1_ana_hours"], [], ["requirement_s1_data_hours"]),
            Q + ("pass", "qualification_declared", ["claim_s1_ana_python_app", "claim_s1_ana_python_profile"], [],
                 ["requirement_s1_data_python"])]),
        label("eligibility_s1_label_ana_ops", ANA, OPS, "4103", "13", "ineligible", [
            A + ("fail", "opportunity_paused", [], [], []),
            P + ("pass", "participation_confirmed", [], ["participation_s1_ana"], []),
            V + ("pass", "availability_meets_required_hours", ["claim_s1_ana_hours"], [], ["requirement_s1_ops_hours"]),
            Q + ("pass", "no_mandatory_qualification", [], [], [])]),
        label("eligibility_s1_label_ben_data", BEN, DATA, "4101", "11", "needs_information", [
            A + ("pass", "opportunity_active", [], [], []),
            P + ("pass", "participation_confirmed", [], ["participation_s1_ben"], []),
            V + ("unknown", "availability_not_declared", ["claim_s1_ben_hours"], [], []),
            Q + ("unknown", "qualification_contested", ["claim_s1_ben_python"], [], ["requirement_s1_data_python"])]),
    ]


def key_request(lab: dict) -> EligibilityRequest:
    """Key projection only: organization, candidate, opportunity and policy pin. No outcome field is read."""
    return EligibilityRequest(organization_id=lab["organization_id"], candidate_id=lab["candidate_id"],
                              opportunity_id=lab["opportunity_id"], policy=lab["policy"],
                              principal_id="principal_s1_coordinator", as_of=AS_OF)


class StructuralBlindnessTests(unittest.TestCase):
    def test_engine_signature_has_no_label_input(self):
        self.assertEqual(list(inspect.signature(assess).parameters), ["request", "context", "authority", "capabilities"])

    def test_eligibility_context_cannot_carry_results(self):
        names = {f.name for f in dataclasses.fields(EligibilityContext)}
        self.assertFalse(any("result" in n or "label" in n for n in names), names)

    def test_package_imports_no_evaluation_or_label_modules_and_reads_no_files(self):
        for path in sorted(PACKAGE.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            modules = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
            modules |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
            calls = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
            with self.subTest(path.name):
                self.assertFalse(any(m.startswith(f) for m in modules for f in FORBIDDEN_MODULES), modules)
                self.assertNotIn("open", calls)
                self.assertNotIn("pathlib", modules)

    def test_request_has_no_outcome_field(self):
        self.assertEqual(set(EligibilityRequest.model_fields),
                         {"organization_id", "candidate_id", "opportunity_id", "policy", "principal_id", "as_of"})


class SyntheticLabelTests(unittest.TestCase):
    """Replaces the former fixture-based golden-scope diagnostic and label-flip tests (review repair R1)."""

    def setUp(self):
        self.ctx, self.caps = World().build()

    def test_synthetic_labels_are_supported_contract_records(self):
        for lab in synthetic_labels():
            with self.subTest(lab["id"]):
                check_eligibility_result(EligibilityResult.model_validate(lab), self.ctx)

    def test_engine_agrees_with_synthetic_labels_from_the_key_projection_only(self):
        for lab in synthetic_labels():
            with self.subTest(lab["id"]):
                out = assess(key_request(lab), self.ctx, StubAuthority(), self.caps)
                self.assertIsInstance(out, Assessed, str(out))
                produced = out.result.model_dump(mode="json")
                self.assertNotEqual(produced["id"], lab["id"])
                self.assertNotEqual(produced["evaluated_by"], lab["evaluated_by"])
                self.assertEqual(produced["decision"], lab["decision"])
                self.assertEqual(produced["rule_outcomes"], lab["rule_outcomes"])

    def test_flipping_every_label_changes_no_engine_output(self):
        before = {lab["id"]: assess(key_request(lab), self.ctx, StubAuthority(), self.caps) for lab in synthetic_labels()}
        flipped = synthetic_labels()
        for lab in flipped:
            lab["decision"] = "eligible" if lab["decision"] != "eligible" else "ineligible"
            for o in lab["rule_outcomes"]:
                o["result"], o["reason_code"], o["claim_ids"] = "unknown", "corrupted_label", []
        for lab in flipped:
            with self.subTest(lab["id"]):
                after = assess(key_request(lab), self.ctx, StubAuthority(), self.caps)
                self.assertEqual(after.result.model_dump_json(), before[lab["id"]].result.model_dump_json())


class FixtureSeparationTests(unittest.TestCase):
    """Owner qualification 5 / review repair R1: no contract fixture contact in PR-S1 development tests."""

    def baseline_files(self):
        files = [p for p in BASELINE.rglob("*") if p.is_file() and p.suffix in (".py", ".md", ".json", ".txt")
                 and "__pycache__" not in p.parts]
        self.assertTrue(files)
        return files

    def test_no_held_out_identifier_under_baseline(self):
        for path in self.baseline_files():
            text = path.read_text(encoding="utf-8")
            for pattern in HELD_OUT_PATTERNS:
                with self.subTest(file=path.name, pattern=pattern.pattern):
                    self.assertIsNone(pattern.search(text))

    def test_no_fixture_reference_under_baseline(self):
        for path in self.baseline_files():
            text = path.read_text(encoding="utf-8")
            for pattern in FIXTURE_PATTERNS:
                with self.subTest(file=path.name, pattern=pattern.pattern):
                    self.assertIsNone(pattern.search(text))

    def test_scan_patterns_are_not_vacuous(self):
        sample = "contracts/fix" + "tures/eligibility-evidence-v0.2.0-dev" + ".json and json" + ".load(fh)"
        self.assertTrue(all(p.search(sample) for p in FIXTURE_PATTERNS))

    def test_scans_cover_the_pr_s2_modules(self):
        names = {p.name for p in self.baseline_files()}
        self.assertLessEqual({"findings.py", "findings_check.py", "selection_check.py", "explanation.py",
                              "g12_cases.py", "dump_scenarios.py", "test_g12_matrix.py"}, names)
        package = {p.name for p in PACKAGE.glob("*.py")}
        self.assertLessEqual({"findings.py", "findings_check.py", "selection_check.py", "explanation.py"}, package)

    def test_no_contract_file_is_opened_while_pr_s2_cases_run(self):
        from g12_cases import CASES
        contracts_dir = str(BASELINE.parent / "contracts")
        opened = []
        real_open = builtins.open

        def spy(file, *args, **kwargs):
            opened.append(str(file))
            return real_open(file, *args, **kwargs)

        with mock.patch.object(builtins, "open", spy):
            for fn in CASES.values():
                w, cand, kw = fn()
                run(w, cand, DATA, PILOT, **kw)
        self.assertEqual([f for f in opened if f.startswith(contracts_dir)], [])

    def test_no_file_under_contracts_is_opened_while_scenarios_run(self):
        contracts_dir = str(BASELINE.parent / "contracts")
        opened = []
        real_open = builtins.open

        def spy(file, *args, **kwargs):
            opened.append(str(file))
            return real_open(file, *args, **kwargs)

        with mock.patch.object(builtins, "open", spy):
            for cand, opp in ((ANA, DATA), (ANA, OPS), (BEN, DATA)):
                out, _ = run(World(), cand, opp, PILOT)
                self.assertIsInstance(out, Assessed)
            ctx, caps = World().build()
            for lab in synthetic_labels():
                assess(key_request(lab), ctx, StubAuthority(), caps)
        self.assertEqual([f for f in opened if f.startswith(contracts_dir)], [])


if __name__ == "__main__":
    unittest.main()
