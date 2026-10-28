"""D-004.12 -- single-record rules of the evaluation contracts (case grammar, statuses, runs, metrics)."""

import copy
import unittest

from pydantic import ValidationError

import eval_harness as H
from rap_contracts.evaluation import (
    NOT_APPLICABLE,
    CaseObservation,
    CaseOutcome,
    CodeRevision,
    DefinitionsPin,
    EvaluationCase,
    EvaluationRun,
    Measurement,
    ObservedRecord,
    RecordAttribution,
    ReviewExpectation,
    Split,
    StepObservation,
    ValidationExpectation,
    derive_case_outcome,
    pin_manifest,
)
from rap_contracts.promotion import (
    REQUIRED_ZERO_TOLERANCE,
    MetricDefinition,
    MetricDefinitionSet,
    MetricValue,
    SafetyCategoryRule,
    SafetyGatePolicy,
    compute_rate,
)
from rap_contracts.adjudication import ReviewerRubric


def raw_case(cid):
    for split in Split:
        for c in H.split_doc(split)["cases"]:
            if c["id"] == cid:
                return copy.deepcopy(c)
    raise KeyError(cid)


class CaseGrammarTests(unittest.TestCase):
    def test_every_committed_case_parses_into_the_operation_union(self):
        ops = set()
        for split in Split:
            for case in H.cases_of(H.split_doc(split)):
                ops |= {s.operation for s in case.steps}
        self.assertEqual(ops, {"record_set_validation", "context_validation", "eligibility_support",
                               "verification_acceptance", "verification_transition", "retrieval_admission",
                               "review_command"})

    def _rejects(self, mutate, cid="evalcase_g023"):
        doc = raw_case(cid)
        mutate(doc)
        with self.assertRaises(ValidationError):
            EvaluationCase.model_validate(doc)

    def test_unknown_operation_rejected(self):
        self._rejects(lambda d: d["steps"][0].update(operation="run_model"))

    def test_expectation_must_fit_the_operation(self):
        self._rejects(lambda d: d["steps"][1].update(expected={"result": "accepted"}))  # eligibility needs labels
        self._rejects(lambda d: d["steps"][4].update(expected={"result": "accepted"}))  # transition needs status_after

    def test_a_case_needs_a_target(self):
        def no_target(d):
            for s in d["steps"]:
                s["role"] = "prerequisite"
                s.pop("consequence_of", None)
                s["safety"] = []
        self._rejects(no_target)

    def test_consequence_must_follow_its_target(self):
        self._rejects(lambda d: d["steps"][4].update(consequence_of="s2"))  # s2 is a prerequisite
        self._rejects(lambda d: d["steps"][4].update(consequence_of="s9"))
        self._rejects(lambda d: d["steps"][3].update(consequence_of="s2"))  # target given consequence_of

    def test_state_from_only_backwards(self):
        self._rejects(lambda d: d["steps"][2].update(state_from=["s4"]))

    def test_safety_only_on_target_or_consequence(self):
        self._rejects(lambda d: d["steps"][0].update(safety=d["steps"][3]["safety"]))

    def test_review_steps_need_a_declared_store_and_explicit_state(self):
        self._rejects(lambda d: d["initial_state"].update(review_store="none"), "evalcase_g018")
        self._rejects(lambda d: d["steps"][3].update(state_from=["s3"]), "evalcase_g018")  # omits s2
        self._rejects(lambda d: d["steps"][3]["expected"].update(same_decision_as="s2"), "evalcase_g018")

    def test_assertions_need_a_store(self):
        self._rejects(lambda d: d.update(assertions=[{"kind": "audit_event_total", "equals": 0}]))

    def test_label_status_and_legacy_prefix_rules(self):
        self._rejects(lambda d: d["provenance"].update(review_status="adjudicated"))
        self._rejects(lambda d: d.update(legacy_label="EVAL-H001"), "evalcase_g001")

    def test_expectation_shapes(self):
        with self.assertRaises(ValidationError):
            ValidationExpectation(result="violation")
        with self.assertRaises(ValidationError):
            ValidationExpectation(result="accepted", violation_code="x_y")
        with self.assertRaises(ValidationError):
            ReviewExpectation(outcome="rejected", external_code="not_permitted", decisions_delta=0, events_delta=0)
        with self.assertRaises(ValidationError):
            ReviewExpectation(outcome="recorded", decisions_delta=0, events_delta=0)
        with self.assertRaises(ValidationError):
            ReviewExpectation(outcome="replayed", decisions_delta=0, events_delta=0)


