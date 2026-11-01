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


# ---------------------------------------------------------------------------
# 0.2.0-dev.foundations.3: recommendation, verification and review schemas
# ---------------------------------------------------------------------------

_PYDANTIC_MODELS.update({
    "recommendation": "rap_contracts.recommendation:Recommendation",
    "verification-result": "rap_contracts.recommendation:VerificationResult",
    "human-review-command": "rap_contracts.review:HumanReviewCommand",
    "review-correction-command": "rap_contracts.review:ReviewCorrectionCommand",
    "review-decision": "rap_contracts.review:ReviewDecision",
    "audit-event": "rap_contracts.review:AuditEvent",
    "review-outcome": "rap_contracts.review:ReviewOutcome",
    "review-reason-vocabulary": "rap_contracts.review:ReviewReasonVocabulary",
})


@unittest.skipIf(Draft202012Validator is None, "jsonschema not installed; install contracts/requirements-dev.txt")
class ReviewConformanceTests(unittest.TestCase):
    def _service_records(self):
        svc = support.review_service()
        outcomes = [
            svc.submit_review("credential-demo-coordinator", support.review_command()),
            svc.submit_review("credential-demo-coordinator", support.review_command()),  # replay
            svc.submit_review(None, support.review_command(key="key-demo-0000000002")),  # rejected
        ]
        from rap_contracts.review import ReviewCorrectionCommand
        correction = ReviewCorrectionCommand.model_validate({
            "idempotency_key": "key-demo-correction-01", "corrects_decision_id": outcomes[0].decision.id,
            "reason": {"vocabulary_id": "review_reasons_demo", "vocabulary_version": 1, "code": "meets_published_criteria"},
            "correction_note": "Reason confirmed after reviewing the checklist."})
        outcomes.append(svc.submit_correction("credential-demo-coordinator", correction))
        return svc, outcomes, correction

    def test_fixture_and_service_generated_records_accepted(self):
        doc = support.review_raw()
        svc, outcomes, correction = self._service_records()
        sections = {
            "recommendation": doc["recommendations"] + [r.model_dump(mode="json") for r in svc.recommendations.values()],
            "verification-result": doc["verifications"],
            "review-reason-vocabulary": doc["reason_vocabularies"],
            "human-review-command": [support.review_command().model_dump(mode="json")],
            "review-correction-command": [correction.model_dump(mode="json")],
            "review-decision": [d.model_dump(mode="json") for d in svc.decisions.values()],
            "audit-event": [e.model_dump(mode="json") for e in svc.events],
            "review-outcome": [o.model_dump(mode="json") for o in outcomes],
        }
        self.assertEqual([o.status.value for o in outcomes], ["recorded", "replayed", "rejected", "recorded"])
        for name, items in sections.items():
            validator = _validator(name)
            for i, item in enumerate(items):
                with self.subTest(schema=name, item=i):
                    self.assertEqual(list(validator.iter_errors(item)), [])

    def _both_reject(self, name, cases):
        validator, model = _validator(name), _model(name)
        for label, payload in cases.items():
            with self.subTest(schema=name, case=label):
                self.assertTrue(list(validator.iter_errors(payload)), f"JSON Schema accepted: {label}")
                with self.assertRaises(ValidationError, msg=f"Pydantic accepted: {label}"):
                    model.model_validate(payload)

    def test_malformed_review_records_rejected_by_both(self):
        svc, outcomes, _ = self._service_records()
        command = support.review_command().model_dump(mode="json")
        decision = outcomes[0].decision.model_dump(mode="json")
        event = svc.events[0].model_dump(mode="json")
        recorded, rejected = outcomes[0].model_dump(mode="json"), outcomes[2].model_dump(mode="json")
        rec = copy.deepcopy(support.review_raw()["recommendations"][0])
        ver = copy.deepcopy(support.review_raw()["verifications"][0])
        vocab = copy.deepcopy(support.review_raw()["reason_vocabularies"][0])
        self._both_reject("human-review-command", {
            "client reviewer id": {**command, "reviewer_id": "principal_demo_coordinator"},
            "client actor type": {**command, "actor_type": "human"},
            "legacy action": {**command, "action": "reject_suggestion"},
            "short idempotency key": {**command, "idempotency_key": "abc"},
            "oversized comment": {**command, "comment": "x" * 2001},
        })
        self._both_reject("recommendation", {
            "discovery context": {**rec, "context": {**rec["context"], "kind": "discovery"}},
            "placement status": {**rec, "status": "placed"},
            "free-text rationale": {**rec, "rationale": "Strong fit."},
        })
        self._both_reject("verification-result", {
            "confidence score": {**ver, "confidence": 0.97},
            "unknown outcome": {**ver, "outcome": "probably_fine"},
        })
        self._both_reject("review-decision", {
            "correction without note": {**decision, "corrects_decision_id": "review_decision_0009"},
            "note without correction": {**decision, "correction_note": "x"},
        })
        self._both_reject("audit-event", {
            "free text": {**event, "comment": "x"},
            "corrected without lineage": {**event, "event_type": "review_decision_corrected"},
            "machine actor": {**event, "actor_kind": "service"},
        })
        self._both_reject("review-outcome", {
            "rejected with decision": {**rejected, "decision": decision},
            "rejected with events": {**rejected, "audit_event_ids": ["audit_event_0001"]},
            "recorded without decision": {**recorded, "decision": None},
            "recorded with error": {**recorded, "error": "not_permitted"},
        })
        legacy_vocab = copy.deepcopy(vocab)
        legacy_vocab["reasons"][0]["actions"] = ["reject_suggestion"]
        self._both_reject("review-reason-vocabulary", {"legacy action": legacy_vocab})

    def test_documented_gaps_python_only(self):
        """Vocabulary-dependent comment rules, outcome derivation from checks and authority are Python-only."""
        ver = copy.deepcopy(support.review_raw()["verifications"][0])
        ver["checks"][0]["status"] = "fail"  # still labelled passed
        self.assertEqual(list(_validator("verification-result").iter_errors(ver)), [])
        with self.assertRaises(ValidationError):
            _model("verification-result").model_validate(ver)
        vocab = copy.deepcopy(support.review_raw()["reason_vocabularies"][0])
        vocab["reasons"].append({"code": "quick_dismissal", "actions": ["dismiss_suggestion"], "comment": "optional"})
        self.assertEqual(list(_validator("review-reason-vocabulary").iter_errors(vocab)), [])
        with self.assertRaises(ValidationError):
            _model("review-reason-vocabulary").model_validate(vocab)


