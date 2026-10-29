"""D-004.12 / ADR-0003 -- safety-gate coverage, held-out lineage, comparison and strict promotion.

Two kinds of input are used:

* the REAL fixture-conformance observations (tier T2), which must always
  produce ``insufficient_evidence``; and
* SYNTHETIC GATE-LOGIC EXAMPLES built in memory by the ``logic_only_*``
  helpers below. They carry T3/T4 bases, trusted attestation values, metric
  values and run identities that were TYPED INTO THIS TEST FILE. They are not
  measurements, not attestation and not evidence about any system; they exist
  only to exercise the pure validation logic, and none is committed.

They do use the GENUINE committed golden case pins (ids, versions, hashes),
because the gate now validates case identity against the authoritative
manifest.
"""

import copy
import unittest

from pydantic import ValidationError

import eval_harness as H
from rap_contracts.evaluation import (
    CaseObservation,
    CaseOutcome,
    CodeRevision,
    ConfigurationPin,
    DefinitionsPin,
    EvaluationRun,
    HeldOutIntegrity,
    Measurement,
    NOT_APPLICABLE,
    ObservedRecord,
    OptionalPin,
    RunKind,
    SafetyObservation,
    Split,
    StepObservation,
    StrategyPin,
    fingerprint_configuration,
    pin_manifest,
)
from rap_contracts.invariants import ContractViolation
from rap_contracts.promotion import (
    CaseComparison,
    CategoryGateStatus,
    DecisionOutcome,
    derive_gate_result,
    GateEvaluation,
    GateResult,
    HeldOutGateAttestation,
    MetricDefinitionSet,
    PromotionDecision,
    RunComparison,
    SafetyGatePolicy,
    assess_comparison,
    check_comparable_runs,
    check_promotion_inputs,
    derive_change,
    evaluate_safety_gate,
    pin_comparison,
)

DEFS = H.load(H.DEFINITIONS_FILE)
METRICS = MetricDefinitionSet.model_validate(DEFS["metric_definitions"])
GOLDEN = H.manifest_of(H.split_doc(Split.GOLDEN))
GOLDEN_PIN = pin_manifest(GOLDEN)
HELD_PIN = pin_manifest(H.manifest_of(H.split_doc(Split.HELD_OUT)))
PINS = {p.case_id: p for p in GOLDEN.case_pins}
TRUSTED = {"principal_id": "principal_example_custodian", "asserted_kind": "human", "asserted_role": "custodian",
           "attestation_basis": "trusted_service_authenticated"}
DECIDER = {"principal_id": "principal_demo_owner", "asserted_kind": "human", "asserted_role": "project_owner",
           "attestation_basis": "trusted_service_authenticated"}
MEASURE = dict(latency=Measurement(status="not_measured", unit="milliseconds"), cost=Measurement(status="not_applicable", unit="usd"))
FULL = ("eligibility", "recommendation", "verifier")
COMMITS = {"evalrun_baseline_1": "b" * 40, "evalrun_candidate_1": "c" * 40, "evalrun_candidate_2": "c" * 40}


def policy(status="approved"):
    return SafetyGatePolicy.model_validate({**DEFS["safety_gate_policy"], "status": status})


def run(rid="evalrun_candidate_1", kind="deterministic_baseline", purpose="promotion_assessment", components=FULL,
        strategy_version=None, config_id=None, **update):
    """A SYNTHETIC, logic-only run record whose configuration fingerprint is correctly recomputed."""
    commit = update.pop("commit", COMMITS.get(rid, "d" * 40))
    strategy = StrategyPin(id="deterministic_rules", version=strategy_version or (1 if "baseline" in rid else 2),
                           components=frozenset(components))
    code = (CodeRevision(status="recorded", commit=commit, dirty=False) if kind != "fixture_conformance"
            else CodeRevision(status="unavailable"))
    pins = {k: _pin(update.pop(k, NOT_APPLICABLE)) for k in ("retrieval_index", "prompt", "model", "judge")}
    contract_version = update.pop("contract_version", "0.2.0-dev.foundations.4")
    payload = dict(
        id=rid, run_kind=kind, purpose=purpose, manifests=(GOLDEN_PIN, HELD_PIN),
        definitions=DefinitionsPin(id="evaldefs_metrics", version=1),
        safety_policy=DefinitionsPin(id="evaldefs_safety_gate", version=1),
        contract_version=contract_version, code_revision=code, strategy=strategy,
        source_authority="drupal" if kind != "fixture_conformance" else "fixture_mock",
        replicates=1, started_at="2026-10-28T20:00:00Z", completed_at="2026-10-28T20:10:00Z", status="completed",
        executed_by="example-runner/0", **pins, **MEASURE)
    payload.update(update)
    if kind != "fixture_conformance" and "configuration" not in update:
        payload["configuration"] = ConfigurationPin(
            id=config_id or ("baseline_config" if "baseline" in rid else "candidate_config"), fingerprint_version=1,
            fingerprint=fingerprint_configuration(run_kind=RunKind(kind), strategy=strategy, code_revision=code,
                                                  contract_version=contract_version, **pins))
    return EvaluationRun.model_validate(payload)


def _pin(value):
    return value if isinstance(value, OptionalPin) else OptionalPin.model_validate(value)


def logic_only_observation(run_id, case_id, *, outcome="pass", basis="integrated_service", safety=(),
                           sha=None, split="golden", version=None, step_status=None):
    """SYNTHETIC gate-logic example bound to a genuine case pin unless overridden."""
    pin = PINS.get(case_id)
    identity = dict(run_id=run_id, case_id=case_id, case_version=version or (pin.version if pin else 1),
                    case_sha256=sha or (pin.sha256 if pin else "sha256:" + "0" * 64), split=split, **MEASURE)
    if outcome == "not_evaluated":
        return CaseObservation(**identity, execution_status="not_run", outcome="not_evaluated")
    status = step_status or ("matched" if outcome == "pass" else ("mismatched" if outcome == "fail" else "not_evaluated"))
    role = "prerequisite" if outcome == "inconclusive" else "target"
    step = StepObservation(step_id="s1", role=role, operation="retrieval_admission", status=status, basis=basis,
                           observed=None if status == "not_evaluated" else ObservedRecord(
                               error_type="harness_error" if status == "errored" else None),
                           safety=() if status == "not_evaluated" else tuple(safety))
    return CaseObservation(**identity, execution_status="executed", steps=(step,), outcome=outcome)


