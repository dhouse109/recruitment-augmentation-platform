"""Reproducible JSON Schema generation and drift detection."""

import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import pydantic

from rap_contracts import CONTRACT_VERSION
from rap_contracts.schema_export import (
    DEFAULT_SCHEMA_DIR,
    EXPORTED_MODELS,
    JSON_SCHEMA_DIALECT,
    build_schema,
    expected_files,
    find_drift,
    render,
)

PINNED_PYDANTIC = next(
    line.split("==", 1)[1].strip()
    for line in (Path(__file__).resolve().parents[1] / "requirements.txt").read_text().splitlines()
    if line.startswith("pydantic==")
)


class SchemaDriftTests(unittest.TestCase):
    def test_running_pinned_pydantic(self):
        self.assertEqual(pydantic.VERSION, PINNED_PYDANTIC, "schemas are only reproducible with the pinned Pydantic")

    def test_committed_schemas_match_generated_output(self):
        self.assertEqual(find_drift(DEFAULT_SCHEMA_DIR), [])

    def test_generation_is_deterministic(self):
        self.assertEqual(expected_files(), expected_files())

    def test_drift_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            for path in DEFAULT_SCHEMA_DIR.glob("*.schema.json"):
                shutil.copy(path, tmp_dir / path.name)
            self.assertEqual(find_drift(tmp_dir), [])

            target = tmp_dir / "application.schema.json"
            doc = json.loads(target.read_text())
            doc["properties"]["status"]["description"] = "edited by hand"
            target.write_text(render(doc))
            (tmp_dir / "candidate.schema.json").unlink()
            (tmp_dir / "stray.schema.json").write_text("{}\n")

            self.assertEqual(
                find_drift(tmp_dir),
                ["missing: candidate.schema.json", "unexpected: stray.schema.json", "changed: application.schema.json"],
            )


class SchemaIdentityTests(unittest.TestCase):
    def test_ids_are_stable_versioned_and_unique(self):
        ids = set()
        for name, model in EXPORTED_MODELS.items():
            schema = build_schema(name, model)
            with self.subTest(name=name):
                self.assertEqual(schema["$schema"], JSON_SCHEMA_DIALECT)
                self.assertTrue(schema["$id"].startswith("https://"))
                self.assertIn(f"/{CONTRACT_VERSION}/{name}.schema.json", schema["$id"])
                self.assertNotIn("#", schema["$id"])
                self.assertEqual(schema["x-contract-version"], CONTRACT_VERSION)
                self.assertIn("NOT frozen", schema["x-contract-status"])
                self.assertFalse(schema.get("additionalProperties", True))
                ids.add(schema["$id"])
        self.assertEqual(len(ids), len(EXPORTED_MODELS))

    def test_development_label(self):
        self.assertIn("-dev.", CONTRACT_VERSION)



#: PR #4 schema bodies as merged on main @ 2e63a939 (sha256 of canonical JSON
#: excluding "$id" and "x-contract-version", which change with the version label).
PR4_SCHEMA_BODY_DIGESTS = {
    "application": "b82bdb102e442c05ff9b20913a3004235a12cdc1d83c20568d06661e43c6b29d",
    "candidate-profile": "20050691aede1b32ef04c2d9ad2e6ab2583de4fce9ed492017c3ca11cfae5ad8",
    "candidate": "73446f0410dd4f84ed967f064a3efffd0e3505a9f60a589871ec456980d5f1d7",
    "opportunity": "1bd3ddb46879851b493764fca516b0413f87340242626b9a6764851f3d653863",
    "program": "522953bd22255c6097164277430ab9f0c28d55ad603844eaabd7c45fcf07da7c",
    "source-check-result": "4ea2ce7ff35ebd177afe30cd22379a401e0a0a3fd8aead5026adf96db09e4d83",
    "source-reference": "0a2c7b88a12053f629f88dc2139633a35f43208f39a187d21c3483b5fb3db857",
}


class Pr4CompatibilityTests(unittest.TestCase):
    def test_pr4_schema_bodies_unchanged(self):
        for name, digest in PR4_SCHEMA_BODY_DIGESTS.items():
            with self.subTest(schema=name):
                body = build_schema(name, EXPORTED_MODELS[name])
                body.pop("$id")
                body.pop("x-contract-version")
                canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
                self.assertEqual(hashlib.sha256(canonical.encode()).hexdigest(), digest)

    def test_pr4_fixture_and_capabilities_still_valid(self):
        import support
        from rap_contracts.invariants import check_record_set
        from rap_contracts.source_checks import check_record_set_versions

        check_record_set(support.records())
        check_record_set_versions(support.records(), support.capabilities())  # PR #4 declaration, new fields defaulted
        caps = support.capabilities()
        self.assertTrue(all(c.verification_entity_types == frozenset() for c in caps.values()))


