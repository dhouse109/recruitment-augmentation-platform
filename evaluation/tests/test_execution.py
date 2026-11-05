"""Phase 2 execution: the real engine on the four selected cases, the section 2.1 workflow, execution-phase
injections, label blindness (B9) and runner failures (exit 4)."""

from __future__ import annotations

import dataclasses
import unittest
from unittest import mock

from helpers import AS_OF, LazyClassFixture, TempDirTest, admitted, case_doc, config, products, tampered
from rap_baseline import Assessed, Errored, Refused, Stage, assess
from rap_contracts.eligibility import EligibilityDecision
from rap_contracts.evaluation import AuthorityOverride, EvaluationCase, ObservationBasis, StepStatus
from rap_contracts.models import AccessStatus, VersionStatus

from rap_evaluation import RunnerFailure, execute
from rap_evaluation.admission import admit
from rap_evaluation.execute import execute_case
from rap_evaluation.run import produce, run_evaluation
from rap_evaluation.scope import LABEL_KEY_FIELDS

SELECTED = ("evalcase_g002", "evalcase_g003", "evalcase_g008", "evalcase_g025")
T3, T2 = ObservationBasis.DETERMINISTIC_BASELINE_EXECUTION, ObservationBasis.REFERENCE_VALIDATOR


def by_case(p):
    return {o.case_id: o for o in p.observations}


class RealExecutionTests(LazyClassFixture):
    """B2 and B7: what the unmodified engine produced on the pinned golden inputs (recorded, not asserted correct)."""

    @classmethod
    def _fixture(cls):
        cls.p = products()
        cls.obs = by_case(cls.p)

    def test_four_cases_executed_twenty_two_not_run(self):
        executed = [o.case_id for o in self.p.observations if o.execution_status == "executed"]
        self.assertEqual(tuple(executed), SELECTED)
        self.assertEqual(sum(o.execution_status == "not_run" for o in self.p.observations), 22)

    def test_step_bases_and_generated_ids(self):
        for cid in SELECTED:
            for s in self.obs[cid].steps:
                if s.operation.value == "eligibility_support":
                    self.assertIs(s.basis, T3)
                    self.assertTrue(s.observed.eligibility_result_id.startswith("eligibility_"))
                else:
                    self.assertIs(s.basis, T2)
                    self.assertIsNone(s.observed.eligibility_result_id)

    def test_observed_label_agreement_is_recorded(self):
        """Observed outcome on the reference as_of: every step agrees with its proposed label (not correctness)."""
        statuses = {(cid, s.step_id): s.status for cid in SELECTED for s in self.obs[cid].steps}
        self.assertEqual(set(statuses.values()), {StepStatus.MATCHED}, statuses)
        self.assertEqual({self.obs[c].outcome.value for c in SELECTED}, {"pass"})

    def test_shared_keys_produce_identical_results(self):
        ids = {(e.case_id, e.step_id): e.result.id for e in self.p.entries}
        # F3 (golden v2): g002 (B x web) and g008 (G x data) are separate assessments.
        self.assertNotEqual(ids[("evalcase_g002", "s1")], ids[("evalcase_g008", "s1")])
        self.assertEqual(ids[("evalcase_g003", "s1")], ids[("evalcase_g025", "s2")])  # A x ops, by design (not F3)
        self.assertNotEqual(ids[("evalcase_g025", "s2")], ids[("evalcase_g025", "s3")])
        self.assertEqual(len(set(ids.values())), 4)

    def test_generated_ids_never_equal_label_ids(self):
        labels = admitted().graph.label_ids
        self.assertFalse({e.result.id for e in self.p.entries} & labels)

    def test_engine_is_invoked_once_per_engine_step_without_caching(self):
        calls = []

        def counting(*args):
            calls.append(args[0])
            return assess(*args)
        products(assess_fn=counting)
        self.assertEqual(len(calls), 5)


class WorkflowOrderTests(unittest.TestCase):
    """B2: assess -> check_eligibility_result on the GENERATED result (full scope) -> compare, for every engine step."""

    def test_order_and_objects(self):
        events = []
        returned = {}

        def engine(request, context, authority, capabilities):
            out = assess(request, context, authority, capabilities)
            events.append(("assess", request.candidate_id, request.opportunity_id))
            returned[id(out.result)] = out.result
            return out

        real_check, real_compare = execute.check_eligibility_result, execute.compare

        def check(result, ctx):
            self.assertIn(id(result), returned, "the validator must receive the engine's generated result object")
            self.assertTrue(any(ctx is s.eligibility for s in admitted().scopes.values()), "full admitted scope expected")
            events.append(("check", result.candidate_id, result.opportunity_id))
            return real_check(result, ctx)

        def compare(step, observed):
            events.append(("compare", step.eligibility_result_id, observed.eligibility_result_id))
            return real_compare(step, observed)

        with mock.patch.object(execute, "check_eligibility_result", side_effect=check), \
                mock.patch.object(execute, "compare", side_effect=compare):
            products(assess_fn=engine)
        kinds = [e[0] for e in events]
        self.assertEqual(kinds, ["assess", "check", "compare"] * 5)


