"""S0-R4: the existing wrapper is the validation API (pre-evaluation and post-check), and post-check
failures are engine defects (``Errored``), never refusals. Owner qualification 6: a schema-valid but
semantically unsupported outcome demonstrates the post-check; an invalid reason code fails earlier,
at model construction, and is classified separately.
"""

import ast
import unittest
from pathlib import Path
from types import MappingProxyType
from unittest import mock

from rap_contracts.eligibility import RuleOutcome, check_eligibility_result
from rap_contracts.recommendation import RecommendationContext, validate_recommendation_inputs

from builders import ANA, BEN, DATA, OPS, WEB, StubAuthority, World, run
from rap_baseline import Assessed, Errored, Stage, assess, engine, rules

PACKAGE = Path(engine.__file__).resolve().parent


class WrapperUseTests(unittest.TestCase):
    def test_wrapper_called_twice_with_empty_then_produced_results(self):
        w = World()
        ctx, caps = w.build()
        spy = mock.Mock(wraps=validate_recommendation_inputs)
        with mock.patch.object(engine, "validate_recommendation_inputs", spy):
            out = assess(w.request(), ctx, StubAuthority(), caps)
        self.assertIsInstance(out, Assessed)
        self.assertEqual(spy.call_count, 2)
        first, second = (c.args[0] for c in spy.call_args_list)
        for rctx in (first, second):
            self.assertIsInstance(rctx, RecommendationContext)
            self.assertIsInstance(rctx.eligibility_results, MappingProxyType)
            self.assertIs(rctx.capabilities, caps)
        self.assertEqual(dict(first.eligibility_results), {})
        self.assertEqual(dict(second.eligibility_results), {out.result.id: out.result})
        self.assertIs(first.eligibility, second.eligibility)
        self.assertEqual(first.eligibility.policies[0].id, "policy_s1_pilot")

    def test_verdict_on_projection_equals_verdict_on_full_context(self):
        for cand, opp in ((ANA, DATA), (ANA, OPS), (ANA, WEB), (BEN, DATA)):
            with self.subTest(cand=cand, opp=opp):
                w = World()
                out, _ = run(w, cand, opp)
                ctx, caps = w.build()
                check_eligibility_result(out.result, ctx)
                validate_recommendation_inputs(RecommendationContext(
                    eligibility=ctx, eligibility_results={out.result.id: out.result}, capabilities=caps))

    def test_no_new_validation_api_is_defined(self):
        for path in sorted(PACKAGE.glob("*.py")):
            names = {n.name for n in ast.walk(ast.parse(path.read_text(encoding="utf-8"))) if isinstance(n, ast.FunctionDef)}
            with self.subTest(path.name):
                self.assertEqual({n for n in names if n.startswith(("check_", "validate_"))}, set())


def unsupported_availability(d):
    """Schema-valid (reason is legal for kind/result) but unsupported: a pass citing no hours or requirement."""
    outcomes = list(REAL_EVALUATE(d))
    for i, o in enumerate(outcomes):
        if o.rule_id == "S1-AVAIL-003":
            outcomes[i] = o.model_copy(update={"claim_ids": (), "requirement_ids": ()})
    return tuple(outcomes)


def cites_other_candidate(d):
    outcomes = list(REAL_EVALUATE(d))
    for i, o in enumerate(outcomes):
        if o.rule_id == "S1-AVAIL-003":
            outcomes[i] = o.model_copy(update={"claim_ids": ("claim_s1_ben_hours",)})
    return tuple(outcomes)


def invalid_reason(d):
    rule = d.policy.rules[0]
    return (RuleOutcome(rule_id=rule.rule_id, rule_version=rule.rule_version, rule_kind=rule.kind, result="fail",
                        reason_code="opportunity_active"),)


REAL_EVALUATE = rules.evaluate


class PostCheckFailureTests(unittest.TestCase):
    def errored(self, replacement, **kw):
        w = World()
        ctx, caps = w.build()
        with mock.patch.object(rules, "evaluate", replacement):
            out = assess(w.request(), ctx, StubAuthority(), caps)
        self.assertIsInstance(out, Errored, str(out))
        self.assertFalse(hasattr(out, "result"))
        return out

    def test_schema_valid_but_unsupported_outcome_fails_the_post_check(self):
        # The replacement outcome is constructible, i.e. schema-valid:
        RuleOutcome.model_validate({"rule_id": "S1-AVAIL-003", "rule_version": 1, "result": "pass",
                                    "rule_kind": "availability_meets_required_hours",
                                    "reason_code": "availability_meets_required_hours"})
        out = self.errored(unsupported_availability)
        self.assertEqual((out.stage, out.code), (Stage.POST_CHECK, "post_check_failed"))
        self.assertIn("unsupported_outcome", out.detail)

    def test_citing_another_candidates_claim_fails_the_post_check(self):
        out = self.errored(cites_other_candidate)
        self.assertEqual((out.stage, out.code), (Stage.POST_CHECK, "post_check_failed"))
        self.assertIn("invalid_citation", out.detail)

    def test_invalid_reason_code_fails_at_construction_not_post_check(self):
        out = self.errored(invalid_reason)
        self.assertEqual((out.stage, out.code), (Stage.RESULT, "result_construction_failed"))

    def test_rule_evaluation_defect_is_errored(self):
        def broken(d):
            raise rules.RuleEvaluationError("synthetic defect")
        out = self.errored(broken)
        self.assertEqual((out.stage, out.code), (Stage.RESULT, "rule_evaluation_failed"))

    def test_ungated_dependency_fails_the_provenance_check(self):
        w = World()
        ctx, caps = w.build()
        real = engine.gate_refs
        drop = lambda p, t: tuple(r for r in real(p, t) if r.entity.entity_type != "program_enrollment")  # noqa: E731
        with mock.patch.object(engine, "gate_refs", drop):
            out = assess(w.request(), ctx, StubAuthority(), caps)
        self.assertIsInstance(out, Errored)
        self.assertEqual((out.stage, out.code), (Stage.POST_CHECK, "provenance_not_gated"))


