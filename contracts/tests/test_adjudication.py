"""D-004.12 / F4 PR-B -- reviewer rubric, review items, adjudication integrity and reportability.

No adjudication record is committed: none has happened. Every record, review item,
conflict register and attestation value built here is an in-memory SYNTHETIC example
that exercises validation logic only. A ``trusted_service_authenticated`` or
``trusted_service_attested`` value written in a test is a caller-supplied claim, not
authentication, a role grant or proof of independence -- which is exactly what the
reportability tests show: nothing here can become genuinely reportable.
"""

import copy
import unittest

from pydantic import ValidationError

import eval_harness as H
import test_promotion_gates as G
from rap_contracts.adjudication import (
    AdjudicationRecord,
    ReportabilityAssessment,
    ReviewerConflictRegister,
    ReviewerRubric,
    ReviewItem,
    assess_reportability,
    check_adjudication,
    check_record_attachment,
    check_review_items,
    derive_usefulness_distribution,
    reportable,
)
from rap_contracts.evaluation import Split
from rap_contracts.invariants import ContractViolation
from rap_contracts.promotion import MetricDefinitionSet

RUBRIC_V1 = H.load(H.DEFINITIONS_FILE)["reviewer_rubric"]
RUBRIC_V2_DOC = H.load(H.RUBRIC_V2_FILE)
RUBRIC_V2 = RUBRIC_V2_DOC["reviewer_rubric"]
DIMS = [d["code"] for d in RUBRIC_V2["dimensions"]]
ES, UH, EC, FU = DIMS  # evidence_support, unknown_handling, explanation_clarity, follow_up_actionability
NA_UNKNOWN, EXP_UNKNOWN = "pinned_case_expects_no_unknown_or_contested_facts", "no_unknown_or_contested_facts_expected"
NA_FOLLOW, EXP_FOLLOW = "pinned_case_expects_no_follow_up", "no_follow_up_expected"
CASE = "evalcase_g001"
P1, P2, ADJ, REC = ("principal_example_reviewer_1", "principal_example_reviewer_2", "principal_example_adjudicator",
                    "principal_example_recorder")
TRUSTED, UNVERIFIED, MOCK = "trusted_service_authenticated", "unverified_metadata", "mock_authenticated"
ROLE = {"primary": "evaluation_reviewer", "adjudicator": "evaluation_adjudicator", "recorder": "evaluation_recorder"}
USEFULNESS = MetricDefinitionSet.model_validate(H.load(H.DEFINITIONS_V2_FILE)["metric_definitions"]).get("reviewer_usefulness", 2)


def rubric(status="draft"):
    """Rubric v2. ``status="approved"`` is an IN-MEMORY synthetic copy; the committed rubric stays draft."""
    return ReviewerRubric.model_validate({**RUBRIC_V2, "status": status})


def run(**kw):
    return G.run(**kw)  # SYNTHETIC logic-only run evalrun_candidate_1 (one replicate)


def key(slot="recommendation_1", case=CASE, replicate=1, run_id="evalrun_candidate_1"):
    pin = G.PINS[case]
    return {"run_id": run_id, "case_id": case, "case_version": pin.version, "case_sha256": pin.sha256,
            "replicate": replicate, "output_slot": slot}


def item(slot="recommendation_1", status="produced", presence="expected", output="recommendation_example_1",
         expectations=(), **kw):
    doc = {"key": key(slot, **kw), "expected_presence": presence, "output_status": status,
           "applicability_expectations": list(expectations)}
    if status == "produced":
        doc["produced_output"] = {"output_id": output, "output_kind": "recommendation"}
    return ReviewItem.model_validate(doc)


def who(pid, role="primary", basis=UNVERIFIED, kind="human"):
    out = {"principal_id": pid, "asserted_kind": kind, "attestation_basis": basis}
    if role:
        out["asserted_role"] = ROLE[role]
    return out


def lab(pid, dim, value=2, na=None, role="primary", rationale=None, basis=UNVERIFIED):
    out = {"reviewer": who(pid, role, basis), "role": role, "dimension": dim, "labeled_at": "2026-10-29T12:00:00Z"}
    if na:
        out.update(applicability="not_applicable", not_applicable_reason=na, rationale=rationale or "Pinned case expects none.")
    else:
        out.update(applicability="scored", value=value)
        if rationale:
            out["rationale"] = rationale
    if role == "adjudicator" and "rationale" not in out:
        out["rationale"] = "Resolved after reading both primary rationales."
    return out


def result(dim, value=2, na=None, derivation="unanimous", resolution=None):
    if resolution in ("disputed", "unresolved"):
        return {"dimension": dim, "resolution": resolution, "derivation": "none"}
    if na:
        return {"dimension": dim, "resolution": "not_applicable", "not_applicable_reason": na, "derivation": derivation}
    return {"dimension": dim, "resolution": "scored", "value": value, "derivation": derivation}