class ExecutionInjectionTests(unittest.TestCase):
    """Execution-phase observations on synthetic in-memory copies of admitted inputs (plan section 8)."""

    def case(self, case_id: str, mutate=None) -> EvaluationCase:
        adm = admitted()
        doc = next(c for c in adm.selected if c.id == case_id).model_dump(mode="json")
        if mutate:
            mutate(doc)
        return EvaluationCase.model_validate(doc)

    def run_case(self, case, scope=None, assess_fn=None):
        adm = admitted()
        return execute_case(case, scope or adm.scopes[case.id], adm.keys, adm.principals[case.id], AS_OF,
                            "evalrun_test", assess_fn)

    def opportunity_ref(self, case_id: str, opp: str):
        s = admitted().scopes[case_id]
        return next(o.source_ref for o in s.eligibility.records.opportunities if o.id == opp)

    def override(self, case_id, opp, version, access):
        ref = self.opportunity_ref(case_id, opp)

        def mutate(doc):
            doc["initial_state"]["authority"]["overrides"] = [AuthorityOverride(
                principal_id="principal_demo_coordinator", source_ref=ref, version_status=version,
                access_status=access).model_dump(mode="json")]
        return mutate

    def test_superseded_gated_source_is_an_engine_refusal(self):
        ex = self.run_case(self.case("evalcase_g003", self.override("evalcase_g003", "opportunity_demo_ops",
                                                                    VersionStatus.SUPERSEDED, AccessStatus.ALLOWED)))
        s = ex.observation.steps[0]
        self.assertEqual((s.status, s.observed.error_type, ex.observation.outcome.value),
                         (StepStatus.ERRORED, "engine_refused", "fail"))
        self.assertIsNone(s.observed.eligibility_result_id)
        self.assertEqual(ex.entries[0].refusal["stage"], "source_gate")
        self.assertIsNone(ex.entries[0].result)

    def test_withdrawn_source_is_an_engine_refusal(self):
        ex = self.run_case(self.case("evalcase_g003", self.override("evalcase_g003", "opportunity_demo_ops",
                                                                    VersionStatus.WITHDRAWN, AccessStatus.ALLOWED)))
        self.assertEqual(ex.observation.steps[0].observed.error_type, "engine_refused")

    def test_denied_principal_is_an_engine_refusal(self):
        # F3: g002 assesses opportunity_demo_web (B x web).
        ex = self.run_case(self.case("evalcase_g002", self.override("evalcase_g002", "opportunity_demo_web",
                                                                    VersionStatus.CURRENT, AccessStatus.DENIED)))
        s = ex.observation.steps[0]
        self.assertEqual((s.status, s.observed.error_type), (StepStatus.ERRORED, "engine_refused"))
        self.assertEqual(ex.entries[0].refusal["stage"], "source_gate")

    def test_removed_participation_is_assessed_and_mismatched(self):
        adm = admitted()
        s = adm.scopes["evalcase_g003"]
        scope = dataclasses.replace(s, eligibility=dataclasses.replace(s.eligibility, participations=()))
        ex = self.run_case(self.case("evalcase_g003"), scope=scope)
        step = ex.observation.steps[0]
        self.assertEqual((step.status, ex.observation.outcome.value), (StepStatus.MISMATCHED, "fail"))
        program = next(r for r in step.observed.rule_outcomes if r.rule_id == "PILOT-PROGRAM-002")
        self.assertNotEqual(program.result.value, "pass")
        self.assertIsNotNone(step.observed.eligibility_result_id)

    def test_injected_engine_error_is_an_errored_observation(self):
        ex = self.run_case(self.case("evalcase_g003"), assess_fn=lambda *a: Errored(Stage.RESULT, "rule_evaluation_failed", "x", 0))
        s = ex.observation.steps[0]
        self.assertEqual((s.status, s.observed.error_type, ex.observation.outcome.value),
                         (StepStatus.ERRORED, "engine_errored", "fail"))
        self.assertEqual(ex.entries[0].refusal, {"stage": "result", "code": "rule_evaluation_failed", "authority_calls": 0})

    def test_refusal_is_never_mapped_to_a_validator_violation(self):
        ex = self.run_case(self.case("evalcase_g003"), assess_fn=lambda *a: Refused(Stage.SOURCE_GATE, "source_denied", "x", 1))
        s = ex.observation.steps[0]
        self.assertIsNone(s.observed.result)
        self.assertIsNone(s.observed.violation_code)
        self.assertEqual(s.observed.error_type, "engine_refused")

    def test_prerequisite_mismatch_is_inconclusive_and_runs_no_engine(self):
        def mutate(doc):
            doc["steps"][0]["expected"] = {"result": "violation", "violation_code": "unknown_reference"}
        calls = []
        ex = self.run_case(self.case("evalcase_g025", mutate), assess_fn=lambda *a: calls.append(a))
        self.assertEqual([s.status for s in ex.observation.steps],
                         [StepStatus.MISMATCHED, StepStatus.NOT_EVALUATED, StepStatus.NOT_EVALUATED])
        self.assertEqual(ex.observation.outcome.value, "inconclusive")
        self.assertEqual((calls, ex.entries), ([], []))

    def test_altered_expectation_is_mismatched_and_not_corrected(self):
        def mutate(doc):
            doc["steps"][0]["expected"]["decision"] = "eligible"
        case = self.case("evalcase_g003", mutate)
        ex = self.run_case(case)
        s = ex.observation.steps[0]
        self.assertEqual((s.status, ex.observation.outcome.value), (StepStatus.MISMATCHED, "fail"))
        self.assertEqual(case.steps[0].expected.decision.value, "eligible")  # the label is not corrected
        self.assertEqual(s.observed.decision.value, "ineligible")

    def test_altered_rule_outcome_expectation_is_mismatched(self):
        def mutate(doc):
            rule = next(r for r in doc["steps"][0]["expected"]["rule_outcomes"] if r["rule_id"] == "PILOT-AVAIL-003")
            rule["reason_code"] = "availability_below_required_hours"
            rule["result"] = "fail"
        ex = self.run_case(self.case("evalcase_g003", mutate))
        s = ex.observation.steps[0]
        self.assertEqual(s.observed.decision.value, "ineligible")  # same decision as the label
        self.assertEqual((s.status, ex.observation.outcome.value), (StepStatus.MISMATCHED, "fail"))


