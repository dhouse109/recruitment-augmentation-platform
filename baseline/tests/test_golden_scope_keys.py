"""DIAGNOSTIC ONLY: engine output on golden-scope fixture keys vs the PROPOSED, unreviewed labels.

The labels are AI-assisted, ``review_status: proposed`` and ``not_adjudicated``
(B3). Agreement here is NOT accuracy and NOT a measurement; it is a common-mode
consistency check (labels, engine and reference validator share authorship
lineage). A failure is a disagreement to record in the owner register (SD-15),
never a reason to edit the engine or a label to force agreement.

Only golden-split candidates (a, b, c) are loaded; nominal held-out records
and labels are never read.
"""

import unittest

from builders import StubAuthority, golden_request, load_golden_scope
from rap_baseline import Assessed, assess


def as_sets(outcomes):
    return {o["rule_id"]: (o["result"], o["reason_code"], frozenset(o.get("claim_ids") or ()),
                           frozenset(o.get("participation_ids") or ()), frozenset(o.get("requirement_ids") or ()))
            for o in outcomes}


class GoldenScopeDiagnosticTests(unittest.TestCase):
    def test_labels_are_proposed_hand_written_expectations(self):
        _, _, labels = load_golden_scope()
        self.assertEqual(sorted(lab["id"] for lab in labels),
                         ["eligibility_a_data", "eligibility_a_ops", "eligibility_a_web", "eligibility_b_data", "eligibility_c_job"])
        self.assertTrue(all(lab["evaluated_by"].startswith("fixture-expected-label/") for lab in labels))

    def test_engine_output_compared_with_proposed_labels(self):
        ctx, caps, labels = load_golden_scope()
        for label in labels:
            with self.subTest(label["id"]):
                out = assess(golden_request(label), ctx, StubAuthority(), caps)
                self.assertIsInstance(out, Assessed, str(out))
                produced = out.result.model_dump(mode="json")
                self.assertNotEqual(produced["id"], label["id"])
                self.assertNotEqual(produced["evaluated_by"], label["evaluated_by"])
                self.assertEqual(produced["decision"], label["decision"], "DISAGREEMENT: record in owner register (SD-15)")
                self.assertEqual(as_sets(produced["rule_outcomes"]), as_sets(label["rule_outcomes"]),
                                 "DISAGREEMENT: record in owner register (SD-15)")


if __name__ == "__main__":
    unittest.main()
