"""F3 -- golden v2 (g002 / g008 scenario separation) and draft safety-gate policy v3.

RAP-F3-PLAN-2026-11-04 rev. 1.1, decisions F3-D1 to F3-D5 (owner-approved, AR-F3).

Golden v2 is a self-contained 26-case dataset: 24 cases are byte-identical
copies of golden v1, and only evalcase_g002 and evalcase_g008 are revised
(version 2) so that each isolates exactly one unknown rule. Golden v1, the
definitions v1/v2 files and the base layers are preserved byte-for-byte; the
harness defaults stay v1.

Held-out boundary (VB-1 to VB-6): the partition and leakage tests in this file
(C8-C11) read the NOMINAL, EXPOSED held-out fixture at test time, exactly as the
existing partition tests do. They report pass/fail only (on failure, the
colliding identifiers). This is a bounded verification activity; it grants the
evaluation runner no access to that file, and its results are not inputs to
scenario design, label authoring, selection or tuning. It is not custody,
blinding or confidentiality proof.
"""

import copy
import hashlib
import json
import unittest

import eval_harness as H
import test_dataset_partition as P
from rap_contracts.evaluation import (
    CaseOutcome,
    EvaluationCase,
    EvaluationDatasetManifest,
    Split,
    case_sha256,
    check_manifest_cases,
    check_partition,
    content_sha256,
    pin_manifest,
)
from rap_contracts.invariants import ContractViolation
from rap_contracts.promotion import MetricDefinitionSet, SafetyGatePolicy, check_policy_manifest
from rap_contracts.adjudication import ReviewerRubric
from rap_contracts.source_checks import canonical_json_sha256

try:
    from jsonschema import Draft202012Validator
except ImportError:  # pragma: no cover - exercised only without dev requirements
    Draft202012Validator = None

AUTHORED = "0.2.0-dev.foundations.6"
HISTORICAL = "0.2.0-dev.foundations.4"
F3_CASES = ("evalcase_g002", "evalcase_g008")
G = "candidate_demo_g"

#: sha256 of file bytes at main 653642e9 (rev. 1.1 section 1). These files must never change.
HISTORICAL_FILE_SHA256 = {
    "evaluation-golden-v0.2.0-dev.json": "a6740c4a25ecbd09b4e4ca900fb535b473c4e3c3635c9331f389a78c1d7204c8",
    "evaluation-definitions-v0.2.0-dev.json": "9445231558c45e4338e7a42d7e31b63e73ef8c122055da8a052a62401d386957",
    "evaluation-definitions-v2-v0.2.0-dev.json": "1b2b0329dcb7e2d547624cc29109b7ebd9d069e713440c5c6879ce9dd2505290",
    "foundations-v0.2.0-dev.json": "45c9c8ed2039fa8ad2f279ee68be3f2bc6b08f79cb807188d4a17d3874afd852",
    "eligibility-evidence-v0.2.0-dev.json": "9b309676047bc220d35f5c0d2b1b10b9fbc6b1c52945e7c1278db2c6798134c5",
    "review-v0.2.0-dev.json": "3126b1b4e048b9e8e63a2e5bbe8822bfaccdf174af6a6e1bb6a272f256108486",
}

#: The 11 new case-local records (9 non-label G records, the G label, the B-web label).
NEW_RECORDS = {
    "candidates": {G},
    "profiles": {"profile_demo_g"},
    "evidence": {"evidence_g_profile_hours", "evidence_g_profile_python", "evidence_g_profile_screening",
                 "evidence_g_enrollment"},
    "claims": {"claim_g_availability", "claim_g_python"},
    "participations": {"participation_g"},
    "eligibility_results": {"eligibility_g_data", "eligibility_b_web"},
}
G_SOURCE_ENTITY_IDS = {"9007", "5007", "6007"}


def v1_doc():
    return H.split_doc(Split.GOLDEN)


def v2_doc():
    return H.load(H.GOLDEN_V2_FILE)


def defs_v1():
    return H.load(H.DEFINITIONS_FILE)


def defs_g2():
    return H.load(H.DEFINITIONS_GOLDEN_V2_FILE)