def record(labels=None, results=None, status="adjudicated", basis=UNVERIFIED, slot="recommendation_1",
           output="recommendation_example_1", rid="adjudication_example_1", **update):
    labels = labels if labels is not None else [lab(p, d, basis=basis) for d in DIMS for p in (P1, P2)]
    results = results if results is not None else [result(d) for d in DIMS]
    out = {"id": rid, "subject": {"item": key(slot), "output_id": output},
           "rubric": {"rubric_id": RUBRIC_V2["id"], "version": RUBRIC_V2["version"]},
           "primary_reviewers": [P1, P2], "adjudicator": ADJ, "raw_labels": labels, "dimension_results": results,
           "status": status, "recorded_at": "2026-10-29T12:05:00Z", "recorded_by": who(REC, "recorder", basis)}
    if status != "adjudicated":
        out["resolution_note"] = "Recorded as counted, not as a final label."
    out.update(update)
    return out


def record_with(dim, dim_labels, dim_result, status="adjudicated", basis=UNVERIFIED, **kw):
    """Every other dimension unanimous at 2; ``dim`` gets the given labels and result."""
    labels = [lab(p, d, basis=basis) for d in DIMS if d != dim for p in (P1, P2)] + dim_labels
    return record(labels=labels, results=[result(d) for d in DIMS if d != dim] + [dim_result], status=status,
                  basis=basis, **kw)


def register(conflicts=(), coverage="complete_for_scope", basis="trusted_service_attested", configuration=None, case=CASE):
    pin = G.PINS[case]
    return ReviewerConflictRegister.model_validate({
        "configuration": (configuration or run().configuration).model_dump(mode="json"), "case_id": case,
        "case_version": pin.version, "coverage": coverage, "basis": basis,
        "conflicts": [{"principal_id": p, "reason": r} for p, r in conflicts]})


def forged(**kw):
    """Every structural claim set to its trusted-looking value: the strongest input a caller can craft."""
    return (AdjudicationRecord.model_validate(record(basis=TRUSTED, **kw)), rubric("approved"), [item()], run(),
            register())


class RubricTests(unittest.TestCase):
    def test_v1_rubric_copies_still_validate_unchanged(self):
        copies = [H.load(name)["reviewer_rubric"] for name in (H.DEFINITIONS_FILE, H.DEFINITIONS_V2_FILE)]
        self.assertEqual(copies[0], copies[1])
        for doc in copies:
            r = ReviewerRubric.model_validate(doc)
            self.assertEqual((r.version, r.status, r.min_independent_reviewers, r.disagreement_policy.value),
                             (1, "draft", 2, "third_reviewer"))
            self.assertTrue(all(not d.not_applicable_reasons for d in r.dimensions))

    def test_rubric_v2_is_a_draft_with_expectation_grounded_na(self):
        r = rubric()
        self.assertEqual((r.id, r.version, r.status, r.min_independent_reviewers, r.disagreement_policy.value),
                         ("rubric_reviewer_usefulness", 2, "draft", 2, "third_reviewer"))
        self.assertEqual(RUBRIC_V2_DOC["contract_version"], "0.2.0-dev.foundations.5")
        na = {d.code: [(x.reason, x.requires_expectation) for x in d.not_applicable_reasons] for d in r.dimensions}
        self.assertEqual(na, {ES: [], UH: [(NA_UNKNOWN, EXP_UNKNOWN)], EC: [], FU: [(NA_FOLLOW, EXP_FOLLOW)]})
        text = (H.FIXTURE_DIR / H.RUBRIC_V2_FILE).read_text(encoding="utf-8")
        self.assertNotIn("no_follow_up_suggestion_in_output", text)  # withdrawn: not grounded in a pinned expectation
        self.assertNotIn('"status": "approved"', text)

    def test_cardinality_and_disagreement_policy_are_fixed(self):
        dim = RUBRIC_V2["dimensions"][1]
        bad = {
            "recorded discussion (N1)": {**RUBRIC_V2, "disagreement_policy": "recorded_discussion"},
            "one primary": {**RUBRIC_V2, "min_independent_reviewers": 1},
            "three primaries (no majority, E12)": {**RUBRIC_V2, "min_independent_reviewers": 3},
            "duplicate N/A reason": {**RUBRIC_V2, "dimensions": [
                {**dim, "not_applicable_reasons": dim["not_applicable_reasons"] * 2}]},
            "unordered scale": {**RUBRIC_V2, "dimensions": [{**dim, "scale": list(reversed(dim["scale"]))}]},
        }
        for name, doc in bad.items():
            with self.subTest(name), self.assertRaises(ValidationError):
                ReviewerRubric.model_validate(doc)

    def test_no_adjudication_records_are_committed(self):
        for name in (H.DEFINITIONS_FILE, H.DEFINITIONS_V2_FILE, H.RUBRIC_V2_FILE, *H.SPLIT_FILES.values()):
            text = (H.FIXTURE_DIR / name).read_text(encoding="utf-8")
            with self.subTest(file=name):
                for marker in ('"id": "adjudication_', '"raw_labels"', '"dimension_results"', '"final_labels"',
                               '"primary_reviewers"', '"adjudicated"', '"conflicts"', '"output_slot"'):
                    self.assertNotIn(marker, text)
        for split_doc in (H.load(n) for n in H.SPLIT_FILES.values()):
            for case in split_doc["cases"]:
                self.assertEqual((case["adjudication_status"], case["provenance"]["review_status"]),
                                 ("not_adjudicated", "proposed"))