def logic_only_observations(pol, run_id, basis="integrated_service", outcome="pass", disposition="attempt_blocked",
                            skip=(), extra=(), override=None):
    """One SYNTHETIC observation per mandatory golden case, covering every category it is mandatory for."""
    cats_by_case = {}
    for rule in pol.categories:
        for ref in rule.mandatory_golden_cases:
            cats_by_case.setdefault(ref.case_id, []).append(rule.category)
    out = []
    for case_id, cats in sorted(cats_by_case.items()):
        if case_id in skip:
            continue
        safety = [SafetyObservation(category=c, exposure_point="model_context", disposition=disposition) for c in cats]
        kwargs = {"outcome": outcome, "basis": basis, **(override or {}).get(case_id, {})}
        out.append(logic_only_observation(run_id, case_id, safety=safety, **kwargs))
    return out + list(extra)


def logic_only_attestation(pol, configuration, status="pass", custody="trusted_custodian", attested_by=TRUSTED,
                           cases=1, violations=0, bases=("integrated_service",), basis_met=True,
                           provenance="trusted_registry_verified"):
    results = [{"category": r.category.value, "status": status, "cases_exercised": cases, "violations": violations,
                "bases_observed": list(bases), "coverage_basis_met": basis_met}
               for r in pol.categories if r.held_out_coverage_required]
    return HeldOutGateAttestation.model_validate({
        "manifest": HELD_PIN.model_dump(mode="json"), "policy": {"id": pol.id, "version": pol.version},
        "configuration": configuration.model_dump(mode="json"), "run_id": "evalrun_held_out_custody",
        "results": results, "custody_basis": custody, "run_provenance_basis": provenance, "attested_by": attested_by,
        "attested_at": "2026-10-28T21:00:00Z"})


# Backwards-compatible names used by the JSON Schema conformance suite.
def attestation(pol, **kw):
    return logic_only_attestation(pol, run().configuration, **kw)


def gate(pol=None, r=None, obs=None, integrity=HeldOutIntegrity.CUSTODIED_UNEXPOSED, att="default", manifest=GOLDEN):
    pol = pol or policy()
    r = r or run()
    obs = logic_only_observations(pol, r.id) if obs is None else obs
    att = logic_only_attestation(pol, r.configuration) if att == "default" else att
    return evaluate_safety_gate(pol, r, manifest, obs, integrity, att)


def status_of(result, category):
    return next(c for c in result.categories if c.category.value == category).status.value


def reasons_of(result, category):
    return next(c for c in result.categories if c.category.value == category).reasons


class ConformanceEvidenceTests(unittest.TestCase):
    def test_real_conformance_observations_are_never_promotion_evidence(self):
        conformance = run("evalrun_conformance_local", kind="fixture_conformance", purpose="regression", components=())
        observations = []
        for split in Split:
            doc = H.split_doc(split)
            observations += [H.run_case(c, doc, run_id=conformance.id).observation for c in H.cases_of(doc)]
        result = evaluate_safety_gate(policy(), conformance, GOLDEN, observations, HeldOutIntegrity.NOMINAL_EXPOSED)
        self.assertIs(result.result, GateResult.INSUFFICIENT_EVIDENCE)
        for reason in ("conformance_run_not_promotion_evidence", "run_not_promotion_assessment", "run_configuration_missing"):
            self.assertIn(reason, result.reasons)
        # The same genuine T2 observations under a promotion-shaped run still satisfy no category.
        relabelled = [o.model_copy(update={"run_id": "evalrun_candidate_1"}) for o in observations]
        result = evaluate_safety_gate(policy(), run(), GOLDEN, relabelled, HeldOutIntegrity.NOMINAL_EXPOSED)
        self.assertIs(result.result, GateResult.INSUFFICIENT_EVIDENCE)
        self.assertTrue(all(c.status.value in ("insufficient_evidence", "not_applicable") for c in result.categories))
        self.assertIn("basis_not_accepted", reasons_of(result, "cross_org_access"))


class GateCoverageTests(unittest.TestCase):
    def test_complete_logic_only_coverage_is_eligible(self):
        self.assertIs(gate().result, GateResult.ELIGIBLE_FOR_HUMAN_DECISION)

    def test_coverage_gaps_are_insufficient(self):
        pol, r = policy(), run()
        gaps = {
            "missing mandatory case": logic_only_observations(pol, r.id, skip=("evalcase_g011",)),
            "inconclusive mandatory case": logic_only_observations(pol, r.id, override={"evalcase_g007": {"outcome": "inconclusive"}}),
            "mismatched but blocked": logic_only_observations(pol, r.id, outcome="fail"),
            "not observable": logic_only_observations(pol, r.id, disposition="not_observable"),
            "not exercised": logic_only_observations(pol, r.id, disposition="not_exercised"),
            "mock-level basis": logic_only_observations(pol, r.id, basis="mock_authority"),
        }
        for name, obs in gaps.items():
            with self.subTest(name):
                self.assertIs(gate(pol, r, obs).result, GateResult.INSUFFICIENT_EVIDENCE)

    def test_offline_basis_satisfies_only_categories_that_accept_it(self):
        result = gate(obs=logic_only_observations(policy(), "evalrun_candidate_1", basis="deterministic_baseline_execution"))
        self.assertIs(result.result, GateResult.INSUFFICIENT_EVIDENCE)
        self.assertEqual(status_of(result, "hard_eligibility_violation"), "pass")
        self.assertEqual(status_of(result, "cross_org_access"), "insufficient_evidence")

    def test_pin_and_policy_mismatches_are_insufficient(self):
        self.assertIs(gate(pol=policy("draft")).result, GateResult.INSUFFICIENT_EVIDENCE)
        other = run(safety_policy=DefinitionsPin(id="evaldefs_safety_gate", version=2))
        self.assertIn("safety_policy_pin_mismatch", gate(r=other, obs=logic_only_observations(policy(), other.id)).reasons)
        moved = run(manifests=(GOLDEN_PIN.model_copy(update={"version": 2}), HELD_PIN))
        self.assertIn("golden_manifest_pin_mismatch", gate(r=moved, obs=logic_only_observations(policy(), moved.id)).reasons)


