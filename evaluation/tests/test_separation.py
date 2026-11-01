"""B5, B6 and B10: separation from test scaffolding and held-out data, and no measurement or promotion."""

from __future__ import annotations

import ast
import builtins
import re
import unittest
from pathlib import Path
from unittest import mock

from helpers import LazyClassFixture, admitted, config

from rap_evaluation.artifacts import load_dir
from rap_evaluation.fixtures import ALLOWED_FILES, FIXTURE_DIR
from rap_evaluation.run import run_evaluation

PACKAGE = Path(__file__).resolve().parents[1] / "rap_evaluation"
SOURCES = sorted(PACKAGE.glob("*.py"))

#: Test scaffolding of other packages that the runner must never import.
SCAFFOLDING = {"support", "eval_harness", "review_double", "builders", "g12_cases", "helpers"}
#: Metric, gate, comparison and promotion APIs (contract module ``promotion``) that must never be called.
FORBIDDEN_CALLS = {"compute_rate", "check_metric_value", "evaluate_safety_gate", "assess_comparison",
                   "check_comparable_runs", "derive_metric", "promotion_decision", "check_promotion",
                   "evaluate_held_out_gate"}
ALLOWED_PROMOTION_IMPORTS = {"MetricDefinitionSet", "SafetyGatePolicy", "check_policy_manifest"}


def trees():
    for path in SOURCES:
        yield path, ast.parse(path.read_text(encoding="utf-8"))


class StaticSeparationTests(unittest.TestCase):
    def test_no_import_of_test_scaffolding(self):
        for path, tree in trees():
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = {a.name.split(".")[0] for a in node.names}
                elif isinstance(node, ast.ImportFrom):
                    names = {(node.module or "").split(".")[0]}
                else:
                    continue
                self.assertFalse(names & SCAFFOLDING, f"{path.name}: {names}")
                self.assertFalse({n for n in names if n == "tests"}, path.name)

    def test_no_sys_path_manipulation(self):
        for path in SOURCES:
            self.assertNotIn("sys.path", path.read_text(encoding="utf-8"), path.name)

    def test_only_policy_consistency_names_are_imported_from_promotion(self):
        for path, tree in trees():
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and (node.module or "").endswith("promotion"):
                    self.assertLessEqual({a.name for a in node.names}, ALLOWED_PROMOTION_IMPORTS, path.name)

    def test_no_metric_gate_comparison_or_promotion_call(self):
        import rap_contracts.promotion as promotion
        defined = {n for n in dir(promotion) if not n.startswith("_") and callable(getattr(promotion, n))
                   and getattr(getattr(promotion, n), "__module__", None) == promotion.__name__ and n.islower()}
        self.assertIn("evaluate_safety_gate", defined | FORBIDDEN_CALLS)
        forbidden = (FORBIDDEN_CALLS | defined) - ALLOWED_PROMOTION_IMPORTS
        for path, tree in trees():
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    f = node.func
                    name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)
                    self.assertNotIn(name, forbidden, f"{path.name}:{node.lineno}")

    def test_held_out_case_file_is_never_named(self):
        for path, tree in trees():
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    self.assertNotIn("held-out-v0", node.value, path.name)
                    self.assertNotIn("nominal-held-out", node.value, path.name)
        self.assertFalse([n for n in ALLOWED_FILES if "held" in n])


class DynamicSeparationTests(LazyClassFixture):
    @classmethod
    def _fixture(cls):
        import shutil
        import tempfile
        cls.dir = Path(tempfile.mkdtemp(prefix="rap-eval-sep-"))
        cls.addClassCleanup(shutil.rmtree, cls.dir, True)
        cls.opened: list[tuple[str, str]] = []
        real_open = builtins.open

        def spy(file, mode="r", *args, **kwargs):
            cls.opened.append((str(file), mode))
            return real_open(file, mode, *args, **kwargs)
        with mock.patch("builtins.open", side_effect=spy), mock.patch("io.open", side_effect=spy):
            cls.out = run_evaluation(config(cls.dir / "out" / "run"))

    def test_only_the_allowed_fixture_files_are_read(self):
        fixtures = str(FIXTURE_DIR.resolve())
        read = [Path(f).name for f, m in self.opened if "r" in m and str(Path(f).resolve()).startswith(fixtures)]
        self.assertEqual(sorted(set(read)), sorted(ALLOWED_FILES))
        self.assertFalse([f for f, _ in self.opened if "held-out" in f or "held_out" in Path(f).name])

    def test_writes_only_under_the_output_parent(self):
        written = [f for f, m in self.opened if any(c in m for c in "wax+")]
        self.assertTrue(written)
        parent = str((self.dir / "out").resolve())
        self.assertTrue(all(str(Path(f).resolve()).startswith(parent) for f in written), written)

    def test_no_held_out_identifier_in_any_artifact(self):
        _, texts = load_dir(self.out)
        ids = admitted().graph.held_out_identifiers
        self.assertIn("candidate_demo_d", ids)
        for name, text in texts.items():
            for ident in ids:
                self.assertIsNone(re.search(r"(?<![A-Za-z0-9_])" + re.escape(ident) + r"(?![A-Za-z0-9_])", text), (name, ident))

    def test_no_measured_value_anywhere(self):
        docs, _ = load_dir(self.out)
        self.assertEqual(docs["run.json"]["latency"]["status"], "not_measured")
        for o in docs["observations.json"]:
            self.assertEqual((o["latency"]["status"], o["cost"]["status"]), ("not_measured", "not_applicable"))
            self.assertIsNone(o["latency"]["value"])
        keys = set()

        def walk(v):
            if isinstance(v, dict):
                keys.update(v)
                for x in v.values():
                    walk(x)
            elif isinstance(v, list):
                for x in v:
                    walk(x)
        walk(docs)
        value_keys = {"metric_value", "metric_values", "gate_evaluation", "gate_result", "category_results", "comparison",
                      "comparisons", "promotion", "promotion_decision", "accuracy", "match_rate", "agreement_rate"}
        self.assertFalse(keys & value_keys)
        self.assertFalse({k for k in keys if k.endswith("_rate")})


if __name__ == "__main__":
    unittest.main()
