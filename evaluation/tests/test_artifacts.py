"""B7: published artifacts -- a partial run, 26 observations, coverage, sidecar, identities, contract and schema
re-validation, and atomic publication."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest import mock

from helpers import LazyClassFixture, TempDirTest, admitted, config, products
from rap_contracts.evaluation import CaseObservation, EvaluationRun, StepStatus

from rap_evaluation import EXECUTED_BY, RunnerFailure, artifacts
from rap_evaluation.artifacts import FILES, load_dir, publish, validate_published
from rap_evaluation.run import run_evaluation

SCHEMAS = Path(__file__).resolve().parents[2] / "contracts" / "schemas"

try:
    import jsonschema
except ImportError:  # runtime-only environment
    jsonschema = None


class PublishedRunTests(LazyClassFixture):
    @classmethod
    def _fixture(cls):
        import shutil
        import tempfile
        cls._dir = Path(tempfile.mkdtemp(prefix="rap-eval-pub-"))
        cls.out = run_evaluation(config(cls._dir / "out" / "run"))
        cls.docs, cls.texts = load_dir(cls.out)
        cls.addClassCleanup(shutil.rmtree, cls._dir, True)

    def test_exactly_the_five_artifact_files(self):
        self.assertEqual(sorted(p.name for p in self.out.iterdir()), sorted(FILES))
        self.assertEqual([p.name for p in self.out.parent.iterdir()], ["run"])

    def test_run_is_partial_deterministic_baseline_regression(self):
        run = EvaluationRun.model_validate(self.docs["run.json"])
        self.assertEqual((run.status, run.completed_at, run.run_kind.value, run.purpose.value),
                         ("partial", None, "deterministic_baseline", "regression"))
        self.assertEqual(run.evidence_tier.value, "t3_offline_measured")
        self.assertEqual((run.source_authority, run.replicates, run.executed_by), ("fixture_mock", 1, EXECUTED_BY))
        self.assertEqual((run.latency.status.value, run.cost.status.value), ("not_measured", "not_applicable"))
        self.assertEqual({p.status for p in (run.prompt, run.model, run.judge, run.retrieval_index)}, {"not_applicable"})
        self.assertEqual(run.manifests, (admitted().golden.pin,))
        self.assertEqual(run.contract_version, "0.2.0-dev.foundations.6")
        self.assertRegex(run.id, r"^evalrun_[0-9a-f]{32}$")

    def test_twenty_six_observations_four_executed(self):
        obs = [CaseObservation.model_validate(o) for o in self.docs["observations.json"]]
        self.assertEqual(len(obs), 26)
        self.assertEqual([o.case_id for o in obs if o.execution_status == "executed"],
                         ["evalcase_g002", "evalcase_g003", "evalcase_g008", "evalcase_g025"])
        for o in obs:
            self.assertEqual(o.split.value, "golden")
            if o.execution_status == "not_run":
                self.assertEqual((o.steps, o.outcome.value), ((), "not_evaluated"))

    def test_v1_to_v4_hold_on_every_emitted_step(self):
        for o in self.docs["observations.json"]:
            for s in o["steps"]:
                bound = s["operation"] == "eligibility_support" and s["basis"] == "deterministic_baseline_execution"
                evaluated = s["status"] in ("matched", "mismatched")
                generated = (s.get("observed") or {}).get("eligibility_result_id")
                self.assertEqual(generated is not None, bound and evaluated, (o["case_id"], s["step_id"]))

    @unittest.skipIf(jsonschema is None, "jsonschema not installed (runtime-only environment)")
    def test_artifacts_validate_against_the_committed_json_schemas(self):
        run_schema = json.loads((SCHEMAS / "evaluation-run.schema.json").read_text())
        obs_schema = json.loads((SCHEMAS / "case-observation.schema.json").read_text())
        jsonschema.Draft202012Validator(run_schema).validate(self.docs["run.json"])
        validator = jsonschema.Draft202012Validator(obs_schema)
        for o in self.docs["observations.json"]:
            validator.validate(o)

    def test_coverage(self):
        c = self.docs["coverage.json"]
        self.assertEqual({k: c[k] for k in ("pinned_cases", "executed_cases", "not_run_cases", "executed_steps",
                                             "engine_steps", "validator_steps", "engine_invocations", "distinct_assessments")},
                         {"pinned_cases": 26, "executed_cases": 4, "not_run_cases": 22, "executed_steps": 6,
                          "engine_steps": 5, "validator_steps": 1, "engine_invocations": 5, "distinct_assessments": 3})
        self.assertEqual(c["f3_shared_scenario"], ["evalcase_g002", "evalcase_g008"])
        self.assertEqual(len(c["not_run"]), 22)
        self.assertTrue(all(n["class"] in "CDEFG" and n["reason"] for n in c["not_run"]))
        self.assertIn("not reviewed correctness", " ".join(c["statements"]))

    def test_coverage_contains_no_aggregate_agreement_rate(self):
        text = json.dumps(self.docs["coverage.json"]).lower()
        for word in ("accuracy", "rate", "precision", "recall", "matched"):
            self.assertNotIn(f'"{word}', text)

    def test_sidecar_entries_bind_engine_steps(self):
        side = self.docs["sidecar.json"]
        self.assertEqual(side["visibility"], "internal_only")
        entries = side["entries"]
        self.assertEqual([(e["case_id"], e["step_id"]) for e in entries],
                         [("evalcase_g002", "s1"), ("evalcase_g003", "s1"), ("evalcase_g008", "s1"),
                          ("evalcase_g025", "s2"), ("evalcase_g025", "s3")])
        for e in entries:
            self.assertEqual(e["evidence"]["tier"], "T3")
            self.assertEqual(e["outcome"], "assessed")
            self.assertEqual(json.loads(e["result_json"])["id"], e["result_id"])
            self.assertFalse(e["citations_evaluated"])
            self.assertEqual(set(e["wall_clock"]), {"started_at", "ended_at"})
            self.assertTrue(e["findings"]["findings_id"] and e["explanation"]["explanation_id"])

    def test_identity_record(self):
        ident = self.docs["identity.json"]
        run = self.docs["run.json"]
        self.assertEqual(ident["execution_id"], run["id"])
        self.assertEqual(ident["configuration_fingerprint"], run["configuration"]["fingerprint"])
        self.assertEqual(ident["specification"]["as_of"], "2026-11-01T00:00:00Z")
        self.assertEqual(ident["specification"]["manifest"]["root"],
                         "sha256:5baf87b79e41dd22a97b23977874683eab9099ad83b1148ef2fd8a883b70c769")

    def test_published_directory_re_validates_from_disk(self):
        docs, texts = load_dir(self.out)
        validate_published(docs, texts, admitted())


class AtomicPublicationTests(TempDirTest):
    def test_failure_during_validation_publishes_nothing(self):
        out = self.tmp / "deep" / "er" / "run"
        with mock.patch.object(artifacts, "validate_published", side_effect=RuntimeError("synthetic")), \
                self.assertRaises(RunnerFailure) as cm:
            publish(products(), out)
        self.assertEqual(cm.exception.code, "publication_failed")
        self.assertNothingPublished(out)
        self.assertFalse((self.tmp / "deep").exists(), "parents created for publication are removed on failure")

    def test_existing_output_is_never_overwritten(self):
        out = self.tmp / "run"
        out.mkdir()
        with self.assertRaises(RunnerFailure):
            publish(products(), out)
        self.assertEqual(list(out.iterdir()), [])

    def test_unexpected_extra_file_fails_validation(self):
        out = self.tmp / "run"
        publish(products(), out)
        (out / "extra.json").write_text("{}")
        with self.assertRaises(RunnerFailure):
            load_dir(out)

    def test_artifacts_are_not_committed(self):
        ignore = (Path(__file__).resolve().parents[2] / ".gitignore").read_text()
        self.assertIn("evaluation/out/", ignore.splitlines())


class StatusTests(unittest.TestCase):
    def test_runner_never_emits_completed(self):
        p = products()
        self.assertEqual(p.run.status, "partial")
        self.assertIsNone(p.run.completed_at)
        self.assertTrue(all(s.status is not StepStatus.NOT_EVALUATED for o in p.observations if o.execution_status == "executed"
                            for s in o.steps))


if __name__ == "__main__":
    unittest.main()
