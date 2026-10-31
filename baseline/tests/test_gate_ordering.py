"""S0-R1: organization checks before any authority call; no value read before source admission."""

import ast
import unittest
from pathlib import Path
from types import MappingProxyType
from unittest import mock

import rap_contracts.claims as claims_module
from rap_contracts.models import VersionStatus

from builders import (ANA, AS_OF, CY, DATA, ORG, ORG2, OTHER, PILOT, BETA_JOB, BETA_POLICY, StubAuthority,
                      World, ref, run)
from rap_baseline import Assessed, Errored, Refused, Stage, assess, engine, rules
from rap_baseline.inputs import project, resolve_targets

PACKAGE = Path(engine.__file__).resolve().parent
VALUE_ATTRIBUTES = {"value", "alternatives", "state", "status", "presence", "hours_per_week", "stance", "duration_months"}


def spy_run(world: World, cand=ANA, opp=DATA, authority=None):
    """Ordered event log: authority checks, wrapper calls, value comparisons and rule evaluations."""
    log: list = []
    auth = authority or StubAuthority()
    auth.log = log
    ctx, caps = world.build()  # model validators run here, before the log starts
    real_validate, real_conflict = engine.validate_recommendation_inputs, claims_module.values_conflict

    def validate(rctx):
        log.append(("postcheck" if rctx.eligibility_results else "phase2",))
        return real_validate(rctx)

    def conflict(a, b):
        log.append(("value",))
        return real_conflict(a, b)

    def wrap(kind, fn):
        def evaluator(rule, d):
            log.append(("rule", kind.value))
            return fn(rule, d)
        return evaluator

    wrapped = {k: wrap(k, f) for k, f in rules.EVALUATORS.items()}
    with mock.patch.object(engine, "validate_recommendation_inputs", validate), \
            mock.patch.object(claims_module, "values_conflict", conflict), mock.patch.dict(rules.EVALUATORS, wrapped):
        out = assess(world.request(cand, opp), ctx, auth, caps)
    return out, [e[0] for e in log], auth


class OrderingTests(unittest.TestCase):
    def test_all_checks_precede_phase2_and_every_value_read(self):
        out, kinds, _ = spy_run(World())
        self.assertIsInstance(out, Assessed)
        first_other = next(i for i, k in enumerate(kinds) if k != "check")
        self.assertEqual(kinds[first_other], "phase2")
        self.assertNotIn("check", kinds[first_other:])
        self.assertIn("value", kinds, "the scenario exercises a value comparison")
        self.assertLess(kinds.index("phase2"), kinds.index("value"))
        self.assertLess(kinds.index("phase2"), kinds.index("rule"))
        self.assertEqual(kinds.count("rule"), 4)
        self.assertEqual(kinds.index("postcheck"), max(i for i, k in enumerate(kinds) if k == "rule") + 1)

    def test_gate_failure_stops_before_any_value_read_or_rule(self):
        for version in (VersionStatus.SUPERSEDED, VersionStatus.WITHDRAWN):
            with self.subTest(version):
                w = World()
                auth = StubAuthority()
                auth.set(w.evidence_record("evidence_s1_ana_python_app")["source_ref"], version)
                out, kinds, _ = spy_run(w, authority=auth)
                self.assertIsInstance(out, Refused)
                self.assertEqual(set(kinds), {"check"})

    def test_phase2_contradiction_refuses_after_gate_with_no_rule(self):
        w = World()
        w.add_participation("participation_s1_ana_conflict", ANA, "program_s1_pathways", "not_participating", "6121", "51")
        out, kinds, _ = spy_run(w)
        self.assertIsInstance(out, Refused)
        self.assertEqual((out.stage, out.code), (Stage.CONTEXT, "participation_conflict"))
        self.assertIn("check", kinds)
        self.assertNotIn("rule", kinds)
        self.assertNotIn("postcheck", kinds)


