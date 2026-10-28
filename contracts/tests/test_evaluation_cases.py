"""D-004.12 -- conformance of every declared evaluation case (TEST-ONLY harness, evidence tier T2).

Each case is executed against the existing reference validators, the MOCK
source authority/chunk store and the in-memory review TEST DOUBLE, and its
observations are compared with expectations pinned in the dataset manifests.

Acceptance is strict: every case must PASS. Inconclusive (a prerequisite or
control did not hold), failed, errored or not-evaluated cases fail the suite.

What a pass means: hand-written labels and declared fault records agree with
the reference validators on synthetic data. It is NOT a deterministic
baseline (T3), not a model evaluation, and not integrated safety evidence (T4).
"""

import json
import unittest

import eval_harness as H
from rap_contracts.eligibility import EligibilityDecision
from rap_contracts.evaluation import (
    BASIS_TIER,
    NOT_APPLICABLE,
    CaseOutcome,
    CodeRevision,
    DefinitionsPin,
    EvaluationRun,
    EvidenceTier,
    Measurement,
    MeasurementStatus,
    SafetyDisposition,
    Split,
    StepStatus,
    check_manifest_cases,
    pin_manifest,
)

EXPECTED_CASES = {
    Split.GOLDEN: {"g001", "g002", "g003", "g004", "g005a", "g005b", "g006", "g007", "g008", "g009", "g010", "g011",
                   "g012", "g013", "g014", "g015", "g016", "g017", "g018", "g019", "g020", "g021", "g022", "g023",
                   "g024", "g025"},
    Split.HELD_OUT: {"h001", "h002", "h003", "h004", "h005"},
}
LABEL_ONLY_CASES = {"evalcase_g002", "evalcase_g003", "evalcase_g008", "evalcase_g025", "evalcase_h001", "evalcase_h003"}


def acceptance_failures(runs):
    """CI acceptance rule: anything other than PASS is a failure (inconclusive included)."""
    return [H.describe(r) for r in runs if r.observation.outcome is not CaseOutcome.PASS]


def run_split(split):
    doc = H.split_doc(split)
    return doc, [H.run_case(c, doc) for c in H.cases_of(doc)]


class ManifestPinTests(unittest.TestCase):
    """Expectations cannot change silently: cases, case records and base layers are content-pinned."""

    def test_manifests_pin_exactly_the_committed_cases(self):
        for split in Split:
            doc = H.split_doc(split)
            manifest = H.manifest_of(doc)
            with self.subTest(split=split.value):
                check_manifest_cases(manifest, H.cases_of(doc))
                self.assertEqual(manifest.fixture_layers, H.layer_pins())
                self.assertEqual(manifest.case_records_sha256, H.case_records_sha256(doc))
                self.assertEqual({c.id.removeprefix("evalcase_") for c in H.cases_of(doc)}, EXPECTED_CASES[split])

    def test_definitions_pin_the_current_manifests(self):
        policy = H.load(H.DEFINITIONS_FILE)["safety_gate_policy"]
        self.assertEqual(policy["golden_manifest"], pin_manifest(H.manifest_of(H.split_doc(Split.GOLDEN))).model_dump(mode="json"))
        self.assertEqual(policy["held_out_manifest"], pin_manifest(H.manifest_of(H.split_doc(Split.HELD_OUT))).model_dump(mode="json"))


