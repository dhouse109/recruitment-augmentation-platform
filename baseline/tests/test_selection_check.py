"""L2 metadata-only projection-selection verification (PR-S2, P2b): plan rev. 2.2 sections 5 and 6.3 (N8a-N8h).

Projection faults are injected by patching ``engine.project`` (the name the engine
imported). Each must become ``Errored(SELECTION, projection_selection_mismatch)``
with zero authority calls -- including faults PR-S1 silently assessed (N8a, N8e,
N8f, N8g) or misreported as data refusals (N8b-N8d).
"""

import dataclasses
import inspect
import unittest
from unittest import mock

from builders import ANA, BEN, CY, DATA, OPS, OTHER, OTHER_PROGRAM, PATHWAYS, WEB, ORG, StubAuthority, World, run
from rap_baseline import Assessed, Errored, Refused, Stage, assess, engine, selection_check
from rap_baseline.inputs import project as real_project


def records(p, **kw):
    return dataclasses.replace(p, records=dataclasses.replace(p.records, **kw))


def with_extra_applications(w: World) -> World:
    w.applications.append({**World._application(ANA, ORG, WEB, PATHWAYS), "id": "application_s1_ana_web"})
    w.applications.append({**World._application(ANA, ORG, OTHER, OTHER_PROGRAM), "id": "application_s1_ana_other"})
    return w


class ProjectionFaultTests(unittest.TestCase):
    def faulty(self, world, mutate, cand=ANA, opp=DATA):
        ctx, caps = world.build()
        auth = StubAuthority()
        with mock.patch.object(engine, "project", lambda c, t: mutate(real_project(c, t), c)):
            out = assess(world.request(cand, opp), ctx, auth, caps)
        return out, auth

    def assert_selection_error(self, world, mutate, **kw):
        out, auth = self.faulty(world, mutate, **kw)
        self.assertIsInstance(out, Errored, str(out))
        self.assertEqual((out.stage, out.code), (Stage.SELECTION, "projection_selection_mismatch"), out.detail)
        self.assertEqual(out.authority_calls, 0)
        self.assertEqual(auth.calls, [])

    def test_n8a_omitted_selected_claim(self):
        self.assert_selection_error(World(), lambda p, c: dataclasses.replace(
            p, claims=tuple(x for x in p.claims if x.id != "claim_s1_ana_python_app")))

    def test_n8b_omitted_application_target_opportunity(self):
        self.assert_selection_error(with_extra_applications(World()), lambda p, c: records(
            p, opportunities=tuple(o for o in p.records.opportunities if o.id != WEB)))

    def test_n8c_omitted_application_target_program(self):
        self.assert_selection_error(with_extra_applications(World()), lambda p, c: records(
            p, programs=tuple(x for x in p.records.programs if x.id != OTHER_PROGRAM)))

    def test_n8d_omitted_vocabulary(self):
        self.assert_selection_error(World(), lambda p, c: dataclasses.replace(p, vocabularies=()))

    def test_n8e_added_unselected_claim(self):
        def add(p, c):
            extra = next(x for x in c.claims if x.id == "claim_s1_ana_remote")
            return dataclasses.replace(p, claims=p.claims + (extra,), evidence={
                **dict(p.evidence), "evidence_s1_ana_remote": c.evidence["evidence_s1_ana_remote"]})
        self.assert_selection_error(World(), add)

    def test_n8f_omitted_participation(self):
        self.assert_selection_error(World(), lambda p, c: dataclasses.replace(p, participations=()))

    def test_n8g_omitted_application(self):
        self.assert_selection_error(with_extra_applications(World()), lambda p, c: records(
            p, applications=tuple(a for a in p.records.applications if a.id != "application_s1_ana_web")))

    def test_n8h_substituted_record_under_the_same_id(self):
        self.assert_selection_error(World(), lambda p, c: dataclasses.replace(
            p, claims=tuple(x.model_copy() if x.id == "claim_s1_ana_hours" else x for x in p.claims)))

    def test_other_collections(self):
        cases = {
            "requirement": lambda p, c: dataclasses.replace(p, requirements=p.requirements[:-1]),
            "profile": lambda p, c: records(p, profiles=()),
            "extra_program": lambda p, c: records(p, programs=p.records.programs + tuple(
                x for x in c.records.programs if x.id == "program_s1_beta")),
            "substituted_evidence": lambda p, c: dataclasses.replace(p, evidence={
                k: (v.model_copy() if k == "evidence_s1_ana_hours" else v) for k, v in p.evidence.items()}),
            "reordered_claims": lambda p, c: dataclasses.replace(p, claims=tuple(reversed(p.claims))),
            "substituted_policy": lambda p, c: dataclasses.replace(p, policies=(p.policies[0].model_copy(),)),
        }
        for label, mutate in cases.items():
            with self.subTest(label):
                self.assert_selection_error(World(), mutate)

    def test_without_l2_a_coherent_omission_is_silently_assessed(self):
        """Why L2 is needed: L1 sees only the admitted projection, so an omission that removes a record AND
        its evidence is internally consistent and would be assessed (as PR-S1 did for N8f). A partial
        omission (record without its evidence) is still caught later by L1's provenance closure."""
        def coherent(p, c):
            return dataclasses.replace(p, participations=(), evidence={
                k: v for k, v in p.evidence.items() if k != "evidence_s1_ana_enrollment"})
        with mock.patch.object(engine, "verify_selection", lambda *a: None):
            out, _ = self.faulty(World(), coherent)
            self.assertIsInstance(out, Assessed)
            self.assertEqual(next(o for o in out.result.rule_outcomes if o.rule_id == "S1-PROGRAM-002").reason_code,
                             "participation_not_recorded")
            out, _ = self.faulty(World(), lambda p, c: dataclasses.replace(p, participations=()))
            self.assertEqual((out.stage, out.code), (Stage.FINDINGS, "findings_verification_failed"))
            self.assertTrue(out.detail.startswith("provenance_mismatch:"))
            out, _ = self.faulty(World(), lambda p, c: dataclasses.replace(p, vocabularies=()))
            self.assertEqual((out.stage, out.code), (Stage.STRUCTURE, "unknown_vocabulary"))
        self.assert_selection_error(World(), coherent)