# ---------------------------------------------------------------------------
# 0.2.0-dev.foundations.4: evaluation, adjudication and promotion schemas (D-004.12)
# ---------------------------------------------------------------------------

_PYDANTIC_MODELS.update({
    "evaluation-case": "rap_contracts.evaluation:EvaluationCase",
    "evaluation-dataset-manifest": "rap_contracts.evaluation:EvaluationDatasetManifest",
    "evaluation-run": "rap_contracts.evaluation:EvaluationRun",
    "case-observation": "rap_contracts.evaluation:CaseObservation",
    "reviewer-rubric": "rap_contracts.adjudication:ReviewerRubric",
    "adjudication-record": "rap_contracts.adjudication:AdjudicationRecord",
    "metric-definition-set": "rap_contracts.promotion:MetricDefinitionSet",
    "safety-gate-policy": "rap_contracts.promotion:SafetyGatePolicy",
    "promotion-decision": "rap_contracts.promotion:PromotionDecision",
    "held-out-gate-attestation": "rap_contracts.promotion:HeldOutGateAttestation",
    "run-comparison": "rap_contracts.promotion:RunComparison",
})


@unittest.skipIf(Draft202012Validator is None, "jsonschema not installed; install contracts/requirements-dev.txt")
class EvaluationConformanceTests(unittest.TestCase):
    """Committed evaluation fixtures and harness-generated records against the committed schemas."""

    @classmethod
    def setUpClass(cls):
        import eval_harness as H
        import test_adjudication
        import test_promotion_gates
        from rap_contracts.evaluation import Split

        cls.H = H
        cls.defs = H.load(H.DEFINITIONS_FILE)
        cls.docs = {split: H.split_doc(split) for split in Split}
        cls.observations = [H.run_case(c, doc).observation.model_dump(mode="json")
                            for doc in cls.docs.values() for c in H.cases_of(doc)]
        cls.run_record = test_promotion_gates.run().model_dump(mode="json")
        cls.decision = test_promotion_gates.decision()
        cls.attestation = test_promotion_gates.attestation(test_promotion_gates.policy()).model_dump(mode="json")
        cls.adjudication = test_adjudication.record()
        cls.comparison = test_promotion_gates.Scenario().comparison.model_dump(mode="json")

    def _accept(self, name, items):
        validator = _validator(name)
        for i, item in enumerate(items):
            with self.subTest(schema=name, item=item.get("id", item.get("case_id", i))):
                self.assertEqual([e.message for e in validator.iter_errors(item)], [])

    def test_committed_and_generated_records_accepted(self):
        self._accept("evaluation-case", [c for doc in self.docs.values() for c in doc["cases"]])
        self._accept("evaluation-dataset-manifest", [doc["manifest"] for doc in self.docs.values()])
        self._accept("metric-definition-set", [self.defs["metric_definitions"]])
        self._accept("safety-gate-policy", [self.defs["safety_gate_policy"]])
        self._accept("reviewer-rubric", [self.defs["reviewer_rubric"]])
        self._accept("case-observation", self.observations)
        self._accept("evaluation-run", [self.run_record])
        self._accept("promotion-decision", [self.decision])
        self._accept("held-out-gate-attestation", [self.attestation])
        self._accept("adjudication-record", [self.adjudication])
        self._accept("run-comparison", [self.comparison])
        self.assertEqual(len(self.observations), 31)

    def _both_reject(self, name, cases):
        validator, model = _validator(name), _model(name)
        for label, payload in cases.items():
            with self.subTest(schema=name, case=label):
                self.assertTrue(list(validator.iter_errors(payload)), f"JSON Schema accepted: {label}")
                with self.assertRaises(ValidationError, msg=f"Pydantic accepted: {label}"):
                    model.model_validate(payload)

    def test_draft_definitions_v2_conform_to_existing_schemas(self):
        """F4 PR-A: the proposed draft v2 objects validate against the committed (not regenerated) schemas."""
        v2 = self.H.load(self.H.DEFINITIONS_V2_FILE)
        self._accept("metric-definition-set", [v2["metric_definitions"]])
        self._accept("safety-gate-policy", [v2["safety_gate_policy"]])
        self._accept("reviewer-rubric", [v2["reviewer_rubric"]])

    def test_adjudication_integrity_conformance(self):
        """F4 PR-B (0.2.0-dev.foundations.5): rubric v2, the per-output adjudication record and the
        diagnostic usefulness value against the regenerated schemas. Records here are SYNTHETIC."""
        import test_adjudication as A

        rubric_v2 = self.H.load(self.H.RUBRIC_V2_FILE)["reviewer_rubric"]
        self._accept("reviewer-rubric", [rubric_v2, self.H.load(self.H.DEFINITIONS_FILE)["reviewer_rubric"]])
        disputed = A.record_with(A.ES, [A.lab(A.P1, A.ES, 2), A.lab(A.P2, A.ES, 0, rationale="x")],
                                 A.result(A.ES, resolution="disputed"), status="disputed")
        not_applicable = A.record_with(A.UH, [A.lab(A.P1, A.UH, na=A.NA_UNKNOWN), A.lab(A.P2, A.UH, na=A.NA_UNKNOWN)],
                                       A.result(A.UH, na=A.NA_UNKNOWN))
        self._accept("adjudication-record", [disputed, not_applicable])
        coverage = {"items_total": 3, "produced_expected": 1, "produced_unexpected": 0, "missing": 1,
                    "correctly_absent": 0, "generation_failed": 1, "reviewed": 1, "unreviewed": 0,
                    "genuinely_reportable": 0, "structurally_eligible_only": 1, "structurally_ineligible": 0,
                    "dimension_states": [{"dimension": "evidence_support", "scored": 1, "not_applicable": 0,
                                          "disputed": 0, "unresolved": 0}]}
        usefulness = {"kind": "distribution", "metric_id": "reviewer_usefulness", "metric_version": 2,
                      "status": "not_measured", "coverage": coverage}
        with_usefulness = {**self.comparison, "metrics": self.comparison["metrics"] + [
            {"metric_id": "reviewer_usefulness", "metric_version": 2, "baseline": usefulness, "candidate": usefulness}]}
        self._accept("run-comparison", [with_usefulness])
        _model("run-comparison").model_validate(with_usefulness)
        legacy = {"kind": "distribution", "metric_id": "reviewer_usefulness", "metric_version": 1, "status": "observed",
                  "counts": [{"value": 2, "count": 1}]}
        self._both_reject("reviewer-rubric", {
            "recorded discussion (N1)": {**rubric_v2, "disagreement_policy": "recorded_discussion"},
            "three primaries": {**rubric_v2, "min_independent_reviewers": 3},
        })
        record = A.record()
        self._both_reject("adjudication-record", {
            "three designated primaries": {**record, "primary_reviewers": [A.P1, A.P2, "principal_example_reviewer_3"]},
            "unknown review role": {**record, "raw_labels": [{**record["raw_labels"][0], "role": "observer"}]},
            "value above every scale": {**record, "raw_labels": [{**record["raw_labels"][0], "value": 11}]},
            "no subject": {k: v for k, v in record.items() if k != "subject"},
            "legacy case-scoped shape": {**{k: v for k, v in record.items() if k != "subject"},
                                         "case_id": "evalcase_g001", "case_version": 1},
            "self-declared reportability": {**record, "reportable": True},
        })
        self._both_reject("run-comparison", {
            "legacy flat distribution": {**self.comparison, "metrics": self.comparison["metrics"] + [
                {"metric_id": "reviewer_usefulness", "metric_version": 1, "baseline": legacy, "candidate": legacy}]},
        })
        # Python-only: result derivation, designated-primary membership and coverage reconciliation.
        python_only = {
            "adjudication-record": [
                A.record_with(A.ES, [A.lab(A.P1, A.ES), A.lab(A.P2, A.ES)], A.result(A.ES, 1)),
                A.record_with(A.ES, [A.lab(A.P1, A.ES), A.lab(A.P2, A.ES), A.lab("principal_example_reviewer_3", A.ES)],
                              A.result(A.ES)),
            ],
            "run-comparison": [{**self.comparison, "metrics": self.comparison["metrics"] + [
                {"metric_id": "reviewer_usefulness", "metric_version": 2,
                 "baseline": {**usefulness, "coverage": {**coverage, "items_total": 9}},
                 "candidate": usefulness}]}],
        }
        for name, payloads in python_only.items():
            for payload in payloads:
                with self.subTest(schema=name, gap="python-only"):
                    self.assertEqual(list(_validator(name).iter_errors(payload)), [])
                    with self.assertRaises(ValidationError):
                        _model(name).model_validate(payload)

    def test_malformed_evaluation_records_rejected_by_both(self):
        case = copy.deepcopy(self.docs[next(iter(self.docs))]["cases"][0])
        bad_step = copy.deepcopy(case)
        bad_step["steps"][0]["operation"] = "run_model"
        manifest = copy.deepcopy(self.docs[next(iter(self.docs))]["manifest"])
        obs = copy.deepcopy(self.observations[0])
        self._both_reject("evaluation-case", {
            "unknown operation": bad_step,
            "free-text expected output": {**case, "expected_output": "Strong fit"},
            "no steps": {**case, "steps": []},
        })
        self._both_reject("evaluation-dataset-manifest", {
            "unknown custody": {**manifest, "custody": "trust_me"},
            "real data policy": {**manifest, "data_policy": "production"},
        })
        self._both_reject("case-observation", {
            "copied text": {**obs, "admitted_text": "Synthetic"},
            "caller-visible observation": {**obs, "visibility": "public"},
        })
        self._both_reject("evaluation-run", {
            "unknown run kind": {**self.run_record, "run_kind": "vibes"},
            "accuracy score field": {**self.run_record, "accuracy": 0.97},
        })
        self._both_reject("promotion-decision", {
            "waiver": {**self.decision, "waiver": "accepted"},
            "auto-promotion": {**self.decision, "decision": "auto_promote"},
        })
        self._both_reject("held-out-gate-attestation", {
            "case identifiers": {**self.attestation, "case_ids": ["evalcase_h001"]},
        })
        self._both_reject("run-comparison", {
            "self-declared completeness": {**self.comparison, "status": "complete"},
            "invented delta": {**self.comparison, "metrics": [{**self.comparison["metrics"][0], "delta": 0.1}]},
            "threshold verdict": {**self.comparison, "passed_threshold": True},
        })
        self._both_reject("promotion-decision", {
            "self-declared comparison status": {**self.decision, "comparison_status": "complete"},
        })
        self._both_reject("adjudication-record", {
            "llm judge field": {**self.adjudication, "llm_judge_score": 0.8},
        })

    def test_documented_gaps_python_only(self):
        """Case grammar, value-iff-observed, zero-tolerance completeness and promotion strictness are Python-only."""
        case = copy.deepcopy(self.docs[next(iter(self.docs))]["cases"][0])
        for step in case["steps"]:
            step["role"] = "prerequisite"
            step.pop("consequence_of", None)
        self.assertEqual(list(_validator("evaluation-case").iter_errors(case)), [])
        with self.assertRaises(ValidationError):
            _model("evaluation-case").model_validate(case)
        fabricated = {**self.run_record, "latency": {"status": "not_measured", "unit": "milliseconds", "value": 0}}
        self.assertEqual(list(_validator("evaluation-run").iter_errors(fabricated)), [])
        with self.assertRaises(ValidationError):
            _model("evaluation-run").model_validate(fabricated)
        edited = copy.deepcopy(self.comparison)
        edited["cases"][0]["change"] = "improved"  # contradicts identical outcomes
        self.assertEqual(list(_validator("run-comparison").iter_errors(edited)), [])
        with self.assertRaises(ValidationError):
            _model("run-comparison").model_validate(edited)
        forged = copy.deepcopy(self.run_record)
        forged["configuration"]["fingerprint"] = "sha256:" + "f" * 64
        self.assertEqual(list(_validator("evaluation-run").iter_errors(forged)), [])
        with self.assertRaises(ValidationError):
            _model("evaluation-run").model_validate(forged)
        weak = {**self.decision, "decided_by": {**self.decision["decided_by"], "attestation_basis": "unverified_metadata"}}
        self.assertEqual(list(_validator("promotion-decision").iter_errors(weak)), [])
        with self.assertRaises(ValidationError):
            _model("promotion-decision").model_validate(weak)



