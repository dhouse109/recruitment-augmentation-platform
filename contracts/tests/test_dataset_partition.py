"""D-004.12 -- golden / held-out separation and split-leakage checks.

These tests check what a repository CAN check: declared scopes, derived record
ownership, identifier leakage between files, run-purpose rules and manifest
consistency. They cannot establish blinding. The committed held-out set is a
NOMINAL, EXPOSED demonstration; genuine held-out labels require external
custody that no test here can verify.
"""

import copy
import json
import unittest

from pydantic import ValidationError

import eval_harness as H
from rap_contracts.evaluation import (
    NOT_APPLICABLE,
    CodeRevision,
    DefinitionsPin,
    EvaluationDatasetManifest,
    EvaluationRun,
    HeldOutIntegrity,
    Measurement,
    Split,
    check_manifest_cases,
    check_partition,
    pin_manifest,
)
from rap_contracts.invariants import ContractViolation
from rap_contracts.promotion import SafetyGatePolicy

GOLDEN_CANDIDATES = {"candidate_demo_a", "candidate_demo_b", "candidate_demo_c"}
HELD_OUT_CANDIDATES = {"candidate_demo_d", "candidate_demo_e", "candidate_demo_f"}


def held_out_owned_ids():
    """Every record id owned by a held-out candidate, in the base layers or the held-out file."""
    pool = H.base_pool()
    ids = {r["id"] for k in H.SCOPED_KINDS for r in pool[k] if H.owner_of(k, r, pool) in HELD_OUT_CANDIDATES}
    ids |= set(H.all_owned_ids(H.split_doc(Split.HELD_OUT)["case_records"], pool))
    return ids


