"""D-004.12 / ADR-0003 -- safety-gate coverage and strict promotion semantics.

Two kinds of input are used:

* the REAL fixture-conformance observations (tier T2), which must always
  produce ``insufficient_evidence``; and
* in-memory SYNTHETIC observations labelled with T3/T4 bases, used only to
  exercise the pure gate logic. They are not measurements, are never
  committed, and say nothing about any real system.
"""

import copy
import unittest

from pydantic import ValidationError

import eval_harness as H
from rap_contracts.evaluation import (
    CaseObservation,
    CaseOutcome,
    CodeRevision,
    DefinitionsPin,
    EvaluationRun,
    HeldOutIntegrity,
    Measurement,
    NOT_APPLICABLE,
    ObservedRecord,
    SafetyObservation,
    Split,
    StepObservation,
    pin_manifest,
)
from rap_contracts.invariants import ContractViolation
from rap_contracts.promotion import (
    GateResult,
    HeldOutGateAttestation,
    PromotionDecision,
    SafetyGatePolicy,
    check_promotion_inputs,
    evaluate_safety_gate,
)

DEFS = H.load(H.DEFINITIONS_FILE)
GOLDEN_PIN = pin_manifest(H.manifest_of(H.split_doc(Split.GOLDEN)))
HELD_PIN = pin_manifest(H.manifest_of(H.split_doc(Split.HELD_OUT)))
TRUSTED = {"principal_id": "principal_example_custodian", "asserted_kind": "human", "asserted_role": "custodian",
           "attestation_basis": "trusted_service_authenticated"}
DECIDER = {"principal_id": "principal_demo_owner", "asserted_kind": "human", "asserted_role": "project_owner",
           "attestation_basis": "trusted_service_authenticated"}
MEASURE = dict(latency=Measurement(status="not_measured", unit="milliseconds"), cost=Measurement(status="not_applicable", unit="usd"))


def policy(status="approved"):
    return SafetyGatePolicy.model_validate({**DEFS["safety_gate_policy"], "status": status})


def run(rid="evalrun_candidate_1", kind="deterministic_baseline", purpose="promotion_assessment", **update):
    payload = dict(
        id=rid, run_kind=kind, purpose=purpose, manifests=(GOLDEN_PIN, HELD_PIN),
        definitions=DefinitionsPin(id="evaldefs_metrics", version=1),
        safety_policy=DefinitionsPin(id="evaldefs_safety_gate", version=1),
        contract_version="0.2.0-dev.foundations.4",
        code_revision=CodeRevision(status="recorded", commit="b" * 40, dirty=False) if purpose == "promotion_assessment"
        else CodeRevision(status="unavailable"),
        source_authority="drupal" if kind != "fixture_conformance" else "fixture_mock",
        retrieval_index=NOT_APPLICABLE, prompt=NOT_APPLICABLE, model=NOT_APPLICABLE, judge=NOT_APPLICABLE,
        replicates=1, started_at="2026-10-28T20:00:00Z", completed_at="2026-10-28T20:10:00Z", status="completed",
        executed_by="example-runner/0", **MEASURE)
    payload.update(update)
    return EvaluationRun.model_validate(payload)


def synthetic_observations(pol, run_id, basis="integrated_service", outcome="pass", disposition="attempt_blocked",
                           skip=(), extra=()):
    """One SYNTHETIC observation per mandatory golden case, covering every category that case is mandatory for."""
    cats_by_case = {}
    for rule in pol.categories:
        for ref in rule.mandatory_golden_cases:
            cats_by_case.setdefault(ref.case_id, []).append(rule.category)
    observations = []
    for case_id, cats in sorted(cats_by_case.items()):
        if case_id in skip:
            continue
        status = "matched" if outcome == "pass" else "mismatched"
        safety = tuple(SafetyObservation(category=c, exposure_point="model_context", disposition=disposition) for c in cats)
        step = StepObservation(step_id="s1", role="target", operation="retrieval_admission", status=status,
                               basis=basis, observed=ObservedRecord(), safety=safety)
        observations.append(CaseObservation(run_id=run_id, case_id=case_id, case_version=1, case_sha256="sha256:" + "0" * 64,
                                            split="golden", execution_status="executed", steps=(step,),
                                            outcome=outcome, **MEASURE))
    return observations + list(extra)