class CorrectProjectionTests(unittest.TestCase):
    """L2 never fails on a correct projection, so PR-S1 outcomes and refusal precedence are unchanged."""

    def test_sweep_never_selection_errors(self):
        worlds = [World(), with_extra_applications(World())]
        for w in worlds:
            for cand in (ANA, BEN, CY):
                for opp in (DATA, WEB, OPS, OTHER):
                    with self.subTest(cand=cand, opp=opp):
                        out, _ = run(w, cand, opp)
                        self.assertFalse(isinstance(out, Errored) and out.stage is Stage.SELECTION, str(out))

    def test_cross_organization_record_is_still_refused_by_p3(self):
        w = World()
        w.claim("claim_s1_ana_hours").update(organization_id="org_s1_beta")
        out, auth = run(w, ANA, DATA)
        self.assertIsInstance(out, Refused)
        self.assertEqual((out.stage, out.code), (Stage.PROJECTION, "cross_org_reference"))
        self.assertEqual(auth.calls, [])


class InventoryTests(unittest.TestCase):
    """A8: L2 copies exactly the metadata inventory of plan section 5 -- no value fields."""

    def test_inventory_is_exact(self):
        self.assertEqual(selection_check.INVENTORY, {
            "requirements": ("id", "opportunity_id", "kind", "skill_code", "vocabulary_pin", "ref"),
            "claims": ("id", "candidate_id", "claim_type", "subject_code", "vocabulary_pin", "evidence_ids", "ref"),
            "participations": ("id", "candidate_id", "program_id", "evidence_ids", "ref"),
            "applications": ("id", "candidate_id", "target_opportunity_id", "target_program_id", "ref"),
            "profiles": ("id", "candidate_id", "ref"),
            "opportunities": ("id", "program_id", "ref"),
            "programs": ("id", "ref"),
            "candidates": ("id", "ref"),
            "policies": ("id", "version", "program_id", "rule_kinds", "rule_programs", "ref"),
            "vocabularies": ("pin", "ref"),
            "evidence": ("key", "ref"),
        })

    def test_metadata_view_matches_inventory(self):
        ctx, _ = World().build()
        view = selection_check.metadata_view(ctx)
        self.assertEqual(set(view), set(selection_check.INVENTORY))
        for name, entries in view.items():
            for entry in entries:
                fields = ("key", "ref") if name == "evidence" else entry._fields
                self.assertEqual(tuple(fields), selection_check.INVENTORY[name])

    def test_interface_takes_no_authority(self):
        self.assertEqual(list(inspect.signature(selection_check.verify_selection).parameters),
                         ["supplied", "targets", "projected"])


if __name__ == "__main__":
    unittest.main()