#: PR #5 schema bodies as merged on main @ d780ac19 (same digest rule as above).
PR5_SCHEMA_BODY_DIGESTS = {
    "candidate-claim": "0d3c40e1d9fc02f2b21b5eaade8868865cd76d85322ab144faa3abd8f6e40b24",
    "claim-vocabulary": "3aec753ca670a503b4eb1a462c7f66c9a6ce738167cb2ada4fca4a4673cc5b74",
    "eligibility-result": "17bf4437e4a6f0fd70e18d6fb12437c7aa3df8d3f21750611c4ad6739965c4b6",
    "evidence-record": "e4031b2e33c993ec189e6552dab2d3e640fd62b0c6264eb146ec74be60f1aba2",
    "opportunity-requirement": "656a620fff6009f62aee59dd3429cd16b2c67b0f53f27def6027d99d1a9ab668",
    "policy-set": "7254a45c2b797fe44bf698dc4c2fb309977ecd62c688452fa7349fe1e365d67c",
    "program-participation": "cc38776e063a54c427e28a8a296e39b2800116d9e8f17d6c7712ff9f46803143",
    "retrieval-chunk": "627757d43e313bcf807b3ae6d9648badedbdcd3bb6b30b01ccbbe68c722eaf64",
    "retrieval-request": "bde2e441cec60a43696d700fcc1b2c6ae61cf81c9e7e9aac3ae7a200a7d79da4",
    "retrieval-response": "1e09ee2b1b901e4b658f8def02e8d0fd465b85a3edd397fd17e3e3a3bc12634a",
}


class Pr5CompatibilityTests(unittest.TestCase):
    def test_pr5_schema_bodies_unchanged(self):
        for name, digest in PR5_SCHEMA_BODY_DIGESTS.items():
            with self.subTest(schema=name):
                body = build_schema(name, EXPORTED_MODELS[name])
                body.pop("$id")
                body.pop("x-contract-version")
                canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
                self.assertEqual(hashlib.sha256(canonical.encode()).hexdigest(), digest)

    def test_pr5_fixture_still_valid(self):
        import support
        from rap_contracts.eligibility import check_eligibility_results

        check_eligibility_results(support.ext_results(), support.ext_context())


#: PR #6 schema bodies as merged on main @ 9f21486f (same digest rule as above).
PR6_SCHEMA_BODY_DIGESTS = {
    "audit-event": "f3bf8597b1a1c9eebb8fff6aa5f82f9ba92fe29984f8263e64b560c992dd1212",
    "human-review-command": "0acfc19ef37bab54509875c02c01d8ecf2f670abb87012d95214739aa0d883f6",
    "recommendation": "d91980bf415c3c8bdb71837740dfadb0aaf246555350e2262e746dd251b4e593",
    "review-correction-command": "35fb038bb4be1d89a92000c654fbac18bb647b062f0fe3b039f17d5a1706e5e6",
    "review-decision": "2452f8bddd03c00c0e86f3d4b4b02d1a655f4f190abbc2f01c40e73cc39fa28d",
    "review-outcome": "1d8d5f8416d661b9df21821b153388cee4c1086aeeea4c12623f9f3ba6f0add4",
    "review-reason-vocabulary": "2d7cc349968887601796aefb71c9b38e7f905ef9172989ddf726d0516edd9ed2",
    "verification-result": "ec1dc610df4e46193e130f61c4a1726a4099159cbf38a7d3895b7752af673a08",
}

#: Schemas added in 0.2.0-dev.foundations.4 (D-004.12). Everything else must be pre-existing.
PR7_NEW_SCHEMAS = {
    "adjudication-record", "case-observation", "evaluation-case", "evaluation-dataset-manifest", "evaluation-run",
    "held-out-gate-attestation", "metric-definition-set", "promotion-decision", "reviewer-rubric", "run-comparison",
    "safety-gate-policy",
}


class Pr6CompatibilityTests(unittest.TestCase):
    def test_pr6_schema_bodies_unchanged(self):
        for name, digest in PR6_SCHEMA_BODY_DIGESTS.items():
            with self.subTest(schema=name):
                body = build_schema(name, EXPORTED_MODELS[name])
                body.pop("$id")
                body.pop("x-contract-version")
                canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
                self.assertEqual(hashlib.sha256(canonical.encode()).hexdigest(), digest)

    def test_pr6_fixture_and_review_flow_still_valid(self):
        import support

        recs, verifications, _ = support.review_models()
        svc = support.review_service()
        self.assertEqual(svc.recommendations["recommendation_a_data"].status.value, "ready_for_review")
        self.assertEqual(svc.recommendations["recommendation_a_web"].status.value, "escalated")
        self.assertEqual(svc.submit_review("credential-demo-coordinator", support.review_command()).status.value, "recorded")
        self.assertEqual(len(recs), 3)
        self.assertEqual(len(verifications), 3)

    def test_only_evaluation_schemas_are_new(self):
        prior = set(PR4_SCHEMA_BODY_DIGESTS) | set(PR5_SCHEMA_BODY_DIGESTS) | set(PR6_SCHEMA_BODY_DIGESTS)
        self.assertEqual(set(EXPORTED_MODELS) - prior, PR7_NEW_SCHEMAS)
        self.assertTrue(prior <= set(EXPORTED_MODELS))  # nothing removed
        self.assertEqual(len(prior), 25)

    def test_version_label_sorts_after_pr6(self):
        self.assertEqual(CONTRACT_VERSION, "0.2.0-dev.foundations.4")


if __name__ == "__main__":
    unittest.main()