class CaseIdentityTests(unittest.TestCase):
    """R2: observations count only when they match the authoritative golden case pins exactly."""

    def test_placeholder_case_hash_no_longer_counts(self):
        obs = logic_only_observations(policy(), "evalrun_candidate_1",
                                      override={"evalcase_g004": {"sha": "sha256:" + "0" * 64}})
        result = gate(obs=obs)
        self.assertIs(result.result, GateResult.INSUFFICIENT_EVIDENCE)
        self.assertIn("observation_case_identity_mismatch", reasons_of(result, "cross_org_access"))

    def test_wrong_split_or_version_no_longer_counts(self):
        for name, override in {"held-out split": {"split": "held_out"}, "other version": {"version": 2}}.items():
            obs = logic_only_observations(policy(), "evalrun_candidate_1", override={"evalcase_g007": override})
            with self.subTest(name):
                result = gate(obs=obs)
                self.assertIs(result.result, GateResult.INSUFFICIENT_EVIDENCE)
                self.assertIn("observation_case_identity_mismatch", reasons_of(result, "unauthorized_source_access"))

    def test_substituted_manifest_is_not_authoritative(self):
        held = H.manifest_of(H.split_doc(Split.HELD_OUT))
        result = gate(manifest=held)
        self.assertIs(result.result, GateResult.INSUFFICIENT_EVIDENCE)
        self.assertIn("golden_manifest_not_authoritative", result.reasons)

    def test_policy_case_missing_from_manifest(self):
        doc = copy.deepcopy(DEFS["safety_gate_policy"])
        doc["status"] = "approved"
        doc["categories"][0]["mandatory_golden_cases"][0]["version"] = 2
        result = gate(pol=SafetyGatePolicy.model_validate(doc))
        self.assertIn("policy_case_not_in_manifest", result.reasons)
        self.assertIs(result.result, GateResult.INSUFFICIENT_EVIDENCE)


class HeldOutLineageTests(unittest.TestCase):
    """R1 and held-out evidence basis."""

    def test_attestation_for_another_configuration_is_rejected(self):
        unrelated = run("evalrun_candidate_2", strategy_version=7).configuration
        result = gate(att=logic_only_attestation(policy(), unrelated))
        self.assertIs(result.result, GateResult.INSUFFICIENT_EVIDENCE)
        self.assertIn("held_out_attestation_lineage_mismatch", reasons_of(result, "cross_org_access"))

    def test_unrelated_violation_does_not_block_but_never_counts(self):
        unrelated = run("evalrun_candidate_2", strategy_version=7).configuration
        result = gate(att=logic_only_attestation(policy(), unrelated, status="fail", violations=1))
        self.assertIs(result.result, GateResult.INSUFFICIENT_EVIDENCE)

    def test_matching_violation_blocks_even_if_untrusted(self):
        att = logic_only_attestation(policy(), run().configuration, status="fail", violations=1,
                                     custody="unverified_declaration", provenance="configuration_pin_match_only")
        self.assertIs(gate(att=att).result, GateResult.BLOCKED)

    def test_configuration_pin_match_is_not_run_provenance(self):
        att = logic_only_attestation(policy(), run().configuration, provenance="configuration_pin_match_only")
        result = gate(att=att)
        self.assertIs(result.result, GateResult.INSUFFICIENT_EVIDENCE)
        self.assertIn("held_out_run_provenance_unverified", reasons_of(result, "cross_org_access"))

    def test_lower_tier_held_out_coverage_is_insufficient(self):
        for bases in (("mock_authority",), ("integrated_service", "in_memory_double"), ("deterministic_baseline_execution",)):
            with self.subTest(bases=bases):
                result = gate(att=logic_only_attestation(policy(), run().configuration, bases=bases))
                self.assertIs(result.result, GateResult.INSUFFICIENT_EVIDENCE)
                self.assertIn("held_out_basis_not_accepted", reasons_of(result, "cross_org_access"))
        # T3 is accepted for categories whose policy accepts it.
        result = gate(att=logic_only_attestation(policy(), run().configuration, bases=("deterministic_baseline_execution",)))
        self.assertEqual(status_of(result, "hard_eligibility_violation"), "pass")

    def test_custody_cannot_claim_pass_without_met_basis(self):
        payload = logic_only_attestation(policy(), run().configuration).model_dump(mode="json")
        payload["results"][0]["coverage_basis_met"] = False
        with self.assertRaises(ValidationError):
            HeldOutGateAttestation.model_validate(payload)
        payload["results"][0]["status"] = "insufficient_evidence"
        result = gate(att=HeldOutGateAttestation.model_validate(payload))
        self.assertIs(result.result, GateResult.INSUFFICIENT_EVIDENCE)

    def test_custody_and_trust(self):
        pol, cfg = policy(), run().configuration
        self.assertIs(gate(integrity=HeldOutIntegrity.NOMINAL_EXPOSED).result, GateResult.INSUFFICIENT_EVIDENCE)
        self.assertIs(gate(att=None).result, GateResult.INSUFFICIENT_EVIDENCE)
        self.assertIs(gate(att=logic_only_attestation(pol, cfg, custody="unverified_declaration")).result,
                      GateResult.INSUFFICIENT_EVIDENCE)
        self.assertIs(gate(att=logic_only_attestation(pol, cfg, attested_by={**TRUSTED, "attestation_basis": "mock_authenticated"})).result,
                      GateResult.INSUFFICIENT_EVIDENCE)
        self.assertIs(gate(att=logic_only_attestation(pol, cfg, status="insufficient_evidence", cases=0, bases=(), basis_met=False)).result,
                      GateResult.INSUFFICIENT_EVIDENCE)

    def test_attestation_cannot_carry_case_identifiers(self):
        props = set(HeldOutGateAttestation.model_json_schema()["properties"])
        result_props = set(HeldOutGateAttestation.model_json_schema()["$defs"]["HeldOutCategoryResult"]["properties"])
        self.assertFalse({p for p in props | result_props if "case_id" in p or "label" in p})
        payload = attestation(policy()).model_dump(mode="json")
        with self.assertRaises(ValidationError):
            HeldOutGateAttestation.model_validate({**payload, "case_ids": ["evalcase_h001"]})


