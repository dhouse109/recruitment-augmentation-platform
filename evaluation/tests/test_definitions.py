"""A4: read-only verification of draft metrics v1 and draft safety-gate policy v3 (plan section 4.3, decision E7;
F3, RAP-F3-PLAN-2026-11-04 rev. 1.1, decision F3-D2 option P1)."""

from __future__ import annotations

import copy
import unittest

from helpers import TempDirTest, config, real_fixtures, tampered
from rap_contracts.evaluation import content_sha256
from rap_contracts.promotion import MetricDefinitionSet, SafetyGatePolicy
from rap_contracts.source_checks import canonical_json_sha256

from rap_evaluation import AdmissionAbort
from rap_evaluation.definitions import METRICS_PIN, POLICY_PIN, verify_definitions
from rap_evaluation.fixtures import DEFINITIONS_FILE, GOLDEN_FILE, check_integrity
from rap_evaluation.run import run_evaluation

#: evalset_golden v2 (F3). Policy v1/v2 pin golden v1 (sha256:5baf87b7...), which this runner never reads.
GOLDEN_ROOT = "sha256:3bd060439f58ce4d28e5272d5169135fc93526d5cec8a78de3a8dc4dfbd4d25e"


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

    def test_only_the_golden_v2_definitions_file_is_loaded(self):
        # F3: the "no v2 in any name" check is replaced by exact names, because the approved golden v2 and
        # golden-v2 definitions files carry "v2" in their names. Intent kept: definitions v1, draft definitions
        # v2, the v2 rubric and golden v1 are never opened.
        opened = real_fixtures().opened
        self.assertEqual((DEFINITIONS_FILE, GOLDEN_FILE),
                         ("evaluation-definitions-golden-v2-v0.2.0-dev.json", "evaluation-golden-v2-v0.2.0-dev.json"))
        self.assertIn(DEFINITIONS_FILE, opened)
        for never in ("evaluation-definitions-v0.2.0-dev.json", "evaluation-definitions-v2-v0.2.0-dev.json",
                      "evaluation-golden-v0.2.0-dev.json"):
            self.assertNotIn(never, opened)
        self.assertFalse([n for n in opened if "rubric" in n])


if __name__ == "__main__":
    unittest.main()
