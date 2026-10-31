"""Source-integrity failures are refusals (never unknown outcomes) and the source-dependency set is exact.

The authority is synthetic: these tests show the engine's fail-closed plumbing,
not real Drupal authorization (T4).
"""

import unittest

from rap_contracts.models import VersionStatus

from builders import (ANA, BEN, DATA, HAS, PRINCIPAL, WEB, StubAuthority, World, as_ref, capabilities_doc, ref, run)
from rap_baseline import Assessed, Refused, Stage

MODES = {
    "denied": (lambda a, r: a.deny(r), "source_access_denied"),
    "superseded": (lambda a, r: a.set(r, VersionStatus.SUPERSEDED), "source_not_current"),
    "withdrawn": (lambda a, r: a.set(r, VersionStatus.WITHDRAWN), "source_withdrawn"),
    "deleted": (lambda a, r: a.set(r, VersionStatus.DELETED), "source_deleted"),
    "unavailable": (lambda a, r: a.set(r, VersionStatus.UNAVAILABLE), "source_unavailable"),
    "authority_error": (lambda a, r: a.raise_for.add(as_ref(r)), "source_check_error"),
    "substitution": (lambda a, r: a.substitute.update({as_ref(r): as_ref({**r, "version": {"kind": "native_revision",
                                                                                           "revision_id": "999"}})}),
                     "source_substitution"),
}


def inferred_world():
    """Ana's python known only by inference, on its own source version (profile revision 19)."""
    w = World()
    for cid in ("claim_s1_ana_python_app", "claim_s1_ana_python_profile"):
        w.remove_claim(cid)
    w.add_evidence("evidence_s1_ana_project", ANA, "candidate_statement", ref("candidate_profile", "5101", "19"), "projects.notes")
    w.add_claim("claim_s1_ana_python_inferred", ANA, "python", "inferred", HAS, ["evidence_s1_ana_project"])
    return w


def verified_world():
    w = World()
    w.add_verification(ANA, "evidence_s1_ana_python_verified", "9401", "assessments.python")
    w.add_claim("claim_s1_ana_python_verified", ANA, "python", "declared", HAS, ["evidence_s1_ana_python_verified"])
    return w


#: category -> (world factory, candidate, the source reference document to fail)
CATEGORIES = {
    "opportunity_and_its_requirements": (World, ANA, lambda w: w.opportunity(DATA)["source_ref"]),
    "policy": (World, ANA, lambda w: w.policy()["source_ref"]),
    "availability_evidence": (World, ANA, lambda w: w.evidence_record("evidence_s1_ana_hours")["source_ref"]),
    "skill_statement_evidence": (World, ANA, lambda w: w.evidence_record("evidence_s1_ana_python_app")["source_ref"]),
    "skill_verification_evidence": (verified_world, ANA, lambda w: w.evidence_record("evidence_s1_ana_python_verified")["source_ref"]),
    "participation_evidence": (World, ANA, lambda w: w.evidence_record("evidence_s1_ana_enrollment")["source_ref"]),
    "contested_alternative_evidence": (World, BEN, lambda w: w.evidence_record("evidence_s1_ben_python_app")["source_ref"]),
    "inferred_claim_evidence": (inferred_world, ANA, lambda w: w.evidence_record("evidence_s1_ana_project")["source_ref"]),
}