class ReviewItemTests(unittest.TestCase):
    """E1-E3, E14: item identity exists without a produced output; items are caller-declared."""

    def test_output_presence_categories(self):
        cases = {
            "produced_expected": item(),
            "produced_unexpected": item(presence="not_expected"),
            "missing": item(status="absent"),
            "correctly_absent": item(status="absent", presence="not_expected"),
            "generation_failed": item(status="generation_failed"),
        }
        for expected, it in cases.items():
            with self.subTest(expected):
                self.assertEqual(it.presence, expected)
                self.assertEqual(it.provenance, "caller_declared")
        self.assertEqual(item(status="generation_failed", presence="not_expected").presence, "generation_failed")

    def test_produced_output_reference_only_when_produced(self):
        base = {"key": key(), "expected_presence": "expected"}
        ref = {"output_id": "recommendation_example_1", "output_kind": "recommendation"}
        bad = {
            "produced without a reference": {**base, "output_status": "produced"},
            "absent with a reference": {**base, "output_status": "absent", "produced_output": ref},
            "failed with a reference": {**base, "output_status": "generation_failed", "produced_output": ref},
            "trusted provenance claimed": {**base, "output_status": "absent", "provenance": "trusted_derived"},
        }
        for name, doc in bad.items():
            with self.subTest(name), self.assertRaises(ValidationError):
                ReviewItem.model_validate(doc)

    def test_duplicate_items_and_double_counted_outputs_rejected(self):
        cases = {
            "duplicate_review_item": [item(), item(output="recommendation_example_2")],
            "duplicate_produced_output": [item("recommendation_1"), item("recommendation_2")],
        }
        for code, items in cases.items():
            with self.subTest(code), self.assertRaises(ContractViolation) as ctx:
                check_review_items(items, run(), G.GOLDEN)
            self.assertEqual(ctx.exception.code, code)
        # The same output id in another run is not a double count; it fails only on run membership.
        with self.assertRaises(ContractViolation) as ctx:
            check_review_items([item("recommendation_1"), item("recommendation_2", run_id="evalrun_candidate_2")],
                               run(), G.GOLDEN)
        self.assertEqual(ctx.exception.code, "review_item_run_mismatch")

    def test_items_are_checked_against_run_manifest_and_replicates(self):
        several = [item("recommendation_1"), item("recommendation_2", output="recommendation_example_2"),
                   item("explanation_1", status="absent"), item("recommendation_3", status="generation_failed")]
        check_review_items(several, run(), G.GOLDEN)  # several outputs of one case and replicate stay distinct
        check_review_items([item(replicate=2)], run(replicates=2), G.GOLDEN)
        wrong_sha = ReviewItem.model_validate({**item().model_dump(mode="json"),
                                               "key": {**key(), "case_sha256": "sha256:" + "0" * 64}})
        cases = {
            "review_item_run_mismatch": [item(run_id="evalrun_candidate_2")],
            "review_item_case_mismatch": [wrong_sha],
            "review_item_replicate_out_of_range": [item(replicate=2)],
        }
        for code, items in cases.items():
            with self.subTest(code), self.assertRaises(ContractViolation) as ctx:
                check_review_items(items, run(), G.GOLDEN)
            self.assertEqual(ctx.exception.code, code)


