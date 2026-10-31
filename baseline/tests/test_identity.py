"""S0-R2 identity: input fingerprint (IF), output digest (OD), result id, UTC normalization.

The result id identifies a deterministic assessment (IF + UTC as_of), not a
globally unique execution event; principal and checks live in provenance.
"""

import ast
import re
import unittest
from pathlib import Path
from datetime import datetime, timedelta, timezone
from unittest import mock

from builders import (ANA, AS_OF, DATA, EASTERN, HAS, OPS, OTHER_PRINCIPAL, StubAuthority, World,
                      capabilities_doc, hours, ref, run, snapshot)
from rap_baseline import Assessed, EVALUATED_BY, engine, identity, rules
from rap_baseline.identity import IdentityError, canonical, output_digest

ELIGIBILITY_ID = re.compile(r"^eligibility_[a-z0-9]+(?:_[a-z0-9]+)*$")


def assessed(world, **kw):
    out, auth = run(world, **kw)
    assert isinstance(out, Assessed), out
    return out


def bump_opportunity_revision(w):
    new = ref("opportunity", "4101", "16")
    w.opportunity(DATA)["source_ref"] = new
    for r in w.requirements:
        if r["opportunity_id"] == DATA:
            r["source_ref"] = new


def bump_policy_revision(w):
    w.policy()["source_ref"] = ref("policy_set", "8101", "84")


def set_requirement_hours(w):
    next(r for r in w.requirements if r["id"] == "requirement_s1_data_hours")["requirement"]["hours_per_week"] = 13


def bump_evidence_revision(w):
    w.evidence_record("evidence_s1_ana_hours")["source_ref"] = ref("candidate_profile", "5101", "24")


def evidence_to_verification(w):
    e = w.evidence_record("evidence_s1_ana_python_app")
    e.update(basis="independent_verification", source_ref=ref("skill_assessment", "9501", "1"))


def change_field_path(w):
    w.evidence_record("evidence_s1_ana_hours")["field_path"] = "availability.weekly_hours_v2"


def add_corroborating_evidence(w):
    w.add_statement(ANA, "evidence_s1_ana_hours_app", "answers.weekly_hours", source="application")
    w.claim("claim_s1_ana_hours")["evidence_ids"].append("evidence_s1_ana_hours_app")


def change_hours(w):
    w.claim("claim_s1_ana_hours")["value"] = hours(21)


def add_corroborating_claim(w):
    w.add_statement(ANA, "evidence_s1_ana_python_more", "skills.python_more")
    w.add_claim("claim_s1_ana_python_more", ANA, "python", "declared", HAS, ["evidence_s1_ana_python_more"])


def bump_participation_evidence(w):
    w.evidence_record("evidence_s1_ana_enrollment")["source_ref"] = ref("program_enrollment", "6101", "35")


def change_vocabulary_content(w):
    w.vocabularies[0]["skills"].append("statistics")


MUTATIONS = {  # name -> (mutation, decision and citations unchanged?)
    "opportunity_revision": (bump_opportunity_revision, False),
    "policy_revision": (bump_policy_revision, False),
    "requirement_hours_same_outcome": (set_requirement_hours, True),
    "evidence_revision": (bump_evidence_revision, True),
    "evidence_basis": (evidence_to_verification, False),
    "evidence_field_path": (change_field_path, True),
    "claim_gains_evidence": (add_corroborating_evidence, True),
    "declared_hours_same_outcome": (change_hours, True),
    "corroborating_claim_added": (add_corroborating_claim, False),
    "participation_evidence_revision": (bump_participation_evidence, True),
    "vocabulary_content_same_pin": (change_vocabulary_content, True),
}