class CaseConformanceTests(unittest.TestCase):
    def test_every_golden_case_passes(self):
        _, runs = run_split(Split.GOLDEN)
        self.assertEqual(len(runs), len(EXPECTED_CASES[Split.GOLDEN]))
        self.assertEqual(acceptance_failures(runs), [])

    def test_every_nominal_held_out_case_passes(self):
        _, runs = run_split(Split.HELD_OUT)
        self.assertEqual(len(runs), len(EXPECTED_CASES[Split.HELD_OUT]))
        self.assertEqual(acceptance_failures(runs), [])

    def test_every_step_was_evaluated_and_matched(self):
        for split in Split:
            _, runs = run_split(split)
            for run in runs:
                for step in run.observation.steps:
                    with self.subTest(case=run.observation.case_id, step=step.step_id):
                        self.assertIs(step.status, StepStatus.MATCHED)

    def test_all_observations_are_tier_t2(self):
        for split in Split:
            _, runs = run_split(split)
            tiers = {BASIS_TIER[s.basis] for r in runs for s in r.observation.steps}
            self.assertEqual(tiers, {EvidenceTier.T2_MOCK_OBSERVED})

    def test_safety_dispositions(self):
        expected_not_observable = {("evalcase_g010", "prompt_injection_compliance")}
        for split in Split:
            _, runs = run_split(split)
            for run in runs:
                for step in run.observation.steps:
                    for sig in step.safety:
                        key = (run.observation.case_id, sig.category.value)
                        with self.subTest(case=key[0], category=key[1]):
                            want = (SafetyDisposition.NOT_OBSERVABLE if key in expected_not_observable
                                    else SafetyDisposition.ATTEMPT_BLOCKED)
                            self.assertIs(sig.disposition, want)

    def test_label_cases_carry_no_safety_signal(self):
        """An ineligible or unknown LABEL is reference-label conformance, never a blocked unsafe action."""
        for split in Split:
            for case in H.cases_of(H.split_doc(split)):
                if case.id in LABEL_ONLY_CASES:
                    with self.subTest(case=case.id):
                        self.assertTrue(all(not s.safety for s in case.steps))
                        self.assertTrue(all(s.operation in ("eligibility_support", "context_validation") for s in case.steps))

    def test_observations_hold_no_source_text(self):
        doc_g, runs_g = run_split(Split.GOLDEN)
        doc_h, runs_h = run_split(Split.HELD_OUT)
        texts = list(H.base_pool()["chunk_store"].values()) + list(doc_g["case_records"].get("chunk_store", {}).values())
        for run in runs_g + runs_h:
            dumped = run.observation.model_dump_json()
            with self.subTest(case=run.observation.case_id):
                self.assertEqual(run.observation.visibility, "internal_only")
                for text in texts:
                    self.assertNotIn(text[:40], dumped)

    def test_conformance_run_record_is_regression_t2_without_measurements(self):
        _, runs = run_split(Split.GOLDEN)
        run = EvaluationRun(
            id="evalrun_conformance_local", run_kind="fixture_conformance", purpose="regression",
            manifests=(pin_manifest(H.manifest_of(H.split_doc(Split.GOLDEN))),
                       pin_manifest(H.manifest_of(H.split_doc(Split.HELD_OUT)))),
            definitions=DefinitionsPin(id="evaldefs_metrics", version=1),
            safety_policy=DefinitionsPin(id="evaldefs_safety_gate", version=1),
            contract_version="0.2.0-dev.foundations.4", code_revision=CodeRevision(status="unavailable"),
            source_authority="fixture_mock", retrieval_index=NOT_APPLICABLE, prompt=NOT_APPLICABLE,
            model=NOT_APPLICABLE, judge=NOT_APPLICABLE, replicates=1, started_at="2026-10-28T20:00:00Z",
            completed_at="2026-10-28T20:00:01Z", status="completed",
            latency=Measurement(status="not_measured", unit="milliseconds"),
            cost=Measurement(status="not_applicable", unit="usd"), executed_by="eval-harness-test-only/0")
        self.assertIs(run.evidence_tier, EvidenceTier.T2_MOCK_OBSERVED)
        for obs in (r.observation for r in runs):
            self.assertIs(obs.latency.status, MeasurementStatus.NOT_MEASURED)
            self.assertIsNone(obs.latency.value)
            self.assertIs(obs.cost.status, MeasurementStatus.NOT_APPLICABLE)


def _case(split, cid):
    doc = H.split_doc(split)
    return doc, next(c for c in H.cases_of(doc) if c.id == cid)


def _with_step(case, step_id, **expected_update):
    steps = []
    for s in case.steps:
        if s.step_id == step_id:
            s = s.model_copy(update={"expected": s.expected.model_copy(update=expected_update)})
        steps.append(s)
    return case.model_copy(update={"steps": tuple(steps)})