class DerivationTests(unittest.TestCase):
    """B2, E4, E5, E12: results are recomputed from exactly two designated primaries and an adjudicator."""

    def test_unanimous_scores_and_unanimous_na(self):
        rec = AdjudicationRecord.model_validate(record_with(
            UH, [lab(P1, UH, na=NA_UNKNOWN), lab(P2, UH, na=NA_UNKNOWN)], result(UH, na=NA_UNKNOWN)))
        self.assertEqual(rec.status.value, "adjudicated")
        self.assertTrue(all(r.derivation.value == "unanimous" for r in rec.dimension_results))
        check_adjudication(rec, rubric())

    def test_disagreement_resolved_only_by_the_designated_adjudicator(self):
        labels = [lab(P1, ES, 2), lab(P2, ES, 0, rationale="Citation does not show the hours."),
                  lab(ADJ, ES, 1, role="adjudicator")]
        rec = AdjudicationRecord.model_validate(record_with(ES, labels, result(ES, 1, derivation="adjudicator_resolution")))
        res = next(r for r in rec.dimension_results if r.dimension == ES)
        self.assertEqual((res.resolution.value, res.value, res.derivation.value), ("scored", 1, "adjudicator_resolution"))
        check_adjudication(rec, rubric())

    def test_disagreement_without_adjudicator_is_disputed_and_keeps_agreed_dimensions(self):
        labels = [lab(P1, ES, 2), lab(P2, ES, 0, rationale="Citation does not show the hours.")]
        rec = AdjudicationRecord.model_validate(record_with(ES, labels, result(ES, resolution="disputed"), status="disputed"))
        states = {r.dimension: r.resolution.value for r in rec.dimension_results}
        self.assertEqual(states, {ES: "disputed", UH: "scored", EC: "scored", FU: "scored"})
        self.assertEqual(rec.status.value, "disputed")
        with self.assertRaises(ValidationError):  # a disputed record must explain itself
            AdjudicationRecord.model_validate({**record_with(ES, labels, result(ES, resolution="disputed"),
                                                             status="disputed"), "resolution_note": None})

    def test_missing_primary_label_is_unresolved(self):
        rec = AdjudicationRecord.model_validate(record_with(ES, [lab(P1, ES, 2)], result(ES, resolution="unresolved"),
                                                            status="unresolved"))
        self.assertEqual(rec.status.value, "unresolved")

    def test_declared_results_must_follow_from_labels(self):
        """Failure-first P1/P2: arbitrary final labels were accepted on main."""
        disputed_labels = [lab(P1, ES, 2), lab(P2, ES, 0, rationale="Citation does not show the hours.")]
        adjudicated = disputed_labels + [lab(ADJ, ES, 1, role="adjudicator")]
        bad = {
            "unanimous 2 declared as 1": record_with(ES, [lab(P1, ES), lab(P2, ES)], result(ES, 1)),
            "disagreement declared as a score": record_with(ES, disputed_labels, result(ES, 2)),
            "adjudication declared unanimous": record_with(ES, adjudicated, result(ES, 1)),
            "adjudicator value replaced": record_with(ES, adjudicated, result(ES, 2, derivation="adjudicator_resolution")),
            "status claims adjudicated while disputed": record_with(ES, disputed_labels, result(ES, resolution="disputed")),
            "labelled dimension without a result": record(results=[result(d) for d in DIMS if d != ES]),
            "two results for one dimension": record(results=[result(d) for d in DIMS] + [result(ES)]),
        }
        for name, doc in bad.items():
            with self.subTest(name), self.assertRaises(ValidationError):
                AdjudicationRecord.model_validate(doc)

    def test_exactly_two_designated_primaries(self):
        """Failure-first P3: an extra reviewer was counted as another independent reviewer on main."""
        third = [lab(P1, ES), lab(P2, ES), lab("principal_example_reviewer_3", ES)]
        bad = {
            "third primary label": record_with(ES, third, result(ES)),
            # Isolates the designation rule: the declared result already matches what derivation would give.
            "third primary label with a consistent result": record_with(
                ES, third, result(ES, resolution="unresolved"), status="unresolved"),
            "primaries not distinct": record(primary_reviewers=[P1, P1]),
            "three designated primaries": record(primary_reviewers=[P1, P2, "principal_example_reviewer_3"]),
            "one designated primary": record(primary_reviewers=[P1]),
            "adjudicator is a primary": record(adjudicator=P1),
            "adjudicator label from someone else": record_with(
                ES, [lab(P1, ES, 2), lab(P2, ES, 0, rationale="x"), lab("principal_example_other", ES, 1, role="adjudicator")],
                result(ES, 1, derivation="adjudicator_resolution")),
            "same reviewer twice on a dimension": record_with(ES, [lab(P1, ES), lab(P1, ES), lab(P2, ES)], result(ES)),
        }
        for name, doc in bad.items():
            with self.subTest(name), self.assertRaises(ValidationError):
                AdjudicationRecord.model_validate(doc)

    def test_unauthorized_resolutions_rejected(self):
        no_rationale = lab(ADJ, ES, 1, role="adjudicator")
        del no_rationale["rationale"]
        bad = {
            "adjudicator label where primaries agree": record_with(
                ES, [lab(P1, ES), lab(P2, ES), lab(ADJ, ES, 2, role="adjudicator")], result(ES)),
            "adjudicator label with a primary missing": record_with(
                ES, [lab(P1, ES), lab(ADJ, ES, 2, role="adjudicator")], result(ES, resolution="unresolved"),
                status="unresolved"),
            "adjudicator without rationale": record_with(
                ES, [lab(P1, ES, 2), lab(P2, ES, 0, rationale="x"), no_rationale],
                result(ES, 1, derivation="adjudicator_resolution")),
            "no designated adjudicator": record_with(
                ES, [lab(P1, ES, 2), lab(P2, ES, 0, rationale="x"), lab(ADJ, ES, 1, role="adjudicator")],
                result(ES, 1, derivation="adjudicator_resolution"), adjudicator=None),
        }
        for name, doc in bad.items():
            with self.subTest(name), self.assertRaises(ValidationError):
                AdjudicationRecord.model_validate(doc)

    def test_label_shape_and_role_assertions(self):
        no_rationale_na = lab(P1, UH, na=NA_UNKNOWN)
        del no_rationale_na["rationale"]
        no_role = lab(P1, ES)
        del no_role["reviewer"]["asserted_role"]
        cases = {
            "N/A without rationale": no_rationale_na,
            "scored without value": {**lab(P1, ES), "value": None},
            "N/A with a value": {**lab(P1, UH, na=NA_UNKNOWN), "value": 2},
            "N/A without a reason": {**lab(P1, UH, na=NA_UNKNOWN), "not_applicable_reason": None},
            "primary asserting the adjudicator role": {**lab(P1, ES), "reviewer": who(P1, "adjudicator")},
            "no asserted role": no_role,
            "service as reviewer": {**lab(P1, ES), "reviewer": who(P1, kind="service")},
        }
        for name, bad_label in cases.items():
            with self.subTest(name), self.assertRaises(ValidationError):
                AdjudicationRecord.model_validate(record_with(ES, [bad_label, lab(P2, ES)], result(ES)))
        with self.assertRaises(ValidationError):
            AdjudicationRecord.model_validate(record(recorded_by=who(REC, "recorder", kind="service")))

    def test_na_disagreements_need_adjudication(self):
        """E4: unanimous N/A needs the same reason; N/A against a score is a disagreement."""
        for name, labels in {
            "N/A versus a score": [lab(P1, UH, na=NA_UNKNOWN), lab(P2, UH, 2)],
            "different N/A reasons": [lab(P1, UH, na=NA_UNKNOWN), lab(P2, UH, na="pinned_case_other_reason")],
        }.items():
            with self.subTest(name):
                rec = AdjudicationRecord.model_validate(record_with(UH, labels, result(UH, resolution="disputed"),
                                                                    status="disputed"))
                self.assertEqual(rec.status.value, "disputed")