class NonAliasingTests(unittest.TestCase):
    def test_every_material_input_change_changes_fingerprint_and_id(self):
        base = assessed(World())
        seen = {base.result.id}
        for name, (mutate, same_output) in MUTATIONS.items():
            with self.subTest(name):
                w = World()
                mutate(w)
                out = assessed(w)
                self.assertNotEqual(out.provenance.input_fingerprint, base.provenance.input_fingerprint)
                self.assertNotEqual(out.result.id, base.result.id)
                self.assertNotIn(out.result.id, seen)
                seen.add(out.result.id)
                if same_output:  # an output-derived id would have aliased these
                    self.assertEqual(out.provenance.output_digest, base.provenance.output_digest)

    def test_engine_identity_is_part_of_the_fingerprint(self):
        base = assessed(World())
        for field_name in ("rule_table_version", "citation_policy_version"):
            with self.subTest(field_name):
                changed = engine.ENGINE.__class__(**{**engine.ENGINE.__dict__, field_name: "changed/9"})
                with mock.patch.object(engine, "ENGINE", changed):
                    out = assessed(World())
                self.assertNotEqual(out.provenance.input_fingerprint, base.provenance.input_fingerprint)
                self.assertNotEqual(out.result.id, base.result.id)


class EquivalentReplayTests(unittest.TestCase):
    def equivalent_world(self):
        w = World()
        for name in ("candidates", "programs", "opportunities", "profiles", "applications", "policies", "vocabularies",
                     "requirements", "evidence", "claims", "participations"):
            getattr(w, name).reverse()
        w.add_skill_requirement(OPS, "spreadsheets")                      # another opportunity's requirement
        w.add_statement(ANA, "evidence_s1_ana_sheets", "skills.spreadsheets")
        w.add_claim("claim_s1_ana_sheets", ANA, "spreadsheets", "declared", HAS, ["evidence_s1_ana_sheets"])  # unrequired code
        w.candidates.append({"id": "candidate_s1_gus", "organization_id": "org_s1_alpha",
                             "identity_source": {"source_system": "fixture", "entity_type": "user", "entity_id": "u104"}})
        return w

    def test_permutation_and_unrelated_records_and_principal_do_not_change_identity(self):
        base = assessed(World())
        out = assessed(self.equivalent_world(), principal=OTHER_PRINCIPAL)
        self.assertEqual(out.provenance.input_fingerprint, base.provenance.input_fingerprint)
        self.assertEqual(out.provenance.output_digest, base.provenance.output_digest)
        self.assertEqual(out.result.id, base.result.id)
        self.assertEqual(out.result.model_dump_json(), base.result.model_dump_json())
        self.assertEqual(out.provenance.principal_id, OTHER_PRINCIPAL)  # principal recorded separately

    def test_exact_replay_is_byte_identical(self):
        a, b = assessed(World()), assessed(World())
        self.assertEqual(a.result.model_dump_json(), b.result.model_dump_json())
        self.assertEqual(a.provenance.canonical(), b.provenance.canonical())

    def test_different_as_of_changes_id_only(self):
        a = assessed(World())
        b = assessed(World(), as_of=AS_OF + timedelta(hours=1))
        self.assertEqual(a.provenance.input_fingerprint, b.provenance.input_fingerprint)
        self.assertEqual(a.provenance.output_digest, b.provenance.output_digest)
        self.assertNotEqual(a.result.id, b.result.id)


