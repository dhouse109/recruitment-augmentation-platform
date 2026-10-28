"""D-004.05 / D-004.06 -- opportunity-specific eligibility, versioned policy, outcome support.

Fixture eligibility results are hand-written EXPECTED LABELS. These tests check
contract validity and that each labeled outcome is supported by its cited
inputs; they do not demonstrate an eligibility engine.
"""

import copy
import unittest

from pydantic import ValidationError

import support
from rap_contracts.eligibility import (
    REASON_CODES,
    EligibilityResult,
    OpportunityRequirement,
    PolicyRule,
    PolicyRuleKind,
    PolicySet,
    RuleOutcome,
    RuleResult,
    check_eligibility_result,
    check_eligibility_results,
    check_policy_sets,
    check_requirements,
    eligibility_source_refs,
)
from rap_contracts.evidence import require_sources_admissible
from rap_contracts.invariants import ContractViolation
from rap_contracts.models import AccessStatus, VersionStatus


def result_doc(doc, result_id):
    return next(r for r in doc["eligibility_results"] if r["id"] == result_id)


def outcome_doc(result, rule_id):
    return next(o for o in result["rule_outcomes"] if o["rule_id"] == rule_id)


def check_one(doc, result_id):
    ctx = support.ext_context(doc)
    check_eligibility_result(EligibilityResult.model_validate(result_doc(doc, result_id)), ctx)


class FixtureCaseTests(unittest.TestCase):
    def test_all_fixture_results_valid_and_supported(self):
        check_eligibility_results(support.ext_results(), support.ext_context())

    def test_rule_case_catalog(self):
        doc = support.ext_raw()
        results = {r.id: r for r in support.ext_results()}
        covered = set()
        for case in doc["rule_cases"]:
            with self.subTest(case=case["case_id"]):
                outcome = next(o for o in results[case["result_id"]].rule_outcomes if o.rule_id == case["rule_id"])
                self.assertEqual(outcome.result.value, case["expected"])
                covered.add((outcome.rule_kind, outcome.result))
        for kind in PolicyRuleKind:
            for res in RuleResult:
                if REASON_CODES[kind][res]:
                    with self.subTest(kind=kind.value, result=res.value):
                        self.assertIn((kind, res), covered, "every representable outcome has a fixture case")

    def test_active_rule_is_pass_fail_only_per_o1(self):
        self.assertEqual(REASON_CODES[PolicyRuleKind.OPPORTUNITY_STATUS_ACTIVE][RuleResult.UNKNOWN], frozenset())
        with self.assertRaises(ValidationError):
            RuleOutcome(rule_id="PILOT-ACTIVE-001", rule_version=1, rule_kind="opportunity_status_active",
                        result="unknown", reason_code="opportunity_status_not_established")

    def test_expected_decisions(self):
        decisions = {r.id: r.decision.value for r in support.ext_results()}
        self.assertEqual(decisions, {
            "eligibility_a_data": "eligible", "eligibility_a_ops": "ineligible", "eligibility_a_web": "eligible",
            "eligibility_b_data": "needs_information", "eligibility_d_data": "ineligible",
            "eligibility_e_data": "needs_information", "eligibility_c_job": "eligible",
        })


class DecisionConsistencyTests(unittest.TestCase):
    def test_decision_must_follow_outcomes(self):
        doc = support.ext_raw()
        for rid, wrong in (("eligibility_a_data", "needs_information"), ("eligibility_d_data", "needs_information"),
                           ("eligibility_b_data", "eligible"), ("eligibility_b_data", "ineligible")):
            with self.subTest(rid=rid, decision=wrong), self.assertRaises(ValidationError):
                EligibilityResult.model_validate({**result_doc(doc, rid), "decision": wrong})

    def test_fail_dominates_unknown(self):
        doc = support.ext_raw()
        res = copy.deepcopy(result_doc(doc, "eligibility_d_data"))
        outcome_doc(res, "PILOT-PROGRAM-002").update(result="unknown", reason_code="participation_not_recorded")
        EligibilityResult.model_validate(res)  # still ineligible: other rules fail
        self.assertEqual(res["decision"], "ineligible")

    def test_one_outcome_per_rule(self):
        res = copy.deepcopy(result_doc(support.ext_raw(), "eligibility_a_data"))
        res["rule_outcomes"].append(copy.deepcopy(res["rule_outcomes"][0]))
        with self.assertRaises(ValidationError):
            EligibilityResult.model_validate(res)

    def test_unknown_reason_codes_cannot_express_integrity_failures(self):
        for kind in PolicyRuleKind:
            for code in ("source_unavailable", "source_access_denied", "source_not_current", "source_withdrawn",
                         "source_deleted", "source_check_error"):
                with self.subTest(kind=kind.value, code=code), self.assertRaises(ValidationError):
                    RuleOutcome(rule_id="PILOT-X-001", rule_version=1, rule_kind=kind, result="unknown", reason_code=code)