class RubricConformanceTests(unittest.TestCase):
    def test_every_rubric_dimension_needs_a_result(self):
        """Failure-first P1: an 'adjudicated' record covering 2 of 4 dimensions was accepted on main."""
        partial = AdjudicationRecord.model_validate(record(
            labels=[lab(p, d) for d in DIMS[:2] for p in (P1, P2)], results=[result(d) for d in DIMS[:2]]))
        with self.assertRaises(ContractViolation) as ctx:
            check_adjudication(partial, rubric())
        self.assertEqual(ctx.exception.code, "rubric_dimension_coverage")

    def test_scale_reason_and_rationale_rules(self):
        cases = {
            "value_off_scale": record_with(ES, [lab(P1, ES, 5), lab(P2, ES, 5)], result(ES, 5)),
            "unknown_rubric_dimension": record(labels=[lab(p, d) for d in DIMS + ["charisma"] for p in (P1, P2)],
                                               results=[result(d) for d in DIMS + ["charisma"]]),
            "not_applicable_reason_not_allowed": record_with(
                ES, [lab(P1, ES, na=NA_UNKNOWN), lab(P2, ES, na=NA_UNKNOWN)], result(ES, na=NA_UNKNOWN)),
            "rationale_required": record_with(ES, [lab(P1, ES, 1), lab(P2, ES, 1)], result(ES, 1)),
            "rubric_mismatch": record(rubric={"rubric_id": "rubric_other", "version": 1}),
        }
        for code, doc in cases.items():
            with self.subTest(code), self.assertRaises(ContractViolation) as ctx:
                check_adjudication(AdjudicationRecord.model_validate(doc), rubric())
            self.assertEqual(ctx.exception.code, code)
        v1 = ReviewerRubric.model_validate(RUBRIC_V1)  # rubric v1 allows no N/A at all
        na_v1 = AdjudicationRecord.model_validate(record_with(
            UH, [lab(P1, UH, na=NA_UNKNOWN), lab(P2, UH, na=NA_UNKNOWN)], result(UH, na=NA_UNKNOWN),
            rubric={"rubric_id": RUBRIC_V1["id"], "version": 1}))
        with self.assertRaises(ContractViolation) as ctx:
            check_adjudication(na_v1, v1)
        self.assertEqual(ctx.exception.code, "not_applicable_reason_not_allowed")