class BlockingTests(unittest.TestCase):
    def violation(self, category, case_id="evalcase_example_extra"):
        return logic_only_observation("evalrun_candidate_1", case_id, outcome="fail", safety=[
            SafetyObservation(category=category, exposure_point="model_context", disposition="unblocked_violation")])

    def test_any_zero_tolerance_violation_blocks_even_outside_mandatory_cases(self):
        for category in ("cross_org_access", "unauthorized_source_access", "stale_or_withdrawn_source",
                         "hard_eligibility_violation", "critical_unsupported_claim", "unauthorized_review_write",
                         "prohibited_review_transition", "source_content_integrity"):
            obs = logic_only_observations(policy(), "evalrun_candidate_1", extra=[self.violation(category)])
            with self.subTest(category=category):
                result = gate(obs=obs)
                self.assertIs(result.result, GateResult.BLOCKED)
                self.assertEqual(status_of(result, category), "fail")

    def test_violation_blocks_even_under_insufficient_coverage(self):
        obs = logic_only_observations(policy(), "evalrun_candidate_1", basis="mock_authority",
                                      extra=[self.violation("source_content_integrity")])
        self.assertIs(gate(obs=obs, integrity=HeldOutIntegrity.NOMINAL_EXPOSED, att=None).result, GateResult.BLOCKED)

    def test_report_only_violation_is_recorded_not_blocking(self):
        r = run(kind="single_model", components=FULL + ("model",), prompt={"status": "pinned", "value": "prompt-example/1"},
                model={"status": "pinned", "value": "model-example/1"})
        obs = logic_only_observations(policy(), r.id, extra=[self.violation("prompt_injection_compliance")])
        result = gate(r=r, obs=obs)
        self.assertIn("violation_reported", reasons_of(result, "prompt_injection_compliance"))
        self.assertIsNot(result.result, GateResult.BLOCKED)

    def test_observations_must_belong_to_the_run(self):
        with self.assertRaises(ContractViolation):
            gate(obs=logic_only_observations(policy(), "evalrun_other"))


# ---------------------------------------------------------------------------
# Comparison and promotion (R3, R4)
# ---------------------------------------------------------------------------


def ratio(mid, status="observed", num=8, den=10, reason=None):
    if status == "observed":
        return {"kind": "ratio", "metric_id": mid, "metric_version": 1, "status": "observed", "numerator": num,
                "denominator": den, "value": num / den}
    out = {"kind": "ratio", "metric_id": mid, "metric_version": 1, "status": status}
    if status == "not_applicable":
        out["not_applicable_reason"] = reason
        if reason == "zero_denominator":
            out["denominator"] = 0
    return out


def default_metrics(**override):
    """SYNTHETIC metric values typed into the test; not measurements."""
    rows = {
        "eligibility_label_correctness": (ratio("eligibility_label_correctness", num=20, den=26),
                                          ratio("eligibility_label_correctness", num=24, den=26)),
        "unknown_state_preservation": (ratio("unknown_state_preservation", num=5, den=6),
                                       ratio("unknown_state_preservation", num=6, den=6)),
        "verification_detection_recall": (ratio("verification_detection_recall", num=3, den=4),
                                          ratio("verification_detection_recall", num=4, den=4)),
        "verification_false_alarm_rate": (ratio("verification_false_alarm_rate", num=1, den=10),
                                          ratio("verification_false_alarm_rate", num=0, den=10)),
        "latency_p95": ({"kind": "duration", "metric_id": "latency_p95", "metric_version": 1, "status": "not_measured",
                         "statistic": "p95"},) * 2,
        "cost_per_reviewed_suggestion": ({"kind": "cost", "metric_id": "cost_per_reviewed_suggestion", "metric_version": 1,
                                          "status": "not_applicable", "not_applicable_reason": "run_kind_not_applicable"},) * 2,
    }
    rows.update(override)
    return [{"metric_id": k, "metric_version": 1, "baseline": b, "candidate": c} for k, (b, c) in rows.items() if b is not None]


def logic_only_case_observations(run_id, outcomes=None):
    """SYNTHETIC per-case observations for every pinned golden case (genuine pins)."""
    outcomes = outcomes or {}
    return [logic_only_observation(run_id, cid, outcome=outcomes.get(cid, "pass"), basis="deterministic_baseline_execution")
            for cid in sorted(PINS)]


def comparison_record(baseline, candidate, b_obs, c_obs, metrics=None, **update):
    b = {o.case_id: o.outcome for o in b_obs}
    c = {o.case_id: o.outcome for o in c_obs}
    cases = [{"case_id": cid, "case_version": PINS[cid].version, "case_sha256": PINS[cid].sha256,
              "baseline_outcome": b.get(cid, CaseOutcome.NOT_EVALUATED).value,
              "candidate_outcome": c.get(cid, CaseOutcome.NOT_EVALUATED).value,
              "change": derive_change(b.get(cid, CaseOutcome.NOT_EVALUATED), c.get(cid, CaseOutcome.NOT_EVALUATED)).value}
             for cid in sorted(PINS)]
    payload = {"id": "comparison_example_1", "baseline_run_id": baseline.id,
               "baseline_config": baseline.configuration.model_dump(mode="json"), "candidate_run_id": candidate.id,
               "candidate_config": candidate.configuration.model_dump(mode="json"),
               "manifests": [GOLDEN_PIN.model_dump(mode="json"), HELD_PIN.model_dump(mode="json")],
               "definitions": {"id": "evaldefs_metrics", "version": 1}, "cases": cases,
               "metrics": default_metrics() if metrics is None else metrics, "recorded_at": "2026-10-28T21:30:00Z",
               "recorded_by": DECIDER}
    payload.update(update)
    return RunComparison.model_validate(payload)


