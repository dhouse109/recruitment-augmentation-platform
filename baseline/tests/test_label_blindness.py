"""The engine computes outcomes; it never receives or reads hand-written expected labels.

Also enforces held-out separation for PR-S1 development (owner qualification 5):
no nominal held-out identifier appears anywhere under ``baseline/``.
"""

import ast
import dataclasses
import inspect
import re
import unittest
from pathlib import Path

from rap_contracts.eligibility import EligibilityContext

from builders import StubAuthority, golden_request, load_golden_scope
from rap_baseline import Assessed, assess

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
                self.assertNotIn("fixtures", path.read_text(encoding="utf-8"))


class LabelMutationInvarianceTests(unittest.TestCase):
    def outputs(self, mutate=None):
        ctx, caps, labels = load_golden_scope(mutate)
        return {lab["id"]: assess(golden_request(lab), ctx, StubAuthority(), caps) for lab in labels}

    def test_flipping_every_label_changes_no_engine_output(self):
        def corrupt(results):
            for r in results:
                r["decision"] = "eligible" if r["decision"] != "eligible" else "ineligible"
                for o in r["rule_outcomes"]:
                    o["result"], o["reason_code"], o["claim_ids"] = "unknown", "corrupted_label", []
        before, after = self.outputs(), self.outputs(corrupt)
        self.assertEqual(set(before), set(after))
        for key in before:
            with self.subTest(key):
                self.assertIsInstance(before[key], Assessed)
                self.assertEqual(after[key].result.model_dump_json(), before[key].result.model_dump_json())


class HeldOutSeparationTests(unittest.TestCase):
    def test_no_held_out_identifier_under_baseline(self):
        files = [p for p in BASELINE.rglob("*") if p.is_file() and p.suffix in (".py", ".md", ".json", ".txt")
                 and "__pycache__" not in p.parts]
        self.assertTrue(files)
        for path in files:
            text = path.read_text(encoding="utf-8")
            for pattern in HELD_OUT_PATTERNS:
                with self.subTest(file=path.name, pattern=pattern.pattern):
                    self.assertIsNone(pattern.search(text))

    def test_golden_scope_loader_returns_golden_candidates_only(self):
        ctx, _, labels = load_golden_scope()
        golden = {"candidate_demo_" + x for x in "abc"}
        owned = ({c.id for c in ctx.records.candidates} | {c.candidate_id for c in ctx.claims}
                 | {p.candidate_id for p in ctx.participations} | {a.candidate_id for a in ctx.records.applications}
                 | {e.subject.id for e in ctx.evidence.values() if e.subject.kind.value == "candidate"}
                 | {lab["candidate_id"] for lab in labels})
        self.assertEqual(owned, golden)


if __name__ == "__main__":
    unittest.main()