def attestation(pol, status="pass", custody="trusted_custodian", attested_by=TRUSTED, cases=1, violations=0):
    results = [{"category": r.category.value, "status": status, "cases_exercised": cases, "violations": violations}
               for r in pol.categories if r.held_out_coverage_required]
    return HeldOutGateAttestation.model_validate({
        "manifest": HELD_PIN.model_dump(mode="json"), "policy": {"id": pol.id, "version": pol.version},
        "run_id": "evalrun_held_out_custody", "results": results, "custody_basis": custody, "attested_by": attested_by,
        "attested_at": "2026-10-28T21:00:00Z"})


def gate(pol=None, r=None, obs=None, integrity=HeldOutIntegrity.CUSTODIED_UNEXPOSED, att="default"):
    pol = pol or policy()
    r = r or run()
    obs = synthetic_observations(pol, r.id) if obs is None else obs
    att = attestation(pol) if att == "default" else att
    return evaluate_safety_gate(pol, r, obs, integrity, att)


def status_of(result, category):
    return next(c for c in result.categories if c.category.value == category).status.value


class ConformanceEvidenceTests(unittest.TestCase):
    def test_real_conformance_observations_are_never_promotion_evidence(self):
        conformance = run("evalrun_conformance_local", kind="fixture_conformance", purpose="regression")
        observations = []
        for split in Split:
            doc = H.split_doc(split)
            observations += [H.run_case(c, doc, run_id=conformance.id).observation for c in H.cases_of(doc)]
        result = evaluate_safety_gate(policy(), conformance, observations, HeldOutIntegrity.NOMINAL_EXPOSED)
        self.assertIs(result.result, GateResult.INSUFFICIENT_EVIDENCE)
        self.assertIn("conformance_run_not_promotion_evidence", result.reasons)
        self.assertIn("run_not_promotion_assessment", result.reasons)
        # The same T2 observations, even under a promotion-shaped run, cannot satisfy any category.
        relabelled = [o.model_copy(update={"run_id": "evalrun_candidate_1"}) for o in observations]
        result = evaluate_safety_gate(policy(), run(), relabelled, HeldOutIntegrity.NOMINAL_EXPOSED)
        self.assertIs(result.result, GateResult.INSUFFICIENT_EVIDENCE)
        self.assertTrue(all(c.status.value in ("insufficient_evidence", "not_applicable") for c in result.categories))
        self.assertIn("basis_not_accepted", next(c for c in result.categories if c.category.value == "cross_org_access").reasons)


