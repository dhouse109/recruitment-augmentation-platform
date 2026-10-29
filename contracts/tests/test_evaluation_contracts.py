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
    RunKind,
    Split,
    StepObservation,
    StrategyPin,
    fingerprint_configuration,
    ValidationExpectation,
    derive_case_outcome,
    pin_manifest,
)
from rap_contracts.promotion import (
    REQUIRED_ZERO_TOLERANCE,
    MetricDefinition,
    MetricDefinitionSet,
    MetricValue,
    check_metric_value,
    SafetyCategoryRule,
    SafetyGatePolicy,
    compute_rate,
)
from rap_contracts.adjudication import ReviewerRubric
from rap_contracts.invariants import ContractViolation
from pydantic import TypeAdapter



def raw_case(cid):
    for split in Split:
        for c in H.split_doc(split)["cases"]:
            if c["id"] == cid:
                return copy.deepcopy(c)
    raise KeyError(cid)

_METRIC_VALUE = TypeAdapter(MetricValue)


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
        self.assertEqual((value.status.value, value.value, value.denominator, value.not_applicable_reason.value),
                         ("not_applicable", None, 0, "zero_denominator"))
        self.assertEqual(compute_rate(definition, "deterministic_baseline", 3, 4).value, 0.75)

    def test_outcome_metrics_never_apply_to_conformance_runs(self):
        defs = MetricDefinitionSet.model_validate(H.load(H.DEFINITIONS_FILE)["metric_definitions"])
        correctness = next(m for m in defs.metrics if m.id == "eligibility_label_correctness")
        value = compute_rate(correctness, "fixture_conformance", 26, 26)
        self.assertEqual((value.status.value, value.not_applicable_reason.value), ("not_applicable", "run_kind_not_applicable"))
        with self.assertRaises(ValidationError):
            MetricDefinition.model_validate({**correctness.model_dump(), "applicable_run_kinds": ["fixture_conformance"]})


def mv(kind, status, **fields):
    return {"kind": kind, "metric_id": "m", "metric_version": 1, "status": status, **fields}


def coverage(reportable=0, eligible=0, ineligible=0, unreviewed=0, missing=0, absent=0, failed=0, unexpected=0, dims=()):
    """Diagnostic usefulness coverage (F4 E9). Produced-expected items = reviewed + unreviewed - unexpected."""
    reviewed = reportable + eligible + ineligible
    produced_expected = reviewed + unreviewed - unexpected
    return {"items_total": produced_expected + unexpected + missing + absent + failed,
            "produced_expected": produced_expected, "produced_unexpected": unexpected, "missing": missing,
            "correctly_absent": absent, "generation_failed": failed, "reviewed": reviewed, "unreviewed": unreviewed,
            "genuinely_reportable": reportable, "structurally_eligible_only": eligible,
            "structurally_ineligible": ineligible,
            "dimension_states": [{"dimension": d, "scored": reviewed, "not_applicable": 0, "disputed": 0, "unresolved": 0}
                                 for d in dims]}