class StaticValueAccessTests(unittest.TestCase):
    def test_only_rules_module_reads_value_attributes(self):
        """identity.py is checked separately: its only such access is Enum ``.value`` in canonicalization."""
        for path in sorted(PACKAGE.glob("*.py")):
            if path.name in ("rules.py", "identity.py"):
                continue
            attrs = {n.attr for n in ast.walk(ast.parse(path.read_text(encoding="utf-8"))) if isinstance(n, ast.Attribute)}
            with self.subTest(path.name):
                self.assertEqual(attrs & VALUE_ATTRIBUTES, set())

    def test_identity_module_reads_only_enum_values(self):
        tree = ast.parse((PACKAGE / "identity.py").read_text(encoding="utf-8"))
        hits = [n for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr in VALUE_ATTRIBUTES]
        self.assertEqual([n.attr for n in hits], ["value", "value"])
        enum_branch = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "canonical")
        self.assertTrue(all(any(h is x for x in ast.walk(enum_branch)) for h in hits))

    def test_rules_module_reads_them(self):  # guards the scan itself against vacuity
        attrs = {n.attr for n in ast.walk(ast.parse((PACKAGE / "rules.py").read_text())) if isinstance(n, ast.Attribute)}
        self.assertLessEqual({"value", "state", "status", "presence", "hours_per_week"}, attrs)


class PreAuthorityRefusalTests(unittest.TestCase):
    """Organization, reference and structural failures make zero authority calls."""

    def refused(self, world, cand=ANA, opp=DATA, pin=PILOT, code=None, stage=None, **kw):
        out, auth = run(world, cand, opp, pin, **kw)
        self.assertIsInstance(out, Refused, str(out))
        self.assertEqual(auth.calls, [], f"{out.code}: authority was called")
        self.assertEqual(out.authority_calls, 0)
        if code:
            self.assertEqual(out.code, code)
        if stage:
            self.assertEqual(out.stage, stage)
        return out

    def test_candidate_in_another_organization(self):
        self.refused(World(), CY, DATA, code="cross_org_reference", stage=Stage.REFERENCE)

    def test_opportunity_in_another_organization(self):
        self.refused(World(), ANA, BETA_JOB, PILOT, code="cross_org_reference", stage=Stage.REFERENCE)

    def test_policy_in_another_organization(self):
        self.refused(World(), ANA, DATA, BETA_POLICY, org=ORG, code="cross_org_reference", stage=Stage.REFERENCE)

    def test_selected_claim_in_another_organization(self):
        w = World()
        w.claim("claim_s1_ana_hours").update(organization_id=ORG2)
        self.refused(w, code="cross_org_reference", stage=Stage.PROJECTION)

    def test_cited_evidence_in_another_organization(self):
        w = World()
        e = w.evidence_record("evidence_s1_ana_hours")
        e.update(organization_id=ORG2, source_ref=ref("candidate_profile", "5101", "21", org=ORG2))
        self.refused(w, code="cross_org_reference", stage=Stage.PROJECTION)

    def test_requirement_in_another_organization(self):
        w = World()
        w.requirements.append({"id": "requirement_s1_data_foreign", "organization_id": ORG2, "opportunity_id": DATA,
                               "requirement": {"kind": "mandatory_qualification", "vocabulary": {"id": "vocabulary_s1_beta",
                                               "version": 1}, "skill_code": "spreadsheets"},
                               "source_ref": ref("opportunity", "4201", "15", org=ORG2), "field_path": "qualifications.mandatory"})
        self.refused(w, code="cross_org_reference", stage=Stage.PROJECTION)

    def test_participation_in_another_organization(self):
        w = World()
        next(p for p in w.participations if p["id"] == "participation_s1_ana").update(organization_id=ORG2)
        self.refused(w, code="cross_org_reference", stage=Stage.PROJECTION)

    def test_application_targeting_another_organizations_opportunity(self):
        w = World()
        w.applications[0]["target"] = {"opportunity_id": BETA_JOB}
        self.refused(w, code="cross_org_reference", stage=Stage.PROJECTION)

    def test_unknown_references_and_pin_mismatch(self):
        self.refused(World(), "candidate_s1_nobody", DATA, code="unknown_reference", stage=Stage.REFERENCE)
        self.refused(World(), ANA, "opportunity_s1_nothing", code="unknown_reference", stage=Stage.REFERENCE)
        w = World()
        req = w.request()
        ctx, caps = w.build()
        moved = req.model_copy(update={"policy": req.policy.model_copy(update={"source_ref": req.policy.source_ref.model_copy(
            update={"version": req.policy.source_ref.version.model_copy(update={"revision_id": "80"})})})})
        auth = StubAuthority()
        out = assess(moved, ctx, auth, caps)
        self.assertEqual((out.code, auth.calls), ("policy_version_mismatch", []))

    def test_policy_scope_and_participation_program(self):
        self.refused(World(), ANA, OTHER, code="policy_scope_mismatch", stage=Stage.REFERENCE)
        w = World()
        w.policies.append({**w.policy(), "id": "policy_s1_unscoped", "program_id": None,
                           "source_ref": ref("policy_set", "8102", "83")})
        self.refused(w, ANA, OTHER, ("policy_s1_unscoped", 1), code="participation_program_mismatch", stage=Stage.REFERENCE)

    def test_structural_failures(self):
        w = World()
        w.claim("claim_s1_ana_hours")["evidence_ids"] = ["evidence_s1_missing"]
        self.refused(w, code="invalid_citation", stage=Stage.PROJECTION)
        w = World()
        w.claim("claim_s1_ana_hours")["evidence_ids"] = ["evidence_s1_ben_python_profile"]  # about another candidate
        self.refused(w, code="invalid_citation", stage=Stage.PROJECTION)
        w = World()
        w.vocabularies[0]["skills"].remove("python")
        out = self.refused(w, stage=Stage.STRUCTURE)
        self.assertEqual(out.code, "unsupported_claim_code")

    def test_naive_as_of_is_an_invalid_request(self):
        w = World()
        ctx, caps = w.build()
        doc = w.request().model_dump(mode="python")
        doc["as_of"] = AS_OF.replace(tzinfo=None)
        auth = StubAuthority()
        out = assess(doc, ctx, auth, caps)
        self.assertIsInstance(out, Errored)
        self.assertEqual((out.stage, out.code, auth.calls), (Stage.REQUEST, "invalid_request", []))