class GateCoverageTests(unittest.TestCase):
    def test_complete_synthetic_coverage_is_eligible_logic_only(self):
        self.assertIs(gate().result, GateResult.ELIGIBLE_FOR_HUMAN_DECISION)

    def test_coverage_gaps_are_insufficient(self):
        pol = policy()
        r = run()
        gaps = {
            "missing mandatory case": synthetic_observations(pol, r.id, skip=("evalcase_g011",)),
            "inconclusive mandatory case": [o.model_copy(update={"outcome": CaseOutcome.INCONCLUSIVE}) if o.case_id == "evalcase_g007" else o
                                            for o in synthetic_observations(pol, r.id)],
            "mismatched but blocked": synthetic_observations(pol, r.id, outcome="fail"),
            "not observable": synthetic_observations(pol, r.id, disposition="not_observable"),
            "not exercised": synthetic_observations(pol, r.id, disposition="not_exercised"),
            "mock-level basis": synthetic_observations(pol, r.id, basis="mock_authority"),
        }
        for name, obs in gaps.items():
            with self.subTest(name):
                self.assertIs(gate(pol, r, obs).result, GateResult.INSUFFICIENT_EVIDENCE)

    def test_offline_basis_satisfies_only_categories_that_accept_it(self):
        result = gate(obs=synthetic_observations(policy(), "evalrun_candidate_1", basis="deterministic_baseline_execution"))
        self.assertIs(result.result, GateResult.INSUFFICIENT_EVIDENCE)
        self.assertEqual(status_of(result, "hard_eligibility_violation"), "pass")
        self.assertEqual(status_of(result, "cross_org_access"), "insufficient_evidence")

    def test_pin_and_policy_mismatches_are_insufficient(self):
        self.assertIs(gate(pol=policy("draft")).result, GateResult.INSUFFICIENT_EVIDENCE)
        other = run(safety_policy=DefinitionsPin(id="evaldefs_safety_gate", version=2))
        self.assertIn("safety_policy_pin_mismatch", gate(r=other, obs=synthetic_observations(policy(), other.id)).reasons)
        moved = run(manifests=(GOLDEN_PIN.model_copy(update={"version": 2}), HELD_PIN))
        self.assertIn("golden_manifest_pin_mismatch", gate(r=moved, obs=synthetic_observations(policy(), moved.id)).reasons)

    def test_held_out_evidence_must_be_custodied_and_trusted(self):
        pol = policy()
        self.assertIs(gate(integrity=HeldOutIntegrity.NOMINAL_EXPOSED).result, GateResult.INSUFFICIENT_EVIDENCE)
        self.assertIs(gate(att=None).result, GateResult.INSUFFICIENT_EVIDENCE)
        self.assertIs(gate(att=attestation(pol, custody="unverified_declaration")).result, GateResult.INSUFFICIENT_EVIDENCE)
        self.assertIs(gate(att=attestation(pol, attested_by={**TRUSTED, "attestation_basis": "mock_authenticated"})).result,
                      GateResult.INSUFFICIENT_EVIDENCE)
        self.assertIs(gate(att=attestation(pol, cases=0)).result, GateResult.INSUFFICIENT_EVIDENCE)


class BlockingTests(unittest.TestCase):
    def violation(self, category, case_id="evalcase_example_extra"):
        step = StepObservation(step_id="s1", role="target", operation="retrieval_admission", status="mismatched",
                               basis="integrated_service", observed=ObservedRecord(),
                               safety=(SafetyObservation(category=category, exposure_point="model_context",
                                                         disposition="unblocked_violation"),))
        return CaseObservation(run_id="evalrun_candidate_1", case_id=case_id, case_version=1,
                               case_sha256="sha256:" + "0" * 64, split="golden", execution_status="executed",
                               steps=(step,), outcome="fail", **MEASURE)

    def test_any_zero_tolerance_violation_blocks_even_outside_mandatory_cases(self):
        for category in ("cross_org_access", "unauthorized_source_access", "stale_or_withdrawn_source",
                         "hard_eligibility_violation", "critical_unsupported_claim", "unauthorized_review_write",
                         "prohibited_review_transition", "source_content_integrity"):
            obs = synthetic_observations(policy(), "evalrun_candidate_1", extra=[self.violation(category)])
            with self.subTest(category=category):
                result = gate(obs=obs)
                self.assertIs(result.result, GateResult.BLOCKED)
                self.assertEqual(status_of(result, category), "fail")

    def test_violation_blocks_even_under_insufficient_coverage(self):
        obs = synthetic_observations(policy(), "evalrun_candidate_1", basis="mock_authority",
                                     extra=[self.violation("source_content_integrity")])
        self.assertIs(gate(obs=obs, integrity=HeldOutIntegrity.NOMINAL_EXPOSED, att=None).result, GateResult.BLOCKED)

    def test_report_only_violation_is_recorded_not_blocking(self):
        r = run(kind="single_model", prompt={"status": "pinned", "value": "prompt-example/1"},
                model={"status": "pinned", "value": "model-example/1"})
        obs = synthetic_observations(policy(), r.id, extra=[self.violation("prompt_injection_compliance")])
        # g010 is the mandatory case for prompt injection on model runs; provide it at an accepted basis.
        result = gate(r=r, obs=obs)
        injection = next(c for c in result.categories if c.category.value == "prompt_injection_compliance")
        self.assertIn("violation_reported", injection.reasons)
        self.assertIsNot(result.result, GateResult.BLOCKED)

    def test_held_out_reported_violation_blocks_even_if_untrusted(self):
        att = attestation(policy(), status="fail", violations=1, custody="unverified_declaration")
        self.assertIs(gate(att=att).result, GateResult.BLOCKED)

    def test_observations_must_belong_to_the_run(self):
        with self.assertRaises(ContractViolation):
            gate(obs=synthetic_observations(policy(), "evalrun_other"))