class Scenario:
    """A complete synthetic baseline/candidate promotion scenario (gate-logic example only)."""

    def __init__(self, metrics=None, components=FULL, b_outcomes=None, c_outcomes=None, b_obs=None, c_obs=None):
        self.baseline = run("evalrun_baseline_1", purpose="regression", components=components)
        self.candidate = run("evalrun_candidate_1", components=components)
        self.b_obs = logic_only_case_observations(self.baseline.id, b_outcomes) if b_obs is None else b_obs
        self.c_obs = logic_only_case_observations(self.candidate.id, c_outcomes) if c_obs is None else c_obs
        self.comparison = comparison_record(self.baseline, self.candidate, self.b_obs, self.c_obs, metrics)
        self.gate = gate(r=self.candidate)

    def decision(self, **update):
        defaults = {"baseline_config": self.baseline.configuration.model_dump(mode="json"),
                    "candidate_config": self.candidate.configuration.model_dump(mode="json"),
                    "comparisons": [pin_comparison(self.comparison).model_dump(mode="json")]}
        return PromotionDecision.model_validate(decision(**{**defaults, **update}))

    def check(self, dec=None, comparisons=None, gates=None, observations=None, pol=None):
        return check_promotion_inputs(
            dec or self.decision(), self.baseline, [self.candidate], gates or [self.gate], pol or policy(),
            [self.comparison] if comparisons is None else comparisons,
            observations or {self.baseline.id: self.b_obs, self.candidate.id: self.c_obs}, METRICS, GOLDEN)

    def assess(self, comparison=None):
        return assess_comparison(comparison or self.comparison, self.baseline, self.candidate, self.b_obs, self.c_obs,
                                 METRICS, GOLDEN)


def decision(**update):
    base = {"id": "promotion_example_1",
            "baseline_config": run("evalrun_baseline_1", purpose="regression").configuration.model_dump(mode="json"),
            "candidate_config": run().configuration.model_dump(mode="json"),
            "baseline_run_id": "evalrun_baseline_1", "candidate_run_ids": ["evalrun_candidate_1"],
            "safety_policy": {"id": "evaldefs_safety_gate", "version": 1},
            "definitions": {"id": "evaldefs_metrics", "version": 1},
            "manifests": [GOLDEN_PIN.model_dump(mode="json"), HELD_PIN.model_dump(mode="json")],
            "gate_result": "eligible_for_human_decision", "held_out_custody_basis": "trusted_custodian",
            "comparisons": [{"comparison_id": "comparison_example_1", "sha256": "sha256:" + "e" * 64}],
            "decision": "promote", "decided_by": DECIDER, "rationale": "Logic-only example.",
            "decided_at": "2026-10-28T22:00:00Z"}
    base.update(update)
    return base


class ComparableRunTests(unittest.TestCase):
    def test_execution_conditions_must_match(self):
        base = run("evalrun_baseline_1", purpose="regression")
        check_comparable_runs(base, run())
        differing = {
            "source authority": run(source_authority="fixture_mock"),
            "replicates": run(replicates=3),
            "manifests": run(manifests=(GOLDEN_PIN,)),
            "definitions": run(definitions=DefinitionsPin(id="evaldefs_metrics", version=2)),
            "safety policy": run(safety_policy=DefinitionsPin(id="evaldefs_safety_gate", version=2)),
            "contract version": run(contract_version="0.2.0-dev.foundations.5"),
            "same configuration": run("evalrun_baseline_2", purpose="regression", commit="b" * 40, strategy_version=1,
                                      config_id="baseline_config"),
        }
        for name, other in differing.items():
            with self.subTest(name), self.assertRaises(ContractViolation) as ctx:
                check_comparable_runs(base, other)
            self.assertEqual(ctx.exception.code, "runs_not_comparable")


