"""Independent JSON Schema conformance (dev dependency: jsonschema).

Validates synthetic fixtures against the *committed* schema files with a
validator that does not share code with Pydantic. Skipped, with a visible
reason, when only runtime requirements are installed; install
``requirements-dev.txt`` to run it.
"""

import copy
import importlib
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



# ---------------------------------------------------------------------------
# 0.2.0-dev.foundations.2: eligibility, claims, evidence and retrieval schemas
# ---------------------------------------------------------------------------

_PYDANTIC_MODELS = {
    "candidate-claim": "rap_contracts.claims:CandidateClaim",
    "claim-vocabulary": "rap_contracts.claims:ClaimVocabulary",
    "program-participation": "rap_contracts.claims:ProgramParticipation",
    "evidence-record": "rap_contracts.evidence:EvidenceRecord",
    "retrieval-chunk": "rap_contracts.evidence:RetrievalChunk",
    "retrieval-request": "rap_contracts.evidence:RetrievalRequest",
    "opportunity-requirement": "rap_contracts.eligibility:OpportunityRequirement",
    "policy-set": "rap_contracts.eligibility:PolicySet",
    "eligibility-result": "rap_contracts.eligibility:EligibilityResult",
}


def _model(name):
    module, attr = _PYDANTIC_MODELS[name].split(":")
    return getattr(importlib.import_module(module), attr)


@unittest.skipIf(Draft202012Validator is None, "jsonschema not installed; install contracts/requirements-dev.txt")
class EligibilityEvidenceConformanceTests(unittest.TestCase):
    def test_all_extended_fixture_records_accepted(self):
        doc = support.ext_raw()
        sections = {
            "candidate-claim": doc["claims"], "claim-vocabulary": doc["vocabularies"],
            "program-participation": doc["participations"], "evidence-record": doc["evidence"],
            "retrieval-chunk": doc["chunks"], "retrieval-request": doc["retrieval_requests"],
            "opportunity-requirement": doc["requirements"], "policy-set": doc["policies"],
            "eligibility-result": doc["eligibility_results"],
            "candidate": doc["additional_records"]["candidates"],
            "candidate-profile": doc["additional_records"]["profiles"],
            "application": doc["additional_records"]["applications"],
        }
        for name, items in sections.items():
            validator = _validator(name)
            for item in items:
                with self.subTest(schema=name, record=item.get("id", "request")):
                    self.assertEqual(list(validator.iter_errors(item)), [])

    def _both_reject(self, name, cases):
        validator, model = _validator(name), _model(name)
        for label, payload in cases.items():
            with self.subTest(schema=name, case=label):
                self.assertTrue(list(validator.iter_errors(payload)), f"JSON Schema accepted: {label}")
                with self.assertRaises(ValidationError, msg=f"Pydantic accepted: {label}"):
                    model.model_validate(payload)

    def test_malformed_claims_rejected_by_both(self):
        doc = support.ext_raw()
        claim = lambda cid: copy.deepcopy(next(c for c in doc["claims"] if c["id"] == cid))
        declared, unknown, contested, inferred = (claim("claim_a_availability"), claim("claim_b_availability"),
                                                  claim("claim_b_python"), claim("claim_e_python_inferred"))
        self._both_reject("candidate-claim", {
            "unknown with fabricated value": {**unknown, "value": {"kind": "availability", "hours_per_week": 9}},
            "declared without evidence": {**declared, "evidence_ids": []},
            "declared without value": {k: v for k, v in declared.items() if k != "value"},
            "inferred without producer": {k: v for k, v in inferred.items() if k != "inferred_by"},
            "declared naming a producer": {**declared, "inferred_by": "synthetic-inference-label/0"},
            "contested with one alternative": {**contested, "alternatives": contested["alternatives"][:1]},
            "contested with a single value": {**contested, "value": {"kind": "skill", "presence": "has"}},
            "sensitive claim type": {**declared, "claim_type": "disability"},
            "sensitive extra field": {**declared, "gender": "synthetic"},
            "availability above hours in a week": {**declared, "value": {"kind": "availability", "hours_per_week": 169}},
            "availability with subject code": {**declared, "subject_code": "python"},
            "skill without subject code": {k: v for k, v in claim("claim_a_python_profile").items() if k != "subject_code"},
            "free text in value": {**declared, "value": {"kind": "availability", "hours_per_week": 9, "note": "x"}},
        })

    def test_malformed_eligibility_rejected_by_both(self):
        doc = support.ext_raw()
        res = lambda rid: copy.deepcopy(next(r for r in doc["eligibility_results"] if r["id"] == rid))
        bad_reason = res("eligibility_b_data")
        bad_reason["rule_outcomes"][2]["reason_code"] = "source_unavailable"
        active_unknown = res("eligibility_e_data")
        active_unknown["rule_outcomes"][0].update(result="unknown", reason_code="opportunity_active")
        self._both_reject("eligibility-result", {
            "fail outcome but eligible": {**res("eligibility_d_data"), "decision": "eligible"},
            "unknown outcome but eligible": {**res("eligibility_b_data"), "decision": "eligible"},
            "all pass but needs_information": {**res("eligibility_a_data"), "decision": "needs_information"},
            "candidate-level decision": {**res("eligibility_a_ops"), "decision": "rejected"},
            "candidate-level field": {**res("eligibility_a_ops"), "candidate_status": "rejected"},
            "integrity failure as unknown": bad_reason,
            "unknown for active-status rule": active_unknown,
            "no outcomes": {**res("eligibility_a_data"), "rule_outcomes": []},
        })

    def test_malformed_retrieval_and_evidence_rejected_by_both(self):
        doc = support.ext_raw()
        chunk, request, ev = copy.deepcopy(doc["chunks"][0]), copy.deepcopy(doc["retrieval_requests"][0]), copy.deepcopy(doc["evidence"][0])
        self._both_reject("retrieval-chunk", {
            "url pointer": {**chunk, "text_pointer": "https://example.invalid/x"},
            "self-declared authorization": {**chunk, "access_status": "allowed"},
            "bad hash": {**chunk, "content_hash": "md5:0"},
        })
        self._both_reject("retrieval-request", {
            "client-supplied principal": {**request, "principal_id": "principal_demo_coordinator"},
            "empty": {**request, "chunk_ids": []},
            "requested sensitive fields": {**request, "fields": ["accommodation"]},
        })
        self._both_reject("evidence-record", {
            "copied excerpt": {**ev, "excerpt": "Synthetic"},
            "unknown basis": {**ev, "basis": "model_output"},
        })

    def test_documented_gaps_python_only(self):
        """Cross-record rules (conflicts, vocabulary membership, outcome support) are not in JSON Schema."""
        doc = support.ext_raw()
        claim = copy.deepcopy(next(c for c in doc["claims"] if c["id"] == "claim_a_python_profile"))
        claim["subject_code"] = "rust"  # not in the vocabulary
        self.assertEqual(list(_validator("candidate-claim").iter_errors(claim)), [])
        corroborating = copy.deepcopy(next(c for c in doc["claims"] if c["id"] == "claim_b_python"))
        corroborating["alternatives"][1]["value"]["presence"] = "has"  # not a genuine conflict
        self.assertEqual(list(_validator("candidate-claim").iter_errors(corroborating)), [])
        with self.assertRaises(ValidationError):
            _model("candidate-claim").model_validate(corroborating)


if __name__ == "__main__":
    unittest.main()