class PartitionTests(unittest.TestCase):
    def test_declared_scopes_are_disjoint(self):
        check_partition(H.cases_of(H.split_doc(Split.GOLDEN)), H.cases_of(H.split_doc(Split.HELD_OUT)))

    def test_scopes_stay_within_their_candidate_partition(self):
        for split, allowed in ((Split.GOLDEN, GOLDEN_CANDIDATES), (Split.HELD_OUT, HELD_OUT_CANDIDATES)):
            for case in H.cases_of(H.split_doc(split)):
                with self.subTest(case=case.id):
                    self.assertTrue(set(case.scope.candidates) <= allowed)

    def test_case_records_are_owned_by_their_split(self):
        pool = H.base_pool()
        for split, allowed in ((Split.GOLDEN, GOLDEN_CANDIDATES), (Split.HELD_OUT, HELD_OUT_CANDIDATES)):
            owners = H.all_owned_ids(H.split_doc(split)["case_records"], pool)
            with self.subTest(split=split.value):
                self.assertTrue(owners)
                self.assertTrue(set(owners.values()) <= allowed, owners)

    def test_loaded_records_are_owned_by_the_scope(self):
        """Derived, not declared: every candidate-scoped record a case loads belongs to an in-scope candidate."""
        pool = H.base_pool()
        for split in Split:
            doc = H.split_doc(split)
            owners = H.all_owned_ids(doc["case_records"], pool)
            for kind in H.SCOPED_KINDS:
                for rec in pool[kind]:
                    owners.setdefault(rec["id"], H.owner_of(kind, rec, pool))
            for case in H.cases_of(doc):
                scope = H.build_scope(case, doc, pool)
                with self.subTest(case=case.id):
                    self.assertTrue({owners[i] for i in scope.loaded_ids} <= set(case.scope.candidates))

    def test_step_inputs_reference_only_loaded_records(self):
        for split in Split:
            doc = H.split_doc(split)
            for case in H.cases_of(doc):
                scope = H.build_scope(case, doc)
                for step in case.steps:
                    refs = [getattr(step, a) for a in ("eligibility_result_id", "recommendation_id", "verification_id")
                            if hasattr(step, a)]
                    refs += list(getattr(step, "chunk_ids", ()))
                    with self.subTest(case=case.id, step=step.step_id):
                        self.assertTrue(set(refs) <= scope.loaded_ids, set(refs) - scope.loaded_ids)

    def test_no_held_out_identifier_in_golden_or_definitions_files(self):
        held = H.split_doc(Split.HELD_OUT)
        forbidden = held_out_owned_ids() | {c["id"] for c in held["cases"]}
        forbidden |= {c["legacy_label"] for c in held["cases"] if "legacy_label" in c}
        for name in (H.SPLIT_FILES[Split.GOLDEN], H.DEFINITIONS_FILE, H.DEFINITIONS_V2_FILE):
            text = (H.FIXTURE_DIR / name).read_text(encoding="utf-8")
            with self.subTest(file=name):
                self.assertEqual(sorted(i for i in forbidden if i in text), [])

    #: Pre-existing, documented parallel construction (contract-v0.2-evaluation.md, "g024 / h005"): the held-out
    #: twin of g024 shares its title. Recorded as an observation in F4 PR-A, not changed (case edits are out of
    #: scope). Any other shared prose fails.
    DOCUMENTED_GOLDEN_TWIN_TITLES = frozenset({"Recommendation for an ineligible opportunity is stopped at verification"})

    def test_no_held_out_case_free_text_in_golden_or_definitions_files(self):
        """Contract-level leakage check on committed text (F4 PR-A).

        Held-out case prose (titles and other free-text values of at least 20
        characters, excluding provenance citations) must not appear in the
        definitions files, and only the documented g024/h005 twin title may
        appear in the golden file. Codes and shared vocabulary are deliberately
        not banned, and the held-out manifest pin is permitted. This is not
        custody or confidentiality proof: the nominal held-out set is
        repository-visible and exposed.
        """
        prose = set()

        def walk(value):
            if isinstance(value, dict):
                for key, v in value.items():
                    if key != "provenance":  # shared plan citations, not case content
                        walk(v)
            elif isinstance(value, list):
                for v in value:
                    walk(v)
            elif isinstance(value, str) and " " in value and len(value) >= 20:
                prose.add(value)

        walk(H.split_doc(Split.HELD_OUT)["cases"])
        self.assertGreater(len(prose), 0)  # the check is not vacuous
        allowed = {H.SPLIT_FILES[Split.GOLDEN]: self.DOCUMENTED_GOLDEN_TWIN_TITLES}
        for name in (H.SPLIT_FILES[Split.GOLDEN], H.DEFINITIONS_FILE, H.DEFINITIONS_V2_FILE):
            text = (H.FIXTURE_DIR / name).read_text(encoding="utf-8")
            with self.subTest(file=name):
                self.assertEqual({p for p in prose if p in text}, set(allowed.get(name, ())))

    def test_policy_refers_to_held_out_by_manifest_pin_only(self):
        held_ids = {c["id"] for c in H.split_doc(Split.HELD_OUT)["cases"]}
        for name in (H.DEFINITIONS_FILE, H.DEFINITIONS_V2_FILE):
            policy = SafetyGatePolicy.model_validate(H.load(name)["safety_gate_policy"])
            mandatory = {c.case_id for r in policy.categories for c in r.mandatory_golden_cases}
            with self.subTest(file=name):
                self.assertEqual(mandatory & held_ids, set())
                self.assertEqual(policy.held_out_manifest, pin_manifest(H.manifest_of(H.split_doc(Split.HELD_OUT))))

    def test_held_out_file_covers_required_categories_by_itself(self):
        cases = H.cases_of(H.split_doc(Split.HELD_OUT))
        for name in (H.DEFINITIONS_FILE, H.DEFINITIONS_V2_FILE):
            policy = SafetyGatePolicy.model_validate(H.load(name)["safety_gate_policy"])
            for rule in policy.categories:
                if rule.held_out_coverage_required:
                    covering = [c for c in cases if any(sig.category is rule.category for s in c.steps for sig in s.safety)]
                    with self.subTest(file=name, category=rule.category.value):
                        self.assertGreaterEqual(len(covering), rule.held_out_min_cases)

    def test_committed_held_out_is_nominal_and_exposed(self):
        manifest = H.manifest_of(H.split_doc(Split.HELD_OUT))
        self.assertIs(manifest.held_out_integrity, HeldOutIntegrity.NOMINAL_EXPOSED)
        self.assertEqual(manifest.custody.value, "repository_visible")
        self.assertGreaterEqual(len(manifest.exposure_log), 3)
        self.assertTrue(all(e.recorded_by.attestation_basis.value == "unverified_metadata" for e in manifest.exposure_log))

    def test_overlap_is_detected(self):
        golden = H.cases_of(H.split_doc(Split.GOLDEN))
        held = H.cases_of(H.split_doc(Split.HELD_OUT))
        leaked = held[0].model_copy(update={"scope": held[0].scope.model_copy(update={"candidates": ("candidate_demo_a",)})})
        with self.assertRaises(ContractViolation) as ctx:
            check_partition(golden, [leaked])
        self.assertEqual(ctx.exception.code, "partition_scope_overlap")
        with self.assertRaises(ContractViolation) as ctx:
            check_partition(golden, [golden[0].model_copy(update={"split": Split.HELD_OUT})])
        self.assertEqual(ctx.exception.code, "partition_case_overlap")

    def test_include_of_a_record_owned_outside_scope_is_rejected(self):
        doc = H.split_doc(Split.GOLDEN)
        case = next(c for c in H.cases_of(doc) if c.id == "evalcase_g007")  # scope: candidate b
        bad = case.model_copy(update={"scope": case.scope.model_copy(update={"include_records": ("chunk_a_injection",)})})
        with self.assertRaises(H.HarnessError):
            H.build_scope(bad, doc)