class UnselectedSourceTests(unittest.TestCase):
    def test_revoking_a_source_used_only_by_an_unselected_claim_changes_nothing(self):
        baseline, _ = run(World())
        w = World()
        auth = StubAuthority()
        auth.deny(w.evidence_record("evidence_s1_ana_remote")["source_ref"])
        out, _ = run(w, authority=auth)
        self.assertIsInstance(out, Assessed)
        self.assertEqual(out.result.model_dump_json(), baseline.result.model_dump_json())

    def test_inconsistency_among_unselected_claims_is_not_read(self):
        """Phase-2 validation runs on the projection only: unselected claim values are never read."""
        baseline, _ = run(World())
        w = World()
        w.add_statement(ANA, "evidence_s1_ana_remote_2", "preferences.remote_again")
        w.add_claim("claim_s1_ana_remote_2", ANA, "remote", "declared", {"kind": "work_preference", "stance": "does_not_prefer"},
                    ["evidence_s1_ana_remote_2"], claim_type="work_preference")  # conflicts with claim_s1_ana_remote
        out, _ = run(w)
        self.assertIsInstance(out, Assessed, str(out))
        self.assertEqual(out.result.model_dump_json(), baseline.result.model_dump_json())


class ProjectionImmutabilityTests(unittest.TestCase):
    def test_projected_evidence_cannot_be_mutated_between_gate_and_use(self):
        w = World()
        ctx, _ = w.build()
        targets = resolve_targets(w.request(), ctx)
        projected = project(ctx, targets)
        self.assertIsInstance(projected.evidence, MappingProxyType)
        with self.assertRaises(TypeError):
            projected.evidence["evidence_s1_new"] = next(iter(projected.evidence.values()))
        with self.assertRaises(Exception):
            projected.claims[0].state = "unknown"  # frozen contract models


if __name__ == "__main__":
    unittest.main()
