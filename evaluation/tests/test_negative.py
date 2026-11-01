"""B3: cross-artifact binding negatives. Each tampering aborts publication (exit 4) with nothing published.

Tampering is applied to the serialized documents between production and the
publication checks (``artifacts.serialize`` is wrapped), i.e. exactly what a
forged or corrupted sidecar or observation would look like on disk.
"""

from __future__ import annotations

import copy
import json
import unittest
from unittest import mock

from helpers import AS_OF, TempDirTest, products
from rap_baseline import Errored, Stage, assess
from rap_baseline.identity import result_id as baseline_result_id

from rap_evaluation import BindingFailure, artifacts
from rap_evaluation.artifacts import COVERAGE_FILE, IDENTITY_FILE, OBSERVATIONS_FILE, RUN_FILE, SIDECAR_FILE, publish

FABRICATED = "eligibility_" + "f" * 40


def step_of(docs, case_id, step_id):
    obs = next(o for o in docs[OBSERVATIONS_FILE] if o["case_id"] == case_id)
    return obs, next(s for s in obs["steps"] if s["step_id"] == step_id)


def entry_of(docs, case_id, step_id):
    return next(e for e in docs[SIDECAR_FILE]["entries"] if (e["case_id"], e["step_id"]) == (case_id, step_id))