class ComparisonTests(unittest.TestCase):
    def test_complete_synthetic_comparison(self):
        s = Scenario()
        self.assertEqual(s.assess().model_dump(include={"complete", "reasons"}), {"complete": True, "reasons": ()})
        self.assertIn("promote", [a.value for a in s.check().allowed])

    def test_change_is_derived(self):
        s = Scenario(b_outcomes={"evalcase_g001": "fail"})
        self.assertEqual(next(c for c in s.comparison.cases if c.case_id == "evalcase_g001").change.value, "improved")
        bad = s.comparison.model_dump(mode="json")
        next(c for c in bad["cases"] if c["case_id"] == "evalcase_g001")["change"] = "unchanged"
        with self.assertRaises(ValidationError):
            RunComparison.model_validate(bad)

    def test_inconclusive_or_missing_execution_is_incomplete(self):
        for name, kw, reason in (
            ("inconclusive candidate", {"c_outcomes": {"evalcase_g004": "inconclusive"}}, "case_not_conclusive"),
            ("not evaluated baseline", {"b_outcomes": {"evalcase_g010": "not_evaluated"}}, "case_not_conclusive"),
        ):
            with self.subTest(name):
                s = Scenario(**kw)
                a = s.assess()
                self.assertFalse(a.complete)
                self.assertIn(reason, a.reasons)
                with self.assertRaises(ContractViolation) as ctx:
                    s.check()
                self.assertEqual(ctx.exception.code, "promotion_not_supported")
        s = Scenario()
        s.c_obs = [o for o in s.c_obs if o.case_id != "evalcase_g012"]
        self.assertIn("candidate_observation_missing", s.assess().reasons)
        dropped = s.comparison.model_dump(mode="json")
        dropped["cases"] = [c for c in dropped["cases"] if c["case_id"] != "evalcase_g013"]
        self.assertIn("case_missing", s.assess(RunComparison.model_validate(dropped)).reasons)

    def test_records_contradicting_evidence_are_rejected(self):
        s = Scenario()
        wrong_hash = s.comparison.model_dump(mode="json")
        wrong_hash["cases"][0]["case_sha256"] = "sha256:" + "0" * 64
        contradicted = s.comparison.model_dump(mode="json")
        contradicted["cases"][0].update(candidate_outcome="fail", change="regressed")
        unknown_case = s.comparison.model_dump(mode="json")
        unknown_case["cases"].append({**unknown_case["cases"][0], "case_id": "evalcase_g999"})
        other_config = s.comparison.model_dump(mode="json")
        other_config["candidate_config"] = run("evalrun_candidate_2", strategy_version=7).configuration.model_dump(mode="json")
        other_defs = s.comparison.model_dump(mode="json")
        other_defs["definitions"] = {"id": "evaldefs_metrics", "version": 2}
        cases = {
            "comparison_case_identity_mismatch": wrong_hash,
            "comparison_outcome_mismatch": contradicted,
            "comparison_case_not_pinned": unknown_case,
            "comparison_config_mismatch": other_config,
            "comparison_definitions_mismatch": other_defs,
        }
        for code, payload in cases.items():
            with self.subTest(code), self.assertRaises(ContractViolation) as ctx:
                s.assess(RunComparison.model_validate(payload))
            self.assertEqual(ctx.exception.code, code)

    def test_required_metrics_must_be_genuinely_observed(self):
        cases = {
            "required metric not applicable": (
                {"eligibility_label_correctness": (ratio("eligibility_label_correctness", "not_applicable", reason="zero_denominator"),) * 2},
                "required_metric_not_observed"),
            "required metric not measured": (
                {"unknown_state_preservation": (ratio("unknown_state_preservation", "not_measured"),) * 2},
                "required_metric_not_observed"),
            "required metric missing": ({"unknown_state_preservation": (None, None)}, "required_metric_missing"),
            "applicable verifier metric not measured": (
                {"verification_detection_recall": (ratio("verification_detection_recall", "not_measured"),) * 2},
                "required_metric_not_measured"),
        }
        for name, (override, reason) in cases.items():
            with self.subTest(name):
                a = Scenario(metrics=default_metrics(**override)).assess()
                self.assertFalse(a.complete)
                self.assertIn(reason, a.reasons)

    def test_no_observed_outcome_metric_floor(self):
        na = lambda m: (ratio(m, "not_applicable", reason="zero_denominator"),) * 2  # noqa: E731
        a = Scenario(metrics=default_metrics(eligibility_label_correctness=na("eligibility_label_correctness"),
                                             unknown_state_preservation=na("unknown_state_preservation"))).assess()
        self.assertIn("no_observed_outcome_metric", a.reasons)

    def test_component_absence_justifies_verifier_not_applicable(self):
        na = lambda m: (ratio(m, "not_applicable", reason="component_not_in_strategy"),) * 2  # noqa: E731
        metrics = default_metrics(verification_detection_recall=na("verification_detection_recall"),
                                  verification_false_alarm_rate=na("verification_false_alarm_rate"))
        self.assertTrue(Scenario(metrics=metrics, components=("eligibility", "recommendation")).assess().complete)
        with self.assertRaises(ContractViolation) as ctx:  # the strategy DOES contain a verifier
            Scenario(metrics=metrics).assess()
        self.assertEqual(ctx.exception.code, "unjustified_not_applicable")

    def test_unjustified_or_mistyped_values_are_rejected(self):
        cases = {
            "run kind claimed inapplicable": ({"unknown_state_preservation": (ratio("unknown_state_preservation", "not_applicable",
                                                                                    reason="run_kind_not_applicable"),) * 2},
                                              "unjustified_not_applicable"),
            "observed for inapplicable run kind": ({"cost_per_reviewed_suggestion": ({
                "kind": "cost", "metric_id": "cost_per_reviewed_suggestion", "metric_version": 1, "status": "observed",
                "total_usd": "1.00", "units": 4, "per_unit_usd": "0.25"},) * 2}, "metric_not_applicable_to_run"),
            "wrong value kind": ({"latency_p95": ({"kind": "count", "metric_id": "latency_p95", "metric_version": 1,
                                                  "status": "not_measured"},) * 2}, "metric_kind_mismatch"),
        }
        for name, (override, code) in cases.items():
            with self.subTest(name), self.assertRaises(ContractViolation) as ctx:
                Scenario(metrics=default_metrics(**override)).assess()
            self.assertEqual(ctx.exception.code, code)
        unknown = default_metrics() + [{"metric_id": "invented_metric", "metric_version": 1,
                                        "baseline": ratio("invented_metric"), "candidate": ratio("invented_metric")}]
        with self.assertRaises(ContractViolation) as ctx:
            Scenario(metrics=unknown).assess()
        self.assertEqual(ctx.exception.code, "comparison_metric_unknown")


class ErroredExecutionTests(unittest.TestCase):
    """R5: an execution error is never a measured failure, even when the observation reports outcome=fail."""

    def errored(self, run_id, case_id):
        return logic_only_observation(run_id, case_id, outcome="fail", step_status="errored",
                                      basis="deterministic_baseline_execution")

    def test_errored_target_reporting_fail_makes_comparison_incomplete(self):
        s = Scenario()
        obs = self.errored(s.candidate.id, "evalcase_g004")
        self.assertEqual((obs.execution_status, obs.outcome.value, obs.steps[0].status.value), ("executed", "fail", "errored"))
        s = Scenario(c_obs=[self.errored(s.candidate.id, c) if c == "evalcase_g004" else
                            logic_only_observation(s.candidate.id, c, basis="deterministic_baseline_execution")
                            for c in sorted(PINS)])
        a = s.assess()
        self.assertFalse(a.complete)
        self.assertIn("case_execution_errored", a.reasons)
        self.assertEqual(next(c for c in s.comparison.cases if c.case_id == "evalcase_g004").change.value, "regressed")
        with self.assertRaises(ContractViolation) as ctx:
            s.check()
        self.assertEqual(ctx.exception.code, "promotion_not_supported")
        self.assertNotIn("promote", [d.value for d in s.check(dec=s.decision(decision="reject")).allowed])

    def test_errored_baseline_is_equally_inconclusive(self):
        base = run("evalrun_baseline_1", purpose="regression")
        b_obs = [self.errored(base.id, c) if c == "evalcase_g010" else
                 logic_only_observation(base.id, c, basis="deterministic_baseline_execution") for c in sorted(PINS)]
        self.assertIn("case_execution_errored", Scenario(b_obs=b_obs).assess().reasons)

    def test_genuine_assertion_failure_remains_conclusive(self):
        s = Scenario(c_outcomes={"evalcase_g004": "fail"})  # target step mismatched, not errored
        self.assertEqual(next(o for o in s.c_obs if o.case_id == "evalcase_g004").steps[0].status.value, "mismatched")
        a = s.assess()
        self.assertTrue(a.complete, a.reasons)  # a regression is evidence for the human decider, not a gap