class TimestampNormalizationTests(unittest.TestCase):
    def test_equivalent_as_of_representations_give_identical_results(self):
        utc = assessed(World(), as_of=AS_OF)
        eastern = assessed(World(), as_of=AS_OF.astimezone(EASTERN))
        self.assertEqual(eastern.result.model_dump_json(), utc.result.model_dump_json())
        self.assertTrue(utc.result.model_dump(mode="json")["evaluated_at"].endswith("Z"))

    def snapshot_policy_world(self, captured_at):
        w = World()
        w.caps = capabilities_doc(policy_snapshot=True)
        w.policy()["source_ref"] = snapshot("policy_set", "8101", "8", captured_at=captured_at)
        return w

    def test_nested_logical_snapshot_captured_at_is_normalized(self):
        instant = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)
        utc = assessed(self.snapshot_policy_world(instant))
        eastern = assessed(self.snapshot_policy_world(instant.astimezone(EASTERN)))
        self.assertEqual(eastern.provenance.input_fingerprint, utc.provenance.input_fingerprint)
        self.assertEqual(eastern.result.id, utc.result.id)
        self.assertEqual(eastern.result.model_dump_json(), utc.result.model_dump_json())
        self.assertEqual(eastern.provenance.canonical(), utc.provenance.canonical())
        dumped = eastern.result.model_dump(mode="json")["policy"]["source_ref"]["version"]["captured_at"]
        self.assertEqual(dumped, "2026-10-30T12:00:00Z")
        later = assessed(self.snapshot_policy_world(instant + timedelta(seconds=1)))
        self.assertNotEqual(later.provenance.input_fingerprint, utc.provenance.input_fingerprint)

    def test_request_pin_in_another_offset_matches_the_record(self):
        instant = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)
        w = self.snapshot_policy_world(instant)
        ctx, caps = w.build()
        req = w.request()
        version = req.policy.source_ref.version.model_copy(update={"captured_at": instant.astimezone(EASTERN)})
        req = req.model_copy(update={"policy": req.policy.model_copy(update={
            "source_ref": req.policy.source_ref.model_copy(update={"version": version})})})
        out = engine.assess(req, ctx, StubAuthority(), caps)
        self.assertIsInstance(out, Assessed)
        self.assertEqual(out.result.model_dump_json(), assessed(self.snapshot_policy_world(instant)).result.model_dump_json())

    def test_canonicalization_rejects_naive_datetimes_and_floats(self):
        with self.assertRaises(IdentityError):
            canonical({"t": datetime(2026, 1, 1)})
        with self.assertRaises(IdentityError):
            canonical({"x": 1.5})
        self.assertEqual(canonical(datetime(2026, 1, 1, 7, tzinfo=timezone(timedelta(hours=-5)))), "2026-01-01T12:00:00Z")


class FingerprintIsWhatIsEvaluatedTests(unittest.TestCase):
    def test_rules_take_decision_inputs_only(self):
        tree = ast.parse(Path(rules.__file__).read_text(encoding="utf-8"))
        imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
        self.assertNotIn("EligibilityContext", imported)
        evaluate = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "evaluate")
        self.assertEqual([a.annotation.id for a in evaluate.args.args], ["DecisionInputs"])

    def test_changing_a_record_outside_the_decision_inputs_changes_nothing(self):
        base = assessed(World())
        w = World()
        w.claim("claim_s1_ana_remote")["value"] = {"kind": "work_preference", "stance": "does_not_prefer"}
        out = assessed(w)
        self.assertEqual(out.provenance.input_fingerprint, base.provenance.input_fingerprint)
        self.assertEqual(out.result.model_dump_json(), base.result.model_dump_json())

    def test_output_digest_excludes_only_id_and_time(self):
        out = assessed(World())
        moved = out.result.model_copy(update={"id": "eligibility_other", "evaluated_at": AS_OF + timedelta(days=1)})
        self.assertEqual(output_digest(moved), out.provenance.output_digest)
        changed = out.result.model_copy(update={"evaluated_by": "someone-else/1"})
        self.assertNotEqual(output_digest(changed), out.provenance.output_digest)


class ContractShapeTests(unittest.TestCase):
    def test_ids_and_component_labels(self):
        for cand, opp in ((ANA, DATA), (ANA, OPS)):
            out = assessed(World(), cand=cand, opp=opp)
            self.assertRegex(out.result.id, ELIGIBILITY_ID)
            self.assertEqual(len(out.result.id), len("eligibility_") + identity.RESULT_ID_HEX_CHARS)
            self.assertEqual(out.result.evaluated_by, EVALUATED_BY)
            self.assertNotIn("fixture-expected-label", out.result.evaluated_by)
            self.assertEqual(out.provenance.result_id, out.result.id)


if __name__ == "__main__":
    unittest.main()