def set_result(entry, **changes):
    r = json.loads(entry["result_json"])
    r.update(changes)
    entry["result_json"] = json.dumps(r, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class BindingNegativeTests(TempDirTest):
    def publish_tampered(self, mutate, check: str, p=None):
        real = artifacts.serialize

        def tampering(prod):
            docs = copy.deepcopy(real(prod))
            mutate(docs)
            return docs
        out = self.tmp / "o" / "run"
        with mock.patch.object(artifacts, "serialize", side_effect=tampering), self.assertRaises(BindingFailure) as cm:
            publish(p or products(), out)
        self.assertEqual(cm.exception.check, check, str(cm.exception))
        self.assertNothingPublished(out)
        self.assertFalse((self.tmp / "o").exists())
        return cm.exception

    def test_untampered_publication_succeeds(self):
        out = publish(products(), self.tmp / "ok")
        self.assertTrue((out / RUN_FILE).exists())

    # --- X1 ---------------------------------------------------------------------------
    def test_missing_sidecar_entry(self):
        self.publish_tampered(lambda d: d[SIDECAR_FILE]["entries"].pop(1), "X1")

    def test_duplicate_sidecar_entry(self):
        self.publish_tampered(lambda d: d[SIDECAR_FILE]["entries"].append(copy.deepcopy(d[SIDECAR_FILE]["entries"][0])), "X1")

    def test_orphan_sidecar_entry(self):
        def orphan(d):
            e = copy.deepcopy(d[SIDECAR_FILE]["entries"][0])
            e["step_id"] = "s9"
            d[SIDECAR_FILE]["entries"].append(e)
        self.publish_tampered(orphan, "X1")

    # --- X2 ---------------------------------------------------------------------------
    def test_substituted_id(self):
        def sub(d):
            other = step_of(d, "evalcase_g025", "s3")[1]["observed"]["eligibility_result_id"]
            step_of(d, "evalcase_g025", "s2")[1]["observed"]["eligibility_result_id"] = other
        self.publish_tampered(sub, "X2")

    def test_fabricated_id_without_sidecar_support(self):
        self.publish_tampered(lambda d: step_of(d, "evalcase_g003", "s1")[1]["observed"].update(eligibility_result_id=FABRICATED), "X2")

    def test_label_id_used_as_generated_id(self):
        self.publish_tampered(lambda d: step_of(d, "evalcase_g003", "s1")[1]["observed"].update(
            eligibility_result_id="eligibility_a_ops"), "X2")

    def test_non_canonical_sidecar_bytes(self):
        def spaced(d):
            e = entry_of(d, "evalcase_g003", "s1")
            e["result_json"] = json.dumps(json.loads(e["result_json"]), indent=1)
        self.publish_tampered(spaced, "X2")

    def test_unparseable_sidecar_bytes(self):
        self.publish_tampered(lambda d: entry_of(d, "evalcase_g003", "s1").update(result_json="{}"), "X2")

    # --- X3 ---------------------------------------------------------------------------
    def test_fabricated_id_with_consistent_sidecar(self):
        def fab(d):
            e = entry_of(d, "evalcase_g003", "s1")
            set_result(e, id=FABRICATED)
            e["result_id"] = e["provenance"]["result_id"] = FABRICATED
            step_of(d, "evalcase_g003", "s1")[1]["observed"]["eligibility_result_id"] = FABRICATED
        self.publish_tampered(fab, "X3")

    def test_label_id_with_consistent_sidecar(self):
        def lab(d):
            e = entry_of(d, "evalcase_g003", "s1")
            set_result(e, id="eligibility_a_ops")
            e["result_id"] = e["provenance"]["result_id"] = "eligibility_a_ops"
            step_of(d, "evalcase_g003", "s1")[1]["observed"]["eligibility_result_id"] = "eligibility_a_ops"
        self.publish_tampered(lab, "X3")

    def test_tampered_result_bytes(self):
        self.publish_tampered(lambda d: set_result(entry_of(d, "evalcase_g003", "s1"),
                                                   evaluated_by="rap-baseline.eligibility/9.9.9"), "X3")

    def test_tampered_result_decision_is_not_a_valid_result(self):
        self.publish_tampered(lambda d: set_result(entry_of(d, "evalcase_g003", "s1"), decision="eligible"), "X2")

    def test_declared_fingerprint_is_not_trusted(self):
        def fp(d):
            e = entry_of(d, "evalcase_g002", "s1")
            e["input_fingerprint"] = e["provenance"]["input_fingerprint"] = "sha256:" + "1" * 64
        self.publish_tampered(fp, "X3")

    def test_forged_fingerprint_with_a_consistent_id_is_not_trusted(self):
        """A forged fingerprint with every dependent id made consistent: only fingerprint recomputation detects it."""
        forged = "sha256:" + "5" * 64

        def forge(d):
            new_id = baseline_result_id(forged, AS_OF)
            for case_id in ("evalcase_g002", "evalcase_g008"):  # one shared key: keep X9 consistent too
                e = entry_of(d, case_id, "s1")
                set_result(e, id=new_id)
                e["result_id"] = e["provenance"]["result_id"] = new_id
                e["input_fingerprint"] = e["provenance"]["input_fingerprint"] = forged
                step_of(d, case_id, "s1")[1]["observed"]["eligibility_result_id"] = new_id
        self.publish_tampered(forge, "X3")

    def test_declared_output_digest_is_not_trusted(self):
        def od(d):
            e = entry_of(d, "evalcase_g002", "s1")
            e["output_digest"] = e["provenance"]["output_digest"] = "sha256:" + "2" * 64
        self.publish_tampered(od, "X3")

    def test_provenance_principal_mismatch(self):
        self.publish_tampered(lambda d: entry_of(d, "evalcase_g002", "s1")["provenance"].update(
            principal_id="principal_demo_viewer"), "X3")

    # --- X4 ---------------------------------------------------------------------------
    def test_generated_id_equal_to_a_label_id_is_rejected(self):
        """Isolates X4: a (hypothetical) recomputed id that collides with a label id."""
        def collide(d):
            e = entry_of(d, "evalcase_g003", "s1")
            set_result(e, id="eligibility_a_ops")
            e["result_id"] = e["provenance"]["result_id"] = "eligibility_a_ops"
            step_of(d, "evalcase_g003", "s1")[1]["observed"]["eligibility_result_id"] = "eligibility_a_ops"
            step_of(d, "evalcase_g025", "s2")[1]["observed"]["eligibility_result_id"] = "eligibility_a_ops"
            e2 = entry_of(d, "evalcase_g025", "s2")
            e2.update(result_json=e["result_json"], result_id="eligibility_a_ops")
            e2["provenance"]["result_id"] = "eligibility_a_ops"
        p = products()
        target = next(e for e in p.entries if e.case_id == "evalcase_g003").provenance["input_fingerprint"]
        real = artifacts.result_id

        def colliding(fp, as_of):
            return "eligibility_a_ops" if fp == target else real(fp, as_of)
        with mock.patch.object(artifacts, "result_id", side_effect=colliding):
            self.publish_tampered(collide, "X4", p=p)

    # --- X5 ---------------------------------------------------------------------------
    def test_sidecar_key_mismatch(self):
        self.publish_tampered(lambda d: entry_of(d, "evalcase_g025", "s3")["label_key"].update(
            opportunity_id="opportunity_demo_ops"), "X5")

    def test_sidecar_request_mismatch(self):
        self.publish_tampered(lambda d: entry_of(d, "evalcase_g025", "s3")["request"].update(
            as_of="2026-11-02T00:00:00Z"), "X5")

    # --- X6 ---------------------------------------------------------------------------
    def test_observed_decision_differs_from_the_result(self):
        self.publish_tampered(lambda d: step_of(d, "evalcase_g003", "s1")[1]["observed"].update(decision="eligible"), "X6")

    def test_observed_rule_outcomes_differ_from_the_result(self):
        self.publish_tampered(lambda d: step_of(d, "evalcase_g003", "s1")[1]["observed"]["rule_outcomes"].pop(), "X6")

    def test_status_not_following_from_the_comparison(self):
        def flip(d):
            obs, step = step_of(d, "evalcase_g003", "s1")
            step["status"], obs["outcome"] = "mismatched", "fail"
        self.publish_tampered(flip, "X6")

    # --- X7 ---------------------------------------------------------------------------
    def test_validator_verdict_not_reproduced(self):
        def verdict(d):
            obs, step = step_of(d, "evalcase_g003", "s1")
            step["observed"].update(result="violation", violation_code="unknown_reference")
            step["status"], obs["outcome"] = "mismatched", "fail"
        self.publish_tampered(verdict, "X7")

    # --- X8 ---------------------------------------------------------------------------
    @staticmethod
    def errored_products():
        def engine(request, context, authority, capabilities):
            if request.opportunity_id == "opportunity_demo_ops":
                return Errored(Stage.RESULT, "rule_evaluation_failed", "synthetic", 0)
            return assess(request, context, authority, capabilities)
        return products(assess_fn=engine)

    def test_errored_products_publish(self):
        out = publish(self.errored_products(), self.tmp / "errored")
        obs = {o["case_id"]: o for o in json.loads((out / OBSERVATIONS_FILE).read_text())}
        self.assertEqual(obs["evalcase_g003"]["outcome"], "fail")
        self.assertEqual(obs["evalcase_g003"]["steps"][0]["observed"]["error_type"], "engine_errored")

    def test_errored_step_with_result_bytes(self):
        def add_bytes(d):
            entry_of(d, "evalcase_g003", "s1")["result_json"] = entry_of(d, "evalcase_g002", "s1")["result_json"]
        self.publish_tampered(add_bytes, "X8", p=self.errored_products())

    def test_errored_step_error_type_mismatch(self):
        self.publish_tampered(lambda d: entry_of(d, "evalcase_g003", "s1").update(outcome="refused"), "X8",
                              p=self.errored_products())

    def test_errored_step_without_stage_or_code(self):
        self.publish_tampered(lambda d: entry_of(d, "evalcase_g003", "s1").update(refusal=None), "X8",
                              p=self.errored_products())

    # --- X9 ---------------------------------------------------------------------------
    def test_steps_sharing_a_key_with_different_bytes(self):
        """Isolates X9 by disabling the per-step checks (X2-X7) for this test only."""
        def differ(d):
            set_result(entry_of(d, "evalcase_g008", "s1"), evaluated_by="rap-baseline.eligibility/9.9.9")
        with mock.patch.object(artifacts, "_check_assessed"):
            self.publish_tampered(differ, "X9")

    # --- publication checks -----------------------------------------------------------------
    def test_engine_step_with_validator_basis_is_rejected(self):
        self.publish_tampered(lambda d: step_of(d, "evalcase_g003", "s1")[1].update(basis="reference_validator"), "P1")

    def test_prerequisite_with_engine_basis_is_rejected(self):
        self.publish_tampered(lambda d: step_of(d, "evalcase_g025", "s1")[1].update(
            basis="deterministic_baseline_execution"), "P3")

    def test_completed_status_is_rejected(self):
        def completed(d):
            d[RUN_FILE]["status"] = "completed"
            d[RUN_FILE]["completed_at"] = "2099-01-01T00:00:00Z"
        self.publish_tampered(completed, "P1")

    def test_executing_a_not_selected_case_is_rejected(self):
        def sneak(d):
            o = next(x for x in d[OBSERVATIONS_FILE] if x["case_id"] == "evalcase_g001")
            o.update(execution_status="errored")
        self.publish_tampered(sneak, "P1")

    def test_coverage_that_does_not_follow_is_rejected(self):
        self.publish_tampered(lambda d: d[COVERAGE_FILE].update(engine_invocations=6), "P4")

    def test_identity_record_that_does_not_follow_is_rejected(self):
        self.publish_tampered(lambda d: d[IDENTITY_FILE].update(output_digest="sha256:" + "3" * 64), "P5")

    def test_held_out_identifier_in_an_artifact_is_rejected(self):
        def leak(d):
            entry_of(d, "evalcase_g003", "s1")["explanation"]["artifact"]["rendered_text"] = "see candidate_demo_d"
        self.publish_tampered(leak, "S1")


if __name__ == "__main__":
    unittest.main()
