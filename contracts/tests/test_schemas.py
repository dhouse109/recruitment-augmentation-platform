"""Reproducible JSON Schema generation and drift detection."""

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


if __name__ == "__main__":
    unittest.main()