def entity_ids(value, out=None):
    """Every source/identity ``entity_id`` in a JSON value."""
    out = set() if out is None else out
    if isinstance(value, dict):
        if "entity_id" in value and isinstance(value["entity_id"], str):
            out.add(value["entity_id"])
        for v in value.values():
            entity_ids(v, out)
    elif isinstance(value, list):
        for v in value:
            entity_ids(v, out)
    return out


class HistoricalPreservationTests(unittest.TestCase):
    """C1, and the unchanged harness defaults."""

    def test_c1_historical_files_are_byte_identical(self):
        for name, digest in HISTORICAL_FILE_SHA256.items():
            with self.subTest(file=name):
                self.assertEqual(hashlib.sha256((H.FIXTURE_DIR / name).read_bytes()).hexdigest(), digest)

    def test_harness_defaults_remain_v1(self):
        self.assertEqual(H.SPLIT_FILES[Split.GOLDEN], "evaluation-golden-v0.2.0-dev.json")
        self.assertEqual(H.DEFINITIONS_FILE, "evaluation-definitions-v0.2.0-dev.json")
        self.assertEqual((H.GOLDEN_V2_FILE, H.DEFINITIONS_GOLDEN_V2_FILE),
                         ("evaluation-golden-v2-v0.2.0-dev.json", "evaluation-definitions-golden-v2-v0.2.0-dev.json"))


