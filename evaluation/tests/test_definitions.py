"""A4: read-only verification of the draft v1 definitions (plan section 4.3, decision E7)."""

from __future__ import annotations

import copy
import unittest

from helpers import TempDirTest, config, real_fixtures, tampered
from rap_contracts.evaluation import content_sha256
from rap_contracts.promotion import MetricDefinitionSet, SafetyGatePolicy
from rap_contracts.source_checks import canonical_json_sha256

from rap_evaluation import AdmissionAbort
from rap_evaluation.definitions import METRICS_PIN, POLICY_PIN, verify_definitions
from rap_evaluation.fixtures import DEFINITIONS_FILE, check_integrity
from rap_evaluation.run import run_evaluation

GOLDEN_ROOT = "sha256:5baf87b79e41dd22a97b23977874683eab9099ad83b1148ef2fd8a883b70c769"


class DefinitionsTests(TempDirTest):
    def setUp(self):
        super().setUp()
        self.doc = copy.deepcopy(real_fixtures().definitions)
        self.manifest = check_integrity(real_fixtures()).manifest

    def aborts(self, mutate, code):
        mutate(self.doc)
        with self.assertRaises(AdmissionAbort) as cm:
            verify_definitions(self.doc, self.manifest)
        self.assertEqual((cm.exception.check, cm.exception.code), ("A4", code))

    def test_v1_drafts_verify_and_digests_are_recorded(self):
        check = verify_definitions(self.doc, self.manifest)
        self.assertEqual((check.metrics, check.policy), (METRICS_PIN, POLICY_PIN))
        self.assertEqual(check.statuses, ("draft", "draft"))
        self.assertEqual(check.file_sha256, canonical_json_sha256(self.doc))
        self.assertEqual(check.metrics_sha256, content_sha256(MetricDefinitionSet.model_validate(self.doc["metric_definitions"])))
        self.assertEqual(check.policy_sha256, content_sha256(SafetyGatePolicy.model_validate(self.doc["safety_gate_policy"])))
        self.assertEqual(check.held_out_manifest_pin["split"], "held_out")
        self.assertEqual(self.manifest.id, "evalset_golden")

    def test_policy_pins_the_current_golden_manifest(self):
        self.assertEqual(self.doc["safety_gate_policy"]["golden_manifest"]["root"], GOLDEN_ROOT)

    def test_wrong_metrics_id(self):
        self.aborts(lambda d: d["metric_definitions"].update(id="evaldefs_other"), "metrics_pin_mismatch")

    def test_wrong_metrics_version(self):
        self.aborts(lambda d: d["metric_definitions"].update(version=2), "metrics_pin_mismatch")

    def test_wrong_policy_id_or_version(self):
        self.aborts(lambda d: d["safety_gate_policy"].update(version=2), "policy_pin_mismatch")

    def test_approved_metrics_status(self):
        self.aborts(lambda d: d["metric_definitions"].update(status="approved"), "definitions_not_draft")

    def test_approved_policy_status(self):
        self.aborts(lambda d: d["safety_gate_policy"].update(status="approved"), "definitions_not_draft")

    def test_policy_definitions_pin_mismatch(self):
        self.aborts(lambda d: d["safety_gate_policy"]["definitions"].update(version=2), "policy_definitions_pin_mismatch")

    def test_policy_manifest_check_failure(self):
        self.aborts(lambda d: d["safety_gate_policy"]["golden_manifest"].update(root="sha256:" + "0" * 64),
                    "golden_manifest_not_authoritative")

    def test_invalid_definitions_document(self):
        self.aborts(lambda d: d.pop("safety_gate_policy"), "definitions_invalid")

    def test_a4_abort_writes_nothing_and_calls_no_engine(self):
        out = self.tmp / "o" / "run"
        with tampered(definitions=lambda d: d["metric_definitions"].update(status="approved")), \
                self.assertRaises(AdmissionAbort) as cm:
            run_evaluation(config(out), assess_fn=lambda *a: self.fail("engine called"))
        self.assertEqual(cm.exception.check, "A4")
        self.assertNothingPublished(out)

    def test_only_the_v1_definitions_file_is_loaded(self):
        self.assertIn(DEFINITIONS_FILE, real_fixtures().opened)
        self.assertFalse([n for n in real_fixtures().opened if "v2" in n or "rubric" in n])


if __name__ == "__main__":
    unittest.main()