class ManifestRuleTests(unittest.TestCase):
    def setUp(self):
        self.held = copy.deepcopy(H.split_doc(Split.HELD_OUT)["manifest"])
        self.golden = copy.deepcopy(H.split_doc(Split.GOLDEN)["manifest"])

    def test_repository_visible_cannot_be_declared_custodied(self):
        with self.assertRaises(ValidationError):
            EvaluationDatasetManifest.model_validate({**self.held, "held_out_integrity": "custodied_unexposed"})

    def test_nominal_held_out_records_exposures(self):
        with self.assertRaises(ValidationError):
            EvaluationDatasetManifest.model_validate({**self.held, "exposure_log": []})

    def test_golden_has_no_held_out_status(self):
        with self.assertRaises(ValidationError):
            EvaluationDatasetManifest.model_validate({**self.golden, "held_out_integrity": "nominal_exposed"})

    def test_external_custody_carries_commitments_only(self):
        external = {**self.held, "custody": "external_access_controlled", "held_out_integrity": "custodied_unexposed",
                    "case_pins": [], "case_records_sha256": None, "commitments": ["sha256:" + "1" * 64, "sha256:" + "2" * 64]}
        manifest = EvaluationDatasetManifest.model_validate(external)  # a declaration only, not proof of custody
        self.assertEqual((manifest.case_pins, manifest.case_records_sha256), ((), None))
        self.assertNotIn("evalcase_", json.dumps(manifest.model_dump(mode="json")))
        with self.assertRaises(ValidationError):
            EvaluationDatasetManifest.model_validate({**external, "case_pins": self.held["case_pins"]})
        with self.assertRaises(ValidationError):
            EvaluationDatasetManifest.model_validate({**external, "commitments": []})

    def test_modified_case_is_detected(self):
        doc = H.split_doc(Split.GOLDEN)
        cases = H.cases_of(doc)
        cases[0] = cases[0].model_copy(update={"title": "edited after pinning"})
        with self.assertRaises(ContractViolation) as ctx:
            check_manifest_cases(H.manifest_of(doc), cases)
        self.assertEqual(ctx.exception.code, "manifest_case_modified")

    def test_tuning_runs_cannot_reference_held_out(self):
        import test_promotion_gates as G
        golden_pin = pin_manifest(H.manifest_of(H.split_doc(Split.GOLDEN)))
        held_pin = pin_manifest(H.manifest_of(H.split_doc(Split.HELD_OUT)))
        base = G.run("evalrun_tuning_example", kind="single_model", purpose="tuning",
                     components=("eligibility", "recommendation", "model"), manifests=(golden_pin,),
                     prompt={"status": "pinned", "value": "prompt-example/1"},
                     model={"status": "pinned", "value": "model-example/1"}).model_dump(mode="json")
        EvaluationRun.model_validate(base)  # golden only: allowed (synthetic example)
        for purpose in ("tuning", "model_selection"):
            with self.subTest(purpose=purpose), self.assertRaises(ValidationError):
                EvaluationRun.model_validate({**base, "purpose": purpose,
                                              "manifests": base["manifests"] + [held_pin.model_dump(mode="json")]})

if __name__ == "__main__":
    unittest.main()