class GoldenV2ManifestTests(unittest.TestCase):
    """C2, C3, C7b, C13."""

    def test_c2_manifest_pins_exactly_the_committed_cases(self):
        doc = v2_doc()
        manifest = H.manifest_of(doc)
        check_manifest_cases(manifest, H.cases_of(doc))
        self.assertEqual((manifest.id, manifest.version, manifest.split), ("evalset_golden", 2, Split.GOLDEN))
        self.assertEqual(manifest.fixture_layers, H.layer_pins())
        self.assertEqual(manifest.case_records_sha256, H.case_records_sha256(doc))
        self.assertEqual({c.id for c in H.cases_of(doc)}, {c.id for c in H.cases_of(v1_doc())})
        self.assertEqual(len(manifest.case_pins), 26)
        self.assertEqual(manifest.exposure_log, ())

    def test_c2_tampering_fails_closed(self):
        doc = copy.deepcopy(v2_doc())
        next(c for c in doc["cases"] if c["id"] == "evalcase_g008")["title"] = "tampered"
        with self.assertRaises(ContractViolation) as cm:
            check_manifest_cases(H.manifest_of(doc), H.cases_of(doc))
        self.assertEqual(cm.exception.code, "manifest_case_modified")
        doc = copy.deepcopy(v2_doc())
        doc["case_records"]["claims"][-1]["value"] = None
        self.assertNotEqual(H.manifest_of(doc).case_records_sha256, H.case_records_sha256(doc))

    def test_c3_only_g002_and_g008_change(self):
        v1 = {p.case_id: p for p in H.manifest_of(v1_doc()).case_pins}
        v2 = {p.case_id: p for p in H.manifest_of(v2_doc()).case_pins}
        unchanged = [cid for cid in v2 if v2[cid] == v1[cid]]
        self.assertEqual(len(unchanged), 24)
        self.assertEqual(sorted(set(v2) - set(unchanged)), list(F3_CASES))
        for cid in F3_CASES:
            with self.subTest(case=cid):
                self.assertEqual((v1[cid].version, v2[cid].version), (1, 2))
                self.assertNotEqual(v1[cid].sha256, v2[cid].sha256)
        v1_cases = {c["id"]: c for c in v1_doc()["cases"]}
        for case in v2_doc()["cases"]:
            if case["id"] not in F3_CASES:
                with self.subTest(case=case["id"]):
                    self.assertEqual(case, v1_cases[case["id"]])

    def test_c3_v1_case_records_carried_verbatim(self):
        v1, v2 = v1_doc()["case_records"], v2_doc()["case_records"]
        for kind, records in v1.items():
            with self.subTest(kind=kind):
                if isinstance(records, list):
                    self.assertEqual(v2[kind][:len(records)], records)
                else:
                    self.assertEqual(v2[kind], records)

    def test_c7b_inventory_is_eleven_case_local_records(self):
        v1, v2 = v1_doc()["case_records"], v2_doc()["case_records"]
        added = {}
        for kind in H.SCOPED_KINDS:
            old = {r["id"] for r in v1.get(kind, [])}
            new = {r["id"] for r in v2.get(kind, [])}
            self.assertLessEqual(old, new, kind)
            if new - old:
                added[kind] = new - old
        self.assertEqual(added, NEW_RECORDS)
        self.assertEqual(sum(len(v) for v in added.values()), 11)
        owners = H.all_owned_ids(v2, H.base_pool())
        new_ids = set().union(*NEW_RECORDS.values())
        self.assertEqual(sum(1 for i in new_ids if owners[i] == G), 10)
        self.assertEqual({i for i in new_ids if owners[i] != G}, {"eligibility_b_web"})
        self.assertEqual(owners["eligibility_b_web"], "candidate_demo_b")
        cases = {c.id: c for c in H.cases_of(v2_doc())}
        self.assertEqual(set(cases["evalcase_g008"].scope.include_records), new_ids - {"eligibility_b_web"})
        self.assertEqual(len(cases["evalcase_g008"].scope.include_records), 10)
        self.assertEqual(cases["evalcase_g002"].scope.include_records, ("eligibility_b_web",))

    def test_c13_contract_version_literals(self):
        doc = v2_doc()
        self.assertEqual(doc["contract_version"], AUTHORED)
        self.assertEqual(doc["manifest"]["contract_version"], AUTHORED)
        self.assertEqual(doc["contract_version"], doc["manifest"]["contract_version"])
        self.assertEqual(defs_g2()["contract_version"], AUTHORED)
        # Historical files keep the version they were authored against (unchanged, byte-identical).
        self.assertEqual((v1_doc()["contract_version"], v1_doc()["manifest"]["contract_version"]), (HISTORICAL, HISTORICAL))
        self.assertEqual((defs_v1()["contract_version"], H.load(H.DEFINITIONS_V2_FILE)["contract_version"]),
                         (HISTORICAL, HISTORICAL))

    def test_c13_contract_version_is_outside_the_manifest_root(self):
        doc = copy.deepcopy(v2_doc())
        root = pin_manifest(H.manifest_of(doc)).root
        doc["manifest"]["contract_version"] = HISTORICAL
        self.assertEqual(pin_manifest(EvaluationDatasetManifest.model_validate(doc["manifest"])).root, root)

    def test_revised_case_metadata(self):
        cases = {c.id: c for c in H.cases_of(v2_doc())}
        for cid, legacy, pilot in (("evalcase_g002", "EVAL-G002", ("PILOT-T002",)),
                                   ("evalcase_g008", "EVAL-G008", ("PILOT-T010",))):
            c = cases[cid]
            with self.subTest(case=cid):
                self.assertEqual((c.version, c.legacy_label, c.pilot_test_refs), (2, legacy, pilot))
                self.assertEqual((c.provenance.origin, c.provenance.review_status.value, c.adjudication_status.value),
                                 ("seed_proposal", "proposed", "not_adjudicated"))
                self.assertTrue(c.provenance.origin_ref.startswith(f"RAP-EVAL-001 v0.1.0 {legacy}; F3 revision of v1"))
                self.assertEqual(c.provenance.authored_by, f"ai-assisted-authoring/{AUTHORED}")
        self.assertNotIn("sources", cases["evalcase_g008"].title)
        self.assertIn("one profile revision", cases["evalcase_g008"].title)


