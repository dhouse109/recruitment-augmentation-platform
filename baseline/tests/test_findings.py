"""Findings producer (PR-S2, P12): accounting identity, ordering, artifact binding and failure handling.

These are producer-side checks written from the test's own view of the inputs; the
independent verifier (L1) is exercised in ``test_findings_check.py``.
"""

import json
import unittest
from unittest import mock

from builders import DATA, StubAuthority, run
from g12_cases import ASSESSED, CASES
from rap_baseline import Errored, Stage, assess, findings, rules
from rap_baseline.identity import normalize_ref


def assessed(name):
    w, cand, kw = CASES[name]()
    out, _ = run(w, cand, DATA, **kw)
    ctx, _ = w.build()
    return out, ctx


class AccountingTests(unittest.TestCase):
    """I3-I5 and I10 from the test's own view of the selected inputs."""

    def test_every_selected_input_and_evidence_record_is_accounted_for(self):
        for name in ASSESSED:
            with self.subTest(name):
                out, ctx = assessed(name)
                content = out.findings.content
                inputs = {c.input_id for r in content.rules for s in r.subjects for c in s.contributions}
                evidence = {a.evidence_id for r in content.rules for s in r.subjects for c in s.contributions
                            for a in c.evidence}
                required_codes = {r.requirement.skill_code for r in ctx.requirements
                                  if r.opportunity_id == DATA and r.requirement.kind == "mandatory_qualification"}
                selected_claims = {c.id for c in ctx.claims if c.candidate_id == out.result.candidate_id and (
                    c.claim_type.value == "availability" or c.subject_code in required_codes)}
                selected_parts = {p.id for p in ctx.participations if p.candidate_id == out.result.candidate_id}
                self.assertEqual(inputs, selected_claims | selected_parts)
                expected_evidence = {e for c in ctx.claims if c.id in selected_claims for e in c.all_evidence_ids()}
                expected_evidence |= {e for p in ctx.participations if p.id in selected_parts for e in p.evidence_ids}
                self.assertEqual(evidence, expected_evidence)

    def test_unselected_records_are_not_contributions(self):
        """D4 (owner qualification): unselected records (here a work preference) never become contributions."""
        out, _ = assessed("C01")
        inputs = {c.input_id for r in out.findings.content.rules for s in r.subjects for c in s.contributions}
        self.assertNotIn("claim_s1_ana_remote", inputs)

    def test_selected_evidence_from_another_application_is_attributed(self):
        """D4 qualification: selected evidence may originate from an application record; it is attributed."""
        out, _ = assessed("C02")
        sources = {a.source_ref.entity.entity_type for r in out.findings.content.rules for s in r.subjects
                   for c in s.contributions for a in c.evidence}
        self.assertIn("application", sources)

    def test_references_equal_the_gated_set(self):  # I10
        for name in ASSESSED:
            with self.subTest(name):
                out, _ = assessed(name)
                c = out.findings.content
                refs = {c.opportunity_ref, c.policy_ref}
                for r in c.rules:
                    for s in r.subjects:
                        if s.requirement:
                            refs.add(s.requirement.source_ref)
                        refs |= {a.source_ref for con in s.contributions for a in con.evidence}
                self.assertEqual(refs, {normalize_ref(x) for x in out.provenance.gated_refs})


class OrderingAndBindingTests(unittest.TestCase):
    def test_canonical_ordering(self):
        for name in ASSESSED:
            with self.subTest(name):
                out, _ = assessed(name)
                for r in out.findings.content.rules:
                    reqs = [s.requirement.requirement_id for s in r.subjects if s.requirement]
                    self.assertEqual(reqs, sorted(reqs))
                    for s in r.subjects:
                        ids = [c.input_id for c in s.contributions]
                        self.assertEqual(ids, sorted(ids))
                        for con in s.contributions:
                            keys = [(-1 if a.alternative_index is None else a.alternative_index, a.evidence_id)
                                    for a in con.evidence]
                            self.assertEqual(keys, sorted(keys))

    def test_artifact_binds_content_to_the_assessment(self):
        out, _ = assessed("C02")
        fa = out.findings
        self.assertEqual((fa.result_id, fa.input_fingerprint, fa.output_digest, fa.as_of),
                         (out.result.id, out.provenance.input_fingerprint, out.provenance.output_digest,
                          out.result.evaluated_at))
        self.assertEqual(fa.content_digest, findings.content_digest(fa.content, "findings/1"))
        self.assertEqual(fa.findings_id, findings.findings_id(out.result.id, fa.content_digest))
        self.assertRegex(fa.findings_id, r"^findings_[0-9a-f]{40}$")
        self.assertEqual((fa.produced_by, fa.findings_policy), ("rap-baseline.findings/0.1.0", "findings/1"))
        json.dumps(findings.artifact_canonical(fa))  # JSON-ready

    def test_construction_failure_is_errored(self):
        w, cand, _ = CASES["C01"]()
        ctx, caps = w.build()
        with mock.patch.object(rules, "build_findings", side_effect=rules.RuleEvaluationError("synthetic")):
            out = assess(w.request(cand, DATA), ctx, StubAuthority(), caps)
        self.assertIsInstance(out, Errored)
        self.assertEqual((out.stage, out.code), (Stage.FINDINGS, "findings_construction_failed"))
        with mock.patch.object(rules, "build_findings", side_effect=KeyError("x")):
            out = assess(w.request(cand, DATA), ctx, StubAuthority(), caps)
        self.assertEqual((out.stage, out.code), (Stage.FINDINGS, "unexpected_exception"))

    def test_misaligned_outcomes_are_rejected_by_the_producer(self):
        out, _ = assessed("C01")
        with self.assertRaises(rules.RuleEvaluationError):
            rules.build_findings(_decision_inputs("C01"), out.result.rule_outcomes[:-1])


def _decision_inputs(name):
    from rap_baseline import engine
    from rap_baseline.identity import build_decision_inputs
    from rap_baseline.inputs import project, resolve_targets
    w, cand, _ = CASES[name]()
    ctx, _ = w.build()
    req = w.request(cand, DATA)
    targets = resolve_targets(req, ctx)
    return build_decision_inputs(project(ctx, targets), req.organization_id, cand, DATA, engine.ENGINE)


if __name__ == "__main__":
    unittest.main()