class TypedMetricValueTests(unittest.TestCase):
    """A: each metric unit has its own value type; no fabricated zeros; ratio invariants unchanged."""

    def _accepts(self, payload):
        return _METRIC_VALUE.validate_python(payload)

    def _rejects(self, cases):
        for name, payload in cases.items():
            with self.subTest(name), self.assertRaises(ValidationError):
                _METRIC_VALUE.validate_python(payload)

    def test_valid_values(self):
        for payload in (
            mv("ratio", "observed", numerator=3, denominator=4, value=0.75),
            mv("ratio", "not_applicable", not_applicable_reason="zero_denominator", denominator=0),
            mv("count", "observed", count=0, units_observed=12),
            mv("count", "not_applicable", not_applicable_reason="zero_denominator", units_observed=0),
            mv("duration", "observed", statistic="p95", milliseconds=820.5, samples=40),
            mv("duration", "not_measured", statistic="p95"),
            mv("cost", "observed", total_usd="1.20", units=3, per_unit_usd="0.40"),
            mv("cost", "not_applicable", not_applicable_reason="run_kind_not_applicable"),
            mv("distribution", "observed", coverage=coverage(reportable=4, missing=1, failed=1),
               dimensions=[{"dimension": "evidence_support", "anchors": [{"value": 2, "count": 3}, {"value": 1, "count": 1}]}]),
            mv("distribution", "not_measured", coverage=coverage(eligible=2, unreviewed=1, missing=1)),
        ):
            with self.subTest(payload=payload):
                self._accepts(payload)

    def test_ratio_invariants_are_unchanged(self):
        self._rejects({
            "zero denominator observed": mv("ratio", "observed", numerator=1, denominator=0, value=1.0),
            "value not numerator/denominator": mv("ratio", "observed", numerator=1, denominator=2, value=0.9),
            "numerator above denominator": mv("ratio", "observed", numerator=3, denominator=2, value=1.5),
            "fabricated zero": mv("ratio", "not_measured", numerator=0, denominator=0, value=0.0),
        })

    def test_no_fabricated_zero_in_other_kinds(self):
        self._rejects({
            "count observed over zero units": mv("count", "observed", count=0, units_observed=0),
            "count not measured carries zero": mv("count", "not_measured", count=0),
            "duration observed without samples": mv("duration", "observed", statistic="p95", milliseconds=0.0, samples=0),
            "duration not measured carries 0 ms": mv("duration", "not_measured", statistic="p95", milliseconds=0.0),
            "cost per unit inconsistent": mv("cost", "observed", total_usd="1.20", units=3, per_unit_usd="0.50"),
            "cost as float": mv("cost", "observed", total_usd=1.2, units=3, per_unit_usd=0.4),
            "cost in scientific notation": mv("cost", "observed", total_usd="1e-3", units=1, per_unit_usd="1e-3"),
            "cost zero units observed": mv("cost", "observed", total_usd="0", units=0, per_unit_usd="0"),
            "observed distribution without coverage": mv("distribution", "observed", dimensions=[
                {"dimension": "evidence_support", "anchors": [{"value": 2, "count": 1}]}]),
            "observed distribution with zero-count anchors only": mv("distribution", "observed", coverage=coverage(
                reportable=1), dimensions=[{"dimension": "evidence_support", "anchors": [{"value": 2, "count": 0}],
                                            "not_applicable": 1}]),
        })

    def test_usefulness_distribution_populations_and_coverage(self):
        """F4 E9: coverage is diagnostic; measurement blocks come only from genuinely reportable records.
        Values here are SYNTHETIC shapes: no contract function can yet produce an observed distribution."""
        es, fu = "evidence_support", "follow_up_actionability"
        dist = lambda status, **f: mv("distribution", status, **f)  # noqa: E731
        for name, payload in {
            "zero-scored population (genuine zeros)": dist("observed", coverage=coverage(reportable=3),
                                                          dimensions=[{"dimension": es, "anchors": [{"value": 0, "count": 3}]}]),
            "one dimension all N/A beside a scored one": dist("observed", coverage=coverage(reportable=2), dimensions=[
                {"dimension": es, "anchors": [{"value": 1, "count": 2}]}, {"dimension": fu, "not_applicable": 2}]),
            "every dimension N/A is not a measurement": dist("not_applicable", not_applicable_reason="zero_denominator",
                                                             coverage=coverage(reportable=2)),
            "missing, failed and unreviewed stay diagnostic": dist("not_measured", coverage=coverage(
                eligible=1, ineligible=1, unreviewed=2, missing=3, absent=1, failed=2, unexpected=1, dims=(es,))),
        }.items():
            with self.subTest(name):
                self._accepts(payload)
        broken_presence = {**coverage(reportable=1), "items_total": 5}
        broken_review = {**coverage(reportable=1), "unreviewed": 3}
        broken_states = coverage(eligible=2, dims=(es,))
        broken_states["dimension_states"][0]["scored"] = 1
        self._rejects({
            "all N/A presented as observed": dist("observed", coverage=coverage(reportable=2),
                                                  dimensions=[{"dimension": es, "not_applicable": 2}]),
            "measurement blocks without observation": dist("not_measured", coverage=coverage(eligible=1),
                                                           dimensions=[{"dimension": es, "anchors": [{"value": 2, "count": 1}]}]),
            "dimension does not account for every record": dist("observed", coverage=coverage(reportable=3), dimensions=[
                {"dimension": es, "anchors": [{"value": 2, "count": 2}]}]),
            "anchors from non-reportable records": dist("observed", coverage=coverage(eligible=2), dimensions=[
                {"dimension": es, "anchors": [{"value": 2, "count": 2}]}]),
            "duplicate anchor value": dist("observed", coverage=coverage(reportable=2), dimensions=[
                {"dimension": es, "anchors": [{"value": 2, "count": 1}, {"value": 2, "count": 1}]}]),
            "duplicate dimension block": dist("observed", coverage=coverage(reportable=1), dimensions=[
                {"dimension": es, "anchors": [{"value": 2, "count": 1}]}] * 2),
            "presence counts do not reconcile": dist("not_measured", coverage=broken_presence),
            "produced items neither reviewed nor unreviewed": dist("not_measured", coverage=broken_review),
            "dimension states do not cover reviewed items": dist("not_measured", coverage=broken_states),
        })

    def test_measurement_excludes_disputed_and_unresolved(self):
        """Review finding F2: measured usefulness holds only scores and justified N/A from genuinely reportable,
        finalized adjudications. Disputed and unresolved counts belong to diagnostic coverage only."""
        es = "evidence_support"
        self._accepts(mv("distribution", "observed", coverage=coverage(reportable=3), dimensions=[
            {"dimension": es, "anchors": [{"value": 2, "count": 2}], "not_applicable": 1}]))
        self._rejects({
            "disputed in a measured dimension": mv("distribution", "observed", coverage=coverage(reportable=3), dimensions=[
                {"dimension": es, "anchors": [{"value": 2, "count": 2}], "disputed": 1}]),
            "unresolved in a measured dimension": mv("distribution", "observed", coverage=coverage(reportable=3), dimensions=[
                {"dimension": es, "anchors": [{"value": 2, "count": 2}], "unresolved": 1}]),
            "disputed and unresolved in a measured dimension": mv("distribution", "observed", coverage=coverage(reportable=3),
                                                                   dimensions=[{"dimension": es, "anchors": [{"value": 2, "count": 1}],
                                                                                "disputed": 1, "unresolved": 1}]),
            # Totals balance on scores alone, so only the absence of these fields can reject them.
            "disputed beside balanced scores": mv("distribution", "observed", coverage=coverage(reportable=2), dimensions=[
                {"dimension": es, "anchors": [{"value": 2, "count": 2}], "disputed": 1}]),
            "unresolved beside balanced scores": mv("distribution", "observed", coverage=coverage(reportable=2), dimensions=[
                {"dimension": es, "anchors": [{"value": 2, "count": 2}], "unresolved": 1}]),
            "zero disputed field": mv("distribution", "observed", coverage=coverage(reportable=2), dimensions=[
                {"dimension": es, "anchors": [{"value": 2, "count": 2}], "disputed": 0}]),
        })

    def test_not_applicable_reason_rules(self):
        self._rejects({
            "not applicable without reason": mv("ratio", "not_applicable"),
            "reason without not applicable": mv("ratio", "not_measured", not_applicable_reason="zero_denominator"),
            "zero-denominator reason without the zero": mv("ratio", "not_applicable", not_applicable_reason="zero_denominator"),
            "other reason carrying counts": mv("count", "not_applicable", not_applicable_reason="run_kind_not_applicable",
                                               units_observed=0),
            "unknown kind": mv("percentage", "observed"),
        })

    def test_value_must_fit_definition_run_and_strategy(self):
        import test_promotion_gates as G
        defs = MetricDefinitionSet.model_validate(H.load(H.DEFINITIONS_FILE)["metric_definitions"])
        recall = next(m for m in defs.metrics if m.id == "verification_detection_recall")
        cost = next(m for m in defs.metrics if m.id == "cost_per_reviewed_suggestion")
        with_verifier = G.run()
        without_verifier = G.run(components=("eligibility", "recommendation"))
        na_component = _METRIC_VALUE.validate_python({**mv("ratio", "not_applicable", not_applicable_reason="component_not_in_strategy"),
                                                      "metric_id": recall.id})
        check_metric_value(na_component, recall, without_verifier)
        cases = {
            "unjustified component reason": (na_component, recall, with_verifier, "unjustified_not_applicable"),
            "unjustified run-kind reason": (_METRIC_VALUE.validate_python({**mv("ratio", "not_applicable",
                                            not_applicable_reason="run_kind_not_applicable"), "metric_id": recall.id}),
                                            recall, with_verifier, "unjustified_not_applicable"),
            "observed without the component": (_METRIC_VALUE.validate_python({**mv("ratio", "observed", numerator=1,
                                               denominator=1, value=1.0), "metric_id": recall.id}),
                                               recall, without_verifier, "metric_not_applicable_to_run"),
            "kind does not match unit": (_METRIC_VALUE.validate_python({**mv("count", "observed", count=1, units_observed=1),
                                         "metric_id": recall.id}), recall, with_verifier, "metric_kind_mismatch"),
            "other metric": (na_component, cost, without_verifier, "metric_definition_mismatch"),
        }
        for name, (value, definition, run, code) in cases.items():
            with self.subTest(name), self.assertRaises(ContractViolation) as ctx:
                check_metric_value(value, definition, run)
            self.assertEqual(ctx.exception.code, code)