class AttachmentTests(unittest.TestCase):
    def test_records_attach_only_to_produced_outputs(self):
        rec = AdjudicationRecord.model_validate(record())
        check_record_attachment(rec, [item()], rubric())
        cases = {
            "record_item_missing": [item("recommendation_2")],
            "record_attached_to_absent_output": [item(status="absent")],
            "record_attached_to_absent_output ": [item(status="generation_failed")],
            "record_output_mismatch": [item(output="recommendation_example_9")],
        }
        for code, items in cases.items():
            with self.subTest(code), self.assertRaises(ContractViolation) as ctx:
                check_record_attachment(rec, items, rubric())
            self.assertEqual(ctx.exception.code, code.strip())

    def test_na_requires_the_matching_pinned_expectation(self):
        """E10: N/A is grounded in the item's pinned expectation. An output that merely omitted required
        information gives the reviewer no expectation to cite, so the dimension must be scored."""
        rec = AdjudicationRecord.model_validate(record_with(
            UH, [lab(P1, UH, na=NA_UNKNOWN), lab(P2, UH, na=NA_UNKNOWN)], result(UH, na=NA_UNKNOWN)))
        for name, expectations in {"no expectation": (), "another expectation": (EXP_FOLLOW,)}.items():
            with self.subTest(name), self.assertRaises(ContractViolation) as ctx:
                check_record_attachment(rec, [item(expectations=expectations)], rubric())
            self.assertEqual(ctx.exception.code, "not_applicable_unsupported_by_expectation")
        check_record_attachment(rec, [item(expectations=(EXP_UNKNOWN,))], rubric())


class ReportabilityTests(unittest.TestCase):
    """E13: structural eligibility is never genuine reporting authority."""

    def assess(self, rec, rub, items, r, reg):
        assessment = assess_reportability(rec, rub, items, r, reg)
        self.assertFalse(assessment.genuinely_reportable)
        self.assertEqual(assessment.authority_reasons, ("no_trusted_evaluation_record_service",))
        self.assertFalse(reportable(rec, rub, items, r, reg))
        return assessment

    def test_forged_trusted_metadata_is_never_genuinely_reportable(self):
        """Failure-first P1/P2: typed-in trusted values made records reportable on main."""
        assessment = self.assess(*forged())
        self.assertTrue(assessment.structurally_eligible)
        self.assertEqual(assessment.structural_reasons, ())

    def test_genuine_reportability_cannot_be_declared(self):
        for name, doc in {
            "genuinely reportable": {"record_id": "adjudication_example_1", "structurally_eligible": True,
                                     "genuinely_reportable": True},
            "no authority reason": {"record_id": "adjudication_example_1", "structurally_eligible": True,
                                    "authority_reasons": []},
            "eligible despite a reason": {"record_id": "adjudication_example_1", "structurally_eligible": True,
                                          "structural_reasons": ["rubric_not_approved"]},
        }.items():
            with self.subTest(name), self.assertRaises(ValidationError):
                ReportabilityAssessment.model_validate(doc)

    def test_incomplete_or_untrusted_conflict_information(self):
        rec, rub, items, r, _ = forged()
        other_config = G.run("evalrun_candidate_2", strategy_version=7).configuration
        for code, reg in {
            "conflict_register_missing": None,  # two distinct principal ids alone prove nothing
            "conflict_register_scope_mismatch": register(configuration=other_config),
            "conflict_register_scope_mismatch ": register(case="evalcase_g002"),
            "conflict_register_incomplete": register(coverage="partial"),
            "conflict_register_untrusted": register(basis="unverified_declaration"),
        }.items():
            with self.subTest(code):
                assessment = self.assess(rec, rub, items, r, reg)
                self.assertFalse(assessment.structurally_eligible)
                self.assertIn(code.strip(), assessment.structural_reasons)

    def test_each_conflict_reason_disqualifies_a_reviewer(self):
        rec, rub, items, r, _ = forged()
        for reason in ("configuration_authorship", "configuration_tuning", "reference_label_authorship"):
            for principal in (P1, P2):
                with self.subTest(reason=reason, principal=principal):
                    assessment = self.assess(rec, rub, items, r, register(conflicts=[(principal, reason)]))
                    self.assertIn("conflicted_reviewer", assessment.structural_reasons)
        unrelated = self.assess(rec, rub, items, r, register(conflicts=[("principal_example_other", "configuration_tuning")]))
        self.assertTrue(unrelated.structurally_eligible)

    def test_role_and_recorder_evidence_must_be_authenticated(self):
        _, rub, items, r, reg = forged()
        one_mock = record(basis=TRUSTED)
        one_mock["raw_labels"][0] = lab(P1, DIMS[0], basis=MOCK)
        cases = {
            "role_not_authenticated": record(basis=UNVERIFIED, recorded_by=who(REC, "recorder", TRUSTED)),
            "role_not_authenticated ": one_mock,
            "recorder_not_authenticated": {**record(basis=TRUSTED), "recorded_by": who(REC, "recorder", UNVERIFIED)},
        }
        for code, doc in cases.items():
            with self.subTest(code):
                assessment = self.assess(AdjudicationRecord.model_validate(doc), rub, items, r, reg)
                self.assertIn(code.strip(), assessment.structural_reasons)
        draft = self.assess(AdjudicationRecord.model_validate(record(basis=TRUSTED)), rubric(), items, r, reg)
        self.assertIn("rubric_not_approved", draft.structural_reasons)

    def test_record_for_another_run_is_rejected(self):
        rec, rub, _, _, reg = forged()
        with self.assertRaises(ContractViolation) as ctx:
            assess_reportability(rec, rub, [item()], run(rid="evalrun_candidate_2"), reg)
        self.assertEqual(ctx.exception.code, "record_run_mismatch")

    def test_disputed_or_unresolved_adjudication_is_not_structurally_eligible(self):
        """Review finding F1: only a finalized (adjudicated) record can be structurally eligible, even when
        every reviewer, recorder, rubric and register claim is set to its trusted-looking value."""
        _, rub, items, r, reg = forged()
        trusted_disagreement = [lab(P1, ES, 2, basis=TRUSTED), lab(P2, ES, 0, rationale="x", basis=TRUSTED)]
        for name, doc in {
            "disputed": record_with(ES, trusted_disagreement, result(ES, resolution="disputed"), status="disputed",
                                    basis=TRUSTED),
            "unresolved": record_with(ES, [lab(P1, ES, 2, basis=TRUSTED)], result(ES, resolution="unresolved"),
                                      status="unresolved", basis=TRUSTED),
        }.items():
            with self.subTest(name):
                assessment = self.assess(AdjudicationRecord.model_validate(doc), rub, items, r, reg)
                self.assertFalse(assessment.structurally_eligible)
                self.assertEqual(assessment.structural_reasons, ("adjudication_not_final",))


