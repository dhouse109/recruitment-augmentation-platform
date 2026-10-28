"""Independent JSON Schema conformance (dev dependency: jsonschema).

Validates synthetic fixtures against the *committed* schema files with a
validator that does not share code with Pydantic. Skipped, with a visible
reason, when only runtime requirements are installed; install
``requirements-dev.txt`` to run it.
"""

import copy
import json
import unittest

from pydantic import ValidationError

import support
from rap_contracts.models import Application
from rap_contracts.schema_export import DEFAULT_SCHEMA_DIR, EXPORTED_MODELS

try:
    from jsonschema import Draft202012Validator
except ImportError:  # pragma: no cover - exercised only without dev requirements
    Draft202012Validator = None


def _validator(name):
    schema = json.loads((DEFAULT_SCHEMA_DIR / f"{name}.schema.json").read_text(encoding="utf-8"))
    return Draft202012Validator(schema)


@unittest.skipIf(Draft202012Validator is None, "jsonschema not installed; install contracts/requirements-dev.txt")
class JsonSchemaConformanceTests(unittest.TestCase):
    def test_committed_schemas_are_valid_draft_2020_12(self):
        for name in EXPORTED_MODELS:
            with self.subTest(schema=name):
                schema = json.loads((DEFAULT_SCHEMA_DIR / f"{name}.schema.json").read_text(encoding="utf-8"))
                Draft202012Validator.check_schema(schema)

    def test_all_synthetic_fixture_records_accepted(self):
        doc = support.raw()
        sections = {
            "candidate": doc["candidates"],
            "candidate-profile": doc["profiles"],
            "program": doc["programs"],
            "opportunity": doc["opportunities"],
            "application": doc["applications"],
            "source-reference": doc["example_source_references"],
        }
        for name, items in sections.items():
            validator = _validator(name)
            for item in items:
                with self.subTest(schema=name, record=item.get("id", "example")):
                    self.assertEqual(list(validator.iter_errors(item)), [])

    def test_malformed_submission_and_target_cases_rejected(self):
        validator = _validator("application")
        submitted = support.raw_record("applications", "application_demo_a_data")
        draft = support.raw_record("applications", "application_demo_b_program")

        def mutate(base, fn):
            rec = copy.deepcopy(base)
            fn(rec)
            return rec

        cases = {
            "draft carrying a submission": {**submitted, "status": "draft"},
            "submitted without submission": {k: v for k, v in submitted.items() if k != "submission"},
            "submitted with null submission": {**submitted, "submission": None},
            "closed without submission": {**draft, "status": "closed"},
            "submission missing profile_ref": mutate(submitted, lambda r: r["submission"].pop("profile_ref")),
            "submission missing application_version": mutate(submitted, lambda r: r["submission"].pop("application_version")),
            "submission with unknown version kind": mutate(
                submitted, lambda r: r["submission"].update(application_version={"kind": "hash", "revision_id": "711"})),
            "submission snapshot token labeled native": mutate(
                submitted, lambda r: r["submission"]["profile_ref"]["version"].update(revision_id="sha256:" + "0" * 64)),
            "submission with extra field": mutate(submitted, lambda r: r["submission"].update(claims={"skill": "python"})),
            "empty target": {**draft, "target": {}},
            "all-null target": {**draft, "target": {"program_id": None, "opportunity_id": None}},
            "target with extra field": mutate(draft, lambda r: r["target"].update(employer="x")),
            "target with malformed id": {**draft, "target": {"opportunity_id": "Opportunity-Demo"}},
            "unknown status": {**draft, "status": "reopened"},
        }
        for label, payload in cases.items():
            with self.subTest(label):
                self.assertTrue(list(validator.iter_errors(payload)), f"JSON Schema accepted: {label}")
                with self.assertRaises(ValidationError, msg=f"Pydantic accepted: {label}"):
                    Application.model_validate(payload)  # both validators agree

    def test_documented_gap_cross_field_org_equality_not_in_json_schema(self):
        """JSON Schema cannot express organization equality; only the Python contract rejects this."""
        bad = support.raw_record("applications", "application_demo_a_data")
        bad["submission"]["profile_ref"]["organization_id"] = "org_demo_002"
        self.assertEqual(list(_validator("application").iter_errors(bad)), [])
        with self.assertRaises(ValidationError):
            Application.model_validate(bad)


if __name__ == "__main__":
    unittest.main()
