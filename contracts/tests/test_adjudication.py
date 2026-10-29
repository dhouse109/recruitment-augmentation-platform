"""D-004.12 -- reviewer rubric and adjudication record rules.

No adjudication record is committed: none has happened. Records built here are
in-memory synthetic examples that exercise validation logic only. A
``trusted_service_authenticated`` value written in a test is not attestation.
"""

import unittest

from pydantic import ValidationError

import eval_harness as H
from rap_contracts.adjudication import AdjudicationRecord, ReviewerRubric, check_adjudication, reportable
from rap_contracts.invariants import ContractViolation

RUBRIC = H.load(H.DEFINITIONS_FILE)["reviewer_rubric"]


def reviewer(n, basis="unverified_metadata", kind="human"):
    return {"principal_id": f"principal_example_reviewer_{n}", "asserted_kind": kind, "asserted_role": "adjudicator",
            "attestation_basis": basis}


def label(n, dim="evidence_support", value=2, rationale=None, basis="unverified_metadata"):
    out = {"reviewer": reviewer(n, basis), "dimension": dim, "value": value, "labeled_at": "2026-10-28T20:00:00Z"}
    if rationale:
        out["rationale"] = rationale
    return out


def record(**update):
    base = {"id": "adjudication_example_1", "case_id": "evalcase_g001", "case_version": 1,
            "rubric": {"rubric_id": RUBRIC["id"], "version": RUBRIC["version"]},
            "raw_labels": [label(1), label(2)], "status": "adjudicated",
            "final_labels": [{"dimension": "evidence_support", "value": 2}],
            "recorded_at": "2026-10-28T20:05:00Z", "recorded_by": reviewer(3)}
    base.update(update)
    return base


class RubricTests(unittest.TestCase):
    def test_committed_rubric_is_a_draft_requiring_two_reviewers(self):
        rubric = ReviewerRubric.model_validate(RUBRIC)
        self.assertEqual((rubric.status, rubric.min_independent_reviewers), ("draft", 2))

    def test_no_adjudication_records_are_committed(self):
        for name in (H.DEFINITIONS_FILE, *H.SPLIT_FILES.values()):
            text = (H.FIXTURE_DIR / name).read_text(encoding="utf-8")
            with self.subTest(file=name):
                self.assertNotIn('"id": "adjudication_', text)
                for key in ('"raw_labels"', '"final_labels"', '"adjudicated"'):
                    self.assertNotIn(key, text)
        for split_doc in (H.load(n) for n in H.SPLIT_FILES.values()):
            for case in split_doc["cases"]:
                self.assertEqual((case["adjudication_status"], case["provenance"]["review_status"]),
                                 ("not_adjudicated", "proposed"))

    def test_unordered_scale_rejected(self):
        bad = {**RUBRIC, "dimensions": [{**RUBRIC["dimensions"][0], "scale": list(reversed(RUBRIC["dimensions"][0]["scale"]))}]}
        with self.assertRaises(ValidationError):
            ReviewerRubric.model_validate(bad)


class AdjudicationRecordTests(unittest.TestCase):
    def setUp(self):
        self.rubric = ReviewerRubric.model_validate(RUBRIC)

    def test_valid_dual_review_record(self):
        rec = AdjudicationRecord.model_validate(record())
        check_adjudication(rec, self.rubric)
        self.assertEqual((rec.independent_reviewers, rec.single_reviewer), (2, False))

    def test_structural_rejections(self):
        bad = {
            "model as reviewer": record(raw_labels=[{**label(1), "reviewer": reviewer(1, kind="service")}]),
            "service recorder": record(recorded_by=reviewer(3, kind="service")),
            "adjudicated without final label": record(final_labels=[]),
            "disputed with final label": record(status="disputed", resolution_note="Reviewers disagree on support."),
            "disputed without note": record(status="disputed", final_labels=[]),
            "duplicate reviewer label": record(raw_labels=[label(1), label(1)]),
            "self supersession": record(supersedes="adjudication_example_1"),
        }
        for name, payload in bad.items():
            with self.subTest(name), self.assertRaises(ValidationError):
                AdjudicationRecord.model_validate(payload)

    def test_disputed_record_keeps_raw_labels(self):
        rec = AdjudicationRecord.model_validate(record(
            status="disputed", final_labels=[], resolution_note="Reviewers disagree; third reviewer required.",
            raw_labels=[label(1, value=2), label(2, value=0, rationale="Citation does not show the stated hours.")]))
        self.assertEqual(len(rec.raw_labels), 2)

    def test_rubric_conformance(self):
        cases = {
            "off scale": (record(raw_labels=[label(1, value=5), label(2)]), "value_off_scale"),
            "unknown dimension": (record(raw_labels=[label(1, dim="charisma"), label(2)],
                                         final_labels=[{"dimension": "charisma", "value": 2},
                                                       {"dimension": "evidence_support", "value": 2}]),
                                  "unknown_rubric_dimension"),
            "rationale missing": (record(raw_labels=[label(1, value=1), label(2)]), "rationale_required"),
            "other rubric": (record(rubric={"rubric_id": "rubric_other", "version": 1}), "rubric_mismatch"),
        }
        for name, (payload, code) in cases.items():
            with self.subTest(name), self.assertRaises(ContractViolation) as ctx:
                check_adjudication(AdjudicationRecord.model_validate(payload), self.rubric)
            self.assertEqual(ctx.exception.code, code)

    def test_nothing_is_reportable_without_trusted_attestation(self):
        approved = self.rubric.model_copy(update={"status": "approved"})
        self.assertFalse(reportable(AdjudicationRecord.model_validate(record()), approved))  # unverified metadata
        mock = record(raw_labels=[label(1, basis="mock_authenticated"), label(2, basis="mock_authenticated")],
                      recorded_by=reviewer(3, "mock_authenticated"))
        self.assertFalse(reportable(AdjudicationRecord.model_validate(mock), approved))
        trusted = record(raw_labels=[label(1, basis="trusted_service_authenticated"),
                                     label(2, basis="trusted_service_authenticated")],
                         recorded_by=reviewer(3, "trusted_service_authenticated"))
        self.assertFalse(reportable(AdjudicationRecord.model_validate(trusted), self.rubric))  # draft rubric
        single = {**trusted, "raw_labels": [label(1, basis="trusted_service_authenticated")]}
        self.assertFalse(reportable(AdjudicationRecord.model_validate(single), approved))  # below two reviewers
        # Logic only: these attestation values were typed into a test, not issued by a trusted service.
        self.assertTrue(reportable(AdjudicationRecord.model_validate(trusted), approved))


if __name__ == "__main__":
    unittest.main()