class OutcomeDerivationTests(unittest.TestCase):
    def step(self, sid, role, status):
        observed = None if status == "not_evaluated" else ObservedRecord()
        return StepObservation(step_id=sid, role=role, operation="context_validation", status=status,
                               basis="reference_validator", observed=observed)

    def test_table(self):
        P, C, T, K = "prerequisite", "control", "target", "consequence"
        cases = [
            ([(P, "matched"), (T, "matched"), (K, "matched")], None, CaseOutcome.PASS),
            ([(P, "mismatched"), (T, "not_evaluated")], None, CaseOutcome.INCONCLUSIVE),
            ([(C, "errored"), (T, "matched")], None, CaseOutcome.INCONCLUSIVE),
            ([(P, "matched"), (T, "mismatched"), (K, "not_evaluated")], None, CaseOutcome.FAIL),
            ([(T, "errored")], None, CaseOutcome.FAIL),
            ([(T, "matched"), (T, "matched")], False, CaseOutcome.FAIL),
            ([(T, "matched"), (T, "matched")], True, CaseOutcome.PASS),
        ]
        for rows, assertions, want in cases:
            steps = [self.step(f"s{i}", r, s) for i, (r, s) in enumerate(rows, 1)]
            with self.subTest(rows=rows):
                self.assertIs(derive_case_outcome(steps, assertions), want)

    def test_case_observation_consistency(self):
        steps = (self.step("s1", "target", "mismatched"),)
        base = dict(run_id="evalrun_x", case_id="evalcase_g001", case_version=1, case_sha256="sha256:" + "0" * 64,
                    split="golden", latency=Measurement(status="not_measured", unit="milliseconds"),
                    cost=Measurement(status="not_applicable", unit="usd"))
        CaseObservation(**base, execution_status="executed", steps=steps, outcome="fail")
        with self.assertRaises(ValidationError):
            CaseObservation(**base, execution_status="executed", steps=steps, outcome="pass")
        with self.assertRaises(ValidationError):
            CaseObservation(**base, execution_status="not_run", steps=steps, outcome="not_evaluated")
        with self.assertRaises(ValidationError):
            StepObservation(step_id="s1", role="target", operation="context_validation", status="not_evaluated",
                            basis="reference_validator", observed=ObservedRecord())
        with self.assertRaises(ValidationError):
            ObservedRecord(admitted_text="Synthetic summary")  # no text fields exist


class MeasurementTests(unittest.TestCase):
    def test_value_only_when_observed(self):
        Measurement(status="observed", unit="milliseconds", value=12.0)
        for status in ("not_run", "not_measured", "not_applicable", "errored"):
            with self.subTest(status=status), self.assertRaises(ValidationError):
                Measurement(status=status, unit="milliseconds", value=0.0)
        with self.assertRaises(ValidationError):
            Measurement(status="observed", unit="usd")

    def test_zero_denominator_is_not_applicable_never_full_marks(self):
        definition = MetricDefinition(id="unknown_state_preservation", version=1, family="outcome", description="d",
                                      numerator="n", denominator="d", unit="ratio",
                                      applicable_run_kinds=("deterministic_baseline",), gate="threshold_uncalibrated")
        value = compute_rate(definition, "deterministic_baseline", 0, 0)
        self.assertEqual((value.status.value, value.value, value.denominator), ("not_applicable", None, 0))
        self.assertEqual(compute_rate(definition, "deterministic_baseline", 3, 4).value, 0.75)
        with self.assertRaises(ValidationError):
            MetricValue(metric_id="m", metric_version=1, status="observed", numerator=1, denominator=0, value=1.0)
        with self.assertRaises(ValidationError):
            MetricValue(metric_id="m", metric_version=1, status="observed", numerator=1, denominator=2, value=0.9)

    def test_outcome_metrics_never_apply_to_conformance_runs(self):
        defs = MetricDefinitionSet.model_validate(H.load(H.DEFINITIONS_FILE)["metric_definitions"])
        correctness = next(m for m in defs.metrics if m.id == "eligibility_label_correctness")
        self.assertEqual(compute_rate(correctness, "fixture_conformance", 26, 26).status.value, "not_applicable")
        with self.assertRaises(ValidationError):
            MetricDefinition.model_validate({**correctness.model_dump(), "applicable_run_kinds": ["fixture_conformance"]})


def run_payload(**update):
    payload = dict(
        id="evalrun_example", run_kind="fixture_conformance", purpose="regression",
        manifests=(pin_manifest(H.manifest_of(H.split_doc(Split.GOLDEN))),),
        definitions=DefinitionsPin(id="evaldefs_metrics", version=1),
        safety_policy=DefinitionsPin(id="evaldefs_safety_gate", version=1),
        contract_version="0.2.0-dev.foundations.4", code_revision=CodeRevision(status="unavailable"),
        source_authority="fixture_mock", retrieval_index=NOT_APPLICABLE, prompt=NOT_APPLICABLE, model=NOT_APPLICABLE,
        judge=NOT_APPLICABLE, replicates=1, started_at="2026-10-28T20:00:00Z", completed_at="2026-10-28T20:00:01Z",
        status="completed", latency=Measurement(status="not_measured", unit="milliseconds"),
        cost=Measurement(status="not_applicable", unit="usd"), executed_by="eval-harness-test-only/0")
    payload.update(update)
    return payload