class NoCandidateLevelRejectionTests(unittest.TestCase):
    def test_no_candidate_level_fields_or_values(self):
        base = result_doc(support.ext_raw(), "eligibility_a_ops")
        for key in ("candidate_status", "rejected", "rank", "score", "application_status"):
            with self.subTest(key=key), self.assertRaises(ValidationError):
                EligibilityResult.model_validate({**base, key: "rejected"})
        for decision in ("rejected", "reject_candidate", "disqualified"):
            with self.subTest(decision=decision), self.assertRaises(ValidationError):
                EligibilityResult.model_validate({**base, "decision": decision})

    def test_ineligible_for_one_opportunity_leaves_others_unchanged(self):
        ctx = support.ext_context()
        results = {r.id: r for r in support.ext_results()}
        self.assertEqual(results["eligibility_a_ops"].decision.value, "ineligible")
        self.assertEqual(results["eligibility_a_web"].decision.value, "eligible")
        self.assertEqual(results["eligibility_a_data"].decision.value, "eligible")
        check_eligibility_results([results["eligibility_a_web"], results["eligibility_a_data"]], ctx)
        check_eligibility_results([results["eligibility_a_ops"], results["eligibility_a_web"]], ctx)
        before = [a.model_dump() for a in ctx.records.applications if a.candidate_id == "candidate_demo_a"]
        check_eligibility_result(results["eligibility_a_ops"], ctx)
        after = [a.model_dump() for a in ctx.records.applications if a.candidate_id == "candidate_demo_a"]
        self.assertEqual(before, after)

    def test_conflicting_or_duplicate_results_for_same_key_rejected(self):
        doc = support.ext_raw()
        twin = copy.deepcopy(result_doc(doc, "eligibility_a_data"))
        twin["id"] = "eligibility_a_data_again"
        doc["eligibility_results"].append(twin)
        with self.assertRaises(ContractViolation) as ctx:
            check_eligibility_results(support.ext_results(doc), support.ext_context(doc))
        self.assertEqual(ctx.exception.code, "duplicate_result")