class GateIdentityTests(unittest.TestCase):
    """R6: gate evaluations are checked against the exact policy and their own categories and reasons."""

    def test_contradictory_gate_cannot_be_constructed(self):
        good = gate().model_dump(mode="json")
        self.assertEqual(good["result"], "eligible_for_human_decision")
        failing = copy.deepcopy(good)
        failing["categories"][0].update(status="fail", reasons=["unblocked_violation_observed"])
        insufficient = copy.deepcopy(good)
        insufficient["categories"][0].update(status="insufficient_evidence", reasons=["mandatory_case_missing"])
        cases = {
            "eligible with failed category": failing,
            "eligible with insufficient category": insufficient,
            "eligible with a global reason": {**good, "reasons": ["safety_policy_not_approved"]},
            "blocked without a failed category": {**good, "result": "blocked"},
            "duplicate category": {**good, "categories": good["categories"] + good["categories"][:1]},
            "no categories": {**good, "categories": []},
        }
        for name, payload in cases.items():
            with self.subTest(name), self.assertRaises(ValidationError):
                GateEvaluation.model_validate(payload)

    def test_contradictory_gate_is_rejected_even_if_validation_was_bypassed(self):
        s = Scenario()
        bad_categories = tuple(c.model_copy(update={"status": CategoryGateStatus.INSUFFICIENT_EVIDENCE}) if i == 0 else c
                               for i, c in enumerate(s.gate.categories))
        for name, forged in {
            "eligible over an insufficient category": s.gate.model_copy(update={"categories": bad_categories}),
            "eligible over a global reason": s.gate.model_copy(update={"reasons": ("run_configuration_missing",)}),
            "missing a policy category": s.gate.model_copy(update={"categories": s.gate.categories[1:]}),
        }.items():
            with self.subTest(name), self.assertRaises(ContractViolation) as ctx:
                s.check(gates=[forged])
            self.assertEqual(ctx.exception.code, "promotion_gate_inconsistent")

    def test_gate_for_another_policy_is_rejected(self):
        s = Scenario()
        other = s.gate.model_copy(update={"policy": DefinitionsPin(id="evaldefs_safety_gate", version=2)})
        with self.assertRaises(ContractViolation) as ctx:
            s.check(gates=[other])
        self.assertEqual(ctx.exception.code, "promotion_gate_policy_mismatch")
        other_policy = SafetyGatePolicy.model_validate({**DEFS["safety_gate_policy"], "status": "approved", "version": 2})
        with self.assertRaises(ContractViolation) as ctx:
            check_promotion_inputs(s.decision(), s.baseline, [s.candidate], [s.gate], other_policy, [s.comparison],
                                   {s.baseline.id: s.b_obs, s.candidate.id: s.c_obs}, METRICS, GOLDEN)
        self.assertEqual(ctx.exception.code, "promotion_policy_mismatch")


def policy_with_kinds(kinds_by_category, status="approved"):
    doc = copy.deepcopy(DEFS["safety_gate_policy"])
    doc["status"] = status
    for rule in doc["categories"]:
        if rule["category"] in kinds_by_category:
            rule["applies_to_run_kinds"] = kinds_by_category[rule["category"]]
    return SafetyGatePolicy.model_validate(doc)


class GateApplicabilityAndApprovalTests(unittest.TestCase):
    """R7: a gate cannot support promotion through not_applicable categories or a draft policy."""

    def forged(self, gate_, status_by_category, result=GateResult.ELIGIBLE_FOR_HUMAN_DECISION):
        cats = tuple(c.model_copy(update={"status": status_by_category.get(c.category.value, c.status), "reasons": ()})
                     for c in gate_.categories)
        return gate_.model_copy(update={"categories": cats, "result": result, "reasons": ()})

    def test_all_not_applicable_gate_is_never_eligible(self):
        s = Scenario()
        all_na = {c.category.value: CategoryGateStatus.NOT_APPLICABLE for c in s.gate.categories}
        self.assertIs(derive_gate_result(self.forged(s.gate, all_na).categories, ()), GateResult.INSUFFICIENT_EVIDENCE)
        payload = self.forged(s.gate, all_na).model_dump(mode="json")
        with self.assertRaises(ValidationError):
            GateEvaluation.model_validate(payload)
        with self.assertRaises(ContractViolation) as ctx:  # matching pins, complete comparison, validation bypassed
            s.check(gates=[self.forged(s.gate, all_na)])
        self.assertEqual(ctx.exception.code, "promotion_gate_applicability_mismatch")

    def test_policy_with_no_applicable_category_cannot_support_promote(self):
        model_only = {r["category"]: ["multi_agent"] for r in DEFS["safety_gate_policy"]["categories"]}
        pol = policy_with_kinds(model_only)
        s = Scenario()
        g = evaluate_safety_gate(pol, s.candidate, GOLDEN, logic_only_observations(pol, s.candidate.id),
                                 HeldOutIntegrity.CUSTODIED_UNEXPOSED, logic_only_attestation(pol, s.candidate.configuration))
        self.assertTrue(all(c.status is CategoryGateStatus.NOT_APPLICABLE for c in g.categories))
        self.assertIs(g.result, GateResult.INSUFFICIENT_EVIDENCE)
        assessment = s.check(dec=s.decision(decision="not_determined", gate_result="insufficient_evidence"),
                             gates=[g], pol=pol)
        self.assertNotIn("promote", [d.value for d in assessment.allowed])
        self.assertIn("gate_not_eligible", assessment.reasons)

    def test_status_must_match_run_kind_applicability(self):
        s = Scenario()
        cases = {
            "applicable category marked not_applicable": {"cross_org_access": CategoryGateStatus.NOT_APPLICABLE},
            "non-applicable category marked pass": {"prompt_injection_compliance": CategoryGateStatus.PASS},
            "non-applicable category marked insufficient": {"prompt_injection_compliance": CategoryGateStatus.INSUFFICIENT_EVIDENCE},
        }
        for name, statuses in cases.items():
            result = GateResult.INSUFFICIENT_EVIDENCE if "insufficient" in name else GateResult.ELIGIBLE_FOR_HUMAN_DECISION
            with self.subTest(name), self.assertRaises(ContractViolation) as ctx:
                s.check(gates=[self.forged(s.gate, statuses, result)])
            self.assertEqual(ctx.exception.code, "promotion_gate_applicability_mismatch")

    def test_zero_tolerance_violation_still_blocks_when_not_applicable(self):
        pol = policy_with_kinds({"cross_org_access": ["single_model", "multi_agent"]})
        s = Scenario()
        violation = logic_only_observation(s.candidate.id, "evalcase_example_extra", outcome="fail", safety=[
            SafetyObservation(category="cross_org_access", exposure_point="model_context", disposition="unblocked_violation")])
        g = evaluate_safety_gate(pol, s.candidate, GOLDEN, logic_only_observations(pol, s.candidate.id, extra=[violation]),
                                 HeldOutIntegrity.CUSTODIED_UNEXPOSED, logic_only_attestation(pol, s.candidate.configuration))
        self.assertIs(g.result, GateResult.BLOCKED)
        self.assertEqual(status_of(g, "cross_org_access"), "fail")
        assessment = s.check(dec=s.decision(decision="reject", gate_result="blocked"), gates=[g], pol=pol)
        self.assertEqual(assessment.allowed, (DecisionOutcome.REJECT, DecisionOutcome.NOT_DETERMINED))
        with self.assertRaises(ContractViolation) as ctx:
            s.check(gates=[g], pol=pol)  # the decision still claims an eligible gate
        self.assertEqual(ctx.exception.code, "promotion_gate_result_mismatch")

    def test_draft_policy_cannot_support_promote(self):
        s = Scenario()  # matching pins, eligible gate, complete comparison
        self.assertEqual(s.check().reasons, ())
        draft = policy("draft")
        self.assertEqual(draft.pin, policy().pin)
        with self.assertRaises(ContractViolation) as ctx:
            s.check(pol=draft)
        self.assertEqual(ctx.exception.code, "promotion_not_supported")
        assessment = s.check(dec=s.decision(decision="not_determined"), pol=draft)
        self.assertIn("safety_policy_not_approved", assessment.reasons)
        self.assertNotIn("promote", [d.value for d in assessment.allowed])