class LabelBlindnessTests(LazyClassFixture):
    """B9: the engine never receives a label; flipping labels changes no generated byte."""

    @classmethod
    def _fixture(cls):
        cls.base = products()
        cls.base_bytes = {(e.case_id, e.step_id): execute.result_json(e.result) for e in cls.base.entries}

    def test_flipping_label_records_changes_no_generated_byte_and_no_status(self):
        def flip(layers):
            for r in layers["eligibility-evidence-v0.2.0-dev.json"]["eligibility_results"]:
                r["decision"] = "eligible" if r["decision"] != "eligible" else "ineligible"
                r["rule_outcomes"] = list(reversed(r["rule_outcomes"]))
                r["evaluated_at"] = "2020-01-01T00:00:00Z"
        with tampered(layers=flip):
            adm = admit(config("/nonexistent/flip"))
        p = products(adm=adm)
        self.assertEqual({(e.case_id, e.step_id): execute.result_json(e.result) for e in p.entries}, self.base_bytes)
        self.assertEqual([o.model_dump(exclude={"run_id"}) for o in p.observations],
                         [o.model_dump(exclude={"run_id"}) for o in self.base.observations])

    def test_flipping_expectations_changes_only_match_statuses(self):
        def flip(golden):
            for cid in SELECTED:
                for step in case_doc(golden, cid)["steps"]:
                    if step["operation"] == "eligibility_support":
                        step["expected"]["decision"] = "eligible" if step["expected"]["decision"] != "eligible" else "ineligible"
        with tampered(golden=flip):
            adm = admit(config("/nonexistent/flip2"))
        p = products(adm=adm)
        self.assertEqual({(e.case_id, e.step_id): execute.result_json(e.result) for e in p.entries}, self.base_bytes)
        engine_steps = [s for o in p.observations for s in o.steps if s.basis is T3]
        self.assertEqual({s.status for s in engine_steps}, {StepStatus.MISMATCHED})

    def test_label_records_are_read_only_through_their_key_fields(self):
        accessed: dict[str, set] = {}

        class Spy(dict):
            def __getitem__(self, k):
                accessed.setdefault(dict.__getitem__(self, "id"), set()).add(k)
                return dict.__getitem__(self, k)

            def get(self, k, default=None):
                accessed.setdefault(dict.__getitem__(self, "id"), set()).add(k)
                return dict.get(self, k, default)

            def items(self):
                accessed.setdefault(dict.__getitem__(self, "id"), set()).add("*items")
                return dict.items(self)

            def values(self):
                accessed.setdefault(dict.__getitem__(self, "id"), set()).add("*values")
                return dict.values(self)

        # F3 (R37): spy on BOTH label sources -- the base layer and the golden case-local labels -- so an
        # unauthorized read of a case-local label field is detected. The spy only records; it never raises, so
        # a violation fails an assertion rather than erroring.
        def spy_layers(layers):
            rs = layers["eligibility-evidence-v0.2.0-dev.json"]["eligibility_results"]
            rs[:] = [Spy(r) for r in rs]

        def spy_case_records(golden):
            rs = golden["case_records"]["eligibility_results"]
            rs[:] = [Spy(r) for r in rs]
        with tampered(layers=spy_layers, golden=spy_case_records):
            adm = admit(config("/nonexistent/spy"))
            products(adm=adm)
        golden_labels = {rid for (kind, rid), owner in adm.graph.owners.items()
                         if kind == "eligibility_results" and owner in adm.graph.golden_candidates}
        self.assertTrue({"eligibility_b_web", "eligibility_g_data", "eligibility_a_ops", "eligibility_a_web"} <= golden_labels)
        for label in golden_labels & set(accessed):
            self.assertLessEqual(accessed[label], set(LABEL_KEY_FIELDS), label)
        # Every selected step's label went through the A7 key projection (not merely the ownership pass, which
        # reads only id and candidate_id). Both case-local labels must be among them.
        for label in ("eligibility_b_web", "eligibility_g_data", "eligibility_a_ops", "eligibility_a_web"):
            self.assertLessEqual({"organization_id", "opportunity_id", "policy"}, accessed.get(label, set()), label)

    def test_request_is_built_from_the_key_and_the_engine_receives_no_label(self):
        seen = []

        def engine(request, context, authority, capabilities):
            seen.append((request, context, capabilities))
            return assess(request, context, authority, capabilities)
        products(assess_fn=engine)
        adm = admitted()
        keys = [adm.keys[(cid, s.step_id)] for cid in SELECTED for s in next(c for c in adm.selected if c.id == cid).steps
                if s.operation == "eligibility_support"]
        self.assertEqual(len(seen), len(keys))
        for (request, context, caps), key in zip(seen, keys):
            self.assertEqual(set(type(request).model_fields), {"organization_id", "candidate_id", "opportunity_id",
                                                               "policy", "principal_id", "as_of"})
            self.assertEqual((request.organization_id, request.candidate_id, request.opportunity_id, request.policy),
                             (key.organization_id, key.candidate_id, key.opportunity_id, key.policy))
            self.assertEqual((request.principal_id, request.as_of), ("principal_demo_coordinator", AS_OF))
            self.assertFalse(hasattr(context, "results") or hasattr(context, "eligibility_results"))
            text = repr(request) + repr(context) + repr(caps)
            for label in adm.graph.label_ids:
                self.assertNotIn(label, text)