class PolicyVersionTests(unittest.TestCase):
    def _expect(self, doc, result_id, code):
        with self.assertRaises(ContractViolation) as ctx:
            check_one(doc, result_id)
        self.assertEqual(ctx.exception.code, code)

    def test_policy_version_mismatch(self):
        doc = support.ext_raw()
        result_doc(doc, "eligibility_a_data")["policy"]["version"] = 2
        self._expect(doc, "eligibility_a_data", "policy_version_mismatch")
        doc = support.ext_raw()
        result_doc(doc, "eligibility_a_data")["policy"]["source_ref"]["version"]["revision_id"] = "82"
        self._expect(doc, "eligibility_a_data", "policy_version_mismatch")

    def test_rule_version_or_set_mismatch(self):
        doc = support.ext_raw()
        outcome_doc(result_doc(doc, "eligibility_a_data"), "PILOT-AVAIL-003")["rule_version"] = 2
        self._expect(doc, "eligibility_a_data", "rule_set_mismatch")
        doc = support.ext_raw()
        res = result_doc(doc, "eligibility_a_data")
        res["rule_outcomes"] = [o for o in res["rule_outcomes"] if o["rule_id"] != "PILOT-SKILL-004"]
        self._expect(doc, "eligibility_a_data", "rule_set_mismatch")

    def test_policy_must_cover_opportunity_and_org(self):
        doc = support.ext_raw()
        result_doc(doc, "eligibility_c_job")["policy"] = copy.deepcopy(result_doc(doc, "eligibility_a_data")["policy"])
        with self.assertRaises(ValidationError):  # pinned policy source is in another org
            EligibilityResult.model_validate(result_doc(doc, "eligibility_c_job"))
        doc = support.ext_raw()
        doc["policies"][0]["program_id"] = None
        doc["policies"][0]["rules"][1]["program_id"] = "program_demo_001"
        opp = next(o for o in support.raw()["opportunities"] if o["id"] == "opportunity_demo_data")
        self.assertEqual(opp["program_id"], "program_demo_001")
        check_one(doc, "eligibility_a_data")  # unscoped policy covers any org opportunity

    def test_program_scoped_policy_cannot_assess_outside_its_program(self):
        doc = support.ext_raw()
        doc["policies"][0]["program_id"] = "program_demo_other"
        doc["policies"][0]["rules"][1]["program_id"] = "program_demo_other"
        self._expect(doc, "eligibility_a_data", "policy_scope_mismatch")

    def test_opportunity_version_must_be_pinned_exactly(self):
        doc = support.ext_raw()
        result_doc(doc, "eligibility_a_data")["opportunity_ref"]["version"]["revision_id"] = "40"
        self._expect(doc, "eligibility_a_data", "opportunity_version_mismatch")

    def test_policy_versions_are_immutable(self):
        doc = support.ext_raw()
        changed = copy.deepcopy(doc["policies"][0])
        changed["rules"] = changed["rules"][:3]
        policies = [PolicySet.model_validate(p) for p in doc["policies"]] + [PolicySet.model_validate(changed)]
        with self.assertRaises(ContractViolation) as ctx:
            check_policy_sets(policies, support.ext_records(), support.ext_capabilities())
        self.assertEqual(ctx.exception.code, "policy_version_conflict")
        bumped = {**copy.deepcopy(doc["policies"][0]), "version": 2}
        with self.assertRaises(ContractViolation) as ctx:  # new version must have its own source version
            check_policy_sets([PolicySet.model_validate(doc["policies"][0]), PolicySet.model_validate(bumped)],
                              support.ext_records(), support.ext_capabilities())
        self.assertEqual(ctx.exception.code, "policy_version_conflict")

    def test_policy_rule_shape(self):
        with self.assertRaises(ValidationError):
            PolicyRule(rule_id="PILOT-PROGRAM-002", rule_version=1, kind="program_participation_confirmed")
        with self.assertRaises(ValidationError):
            PolicyRule(rule_id="PILOT-ACTIVE-001", rule_version=1, kind="opportunity_status_active", program_id="program_demo_001")
        for bad in ("pilot-active-001", "PILOT-ACTIVE", "PILOT_ACTIVE_001"):
            with self.subTest(rule_id=bad), self.assertRaises(ValidationError):
                PolicyRule(rule_id=bad, rule_version=1, kind="opportunity_status_active")
        dup = copy.deepcopy(support.ext_raw()["policies"][0])
        dup["rules"].append(dup["rules"][0])
        with self.assertRaises(ValidationError):
            PolicySet.model_validate(dup)