class PolicyV3Tests(unittest.TestCase):
    """C4, C5, C6."""

    def test_c4_policy_v3_differs_from_v1_only_in_version_and_golden_pin(self):
        p1, p3 = defs_v1()["safety_gate_policy"], defs_g2()["safety_gate_policy"]
        policy = SafetyGatePolicy.model_validate(p3)
        self.assertEqual((policy.id, policy.version, policy.status), ("evaldefs_safety_gate", 3, "draft"))
        self.assertEqual(policy.golden_manifest, pin_manifest(H.manifest_of(v2_doc())))
        self.assertEqual((policy.definitions.id, policy.definitions.version), ("evaldefs_metrics", 1))
        self.assertEqual({k: v for k, v in p3.items() if k not in ("version", "golden_manifest")},
                         {k: v for k, v in p1.items() if k not in ("version", "golden_manifest")})
        self.assertEqual(p3["held_out_manifest"], p1["held_out_manifest"])
        self.assertEqual(p3["categories"], p1["categories"])
        self.assertEqual(sum(1 for c in policy.categories if c.zero_tolerance), 8)

    def test_c5_check_policy_manifest_combinations(self):
        p1 = SafetyGatePolicy.model_validate(defs_v1()["safety_gate_policy"])
        p3 = SafetyGatePolicy.model_validate(defs_g2()["safety_gate_policy"])
        g1, g2 = H.manifest_of(v1_doc()), H.manifest_of(v2_doc())
        check_policy_manifest(p3, g2)
        check_policy_manifest(p1, g1)
        for policy, manifest in ((p1, g2), (p3, g1)):
            with self.subTest(policy=policy.version, manifest=manifest.version):
                with self.assertRaises(ContractViolation) as cm:
                    check_policy_manifest(policy, manifest)
                self.assertEqual(cm.exception.code, "golden_manifest_not_authoritative")

    def test_c6_metrics_and_rubric_are_v1_copies(self):
        d1, d3 = defs_v1(), defs_g2()
        self.assertEqual(d3["metric_definitions"], d1["metric_definitions"])
        self.assertEqual(d3["reviewer_rubric"], d1["reviewer_rubric"])
        self.assertEqual(content_sha256(MetricDefinitionSet.model_validate(d3["metric_definitions"])),
                         content_sha256(MetricDefinitionSet.model_validate(d1["metric_definitions"])))
        self.assertEqual(content_sha256(ReviewerRubric.model_validate(d3["reviewer_rubric"])),
                         content_sha256(ReviewerRubric.model_validate(d1["reviewer_rubric"])))
        self.assertEqual((d3["metric_definitions"]["status"], d3["reviewer_rubric"]["status"]), ("draft", "draft"))
        self.assertEqual(set(d3), set(d1))


class ScenarioIsolationTests(unittest.TestCase):
    """C7: the T2 conformance harness on all 26 golden v2 cases; each F3 case isolates exactly one unknown rule."""

    @classmethod
    def setUpClass(cls):
        cls.doc = v2_doc()
        cls.runs = {c.id: H.run_case(c, cls.doc) for c in H.cases_of(cls.doc)}

    def test_c7_all_26_cases_pass_the_reference_harness(self):
        failures = [H.describe(r) for r in self.runs.values() if r.observation.outcome is not CaseOutcome.PASS]
        self.assertEqual(failures, [])
        self.assertEqual(len(self.runs), 26)

    def test_c7_each_f3_case_isolates_exactly_one_unknown_rule(self):
        expected = {"evalcase_g002": ("PILOT-AVAIL-003", "availability_not_declared", "eligibility_b_web"),
                    "evalcase_g008": ("PILOT-SKILL-004", "qualification_contested", "eligibility_g_data")}
        cases = {c.id: c for c in H.cases_of(self.doc)}
        for cid, (rule, code, label) in expected.items():
            step = cases[cid].steps[0]
            with self.subTest(case=cid):
                self.assertEqual(step.eligibility_result_id, label)
                unknown = [(o.rule_id, o.reason_code) for o in step.expected.rule_outcomes if o.result.value == "unknown"]
                self.assertEqual(unknown, [(rule, code)])
                self.assertFalse([o for o in step.expected.rule_outcomes if o.result.value == "fail"])
                self.assertEqual(step.expected.decision.value, "needs_information")
                obs = self.runs[cid].observation.steps[0]
                self.assertEqual(obs.status.value, "matched")

    def test_c7_f3_cases_are_distinct_assessment_keys(self):
        labels = {r["id"]: r for r in self.doc["case_records"]["eligibility_results"]}
        keys = {(lab["candidate_id"], lab["opportunity_id"], lab["policy"]["policy_set_id"], lab["policy"]["version"])
                for lab in labels.values()}
        self.assertEqual(keys, {("candidate_demo_b", "opportunity_demo_web", "policy_demo_pilot", 1),
                                (G, "opportunity_demo_data", "policy_demo_pilot", 1)})
        cases = {c.id: c for c in H.cases_of(self.doc)}
        self.assertEqual((cases["evalcase_g002"].scope.candidates, cases["evalcase_g008"].scope.candidates),
                         (("candidate_demo_b",), (G,)))