class PromotionDecisionTests(unittest.TestCase):
    def test_promote_without_comparison_is_rejected(self):
        """The reproduced R4 gap: a promote record with no comparison evidence."""
        with self.assertRaises(ValidationError):
            PromotionDecision.model_validate(decision(comparisons=[]))
        s = Scenario()
        undecided = s.decision(decision="not_determined", comparisons=[])
        assessment = s.check(dec=undecided, comparisons=[])
        self.assertNotIn("promote", [a.value for a in assessment.allowed])
        self.assertIn("comparison_missing", assessment.reasons)

    def test_strict_shape(self):
        PromotionDecision.model_validate(decision())  # shape only; check_promotion_inputs decides support
        bad = {
            "insufficient gate": decision(gate_result="insufficient_evidence"),
            "blocked gate": decision(gate_result="blocked"),
            "unverified decider": decision(decided_by={**DECIDER, "attestation_basis": "unverified_metadata"}),
            "mock decider": decision(decided_by={**DECIDER, "attestation_basis": "mock_authenticated"}),
            "service decider": decision(decided_by={**DECIDER, "asserted_kind": "service"}),
            "no decider": decision(decided_by=None),
            "untrusted custody": decision(held_out_custody_basis="unverified_declaration"),
            "baseline among candidates": decision(candidate_run_ids=["evalrun_baseline_1"]),
            "same configuration": decision(candidate_config=decision()["baseline_config"]),
            "waiver field": decision(waiver="accepted risk"),
            "self-declared status": decision(comparison_status="complete"),
            "reject by service": decision(decision="reject", decided_by={**DECIDER, "asserted_kind": "service"}),
        }
        for name, payload in bad.items():
            with self.subTest(name), self.assertRaises(ValidationError):
                PromotionDecision.model_validate(payload)
        PromotionDecision.model_validate(decision(decision="not_determined", gate_result="insufficient_evidence",
                                                  decided_by=None, held_out_custody_basis="unverified_declaration",
                                                  comparisons=[]))

    def test_inputs_are_validated_against_evidence(self):
        s = Scenario()
        self.assertEqual(s.check().reasons, ())
        other_cfg = run("evalrun_candidate_2", strategy_version=7).configuration.model_dump(mode="json")
        with self.assertRaises(ContractViolation) as ctx:
            s.check(dec=s.decision(candidate_config=other_cfg))
        self.assertEqual(ctx.exception.code, "promotion_config_mismatch")
        altered = s.decision(comparisons=[{"comparison_id": "comparison_example_1", "sha256": "sha256:" + "e" * 64}])
        with self.assertRaises(ContractViolation) as ctx:
            s.check(dec=altered)
        self.assertEqual(ctx.exception.code, "promotion_comparison_mismatch")
        blocked = gate(r=s.candidate, obs=logic_only_observations(policy(), s.candidate.id, extra=[
            BlockingTests.violation(None, "source_content_integrity")]))
        self.assertIs(blocked.result, GateResult.BLOCKED)
        with self.assertRaises(ContractViolation) as ctx:
            s.check(gates=[blocked])  # decision still records eligible
        self.assertEqual(ctx.exception.code, "promotion_gate_result_mismatch")
        other_set = run("evalrun_baseline_1", purpose="regression", manifests=(GOLDEN_PIN,))
        with self.assertRaises(ContractViolation) as ctx:
            check_promotion_inputs(s.decision(), other_set, [s.candidate], [s.gate], policy(), [s.comparison],
                                   {}, METRICS, GOLDEN)
        self.assertEqual(ctx.exception.code, "promotion_case_set_mismatch")

    def test_incomplete_comparison_cannot_support_promote(self):
        s = Scenario(metrics=default_metrics(unknown_state_preservation=(ratio("unknown_state_preservation", "not_measured"),) * 2))
        with self.assertRaises(ContractViolation) as ctx:
            s.check()
        self.assertEqual(ctx.exception.code, "promotion_not_supported")
        rejected = s.decision(decision="reject")
        self.assertIn("comparison_incomplete", s.check(dec=rejected).reasons)


if __name__ == "__main__":
    unittest.main()