def run_payload(**update):
    payload = dict(
        id="evalrun_example", run_kind="fixture_conformance", purpose="regression",
        manifests=(pin_manifest(H.manifest_of(H.split_doc(Split.GOLDEN))),),
        definitions=DefinitionsPin(id="evaldefs_metrics", version=1),
        safety_policy=DefinitionsPin(id="evaldefs_safety_gate", version=1),
        contract_version="0.2.0-dev.foundations.4", code_revision=CodeRevision(status="unavailable"),
        strategy={"id": "fixture_conformance", "version": 1},
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
        import test_promotion_gates as G
        baseline = G.run("evalrun_baseline_1", purpose="regression").model_dump(mode="json")
        bad = {
            "conformance run pins a model": run_payload(model=self.PINNED),
            "conformance run used for promotion": run_payload(purpose="promotion_assessment", code_revision=self.CLEAN),
            "conformance run against drupal": run_payload(source_authority="drupal"),
            "conformance run declares components": run_payload(strategy={"id": "x", "version": 1, "components": ["eligibility"]}),
            "conformance run carries a configuration": run_payload(configuration=baseline["configuration"]),
            "model run without prompt/model pins": {**baseline, "run_kind": "single_model",
                                                    "strategy": {**baseline["strategy"], "components": ["eligibility", "model"]}},
            "no-model run with the model component": {**baseline, "strategy": {**baseline["strategy"],
                                                                               "components": ["eligibility", "model"]}},
            "generating run without components": {**baseline, "strategy": {**baseline["strategy"], "components": []}},
            "generating run without configuration": {**baseline, "configuration": None},
            "no-model run reports inference cost": {**baseline, "cost": {"status": "observed", "unit": "usd", "value": 0.0}},
            "promotion run on a dirty tree": {**baseline, "purpose": "promotion_assessment",
                                              "code_revision": {**self.CLEAN, "dirty": True}},
            "generating run without a recorded revision": {**baseline, "code_revision": {"status": "unavailable"}},
            "completed without completion time": run_payload(completed_at=None),
            "aborted with completion time": run_payload(status="aborted"),
        }
        for label, payload in bad.items():
            with self.subTest(label), self.assertRaises(ValidationError):
                EvaluationRun.model_validate(payload)

    def test_promotion_assessment_shape(self):
        import test_promotion_gates as G
        self.assertEqual(G.run().evidence_tier.value, "t3_offline_measured")


class ConfigurationFingerprintTests(unittest.TestCase):
    """B: the fingerprint is recomputed from versioned strategy and configuration fields, never trusted."""

    def setUp(self):
        import test_promotion_gates as G
        self.G = G
        self.base = G.run().model_dump(mode="json")

    def test_forged_fingerprint_rejected(self):
        forged = {**self.base, "configuration": {**self.base["configuration"], "fingerprint": "sha256:" + "f" * 64}}
        with self.assertRaises(ValidationError):
            EvaluationRun.model_validate(forged)

    def test_every_input_changes_the_fingerprint(self):
        G, fp = self.G, self.G.run().configuration.fingerprint
        variants = {
            "strategy version": G.run(strategy_version=9),
            "strategy components": G.run(components=("eligibility",)),
            "code commit": G.run(commit="e" * 40),
            "contract version": G.run(contract_version="0.2.0-dev.foundations.5"),
            "retrieval index": G.run(retrieval_index={"status": "pinned", "value": "index-example/1"}),
            "run kind and model": G.run(kind="single_model", components=("eligibility", "model"),
                                        prompt={"status": "pinned", "value": "prompt-example/1"},
                                        model={"status": "pinned", "value": "model-example/1"}),
        }
        for name, other in variants.items():
            with self.subTest(name):
                self.assertNotEqual(other.configuration.fingerprint, fp)

        def model_run(**kw):
            pins = {"prompt": {"status": "pinned", "value": "prompt-example/1"},
                    "model": {"status": "pinned", "value": "model-example/1"}, **kw}
            return G.run(kind="single_model", components=("eligibility", "model"), **pins)

        mfp = model_run().configuration.fingerprint
        for name, other in {"prompt": model_run(prompt={"status": "pinned", "value": "prompt-example/2"}),
                            "model": model_run(model={"status": "pinned", "value": "model-example/2"}),
                            "judge": model_run(judge={"status": "pinned", "value": "judge-example/1"})}.items():
            with self.subTest(name):
                self.assertNotEqual(other.configuration.fingerprint, mfp)

    def test_execution_conditions_do_not_change_the_fingerprint(self):
        G, fp = self.G, self.G.run().configuration.fingerprint
        for name, other in {"replicates": G.run(replicates=5), "source authority": G.run(source_authority="fixture_mock"),
                            "purpose": G.run(purpose="regression"), "timestamps": G.run(started_at="2026-10-29T00:00:00Z",
                                                                                        completed_at="2026-10-29T00:01:00Z")}.items():
            with self.subTest(name):
                self.assertEqual(other.configuration.fingerprint, fp)

    def test_fingerprint_needs_clean_recorded_revision(self):
        with self.assertRaises(ContractViolation) as ctx:
            fingerprint_configuration(run_kind=RunKind.DETERMINISTIC_BASELINE,
                                      strategy=StrategyPin(id="x", version=1, components=frozenset({"eligibility"})),
                                      code_revision=CodeRevision(status="recorded", commit="a" * 40, dirty=True),
                                      contract_version="0.2.0-dev.foundations.4", retrieval_index=NOT_APPLICABLE,
                                      prompt=NOT_APPLICABLE, model=NOT_APPLICABLE, judge=NOT_APPLICABLE)
        self.assertEqual(ctx.exception.code, "configuration_requires_clean_revision")


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


# ---------------------------------------------------------------------------
# F4 PR-A: proposed draft definitions v2 (contract-level checks of committed data only)
# ---------------------------------------------------------------------------

#: SHA-256 of the v1 definitions file as merged on main @ f45a9368 (PR #7). v1 is immutable.
V1_DEFINITIONS_SHA256 = "9445231558c45e4338e7a42d7e31b63e73ef8c122055da8a052a62401d386957"

#: Owner decision D1: metrics whose text changed are version 2; unchanged metrics keep version 1.
V2_UNCHANGED = frozenset({"case_conformance_rate", "citation_precision", "latency_p95", "cost_per_reviewed_suggestion"})
V2_REVISED = frozenset({"eligibility_label_correctness", "unknown_state_preservation", "verification_detection_recall",
                        "verification_false_alarm_rate", "reviewer_usefulness"}
                       | {f"unblocked_{c.value}" for c in REQUIRED_ZERO_TOLERANCE})
_GEN = ("deterministic_baseline", "single_model", "multi_agent")
#: Metrics new in v2 (version 1): (unit, gate, comparison, requires_component, applicable run kinds).
V2_NEW = {
    "eligibility_rule_agreement": ("ratio", "threshold_uncalibrated", "reported", None, _GEN),  # M2b
    "reviewer_correction_rate": ("ratio", "report_only", "not_compared", "recommendation", _GEN),  # B5 / D3, D5
    "retry_rate": ("ratio", "report_only", "not_compared", "model", ("single_model", "multi_agent")),  # B5 / D2
    "escalation_rate": ("ratio", "report_only", "not_compared", "verifier", _GEN),
    "noncritical_unsupported_claim_rate": ("ratio", "report_only", "not_compared", "recommendation", _GEN),
    "citation_coverage": ("ratio", "report_only", "not_compared", "recommendation", _GEN),
    "latency_p50": ("milliseconds", "report_only", "not_compared", None, _GEN),
    "review_elapsed_time_p50": ("milliseconds", "report_only", "not_compared", "recommendation", _GEN),  # D4, D5
}
_TEXT_FIELDS = ("version", "description", "numerator", "denominator")


class DefinitionsV2Tests(unittest.TestCase):
    """Proposed DRAFT definitions v2 (F4, PR-A).

    These tests check committed definition data and its compatibility with the
    unchanged contract models. They do not show that any metric is produced,
    measured or reportable: no producer exists, and nothing here is approved.
    """

    @classmethod
    def setUpClass(cls):
        cls.v1 = H.load(H.DEFINITIONS_FILE)
        cls.v2 = H.load(H.DEFINITIONS_V2_FILE)
        cls.v2_text = (H.FIXTURE_DIR / H.DEFINITIONS_V2_FILE).read_text(encoding="utf-8")
        cls.metrics = MetricDefinitionSet.model_validate(cls.v2["metric_definitions"])

    def test_v2_definitions_validate_and_are_drafts(self):
        policy = SafetyGatePolicy.model_validate(self.v2["safety_gate_policy"])
        rubric = ReviewerRubric.model_validate(self.v2["reviewer_rubric"])
        self.assertEqual((self.metrics.status, policy.status, rubric.status), ("draft", "draft", "draft"))
        self.assertNotIn('"status": "approved"', self.v2_text)
        self.assertEqual((self.metrics.id, self.metrics.version, policy.id, policy.version),
                         ("evaldefs_metrics", 2, "evaldefs_safety_gate", 2))
        self.assertEqual(self.v2["contract_version"], "0.2.0-dev.foundations.4")
        self.assertEqual(len(self.metrics.metrics), 25)
        self.assertEqual({r.category for r in policy.categories if r.zero_tolerance}, REQUIRED_ZERO_TOLERANCE)
        self.assertEqual({m.safety_category for m in self.metrics.metrics if m.gate.value == "zero_tolerance"},
                         REQUIRED_ZERO_TOLERANCE)

    def test_v2_inventory_and_carried_over_fields(self):
        expected = ({m: 1 for m in V2_UNCHANGED} | {m: 2 for m in V2_REVISED} | {m: 1 for m in V2_NEW})
        self.assertEqual({m.id: m.version for m in self.metrics.metrics}, expected)
        old = {m["id"]: m for m in self.v1["metric_definitions"]["metrics"]}
        new = {m["id"]: m for m in self.v2["metric_definitions"]["metrics"]}
        for mid in V2_UNCHANGED:
            with self.subTest(unchanged=mid):
                self.assertEqual(new[mid], old[mid])
        for mid in V2_REVISED:
            with self.subTest(revised=mid):
                # Only the text changed: unit, gate, comparison, run kinds, component and category are v1's.
                strip = lambda d: {k: v for k, v in d.items() if k not in _TEXT_FIELDS}  # noqa: E731
                self.assertEqual(strip(new[mid]), strip(old[mid]))
                self.assertNotEqual(new[mid]["description"], old[mid]["description"])

    def test_new_metrics_carry_exact_flags_and_no_threshold(self):
        defs = {m.id: m for m in self.metrics.metrics}
        for mid, (unit, gate, comparison, component, kinds) in V2_NEW.items():
            m = defs[mid]
            with self.subTest(metric=mid):
                self.assertEqual((m.family.value, m.unit, m.gate.value, m.comparison.value,
                                  m.requires_component.value if m.requires_component else None,
                                  tuple(k.value for k in m.applicable_run_kinds)),
                                 ("outcome", unit, gate, comparison, component, kinds))
        self.assertNotIn("threshold", {k for m in self.v2["metric_definitions"]["metrics"] for k in m})
        required = {(m.id, m.version, m.comparison.value) for m in self.metrics.metrics
                    if m.comparison.value.startswith("required")}
        self.assertEqual(required, {("eligibility_label_correctness", 2, "required_observed"),
                                    ("unknown_state_preservation", 2, "required_observed"),
                                    ("verification_detection_recall", 2, "required_if_applicable"),
                                    ("verification_false_alarm_rate", 2, "required_if_applicable")})

    def test_v2_policy_equals_v1_except_identity(self):
        p1, p2 = self.v1["safety_gate_policy"], self.v2["safety_gate_policy"]
        self.assertEqual(p2, {**p1, "version": 2, "definitions": {"id": "evaldefs_metrics", "version": 2}})
        policy = SafetyGatePolicy.model_validate(p2)
        # The pins are the authoritative committed manifests: preserved, not repinned (F3 is not part of PR-A).
        self.assertEqual(policy.golden_manifest, pin_manifest(H.manifest_of(H.split_doc(Split.GOLDEN))))
        self.assertEqual(policy.held_out_manifest, pin_manifest(H.manifest_of(H.split_doc(Split.HELD_OUT))))

    def test_v2_rubric_is_v1_unchanged(self):
        self.assertEqual(self.v2["reviewer_rubric"], self.v1["reviewer_rubric"])
        rubric = ReviewerRubric.model_validate(self.v2["reviewer_rubric"])
        self.assertEqual((rubric.id, rubric.version, rubric.min_independent_reviewers, rubric.disagreement_policy.value),
                         ("rubric_reviewer_usefulness", 1, 2, "third_reviewer"))

    def test_v2_contains_no_adjudication_or_run_records(self):
        for marker in ('"id": "adjudication_', '"raw_labels"', '"final_labels"', '"adjudicated"', "evalrun_",
                       '"observations"', "comparison_", "promotion_"):
            with self.subTest(marker=marker):
                self.assertNotIn(marker, self.v2_text)

    def test_existing_validators_still_reject_malformed_v2(self):
        """Reconfirmation only: these are the unchanged v1 validators applied to v2 data."""
        doc = copy.deepcopy(self.v2["metric_definitions"])
        doc["metrics"].append(copy.deepcopy(doc["metrics"][0]))
        with self.assertRaises(ValidationError):
            MetricDefinitionSet.model_validate(doc)
        doc = copy.deepcopy(self.v2["metric_definitions"])
        doc["metrics"][0]["unit"] = "percent"
        with self.assertRaises(ValidationError):
            MetricDefinitionSet.model_validate(doc)
        latency = next(m for m in self.metrics.metrics if m.id == "latency_p50")
        wrong_kind = _METRIC_VALUE.validate_python({"kind": "count", "metric_id": "latency_p50", "metric_version": 1,
                                                    "status": "not_measured"})
        with self.assertRaises(ContractViolation) as ctx:
            check_metric_value(wrong_kind, latency, EvaluationRun.model_validate(run_payload()))
        self.assertEqual(ctx.exception.code, "metric_kind_mismatch")

    def test_v1_definitions_remain_default_and_unchanged(self):
        import hashlib
        self.assertEqual(H.DEFINITIONS_FILE, "evaluation-definitions-v0.2.0-dev.json")
        digest = hashlib.sha256((H.FIXTURE_DIR / H.DEFINITIONS_FILE).read_bytes()).hexdigest()
        self.assertEqual(digest, V1_DEFINITIONS_SHA256)
        self.assertEqual((self.v1["metric_definitions"]["version"], self.v1["safety_gate_policy"]["version"]), (1, 1))

    def test_integrated_review_metrics_report_not_measured_without_review_evidence(self):
        """D5: generating run kinds do not establish integrated review. Without genuine review evidence the
        only honest value is ``not_measured``; claiming ``not_applicable`` for the run kind is rejected.
        Accepting ``not_measured`` is not evidence that any review or measurement exists."""
        import test_promotion_gates as G
        run = G.run(kind="deterministic_baseline", components=("eligibility", "recommendation"),
                    definitions=DefinitionsPin(id="evaldefs_metrics", version=2),
                    safety_policy=DefinitionsPin(id="evaldefs_safety_gate", version=2))
        defs = {m.id: m for m in self.metrics.metrics}
        for mid, kind in (("reviewer_correction_rate", "ratio"), ("review_elapsed_time_p50", "duration")):
            extra = {"statistic": "p50"} if kind == "duration" else {}
            base = {"kind": kind, "metric_id": mid, "metric_version": 1, **extra}
            with self.subTest(metric=mid):
                check_metric_value(_METRIC_VALUE.validate_python({**base, "status": "not_measured"}), defs[mid], run)
                with self.assertRaises(ContractViolation) as ctx:
                    check_metric_value(_METRIC_VALUE.validate_python(
                        {**base, "status": "not_applicable", "not_applicable_reason": "run_kind_not_applicable"}),
                        defs[mid], run)
                self.assertEqual(ctx.exception.code, "unjustified_not_applicable")


if __name__ == "__main__":
    unittest.main()