class HarnessStrictnessTests(unittest.TestCase):
    """The harness must not pass cases vacuously."""

    def test_wrong_expected_code_fails_the_case(self):
        doc, case = _case(Split.GOLDEN, "evalcase_g023")
        run = H.run_case(_with_step(case, "s4", violation_code="verification_incomplete"), doc)
        self.assertIs(run.observation.outcome, CaseOutcome.FAIL)
        self.assertEqual(run.observed["s4"].violation_code, "non_authoritative_input")

    def test_precision_controls_actually_accept(self):
        for split, cid, control in ((Split.GOLDEN, "evalcase_g005b", "s3"), (Split.GOLDEN, "evalcase_g023", "s3"),
                                    (Split.HELD_OUT, "evalcase_h004", "s3")):
            doc, case = _case(split, cid)
            with self.subTest(case=cid):
                self.assertEqual(H.run_case(case, doc).observed[control].result.value, "accepted")

    def test_g005b_fault_is_a_single_field_mutation_with_identical_coverage(self):
        from rap_contracts.recommendation import recommendation_source_refs

        doc, case = _case(Split.GOLDEN, "evalcase_g005b")
        scope = H.build_scope(case, doc)
        control = scope.recommendations["recommendation_a_web"].model_dump(mode="json")
        fault = scope.recommendations["recommendation_a_web_uncited"].model_dump(mode="json")
        differing = {k for k in control if control[k] != fault[k]} - {"id", "generated_by", "generated_at"}
        self.assertEqual(differing, {"evidence_ids"})
        self.assertEqual(recommendation_source_refs(scope.recommendations["recommendation_a_web"], scope.context),
                         recommendation_source_refs(scope.recommendations["recommendation_a_web_uncited"], scope.context))

    def test_inconclusive_prerequisite_fails_acceptance(self):
        doc, case = _case(Split.GOLDEN, "evalcase_g023")
        broken = _with_step(case, "s2", decision=EligibilityDecision.NEEDS_INFORMATION)
        run = H.run_case(broken, doc)
        self.assertIs(run.observation.outcome, CaseOutcome.INCONCLUSIVE)
        self.assertEqual([s.status for s in run.observation.steps][2:], [StepStatus.NOT_EVALUATED] * 3)
        self.assertEqual(len(acceptance_failures([run])), 1)

    def test_consequence_not_evaluated_when_target_mismatches(self):
        doc, case = _case(Split.GOLDEN, "evalcase_g024")
        run = H.run_case(_with_step(case, "s3", violation_code="policy_version_mismatch"), doc)
        self.assertIs(run.observation.outcome, CaseOutcome.FAIL)
        self.assertIs(run.observation.steps[-1].status, StepStatus.NOT_EVALUATED)

    def test_unblocked_retrieval_is_observed_as_violation(self):
        doc, case = _case(Split.GOLDEN, "evalcase_g007")
        step = case.steps[0].model_copy(update={"authority_delta": ()})  # access no longer revoked
        run = H.run_case(case.model_copy(update={"steps": (step,)}), doc)
        self.assertIs(run.observation.outcome, CaseOutcome.FAIL)
        self.assertIs(run.observation.steps[0].safety[0].disposition, SafetyDisposition.UNBLOCKED_VIOLATION)
        self.assertEqual(run.observed["s1"].admitted_chunk_ids, ("chunk_b_profile",))

    def test_unauthorized_write_is_observed_as_violation(self):
        doc, case = _case(Split.GOLDEN, "evalcase_g012")
        steps = list(case.steps)
        steps[2] = steps[2].model_copy(update={"credential": "credential-demo-coordinator"})
        run = H.run_case(case.model_copy(update={"steps": tuple(steps)}), doc)
        self.assertIs(run.observation.outcome, CaseOutcome.FAIL)
        self.assertIs(run.observation.steps[2].safety[0].disposition, SafetyDisposition.UNBLOCKED_VIOLATION)

    def test_failed_assertion_fails_the_case(self):
        doc, case = _case(Split.GOLDEN, "evalcase_g018")
        bad = case.model_copy(update={"assertions": (case.assertions[0].model_copy(update={"equals": 2}),)})
        self.assertIs(H.run_case(bad, doc).observation.outcome, CaseOutcome.FAIL)

    def test_no_hidden_verification_in_review_store(self):
        """The review double starts empty: without the explicit transition step a review cannot proceed."""
        doc, case = _case(Split.GOLDEN, "evalcase_g018")
        scope = H.build_scope(case, doc)
        store = H.build_review_store(scope, H.build_authority(case, scope))
        self.assertEqual(store.latest_verification, {})
        self.assertEqual({r.status.value for r in store.recommendations.values()}, {"pending_verification"})


if __name__ == "__main__":
    unittest.main()
