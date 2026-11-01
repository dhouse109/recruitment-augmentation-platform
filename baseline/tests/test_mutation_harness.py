"""Review repair R1: the mutation harness never reports a harness failure as a caught mutation.

Unit tests of ``tools/mutations.py``'s pure classifier on synthetic runner output. The
end-to-end controls (a no-op edit and an import-breaking edit) run inside the harness itself.
"""

import importlib.util
import unittest
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location("rap_mutation_harness",
                                               Path(__file__).resolve().parent / "tools" / "mutations.py")
harness = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(harness)

SEP = "-" * 70


def output(blocks=(), ran=10, summary="OK"):
    lines = []
    for kind, name, where in blocks:
        lines += ["=" * 70, f"{kind}: {name} ({where})", SEP, "Traceback (most recent call last):", "AssertionError", ""]
    lines += [SEP, f"Ran {ran} tests in 0.123s", "", summary]
    return "\n".join(lines) + "\n"


class ClassifierTests(unittest.TestCase):
    def test_clean_complete_run(self):
        r = harness.classify(0, output(), 10)
        self.assertEqual(r["status"], "completed_ok")

    def test_genuine_failures(self):
        text = output([("FAIL", "test_a", "test_m.C.test_a"), ("ERROR", "test_b", "test_m.C.test_b")], 10,
                      "FAILED (failures=1, errors=1)")
        r = harness.classify(1, text, 10)
        self.assertEqual((r["status"], r["failures"], r["errors"], r["methods"]),
                         ("completed_failed", 1, 1, {"test_a", "test_b"}))

    def test_runner_did_not_finish(self):
        self.assertEqual(harness.classify(None, "", 10)["status"], "harness_error")

    def test_missing_test_count(self):
        text = "Traceback (most recent call last):\nSyntaxError: invalid syntax\n"
        r = harness.classify(1, text, 10)
        self.assertEqual(r["status"], "harness_error")
        self.assertIn("Ran N tests", r["reason"])

    def test_missing_summary(self):
        text = output([("FAIL", "test_a", "test_m.C.test_a")], 10, "FAILED (failures=1)").rsplit("FAILED", 1)[0]
        self.assertEqual(harness.classify(1, text, 10)["status"], "harness_error")

    def test_incomplete_or_resized_suite(self):
        text = output([("FAIL", "test_a", "test_m.C.test_a")], 4, "FAILED (failures=1)")
        r = harness.classify(1, text, 10)
        self.assertEqual(r["status"], "harness_error")
        self.assertIn("expected 10", r["reason"])

    def test_module_import_failure_is_not_detection(self):
        text = output([("ERROR", "test_m", "unittest.loader._FailedTest.test_m")], 10, "FAILED (errors=1)")
        r = harness.classify(1, text, 10)
        self.assertEqual(r["status"], "harness_error")
        self.assertIn("import", r["reason"])

    def test_summary_must_match_blocks(self):
        text = output([("FAIL", "test_a", "test_m.C.test_a")], 10, "FAILED (failures=3)")
        self.assertEqual(harness.classify(1, text, 10)["status"], "harness_error")

    def test_failed_summary_without_blocks_or_wrong_exit(self):
        self.assertEqual(harness.classify(1, output([], 10, "FAILED (failures=0)"), 10)["status"], "harness_error")
        text = output([("FAIL", "test_a", "test_m.C.test_a")], 10, "FAILED (failures=1)")
        self.assertEqual(harness.classify(0, text, 10)["status"], "harness_error")
        self.assertEqual(harness.classify(1, output(), 10)["status"], "harness_error")

    def test_judge_requires_discriminators(self):
        failed = harness.classify(1, output([("FAIL", "test_a", "test_m.C.test_a")], 10, "FAILED (failures=1)"), 10)
        self.assertEqual(harness.judge(failed, ["test_a"])[0], harness.CAUGHT)
        self.assertEqual(harness.judge(failed, ["test_b"])[0], harness.NOT_CAUGHT)
        self.assertEqual(harness.judge(harness.classify(0, output(), 10), [])[0], harness.NOT_CAUGHT)
        self.assertEqual(harness.judge(harness.classify(None, "", 10), [])[0], harness.HARNESS_ERROR)

    def test_controls_are_defined(self):
        self.assertEqual({want for *_, want in harness.CONTROLS}, {harness.NOT_CAUGHT, harness.HARNESS_ERROR})


if __name__ == "__main__":
    unittest.main()