class GoldenV2PartitionTests(unittest.TestCase):
    """C8-C11. These read the nominal, exposed held-out fixture (VB-1 to VB-6); pass/fail only."""

    def test_c8_scopes_are_disjoint_from_the_held_out_split(self):
        check_partition(H.cases_of(v2_doc()), H.cases_of(H.split_doc(Split.HELD_OUT)))
        allowed = P.GOLDEN_CANDIDATES | {G}
        for case in H.cases_of(v2_doc()):
            with self.subTest(case=case.id):
                self.assertTrue(set(case.scope.candidates) <= allowed)
        owners = H.all_owned_ids(v2_doc()["case_records"], H.base_pool())
        self.assertEqual(set(owners.values()), {"candidate_demo_a", "candidate_demo_b", G})
        self.assertFalse(set(owners.values()) & P.HELD_OUT_CANDIDATES)

    def test_c8_loaded_records_are_owned_by_the_scope(self):
        doc, pool = v2_doc(), H.base_pool()
        owners = H.all_owned_ids(doc["case_records"], pool)
        for kind in H.SCOPED_KINDS:
            for rec in pool[kind]:
                owners.setdefault(rec["id"], H.owner_of(kind, rec, pool))
        for case in H.cases_of(doc):
            scope = H.build_scope(case, doc, pool)
            with self.subTest(case=case.id):
                self.assertTrue({owners[i] for i in scope.loaded_ids} <= set(case.scope.candidates))

    def test_c9_no_held_out_identifier_or_prose_in_the_new_files(self):
        held = H.split_doc(Split.HELD_OUT)
        forbidden = P.held_out_owned_ids() | {c["id"] for c in held["cases"]}
        forbidden |= {c["legacy_label"] for c in held["cases"] if "legacy_label" in c}
        prose = set()

        def walk(value):
            if isinstance(value, dict):
                for key, v in value.items():
                    if key != "provenance":
                        walk(v)
            elif isinstance(value, list):
                for v in value:
                    walk(v)
            elif isinstance(value, str) and " " in value and len(value) >= 20:
                prose.add(value)

        walk(held["cases"])
        self.assertGreater(len(prose), 0)
        allowed = {H.GOLDEN_V2_FILE: P.PartitionTests.DOCUMENTED_GOLDEN_TWIN_TITLES}
        for name in (H.GOLDEN_V2_FILE, H.DEFINITIONS_GOLDEN_V2_FILE):
            text = (H.FIXTURE_DIR / name).read_text(encoding="utf-8")
            with self.subTest(file=name):
                self.assertEqual(sorted(i for i in forbidden if i in text), [])
                self.assertEqual({p for p in prose if p in text}, set(allowed.get(name, ())))

    def test_c9_policy_v3_refers_to_held_out_by_manifest_pin_only(self):
        policy = SafetyGatePolicy.model_validate(defs_g2()["safety_gate_policy"])
        held_ids = {c["id"] for c in H.split_doc(Split.HELD_OUT)["cases"]}
        mandatory = {c.case_id for r in policy.categories for c in r.mandatory_golden_cases}
        self.assertEqual(mandatory & held_ids, set())
        self.assertEqual(policy.held_out_manifest, pin_manifest(H.manifest_of(H.split_doc(Split.HELD_OUT))))

    def test_c10_new_identifiers_collide_with_nothing(self):
        v2 = v2_doc()["case_records"]
        new_ids = set().union(*NEW_RECORDS.values())
        g_records = [r for kind, ids in NEW_RECORDS.items() for r in v2[kind] if r["id"] in ids]
        self.assertEqual(entity_ids([r for r in g_records if r["id"] != "eligibility_b_web"]) - {"8001", "4001"},
                         G_SOURCE_ENTITY_IDS)
        # Every other entity id visible anywhere: base layers, golden v1 case records, held-out file.
        others = entity_ids([H.load(n) for n in H.LAYER_FILES]) | entity_ids(v1_doc()["case_records"])
        others |= entity_ids(H.split_doc(Split.HELD_OUT))
        self.assertEqual(sorted(G_SOURCE_ENTITY_IDS & others), [])
        # No new record id is used anywhere else (base layers, golden v1, held-out file).
        texts = [(H.FIXTURE_DIR / n).read_text(encoding="utf-8")
                 for n in H.LAYER_FILES + (H.SPLIT_FILES[Split.GOLDEN], H.SPLIT_FILES[Split.HELD_OUT])]
        self.assertEqual(sorted(i for i in new_ids if any(f'"{i}"' in t for t in texts)), [])
        self.assertEqual(sorted(new_ids & P.held_out_owned_ids()), [])

    def test_c11_g_records_are_owned_by_g_and_reference_no_held_out_record(self):
        v2 = v2_doc()["case_records"]
        owners = H.all_owned_ids(v2, H.base_pool())
        g_ids = set().union(*NEW_RECORDS.values()) - {"eligibility_b_web"}
        self.assertEqual({owners[i] for i in g_ids}, {G})
        held = P.held_out_owned_ids()
        g_text = json.dumps([r for kind, ids in NEW_RECORDS.items() for r in v2[kind] if r["id"] in ids])
        self.assertEqual(sorted(i for i in held if f'"{i}"' in g_text), [])


