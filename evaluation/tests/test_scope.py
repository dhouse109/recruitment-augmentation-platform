"""Ownership, scoped construction, the cross-scope and held-out guards, organization scoping and the mock authority."""

from __future__ import annotations

import unittest
from unittest import mock

from helpers import AS_OF, LazyClassFixture, TempDirTest, admitted, config, products, real_fixtures
from rap_contracts.models import AccessStatus, VersionStatus

from rap_evaluation import MOCK_AUTHORITY_ID, AdmissionAbort, scope
from rap_evaluation.authority import FixtureMockAuthority
from rap_evaluation.run import run_evaluation

GOLDEN = {"candidate_demo_a", "candidate_demo_b", "candidate_demo_c", "candidate_demo_g"}  # G: golden v2 (F3)
HELD_OUT = {"candidate_demo_d", "candidate_demo_e"}


class OwnershipTests(unittest.TestCase):
    def test_held_out_candidates_are_derived_from_the_golden_scopes(self):
        g = admitted().graph
        self.assertEqual(set(g.golden_candidates), GOLDEN)
        self.assertEqual(set(g.held_out_candidates), HELD_OUT)

    def test_held_out_identifiers_cover_their_records(self):
        ids = admitted().graph.held_out_identifiers
        for expected in ("candidate_demo_d", "candidate_demo_e", "eligibility_d_data", "profile_demo_d", "claim_e_python_inferred"):
            self.assertIn(expected, ids)
        self.assertFalse(ids & {"candidate_demo_a", "candidate_demo_b", "candidate_demo_c", "candidate_demo_g"})

    def test_every_owner_is_resolved(self):
        g = admitted().graph
        self.assertTrue(all(o is None or o in GOLDEN | HELD_OUT for o in g.owners.values()))
        self.assertTrue(all(o is not None for (k, _), o in g.owners.items() if k != "evidence"))


class ScopedConstructionTests(TempDirTest):
    def test_each_scope_constructs_only_its_own_candidate_records(self):
        adm = admitted()
        g = adm.graph
        for case in adm.selected:
            s = adm.scopes[case.id]
            self.assertEqual(s.candidates, frozenset(case.scope.candidates))
            for kind, rid in s.constructed:
                self.assertIn(g.owners[(kind, rid)], s.candidates, (case.id, kind, rid))
            self.assertEqual({c.id for c in s.eligibility.records.candidates}, set(case.scope.candidates))
            self.assertTrue(all(c.candidate_id in s.candidates for c in s.eligibility.claims))
            self.assertTrue(all(p.candidate_id in s.candidates for p in s.eligibility.participations))

    def test_no_held_out_owned_model_is_constructed_anywhere(self):
        adm = admitted()
        for s in adm.scopes.values():
            built = {rid for _, rid in s.constructed} | set(s.eligibility.evidence)
            self.assertFalse(built & adm.graph.held_out_identifiers)
            text = repr(s.eligibility)
            for cand in HELD_OUT:
                self.assertNotIn(cand, text)

    def test_labels_are_never_constructed(self):
        for s in admitted().scopes.values():
            self.assertFalse(hasattr(s.eligibility, "results"))
            self.assertFalse([k for k, _ in s.constructed if k == "eligibility_results"])

    def _inject(self, owner: str):
        pool = scope.raw_pool(real_fixtures().layers)
        intruder = next(r for r in pool["claims"] if r["candidate_id"] == owner)
        real = scope.select

        def select(kind, pool_, graph, cands):
            got = real(kind, pool_, graph, cands)
            return got + [intruder] if kind == "claims" else got
        return mock.patch.object(scope, "select", side_effect=select)

    def test_injected_held_out_record_is_refused_before_construction(self):
        out = self.tmp / "o" / "run"
        with self._inject("candidate_demo_d"), self.assertRaises(AdmissionAbort) as cm:
            run_evaluation(config(out), assess_fn=lambda *a: self.fail("engine called"))
        self.assertEqual((cm.exception.check, cm.exception.code), ("A6", "held_out_construction"))
        self.assertNothingPublished(out)

    def test_injected_other_golden_candidate_record_is_refused(self):
        out = self.tmp / "o" / "run"
        with self._inject("candidate_demo_c"), self.assertRaises(AdmissionAbort) as cm:
            run_evaluation(config(out), assess_fn=lambda *a: self.fail("engine called"))
        self.assertEqual((cm.exception.check, cm.exception.code), ("A6", "cross_scope_construction"))
        self.assertNothingPublished(out)


class OrganizationScopingTests(LazyClassFixture):
    """Synthetic organization scoping: every generated result, gated source and check stays in the key's organization."""

    @classmethod
    def _fixture(cls):
        cls.p = products()

    def test_scope_contains_another_organizations_shared_records(self):
        s = admitted().scopes["evalcase_g003"]
        self.assertIn("org_demo_002", {o.organization_id for o in s.eligibility.records.opportunities})

    def test_generated_results_and_provenance_stay_in_the_key_organization(self):
        self.assertEqual(len(self.p.entries), 5)
        for e in self.p.entries:
            org = e.key.organization_id
            self.assertEqual(e.result.organization_id, org)
            refs = e.provenance["gated_refs"]
            self.assertTrue(refs)
            self.assertEqual({r["organization_id"] for r in refs}, {org})
            self.assertEqual({c["source"]["organization_id"] for c in e.provenance["checks"]}, {org})
            self.assertEqual({c["checked_by"] for c in e.provenance["checks"]}, {MOCK_AUTHORITY_ID})


class MockAuthorityTests(unittest.TestCase):
    def test_in_scope_refs_allowed_for_declared_principals_only(self):
        s = admitted().scopes["evalcase_g002"]
        ref = next(iter(s.source_refs))
        auth = FixtureMockAuthority(["principal_demo_coordinator"], s.source_refs, AS_OF)
        ok = auth.check("principal_demo_coordinator", ref)
        self.assertEqual((ok.version_status, ok.access_status), (VersionStatus.CURRENT, AccessStatus.ALLOWED))
        self.assertEqual((ok.checked_at, ok.checked_by), (AS_OF, MOCK_AUTHORITY_ID))
        other = auth.check("principal_demo_viewer", ref)
        self.assertEqual((other.version_status, other.access_status), (VersionStatus.UNAVAILABLE, AccessStatus.DENIED))

    def test_unknown_reference_is_unavailable_and_denied(self):
        s = admitted().scopes["evalcase_g002"]
        auth = FixtureMockAuthority(["principal_demo_coordinator"], [], AS_OF)
        res = auth.check("principal_demo_coordinator", next(iter(s.source_refs)))
        self.assertEqual((res.version_status, res.access_status), (VersionStatus.UNAVAILABLE, AccessStatus.DENIED))


if __name__ == "__main__":
    unittest.main()