@unittest.skipIf(Draft202012Validator is None, "jsonschema not installed; install contracts/requirements-dev.txt")
class GeneratedResultBindingConformanceTests(unittest.TestCase):
    """PR-S3a V5: the committed case-observation schema enforces the same binding shape as Python (V1, V2, V4).

    Synthetic step payloads only; no fixture file is read. Both validators check SHAPE, not provenance.
    """

    GENERATED = "eligibility_" + "b2" * 20

    def observation(self, operation="eligibility_support", basis="deterministic_baseline_execution",
                    status="matched", rid=GENERATED):
        observed = None if status == "not_evaluated" else {"result": "accepted", "decision": "eligible",
                                                           "eligibility_result_id": rid}
        if status == "errored" and observed is not None:
            observed = {"error_type": "engine_refused", "eligibility_result_id": rid}
        return {"run_id": "evalrun_example", "case_id": "evalcase_example", "case_version": 1,
                "case_sha256": "sha256:" + "0" * 64, "split": "golden", "execution_status": "executed",
                "steps": [{"step_id": "s1", "role": "target", "operation": operation, "status": status,
                           "basis": basis, "observed": observed}],
                "outcome": {"matched": "pass", "mismatched": "fail", "errored": "fail",
                            "not_evaluated": "inconclusive"}[status],
                "latency": {"status": "not_measured", "unit": "milliseconds"},
                "cost": {"status": "not_applicable", "unit": "usd"}}

    def setUp(self):
        self.validator, self.model = _validator("case-observation"), _model("case-observation")

    def accepted_by_both(self, payload):
        self.assertEqual([e.message for e in self.validator.iter_errors(payload)], [])
        self.model.model_validate(payload)

    def rejected_by_both(self, payload, label):
        self.assertTrue(list(self.validator.iter_errors(payload)), f"JSON Schema accepted: {label}")
        with self.assertRaises(ValidationError, msg=f"Pydantic accepted: {label}"):
            self.model.model_validate(payload)

    def test_accepted_shapes(self):
        cases = {
            "matched, named": self.observation(),
            "mismatched, named": self.observation(status="mismatched"),
            "errored, unnamed": self.observation(status="errored", rid=None),
            "not evaluated": self.observation(status="not_evaluated"),
            "T2 reference validator, unnamed": self.observation(basis="reference_validator", rid=None),
            "offline model, unnamed": self.observation(basis="offline_model_execution", rid=None),
            "other operation, unnamed": self.observation(operation="context_validation", rid=None),
        }
        for label, payload in cases.items():
            with self.subTest(label):
                self.accepted_by_both(payload)

    def test_rejected_shapes(self):
        cases = {
            "V1 missing id (null)": self.observation(rid=None),
            "V1 mismatched missing id": self.observation(status="mismatched", rid=None),
            "V2 errored with id": self.observation(status="errored"),
            "V4 T2 basis with id": self.observation(basis="reference_validator"),
            "V4 offline model with id": self.observation(basis="offline_model_execution"),
            "V4 other operation with id": self.observation(operation="context_validation"),
            "malformed id": self.observation(rid="claim_not_a_result"),
        }
        missing_key = self.observation()
        del missing_key["steps"][0]["observed"]["eligibility_result_id"]
        cases["V1 missing id (absent key)"] = missing_key
        for label, payload in cases.items():
            with self.subTest(label):
                self.rejected_by_both(payload, label)

    def test_fabricated_well_formed_id_is_accepted_by_both(self):
        """Documented limit: neither validator can know whether a named result was really generated."""
        self.accepted_by_both(self.observation(rid="eligibility_fabricated_by_hand"))


if __name__ == "__main__":
    unittest.main()