@unittest.skipIf(Draft202012Validator is None, "jsonschema not installed; install contracts/requirements-dev.txt")
class GoldenV2SchemaConformanceTests(unittest.TestCase):
    """C12: the new fixtures against the EXISTING committed JSON Schemas (no schema change)."""

    def _accept(self, name, items):
        from rap_contracts.schema_export import DEFAULT_SCHEMA_DIR
        schema = json.loads((DEFAULT_SCHEMA_DIR / f"{name}.schema.json").read_text(encoding="utf-8"))
        validator = Draft202012Validator(schema)
        for i, item in enumerate(items):
            with self.subTest(schema=name, item=item.get("id", i)):
                self.assertEqual([e.message for e in validator.iter_errors(item)], [])

    def test_c12_new_fixtures_conform(self):
        doc, defs = v2_doc(), defs_g2()
        self._accept("evaluation-case", doc["cases"])
        self._accept("evaluation-dataset-manifest", [doc["manifest"]])
        self._accept("safety-gate-policy", [defs["safety_gate_policy"]])
        self._accept("metric-definition-set", [defs["metric_definitions"]])
        self._accept("reviewer-rubric", [defs["reviewer_rubric"]])
        self._accept("eligibility-result", doc["case_records"]["eligibility_results"])
        self._accept("candidate", doc["case_records"]["candidates"])
        self._accept("candidate-profile", doc["case_records"]["profiles"])
        self._accept("evidence-record", doc["case_records"]["evidence"])
        self._accept("candidate-claim", [c for c in doc["case_records"]["claims"] if c["id"].startswith("claim_g_")])
        self._accept("program-participation", doc["case_records"]["participations"])

    def test_case_hashes_recompute(self):
        pins = {p.case_id: p.sha256 for p in H.manifest_of(v2_doc()).case_pins}
        for case in v2_doc()["cases"]:
            self.assertEqual(case_sha256(EvaluationCase.model_validate(case)), pins[case["id"]])
        self.assertEqual(H.manifest_of(v2_doc()).case_records_sha256, canonical_json_sha256(v2_doc()["case_records"]))


if __name__ == "__main__":
    unittest.main()