class RunRuleTests(unittest.TestCase):
    PINNED = {"status": "pinned", "value": "example/1"}
    CLEAN = {"status": "recorded", "commit": "a" * 40, "dirty": False}

    def test_valid_conformance_run(self):
        self.assertEqual(EvaluationRun.model_validate(run_payload()).evidence_tier.value, "t2_mock_observed")

    def test_invalid_runs(self):
        bad = {
            "conformance run pins a model": run_payload(model=self.PINNED),
            "conformance run used for promotion": run_payload(purpose="promotion_assessment", code_revision=self.CLEAN),
            "conformance run against drupal": run_payload(source_authority="drupal"),
            "model run without prompt/model pins": run_payload(run_kind="single_model"),
            "no-model run reports inference cost": run_payload(run_kind="deterministic_baseline",
                                                               cost=Measurement(status="observed", unit="usd", value=0.0)),
            "promotion run on a dirty tree": run_payload(run_kind="deterministic_baseline", purpose="promotion_assessment",
                                                         code_revision={**self.CLEAN, "dirty": True}),
            "promotion run without a recorded revision": run_payload(run_kind="deterministic_baseline",
                                                                     purpose="promotion_assessment"),
            "completed without completion time": run_payload(completed_at=None),
            "aborted with completion time": run_payload(status="aborted"),
        }
        for label, payload in bad.items():
            with self.subTest(label), self.assertRaises(ValidationError):
                EvaluationRun.model_validate(payload)

    def test_promotion_assessment_shape(self):
        run = EvaluationRun.model_validate(run_payload(run_kind="deterministic_baseline", purpose="promotion_assessment",
                                                       code_revision=self.CLEAN))
        self.assertEqual(run.evidence_tier.value, "t3_offline_measured")


class DefinitionsTests(unittest.TestCase):
    def setUp(self):
        self.doc = H.load(H.DEFINITIONS_FILE)

    def test_committed_definitions_validate_and_are_drafts(self):
        metrics = MetricDefinitionSet.model_validate(self.doc["metric_definitions"])
        policy = SafetyGatePolicy.model_validate(self.doc["safety_gate_policy"])
        rubric = ReviewerRubric.model_validate(self.doc["reviewer_rubric"])
        self.assertEqual((metrics.status, policy.status, rubric.status), ("draft", "draft", "draft"))
        zero = {r.category for r in policy.categories if r.zero_tolerance}
        self.assertEqual(zero, REQUIRED_ZERO_TOLERANCE)
        self.assertEqual({m.safety_category for m in metrics.metrics if m.gate.value == "zero_tolerance"}, REQUIRED_ZERO_TOLERANCE)

    def test_no_threshold_is_invented(self):
        metrics = MetricDefinitionSet.model_validate(self.doc["metric_definitions"])
        self.assertTrue(all(m.gate.value in ("zero_tolerance", "report_only", "threshold_uncalibrated") for m in metrics.metrics))
        self.assertNotIn("threshold", {k for m in self.doc["metric_definitions"]["metrics"] for k in m})

    def test_policy_requires_every_zero_tolerance_category(self):
        doc = copy.deepcopy(self.doc["safety_gate_policy"])
        doc["categories"] = [r for r in doc["categories"] if r["category"] != "source_content_integrity"]
        with self.assertRaises(ValidationError):
            SafetyGatePolicy.model_validate(doc)
        doc = copy.deepcopy(self.doc["safety_gate_policy"])
        next(r for r in doc["categories"] if r["category"] == "unauthorized_review_write")["zero_tolerance"] = False
        with self.assertRaises(ValidationError):
            SafetyGatePolicy.model_validate(doc)

    def test_t1_t2_bases_can_never_satisfy_a_category(self):
        rule = copy.deepcopy(self.doc["safety_gate_policy"]["categories"][0])
        for basis in ("schema_validation", "reference_validator", "mock_authority", "in_memory_double"):
            with self.subTest(basis=basis), self.assertRaises(ValidationError):
                SafetyCategoryRule.model_validate({**rule, "accepted_bases": [basis]})
        with self.assertRaises(ValidationError):
            SafetyCategoryRule.model_validate({**rule, "applies_to_run_kinds": ["fixture_conformance"]})

    def test_attribution_is_metadata(self):
        a = RecordAttribution(principal_id="principal_demo_owner", asserted_kind="human", attestation_basis="unverified_metadata")
        self.assertEqual(a.attestation_basis.value, "unverified_metadata")
        with self.assertRaises(ValidationError):
            RecordAttribution(principal_id="principal_demo_owner", asserted_kind="human", attestation_basis="self_attested")


if __name__ == "__main__":
    unittest.main()