class OutcomeSupportTests(unittest.TestCase):
    """Outcomes must be supported by cited inputs; missing/inferred/contested facts never support failure."""

    def _expect(self, mutate, result_id, code):
        doc = support.ext_raw()
        mutate(result_doc(doc, result_id), doc)
        with self.assertRaises((ContractViolation, ValidationError)) as ctx:
            check_one(doc, result_id)
        if isinstance(ctx.exception, ContractViolation):
            self.assertEqual(ctx.exception.code, code)
        else:
            self.assertIsNone(code, "expected a ContractViolation, got a model validation error")

    def _set(self, rule_id, **fields):
        def mutate(res, _doc):
            outcome_doc(res, rule_id).update(fields)
            res["decision"] = "ineligible" if any(
                o["result"] == "fail" for o in res["rule_outcomes"]) else (
                "needs_information" if any(o["result"] == "unknown" for o in res["rule_outcomes"]) else "eligible")
        return mutate

    def test_missing_qualification_cannot_fail(self):
        self._expect(self._set("PILOT-SKILL-004", result="fail", reason_code="qualification_contradicted_by_declaration",
                               claim_ids=[]), "eligibility_e_data", "unsupported_outcome")

    def test_inferred_or_contested_cannot_support_pass_or_fail(self):
        self._expect(self._set("PILOT-SKILL-004", result="pass", reason_code="qualification_declared"),
                     "eligibility_e_data", "non_authoritative_input")
        self._expect(self._set("PILOT-SKILL-004", result="fail", reason_code="qualification_contradicted_by_declaration"),
                     "eligibility_b_data", "non_authoritative_input")

    def test_inferred_lacks_cannot_fail(self):
        def mutate(res, doc):
            claim = next(c for c in doc["claims"] if c["id"] == "claim_e_python_inferred")
            claim["value"]["presence"] = "lacks"
            self._set("PILOT-SKILL-004", result="fail", reason_code="qualification_contradicted_by_declaration")(res, doc)
        self._expect(mutate, "eligibility_e_data", "non_authoritative_input")

    def test_declared_versus_verified_distinction(self):
        self._expect(self._set("PILOT-SKILL-004", reason_code="qualification_independently_verified"),
                     "eligibility_a_data", "unsupported_outcome")
        self._expect(self._set("PILOT-SKILL-004", reason_code="qualification_contradicted_by_verification"),
                     "eligibility_d_data", "unsupported_outcome")

    def test_unknown_reason_must_match_inputs(self):
        self._expect(self._set("PILOT-SKILL-004", reason_code="qualification_only_inferred"),
                     "eligibility_b_data", "unsupported_outcome")
        self._expect(self._set("PILOT-AVAIL-003", reason_code="availability_contested"),
                     "eligibility_e_data", "unsupported_outcome")

    def test_not_evidenced_is_valid_when_no_source_backed_claim_exists(self):
        doc = support.ext_raw()
        outcome_doc(result_doc(doc, "eligibility_e_data"), "PILOT-SKILL-004").update(
            reason_code="qualification_not_evidenced", claim_ids=[])
        check_one(doc, "eligibility_e_data")

    def test_availability_support(self):
        self._expect(self._set("PILOT-AVAIL-003", result="fail", reason_code="availability_below_required_hours"),
                     "eligibility_a_data", "unsupported_outcome")  # 20 >= 12
        self._expect(self._set("PILOT-AVAIL-003", requirement_ids=["requirement_ops_hours"]),
                     "eligibility_a_data", "invalid_citation")
        self._expect(self._set("PILOT-AVAIL-003", result="unknown", reason_code="availability_not_declared", claim_ids=[]),
                     "eligibility_a_data", "unsupported_outcome")

    def test_participation_support(self):
        self._expect(self._set("PILOT-PROGRAM-002", participation_ids=["participation_d"]),
                     "eligibility_a_data", "invalid_citation")
        self._expect(self._set("PILOT-PROGRAM-002", result="unknown", reason_code="participation_not_recorded",
                               participation_ids=[]), "eligibility_b_data", "unsupported_outcome")
        self._expect(self._set("PILOT-PROGRAM-002", result="pass", reason_code="participation_confirmed"),
                     "eligibility_d_data", "unsupported_outcome")

    def test_active_status_support(self):
        self._expect(self._set("PILOT-ACTIVE-001", result="pass", reason_code="opportunity_active"),
                     "eligibility_a_ops", "unsupported_outcome")

    def test_citing_another_candidates_claim_rejected(self):
        self._expect(self._set("PILOT-AVAIL-003", claim_ids=["claim_d_availability"]),
                     "eligibility_a_data", "invalid_citation")