class UnexpectedPostCheckErrorTests(unittest.TestCase):
    """R2: an unexpected exception in P10 or provenance construction is ``Errored`` -- never an escaped
    exception and never a partial ``Assessed``."""

    def assess_with(self, target, attribute, replacement):
        w = World()
        ctx, caps = w.build()
        with mock.patch.object(target, attribute, replacement):
            try:
                return assess(w.request(), ctx, StubAuthority(), caps)
            except Exception as exc:  # noqa: BLE001 - the boundary under test
                self.fail(f"exception escaped the three-outcome boundary: {type(exc).__name__}")

    def assert_errored(self, out, stage):
        self.assertIsInstance(out, Errored, str(out))
        self.assertNotIsInstance(out, Assessed)
        self.assertFalse(hasattr(out, "result") or hasattr(out, "provenance"))
        self.assertEqual((out.stage, out.code), (stage, "unexpected_exception"))
        self.assertGreater(out.authority_calls, 0)

    def test_unexpected_exception_in_post_check_wrapper(self):
        def post_check_crashes(rctx):
            if rctx.eligibility_results:
                raise RuntimeError("synthetic post-check crash")
            return validate_recommendation_inputs(rctx)
        out = self.assess_with(engine, "validate_recommendation_inputs", post_check_crashes)
        self.assert_errored(out, Stage.POST_CHECK)
        self.assertIn("RuntimeError", out.detail)

    def test_unexpected_exception_in_dependency_collection(self):
        def crashes(result, ctx):
            raise KeyError("synthetic missing dependency record")
        self.assert_errored(self.assess_with(engine, "eligibility_source_refs", crashes), Stage.POST_CHECK)

    def test_unexpected_exception_in_output_digest(self):
        def crashes(result):
            raise ValueError("synthetic digest failure")
        self.assert_errored(self.assess_with(engine, "output_digest", crashes), Stage.PROVENANCE)

    def test_unexpected_exception_in_provenance_record(self):
        def crashes(**kwargs):
            raise TypeError("synthetic provenance failure")
        self.assert_errored(self.assess_with(engine, "AssessmentProvenance", crashes), Stage.PROVENANCE)

    def test_specific_post_check_codes_are_preserved(self):
        """The generic handler does not swallow the specific ContractViolation / provenance classifications."""
        out = self.assess_with(rules, "evaluate", unsupported_availability)
        self.assertEqual((out.stage, out.code), (Stage.POST_CHECK, "post_check_failed"))
        real = engine.gate_refs
        drop = lambda p, t: tuple(r for r in real(p, t) if r.entity.entity_type != "program_enrollment")  # noqa: E731
        out = self.assess_with(engine, "gate_refs", drop)
        self.assertEqual((out.stage, out.code), (Stage.POST_CHECK, "provenance_not_gated"))


class DefenceInDepthTests(unittest.TestCase):
    """If phase-2 validation were bypassed, contradictory inputs still never become an outcome."""

    def bypass_phase2(self, world):
        ctx, caps = world.build()

        def only_post_check(rctx):
            if rctx.eligibility_results:
                return validate_recommendation_inputs(rctx)
            return None  # simulated defect: pre-evaluation validation skipped

        with mock.patch.object(engine, "validate_recommendation_inputs", only_post_check):
            return assess(world.request(), ctx, StubAuthority(), caps)

    def assert_rule_defence(self, world):
        out = self.bypass_phase2(world)
        self.assertIsInstance(out, Errored, str(out))
        self.assertEqual((out.stage, out.code), (Stage.RESULT, "rule_evaluation_failed"))

    def test_conflicting_participation_records(self):
        w = World()
        w.add_participation("participation_s1_ana_conflict", ANA, "program_s1_pathways", "not_participating", "6141", "71")
        self.assert_rule_defence(w)

    def test_conflicting_declared_hours(self):
        w = World()
        w.add_statement(ANA, "evidence_s1_ana_hours_app", "answers.weekly_hours", source="application")
        w.add_claim("claim_s1_ana_hours_app", ANA, None, "declared", {"kind": "availability", "hours_per_week": 3},
                    ["evidence_s1_ana_hours_app"])
        self.assert_rule_defence(w)

    def test_conflicting_declared_skills(self):
        w = World()
        w.add_statement(ANA, "evidence_s1_ana_python_no", "answers.python_screening", source="application")
        w.add_claim("claim_s1_ana_python_no", ANA, "python", "declared", {"kind": "skill", "presence": "lacks"},
                    ["evidence_s1_ana_python_no"])
        self.assert_rule_defence(w)


if __name__ == "__main__":
    unittest.main()