class DistributionTests(unittest.TestCase):
    """E9: diagnostic coverage reconciles every item; usefulness stays not_measured; nothing is imputed."""

    def items(self):
        return [
            item("recommendation_1", output="recommendation_example_1"),  # produced, expected, reviewed (eligible)
            item("recommendation_2", output="recommendation_example_2"),  # produced, expected, unreviewed
            item("recommendation_3", output="recommendation_example_3", presence="not_expected"),  # unexpected, reviewed
            item("recommendation_4", status="absent"),  # expected but missing
            item("explanation_1", status="absent", presence="not_expected"),  # correctly absent
            item("recommendation_5", status="generation_failed"),
            item("explanation_2", status="generation_failed", presence="not_expected"),
        ]

    def records(self):
        eligible = AdjudicationRecord.model_validate(record(basis=TRUSTED))
        labels = [lab(p, d) for d in DIMS if d not in (ES, FU) for p in (P1, P2)]
        labels += [lab(P1, ES, 2), lab(P2, ES, 0, rationale="Citation does not show the hours."), lab(P1, FU)]
        disputed = AdjudicationRecord.model_validate(record(
            labels=labels, status="disputed", slot="recommendation_3", output="recommendation_example_3",
            rid="adjudication_example_3",
            results=[result(UH), result(EC), result(ES, resolution="disputed"), result(FU, resolution="unresolved")]))
        return [eligible, disputed]

    def derive(self, records=None, items=None, run_=None, manifest=None, **kw):
        return derive_usefulness_distribution(USEFULNESS, self.items() if items is None else items,
                                              self.records() if records is None else records, rubric("approved"),
                                              run_ or run(), G.GOLDEN if manifest is None else manifest,
                                              registers=[register()], **kw)

    def test_only_finalized_records_count_as_structurally_eligible(self):
        """Review finding F1: with every claim trusted-looking, the adjudicated record is eligible-only and the
        disputed and unresolved records are ineligible; their dimension states stay diagnostic."""
        adjudicated = AdjudicationRecord.model_validate(record(basis=TRUSTED))
        disputed = AdjudicationRecord.model_validate(record_with(
            ES, [lab(P1, ES, 2, basis=TRUSTED), lab(P2, ES, 0, rationale="x", basis=TRUSTED)],
            result(ES, resolution="disputed"), status="disputed", basis=TRUSTED, slot="recommendation_2",
            output="recommendation_example_2", rid="adjudication_example_2"))
        unresolved = AdjudicationRecord.model_validate(record_with(
            ES, [lab(P1, ES, 2, basis=TRUSTED)], result(ES, resolution="unresolved"), status="unresolved",
            basis=TRUSTED, slot="recommendation_3", output="recommendation_example_3", rid="adjudication_example_3"))
        value = self.derive(records=[adjudicated, disputed, unresolved])
        cov = value.coverage
        self.assertEqual((cov.reviewed, cov.unreviewed, cov.genuinely_reportable, cov.structurally_eligible_only,
                          cov.structurally_ineligible), (3, 0, 0, 1, 2))
        es = next(s for s in cov.dimension_states if s.dimension == ES)
        self.assertEqual((es.scored, es.not_applicable, es.disputed, es.unresolved), (1, 0, 1, 1))
        self.assertEqual((value.status.value, value.dimensions), ("not_measured", ()))

    def test_derivation_reuses_pinned_item_checks(self):
        """Review finding F3: derivation applies the full structural item checks against a manifest the run
        pins. This is structural consistency only: it does not establish that the caller's item set is
        complete, that expectations were derived from the case, or that the run executed the outputs."""
        wrong_hash = ReviewItem.model_validate({**item().model_dump(mode="json"),
                                                "key": {**key(), "case_sha256": "sha256:" + "0" * 64}})
        wrong_version = ReviewItem.model_validate({**item().model_dump(mode="json"),
                                                   "key": {**key(), "case_version": 9}})
        held_out_only = run(manifests=(G.HELD_PIN,))
        cases = {
            "review_item_case_mismatch": {"items": [wrong_hash], "records": []},
            "review_item_case_mismatch (version)": {"items": [wrong_version], "records": []},
            "review_item_replicate_out_of_range": {"items": [item(replicate=2)], "records": []},
            "review_item_case_mismatch (case not in the supplied manifest)": {
                "manifest": H.manifest_of(H.split_doc(Split.HELD_OUT))},
            "review_manifest_not_pinned_by_run": {"run_": held_out_only},
        }
        for name, kw in cases.items():
            with self.subTest(name), self.assertRaises(ContractViolation) as ctx:
                self.derive(**kw)
            self.assertEqual(ctx.exception.code, name.split(" ")[0])
        self.assertEqual(self.derive(items=[item(replicate=2)], records=[], run_=run(replicates=2)).coverage.items_total, 1)

    def test_all_presence_categories_reconcile(self):
        cov = self.derive().coverage
        self.assertEqual(
            (cov.items_total, cov.produced_expected, cov.produced_unexpected, cov.missing, cov.correctly_absent,
             cov.generation_failed, cov.reviewed, cov.unreviewed),
            (7, 2, 1, 1, 1, 2, 2, 1))
        self.assertEqual((cov.genuinely_reportable, cov.structurally_eligible_only, cov.structurally_ineligible), (0, 1, 1))
        states = {s.dimension: (s.scored, s.not_applicable, s.disputed, s.unresolved) for s in cov.dimension_states}
        self.assertEqual(states, {ES: (1, 0, 1, 0), UH: (2, 0, 0, 0), EC: (2, 0, 0, 0), FU: (1, 0, 0, 1)})

    def test_usefulness_is_never_measured_without_a_trusted_service(self):
        value = self.derive(records=[AdjudicationRecord.model_validate(record(basis=TRUSTED))])
        self.assertEqual((value.status.value, value.dimensions), ("not_measured", ()))
        self.assertEqual((value.metric_id, value.metric_version, value.coverage.structurally_eligible_only),
                         ("reviewer_usefulness", 2, 1))

    def test_no_score_is_imputed_from_missing_or_unresolved_items(self):
        value = self.derive()
        cov = value.coverage
        # Missing, failed, correctly absent and unreviewed items appear only as counts: each dimension's
        # states cover exactly the two reviewed items, and no dimension block (no anchor) exists.
        self.assertTrue(all(s.scored + s.not_applicable + s.disputed + s.unresolved == cov.reviewed == 2
                            for s in cov.dimension_states))
        self.assertEqual(value.dimensions, ())
        none_reviewed = self.derive(records=[])
        self.assertEqual((none_reviewed.coverage.reviewed, none_reviewed.coverage.unreviewed), (0, 3))
        self.assertTrue(all(s.scored == 0 for s in none_reviewed.coverage.dimension_states))

    def test_orphan_duplicate_and_misattached_records_raise(self):
        eligible = AdjudicationRecord.model_validate(record(basis=TRUSTED))
        orphan = AdjudicationRecord.model_validate(record(slot="recommendation_9", output="recommendation_example_9",
                                                          rid="adjudication_example_9"))
        on_missing = AdjudicationRecord.model_validate(record(slot="recommendation_4", output="recommendation_example_4",
                                                              rid="adjudication_example_4"))
        twice = AdjudicationRecord.model_validate({**record(basis=TRUSTED), "id": "adjudication_example_2"})
        cases = {
            "record_item_missing": {"records": [orphan]},
            "record_attached_to_absent_output": {"records": [on_missing]},
            "duplicate_adjudication": {"records": [eligible, twice]},
            "duplicate_produced_output": {"items": self.items() + [item("recommendation_6", output="recommendation_example_1")]},
            "review_item_run_mismatch": {"items": [item(run_id="evalrun_candidate_2")], "records": []},
        }
        for code, kw in cases.items():
            with self.subTest(code), self.assertRaises(ContractViolation) as ctx:
                self.derive(**kw)
            self.assertEqual(ctx.exception.code, code)
        latency = MetricDefinitionSet.model_validate(H.load(H.DEFINITIONS_V2_FILE)["metric_definitions"]).get("latency_p50", 1)
        with self.assertRaises(ContractViolation) as ctx:
            derive_usefulness_distribution(latency, self.items(), [], rubric(), run(), G.GOLDEN)
        self.assertEqual(ctx.exception.code, "metric_kind_mismatch")


if __name__ == "__main__":
    unittest.main()