class IntegrityGateTests(unittest.TestCase):
    """Refinement B: integrity/authorization failures fail closed BEFORE eligibility (mock authority)."""

    def setUp(self):
        self.ctx = support.ext_context()
        self.result = next(r for r in support.ext_results() if r.id == "eligibility_a_data")
        self.refs = eligibility_source_refs(self.result, self.ctx)
        self.authority = support.scenario_authority()
        self.caps = support.ext_capabilities()

    def _gate(self):
        require_sources_admissible(self.refs, self.authority, support.COORDINATOR, self.caps)

    def test_gate_covers_every_dependency(self):
        entity_types = {r.entity.entity_type for r in self.refs}
        self.assertEqual(entity_types, {"opportunity", "policy_set", "candidate_profile", "application", "program_enrollment"})
        self._gate()

    def _expect(self, ref, version, access, code):
        self.authority.set(support.COORDINATOR, ref, version, access)
        with self.assertRaises(ContractViolation) as ctx:
            self._gate()
        self.assertEqual(ctx.exception.code, code)

    def test_failures_raise_rather_than_becoming_unknown(self):
        profile = self.ctx.evidence["evidence_a_profile_hours"].source_ref
        enrollment = self.ctx.evidence["evidence_a_enrollment"].source_ref
        cases = [
            (profile, VersionStatus.CURRENT, AccessStatus.DENIED, "source_access_denied"),
            (profile, VersionStatus.SUPERSEDED, AccessStatus.ALLOWED, "source_not_current"),
            (enrollment, VersionStatus.UNAVAILABLE, AccessStatus.ALLOWED, "source_unavailable"),
            (self.result.opportunity_ref, VersionStatus.DELETED, AccessStatus.ALLOWED, "source_deleted"),
            (self.result.policy.source_ref, VersionStatus.WITHDRAWN, AccessStatus.ALLOWED, "source_withdrawn"),
        ]
        for ref, version, access, code in cases:
            with self.subTest(code=code):
                self.authority = support.scenario_authority()
                self._expect(ref, version, access, code)

    def test_authority_error_fails_closed(self):
        self.authority.raise_error = True
        with self.assertRaises(ContractViolation) as ctx:
            self._gate()
        self.assertEqual(ctx.exception.code, "source_check_error")

    def test_other_principal_denied(self):
        with self.assertRaises(ContractViolation) as ctx:
            require_sources_admissible(self.refs, self.authority, "principal_demo_unrelated", self.caps)
        self.assertEqual(ctx.exception.code, "source_access_denied")


class RequirementTests(unittest.TestCase):
    def _check(self, doc):
        check_requirements(support.ext_context(doc), support.ext_capabilities())

    def _expect(self, doc, code):
        with self.assertRaises(ContractViolation) as ctx:
            self._check(doc)
        self.assertEqual(ctx.exception.code, code)

    def test_fixture_requirements_valid(self):
        self._check(support.ext_raw())

    def test_requirement_must_pin_opportunity_source_version(self):
        doc = support.ext_raw()
        doc["requirements"][0]["source_ref"]["version"]["revision_id"] = "40"
        self._expect(doc, "requirement_source_mismatch")
        doc = support.ext_raw()
        doc["requirements"][0]["source_ref"] = copy.deepcopy(doc["requirements"][2]["source_ref"])  # web's source
        self._expect(doc, "requirement_source_mismatch")

    def test_requirement_may_come_from_covering_policy_source(self):
        doc = support.ext_raw()
        doc["requirements"][0]["source_ref"] = copy.deepcopy(doc["policies"][0]["source_ref"])
        self._check(doc)

    def test_cross_org_requirement_rejected(self):
        doc = support.ext_raw()
        doc["requirements"][4]["opportunity_id"] = "opportunity_demo_data"  # org_demo_002 record
        self._expect(doc, "cross_org_reference")

    def test_conflicting_or_duplicate_requirements_rejected(self):
        doc = support.ext_raw()
        doc["requirements"].append({**copy.deepcopy(doc["requirements"][0]), "id": "requirement_data_hours_2"})
        self._expect(doc, "requirement_conflict")
        doc = support.ext_raw()
        doc["requirements"].append({**copy.deepcopy(doc["requirements"][1]), "id": "requirement_data_python_2"})
        self._expect(doc, "duplicate_requirement")

    def test_qualification_code_must_be_in_vocabulary(self):
        doc = support.ext_raw()
        doc["requirements"][1]["requirement"]["skill_code"] = "rust"
        self._expect(doc, "unsupported_claim_code")

    def test_requirement_shape(self):
        base = support.ext_raw()["requirements"][0]
        for bad in ({"kind": "weekly_hours", "hours_per_week": 200}, {"kind": "weekly_hours"},
                    {"kind": "minimum_age", "years": 18}):
            with self.subTest(requirement=bad), self.assertRaises(ValidationError):
                OpportunityRequirement.model_validate({**base, "requirement": bad})