class GateFailureMatrixTests(unittest.TestCase):
    def test_every_failure_mode_on_every_gated_category_refuses(self):
        for cat, (factory, cand, pick) in CATEGORIES.items():
            for mode, (apply, code) in MODES.items():
                with self.subTest(category=cat, mode=mode):
                    w = factory()
                    auth = StubAuthority()
                    apply(auth, pick(w))
                    out, _ = run(w, cand, DATA, authority=auth)
                    self.assertIsInstance(out, Refused, f"{cat}/{mode}: {out}")
                    self.assertEqual((out.stage, out.code), (Stage.SOURCE_GATE, code))
                    self.assertFalse(hasattr(out, "result"))

    def test_unknown_principal_is_refused(self):
        out, _ = run(World(), principal="principal_s1_stranger")
        self.assertIsInstance(out, Refused)
        self.assertEqual((out.stage, out.code), (Stage.SOURCE_GATE, "source_access_denied"))

    def test_revoked_declared_availability_is_refused_not_not_declared(self):
        w = World()
        auth = StubAuthority()
        auth.deny(w.evidence_record("evidence_s1_ana_hours")["source_ref"])
        out, _ = run(w, ANA, WEB, authority=auth)
        self.assertIsInstance(out, Refused)
        self.assertNotIsInstance(out, Assessed)  # never availability_not_declared

    def test_version_kind_violations_refuse_before_any_authority_call(self):
        w = World()
        w.caps = capabilities_doc()
        w.caps["native_revision_entity_types"].remove("opportunity")  # opportunities now declared snapshot-only
        w.caps["logical_snapshot_entity_types"].append("opportunity")
        out, auth = run(w)
        self.assertIsInstance(out, Refused)
        self.assertEqual((out.stage, out.code, auth.calls), (Stage.STRUCTURE, "native_revision_claim_unsupported", []))


class SourceDependencyTests(unittest.TestCase):
    """Regression tests for the enumerated source dependencies (owner qualification 2)."""

    def gated(self, world, cand=ANA, opp=DATA):
        out, auth = run(world, cand, opp)
        self.assertIsInstance(out, Assessed, str(out))
        return out, auth

    def test_exact_gate_set_for_a_qualification_opportunity(self):
        w = World()
        out, auth = self.gated(w)
        expected = {as_ref(x) for x in (
            w.opportunity(DATA)["source_ref"], w.policy()["source_ref"],
            ref("candidate_profile", "5101", "21"), ref("application", "7101", "71"), ref("program_enrollment", "6101", "31"))}
        self.assertEqual(set(out.provenance.gated_refs), expected)
        self.assertEqual(set(auth.calls), expected)
        self.assertEqual(len(auth.calls), len(expected), "each source is checked once")

    def test_no_mandatory_qualification_means_no_skill_source_is_gated(self):
        out, auth = self.gated(World(), ANA, WEB)
        self.assertNotIn(as_ref(ref("application", "7101", "71")), auth.calls)

    def test_every_result_dependency_was_gated(self):
        from rap_contracts.eligibility import eligibility_source_refs
        for cand in (ANA, BEN):
            with self.subTest(cand):
                w = World()
                out, _ = self.gated(w, cand)
                deps = set(eligibility_source_refs(out.result, w.build()[0]))
                self.assertLessEqual(deps, set(out.provenance.gated_refs))

    def test_both_contested_alternatives_and_inferred_evidence_are_gated(self):
        out, _ = self.gated(World(), BEN)
        self.assertLessEqual({as_ref(ref("candidate_profile", "5102", "22")), as_ref(ref("application", "7102", "72"))},
                             set(out.provenance.gated_refs))
        out, _ = self.gated(inferred_world())
        self.assertIn(as_ref(ref("candidate_profile", "5101", "19")), out.provenance.gated_refs)

    def test_structural_metadata_and_unselected_sources_are_not_gated(self):
        w = World()
        out, auth = self.gated(w)
        never = [as_ref(p["source_ref"]) for p in w.programs] + [as_ref(ref("candidate_profile", "5101", "20"))]
        for r in never:
            self.assertNotIn(r, auth.calls)

    def test_checks_are_recorded_in_provenance(self):
        out, auth = self.gated(World())
        self.assertEqual([c.source for c in out.provenance.checks], auth.calls)
        self.assertTrue(all(c.checked_by == "s1-test-authority/1" for c in out.provenance.checks))
        self.assertEqual(out.provenance.principal_id, PRINCIPAL)


if __name__ == "__main__":
    unittest.main()