class RunnerFailureTests(TempDirTest):
    def test_unexpected_exception_after_admission_exits_4_with_nothing_published(self):
        out = self.tmp / "o" / "run"

        def boom(*a):
            raise RuntimeError("synthetic")
        with self.assertRaises(RunnerFailure) as cm:
            run_evaluation(config(out), assess_fn=boom)
        self.assertEqual(cm.exception.code, "unexpected_runner_exception")
        self.assertNothingPublished(out)
        self.assertFalse((self.tmp / "o").exists())

    def test_in_run_inconsistency_is_a_runner_failure(self):
        seen = set()

        def drifting(request, context, authority, capabilities):
            out = assess(request, context, authority, capabilities)
            key = (request.candidate_id, request.opportunity_id)
            if key in seen and isinstance(out, Assessed):
                out = dataclasses.replace(out, result=out.result.model_copy(update={"decision": EligibilityDecision.ELIGIBLE}))
            seen.add(key)
            return out
        with self.assertRaises(RunnerFailure) as cm:
            produce(config(self.tmp / "unused"), admitted(), "evalrun_x", drifting)
        self.assertEqual(cm.exception.code, "in_run_inconsistency")

    def test_non_engine_outcome_is_a_runner_failure(self):
        with self.assertRaises(RunnerFailure):
            produce(config(self.tmp / "unused"), admitted(), "evalrun_x", lambda *a: "not an outcome")


if __name__ == "__main__":
    unittest.main()