class PortabilityTests(unittest.TestCase):
    def test_job_result_uses_same_contracts_with_independent_policy(self):
        job = next(r for r in support.ext_results() if r.id == "eligibility_c_job")
        self.assertEqual(job.organization_id, "org_demo_002")
        self.assertEqual(job.policy.policy_set_id, "policy_lantern_jobs")
        check_eligibility_result(job, support.ext_context())


if __name__ == "__main__":
    unittest.main()


class ProgramScopeTests(unittest.TestCase):
    """R1: a participation rule for Program A cannot establish eligibility for a Program B opportunity.

    Builds a second program and opportunity in org_demo_001 locally (not added to the shared fixture).
    """

    def setUp(self):
        import dataclasses

        from rap_contracts.claims import ProgramParticipation
        from rap_contracts.invariants import ContractRecordSet
        from rap_contracts.models import Opportunity, Program
        from rap_contracts.source_checks import canonical_json_sha256

        base = support.ext_context()
        program_b = Program.model_validate({
            "id": "program_demo_002", "organization_id": "org_demo_001",
            "source_ref": {"organization_id": "org_demo_001",
                           "entity": {"source_system": "fixture", "entity_type": "program", "entity_id": "3002"},
                           "version": {"kind": "logical_snapshot", "method": "sha256-canonical-json/v1",
                                       "token": canonical_json_sha256({"fixture": "program-3002"}),
                                       "captured_at": "2026-10-28T12:00:00Z",
                                       "captured_by": "fixture-adapter/0.2.0-dev.foundations.2"}}})
        self.opp_b_ref = {"organization_id": "org_demo_001",
                          "entity": {"source_system": "fixture", "entity_type": "opportunity", "entity_id": "4004"},
                          "version": {"kind": "native_revision", "revision_id": "44"}}
        opp_b = Opportunity.model_validate({"id": "opportunity_demo_events", "organization_id": "org_demo_001",
                                            "opportunity_type": "internship", "status": "active",
                                            "program_id": "program_demo_002", "source_ref": self.opp_b_ref})
        opp_none = Opportunity.model_validate({"id": "opportunity_demo_unaffiliated", "organization_id": "org_demo_001",
                                               "opportunity_type": "job", "status": "active",
                                               "source_ref": {**self.opp_b_ref, "entity": {**self.opp_b_ref["entity"], "entity_id": "4005"}}})
        part_b = ProgramParticipation.model_validate({
            "id": "participation_a_program_b", "organization_id": "org_demo_001", "candidate_id": "candidate_demo_a",
            "program_id": "program_demo_002", "status": "confirmed", "evidence_ids": ["evidence_a_enrollment"]})
        records = ContractRecordSet(**{**base.records.__dict__,
                                       "programs": base.records.programs + (program_b,),
                                       "opportunities": base.records.opportunities + (opp_b, opp_none)})
        self.unscoped_policy_doc = {
            "id": "policy_demo_org_wide", "organization_id": "org_demo_001", "version": 1,
            "source_ref": {"organization_id": "org_demo_001",
                           "entity": {"source_system": "fixture", "entity_type": "policy_set", "entity_id": "8002"},
                           "version": {"kind": "native_revision", "revision_id": "82"}},
            "rules": [{"rule_id": "ORG-ACTIVE-001", "rule_version": 1, "kind": "opportunity_status_active"},
                      {"rule_id": "ORG-PROGRAM-002", "rule_version": 1, "kind": "program_participation_confirmed",
                       "program_id": "program_demo_001"}]}
        self.base, self.records, self.part_b = base, records, part_b
        self.replace = dataclasses.replace

    def _ctx(self, policy_doc, extra_parts=()):
        return self.replace(self.base, records=self.records,
                            policies=self.base.policies + (PolicySet.model_validate(policy_doc),),
                            participations=self.base.participations + tuple(extra_parts))

    def _result(self, policy_doc, opportunity_id, opportunity_ref, participation_id):
        return EligibilityResult.model_validate({
            "id": "eligibility_a_scope_case", "organization_id": "org_demo_001", "candidate_id": "candidate_demo_a",
            "opportunity_id": opportunity_id, "opportunity_ref": opportunity_ref,
            "policy": {"policy_set_id": policy_doc["id"], "version": policy_doc["version"], "source_ref": policy_doc["source_ref"]},
            "rule_outcomes": [
                {"rule_id": "ORG-ACTIVE-001", "rule_version": 1, "rule_kind": "opportunity_status_active",
                 "result": "pass", "reason_code": "opportunity_active"},
                {"rule_id": "ORG-PROGRAM-002", "rule_version": 1, "rule_kind": "program_participation_confirmed",
                 "result": "pass", "reason_code": "participation_confirmed", "participation_ids": [participation_id]}],
            "decision": "eligible", "evaluated_at": "2026-10-28T12:00:00Z",
            "evaluated_by": "fixture-expected-label/0.2.0-dev.foundations.2"})

    def _expect(self, ctx, result, code):
        with self.assertRaises(ContractViolation) as caught:
            check_eligibility_result(result, ctx)
        self.assertEqual(caught.exception.code, code)

    def test_program_a_participation_rejected_for_program_b_opportunity(self):
        """Unscoped org-wide policy; rule names Program A; opportunity is in Program B; candidate is in Program A."""
        ctx = self._ctx(self.unscoped_policy_doc)
        result = self._result(self.unscoped_policy_doc, "opportunity_demo_events", self.opp_b_ref, "participation_a")
        self._expect(ctx, result, "participation_program_mismatch")

    def test_rejected_even_when_candidate_also_participates_in_program_b(self):
        ctx = self._ctx(self.unscoped_policy_doc, [self.part_b])
        result = self._result(self.unscoped_policy_doc, "opportunity_demo_events", self.opp_b_ref, "participation_a")
        self._expect(ctx, result, "participation_program_mismatch")

    def test_participation_rule_rejected_for_opportunity_without_program(self):
        ctx = self._ctx(self.unscoped_policy_doc)
        ref = {**self.opp_b_ref, "entity": {**self.opp_b_ref["entity"], "entity_id": "4005"}}
        result = self._result(self.unscoped_policy_doc, "opportunity_demo_unaffiliated", ref, "participation_a")
        self._expect(ctx, result, "participation_program_mismatch")

    def test_program_scoped_policy_for_a_rejected_for_program_b_opportunity(self):
        scoped = copy.deepcopy(self.unscoped_policy_doc)
        scoped["program_id"] = "program_demo_001"
        ctx = self._ctx(scoped)
        result = self._result(scoped, "opportunity_demo_events", self.opp_b_ref, "participation_a")
        self._expect(ctx, result, "policy_scope_mismatch")

    def test_matching_program_b_rule_is_accepted(self):
        doc_b = copy.deepcopy(self.unscoped_policy_doc)
        doc_b["rules"][1]["program_id"] = "program_demo_002"
        ctx = self._ctx(doc_b, [self.part_b])
        check_eligibility_result(self._result(doc_b, "opportunity_demo_events", self.opp_b_ref, "participation_a_program_b"), ctx)
        self._expect(ctx, self._result(doc_b, "opportunity_demo_events", self.opp_b_ref, "participation_a"),
                     "unsupported_outcome")  # Program A record cannot satisfy a Program B rule

    def test_policy_rule_program_must_match_policy_scope(self):
        scoped = copy.deepcopy(self.unscoped_policy_doc)
        scoped["program_id"] = "program_demo_002"
        with self.assertRaises(ValidationError):
            PolicySet.model_validate(scoped)