def decision(**update):
    base = {"id": "promotion_example_1", "candidate_config": {"id": "candidate_example", "sha256": "sha256:" + "c" * 64},
            "baseline_run_id": "evalrun_baseline_1", "candidate_run_ids": ["evalrun_candidate_1"],
            "safety_policy": {"id": "evaldefs_safety_gate", "version": 1},
            "manifests": [GOLDEN_PIN.model_dump(mode="json"), HELD_PIN.model_dump(mode="json")],
            "gate_result": "eligible_for_human_decision", "held_out_custody_basis": "trusted_custodian",
            "decision": "promote", "decided_by": DECIDER, "rationale": "Logic-only example.",
            "decided_at": "2026-10-28T22:00:00Z"}
    base.update(update)
    return base


class PromotionDecisionTests(unittest.TestCase):
    def test_strict_promotion(self):
        PromotionDecision.model_validate(decision())  # logic only: typed-in attestation values
        bad = {
            "insufficient gate": decision(gate_result="insufficient_evidence"),
            "blocked gate": decision(gate_result="blocked"),
            "unverified decider": decision(decided_by={**DECIDER, "attestation_basis": "unverified_metadata"}),
            "mock decider": decision(decided_by={**DECIDER, "attestation_basis": "mock_authenticated"}),
            "service decider": decision(decided_by={**DECIDER, "asserted_kind": "service"}),
            "no decider": decision(decided_by=None),
            "untrusted custody": decision(held_out_custody_basis="unverified_declaration"),
            "baseline among candidates": decision(candidate_run_ids=["evalrun_baseline_1"]),
            "waiver field": decision(waiver="accepted risk"),
            "reject by service": decision(decision="reject", decided_by={**DECIDER, "asserted_kind": "service"}),
        }
        for name, payload in bad.items():
            with self.subTest(name), self.assertRaises(ValidationError):
                PromotionDecision.model_validate(payload)
        PromotionDecision.model_validate(decision(decision="not_determined", gate_result="insufficient_evidence",
                                                  decided_by=None, held_out_custody_basis="unverified_declaration"))
        PromotionDecision.model_validate(decision(decision="reject", gate_result="blocked",
                                                  decided_by={**DECIDER, "attestation_basis": "unverified_metadata"}))

    def test_inputs_must_be_comparable_and_gate_worst_case(self):
        dec = PromotionDecision.model_validate(decision())
        baseline, candidate = run("evalrun_baseline_1"), run("evalrun_candidate_1")
        good_gate = gate(r=candidate)
        check_promotion_inputs(dec, baseline, [candidate], [good_gate])
        other_set = run("evalrun_baseline_1", manifests=(GOLDEN_PIN,))
        with self.assertRaises(ContractViolation) as ctx:
            check_promotion_inputs(dec, other_set, [candidate], [good_gate])
        self.assertEqual(ctx.exception.code, "promotion_case_set_mismatch")
        blocked = good_gate.model_copy(update={"result": GateResult.BLOCKED})
        with self.assertRaises(ContractViolation) as ctx:
            check_promotion_inputs(dec, baseline, [candidate], [blocked])
        self.assertEqual(ctx.exception.code, "promotion_gate_result_mismatch")


class AttestationShapeTests(unittest.TestCase):
    def test_attestation_cannot_carry_case_identifiers(self):
        props = set(HeldOutGateAttestation.model_json_schema()["properties"])
        self.assertFalse({p for p in props if "case" in p})
        payload = attestation(policy()).model_dump(mode="json")
        with self.assertRaises(ValidationError):
            HeldOutGateAttestation.model_validate({**payload, "case_ids": ["evalcase_h001"]})
        bad = copy.deepcopy(payload)
        bad["results"][0]["status"] = "fail"  # fail without violations
        with self.assertRaises(ValidationError):
            HeldOutGateAttestation.model_validate(bad)


if __name__ == "__main__":
    unittest.main()
