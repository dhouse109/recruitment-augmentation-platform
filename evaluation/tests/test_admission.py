"""Admission A1-A8: all-or-nothing; every abort exits 3 and writes nothing (plan sections 4.1 and 8)."""

from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
from pathlib import Path
from unittest import mock

from helpers import AS_OF, CLEAN, LAYER_EVIDENCE, TempDirTest, case_doc, config, copy_allowed, layer_record, tampered
from rap_contracts.evaluation import CodeRevision, OptionalPin

from rap_evaluation import EXIT_ADMISSION, AdmissionAbort, __main__ as cli, admission
from rap_evaluation import fixtures as fx
from rap_evaluation.run import run_evaluation


class AdmissionTestCase(TempDirTest):
    def assertAborts(self, check: str, code: str | None = None, *, fixture_dir: Path | None = None, **cfg) -> AdmissionAbort:
        out = cfg.pop("out", self.tmp / "out" / "run")
        existing = cfg.pop("_existing", False)
        engine = mock.MagicMock(name="assess")
        with self.assertRaises(AdmissionAbort) as cm:
            run_evaluation(config(out, **cfg), fixture_dir=fixture_dir or fx.FIXTURE_DIR, assess_fn=engine)
        self.assertEqual(cm.exception.check, check, str(cm.exception))
        if code is not None:
            self.assertEqual(cm.exception.code, code, str(cm.exception))
        engine.assert_not_called()
        if not existing:
            self.assertNothingPublished(out)
            self.assertFalse((self.tmp / "out").exists(), "the output parent must not be created on abort")
        return cm.exception


class EnvironmentTests(AdmissionTestCase):
    """A1."""

    def test_dirty_tree(self):
        self.assertAborts("A1", "code_revision_not_clean", code_revision=CodeRevision(status="recorded", commit="b" * 40, dirty=True))

    def test_unavailable_revision(self):
        self.assertAborts("A1", "code_revision_not_clean", code_revision=CodeRevision(status="unavailable"))

    def test_contract_version_mismatch(self):
        with mock.patch.object(admission, "CONTRACT_VERSION", "0.2.0-dev.foundations.5"):
            self.assertAborts("A1", "contract_version_mismatch")

    def test_purpose_other_than_regression(self):
        for purpose in ("tuning", "model_selection", "promotion_assessment"):
            with self.subTest(purpose=purpose):
                self.assertAborts("A1", "purpose_not_regression", purpose=purpose)

    def test_model_prompt_judge_or_index_pin(self):
        pin = OptionalPin(status="pinned", value="model-x/1")
        for field in ("model", "prompt", "judge", "retrieval_index"):
            with self.subTest(field=field):
                self.assertAborts("A1", "model_pin_present", **{field: pin})

    def test_replicates_greater_than_one(self):
        self.assertAborts("A1", "replicates_not_one", replicates=2)

    def test_naive_as_of(self):
        self.assertAborts("A1", "as_of_not_aware", as_of=datetime(2026, 11, 1))

    def test_existing_output_path(self):
        out = self.tmp / "existing"
        out.mkdir()
        (out / "keep.txt").write_text("x")
        self.assertAborts("A1", "output_exists", out=out, _existing=True)
        self.assertEqual(sorted(p.name for p in out.iterdir()), ["keep.txt"])


class LoadingAndIntegrityTests(AdmissionTestCase):
    """A2 and A3, on temporary copies of the five allowed files (no integrity bypass)."""

    def setUp(self):
        super().setUp()
        self.fixtures = copy_allowed(self.tmp / "fixtures")

    def edit(self, name: str, fn) -> None:
        path = self.fixtures / name
        doc = json.loads(path.read_text(encoding="utf-8"))
        fn(doc)
        path.write_text(json.dumps(doc), encoding="utf-8")

    def test_json_parse_error(self):
        (self.fixtures / fx.GOLDEN_FILE).write_text("{not json", encoding="utf-8")
        self.assertAborts("A2", "json_parse_error", fixture_dir=self.fixtures)

    def test_missing_allowed_file(self):
        (self.fixtures / fx.DEFINITIONS_FILE).unlink()
        self.assertAborts("A2", "fixture_missing", fixture_dir=self.fixtures)

    def test_disallowed_name_is_refused_before_open(self):
        with mock.patch("builtins.open") as spy, self.assertRaises(AdmissionAbort) as cm:
            fx.read_allowed(self.fixtures, "evaluation-definitions-v2-v0.2.0-dev.json")
        spy.assert_not_called()
        self.assertEqual((cm.exception.check, cm.exception.code), ("A2", "path_not_allowed"))

    def test_tampered_layer(self):
        self.edit(fx.LAYER_FILES[1], lambda d: d["claims"][0].update(id=d["claims"][0]["id"] + "x"))
        self.assertAborts("A3", "layer_digest_mismatch", fixture_dir=self.fixtures)

    def test_tampered_case_content(self):
        self.edit(fx.GOLDEN_FILE, lambda d: case_doc(d, "evalcase_g003").update(title="tampered title"))
        self.assertAborts("A3", "manifest_case_modified", fixture_dir=self.fixtures)

    def test_tampered_label_expectation(self):
        def flip(d):
            case_doc(d, "evalcase_g003")["steps"][0]["expected"]["decision"] = "eligible"
        self.edit(fx.GOLDEN_FILE, flip)
        self.assertAborts("A3", fixture_dir=self.fixtures)

    def test_tampered_case_records(self):
        self.edit(fx.GOLDEN_FILE, lambda d: d["case_records"]["claims"][0].update(id="claim_a_tampered"))
        self.assertAborts("A3", "case_records_digest_mismatch", fixture_dir=self.fixtures)

    def test_wrong_case_set(self):
        self.edit(fx.GOLDEN_FILE, lambda d: d["cases"].pop())
        self.assertAborts("A3", "manifest_case_set_mismatch", fixture_dir=self.fixtures)

    def test_held_out_manifest_or_split_supplied(self):
        def to_held_out(d):
            d["manifest"]["split"] = "held_out"
            d["manifest"]["held_out_integrity"] = "nominal_exposed"
        self.edit(fx.GOLDEN_FILE, to_held_out)
        self.assertAborts("A3", fixture_dir=self.fixtures)

    def test_held_out_split_case_supplied(self):
        self.edit(fx.GOLDEN_FILE, lambda d: case_doc(d, "evalcase_g002").update(split="held_out"))
        self.assertAborts("A3", fixture_dir=self.fixtures)


class OwnershipScopeKeyApplicabilityTests(AdmissionTestCase):
    """A5-A8 with in-memory synthetic copies (A3 explicitly bypassed by ``tampered``)."""

    def test_unresolvable_owner(self):
        with tampered(layers=lambda L: layer_record(L, "claims", "claim_b_python").pop("candidate_id")):
            self.assertAborts("A5", "owner_unresolvable")

    def test_unknown_owner(self):
        with tampered(layers=lambda L: layer_record(L, "claims", "claim_b_python").update(candidate_id="candidate_demo_z")):
            self.assertAborts("A5", "owner_unknown")

    def test_include_record_owned_out_of_scope(self):
        # claim_a_web_content_inferred (golden case record) is owned by candidate A; g002 scopes candidate B.
        with tampered(golden=lambda g: case_doc(g, "evalcase_g002")["scope"].update(include_records=["claim_a_web_content_inferred"])):
            self.assertAborts("A5", "include_record_out_of_scope")

    def test_include_record_unresolvable(self):
        with tampered(golden=lambda g: case_doc(g, "evalcase_g003")["scope"].update(include_records=["claim_nowhere"])):
            self.assertAborts("A5", "include_record_unresolvable")

    def test_label_missing(self):
        with tampered(golden=lambda g: case_doc(g, "evalcase_g002")["steps"][0].update(eligibility_result_id="eligibility_b_missing")):
            self.assertAborts("A7", "label_id_missing")

    def test_label_duplicate(self):
        def dup(L):
            L[LAYER_EVIDENCE]["eligibility_results"].append(dict(layer_record(L, "eligibility_results", "eligibility_b_data")))
        with tampered(layers=dup):
            self.assertAborts("A7", "label_id_duplicate")

    def test_label_out_of_scope(self):
        with tampered(golden=lambda g: case_doc(g, "evalcase_g002")["steps"][0].update(eligibility_result_id="eligibility_a_data")):
            self.assertAborts("A7", "label_out_of_scope")

    def test_policy_pin_mismatch(self):
        with tampered(layers=lambda L: layer_record(L, "eligibility_results", "eligibility_b_data")["policy"].update(version=2)):
            self.assertAborts("A7", "key_policy_pin_mismatch")

    def test_key_organization_mismatch(self):
        with tampered(layers=lambda L: layer_record(L, "eligibility_results", "eligibility_b_data").update(organization_id="org_demo_002")):
            self.assertAborts("A7", "key_organization_mismatch")

    def test_key_opportunity_unknown(self):
        with tampered(layers=lambda L: layer_record(L, "eligibility_results", "eligibility_a_web").update(opportunity_id="opportunity_demo_none")):
            self.assertAborts("A7", "key_opportunity_unknown")

    def test_multiple_principals(self):
        def two(g):
            case_doc(g, "evalcase_g003")["initial_state"]["authority"]["principals"].append("principal_demo_coordinator_two")
        with tampered(golden=two):
            self.assertAborts("A7", "principal_count")

    def test_classification_table_mismatch(self):
        with tampered(golden=lambda g: g["cases"].pop(0)):
            self.assertAborts("A8", "classification_mismatch")

    def test_selection_mismatch(self):
        from rap_evaluation import applicability
        with mock.patch.dict(applicability.CLASS_TABLE, {"evalcase_g001": "A"}):
            self.assertAborts("A8", "selection_mismatch")

    def test_selected_case_shape(self):
        def extra(g):
            steps = case_doc(g, "evalcase_g003")["steps"]
            steps.append(dict(steps[0], step_id="s2"))
        with tampered(golden=extra):
            self.assertAborts("A8", "selected_case_shape")

    def test_selected_case_with_safety_expectation(self):
        def safety(g):
            case_doc(g, "evalcase_g002")["steps"][0]["safety"] = [
                {"category": "hard_eligibility_violation", "exposure_point": "recommendation_output",
                 "disposition": "attempt_blocked"}]
        with tampered(golden=safety):
            self.assertAborts("A8", "selected_case_has_safety_expectations")


class AdmissionIsAllOrNothingTests(AdmissionTestCase):
    def test_late_abort_after_three_cases_are_scoped_calls_no_engine(self):
        # g025's label key is broken: g002-g008 are already scoped when A7 aborts.
        with tampered(layers=lambda L: layer_record(L, "eligibility_results", "eligibility_a_web").update(organization_id="org_demo_002")):
            self.assertAborts("A7")

    def test_successful_admission_opens_only_the_allowed_files(self):
        adm = admission.admit(config(self.tmp / "x" / "run"))
        self.assertEqual(adm.opened, fx.LAYER_FILES + (fx.GOLDEN_FILE, fx.DEFINITIONS_FILE))
        self.assertEqual(adm.as_of, AS_OF)
        self.assertEqual([c.id for c in adm.selected], ["evalcase_g002", "evalcase_g003", "evalcase_g008", "evalcase_g025"])
        self.assertEqual(len(adm.keys), 5)
        self.assertFalse((self.tmp / "x").exists())


class CliExitCodeTests(TempDirTest):
    def run_cli(self, argv):
        err, out = io.StringIO(), io.StringIO()
        with redirect_stderr(err), redirect_stdout(out):
            code = cli.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_admission_abort_exits_3_with_structured_diagnostic(self):
        out = self.tmp / "cli" / "run"
        with mock.patch.object(cli, "read_code_revision", return_value=CodeRevision(status="recorded", commit="c" * 40, dirty=True)):
            code, stdout, stderr = self.run_cli(["run", "--as-of", "2026-11-01T00:00:00Z", "--out", str(out)])
        self.assertEqual(code, EXIT_ADMISSION)
        diag = json.loads(stderr.strip().splitlines()[-1])
        self.assertEqual((diag["phase"], diag["check"], diag["code"]), ("admission", "A1", "code_revision_not_clean"))
        self.assertEqual(stdout, "")
        self.assertFalse((self.tmp / "cli").exists())

    def test_unparseable_and_naive_as_of_exit_3(self):
        for value in ("not-a-time", "2026-11-01T00:00:00"):
            with self.subTest(value=value), mock.patch.object(cli, "read_code_revision", return_value=CLEAN):
                code, _, stderr = self.run_cli(["run", "--as-of", value, "--out", str(self.tmp / "n" / "run")])
                self.assertEqual(code, EXIT_ADMISSION)
                self.assertIn('"A1"', stderr)
                self.assertFalse((self.tmp / "n").exists())

    def test_cli_run_publishes_with_injected_clean_revision(self):
        out = self.tmp / "cli-ok" / "run"
        with mock.patch.object(cli, "read_code_revision", return_value=CLEAN):
            code, stdout, _ = self.run_cli(["run", "--as-of", "2026-11-01T00:00:00Z", "--out", str(out)])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout)["status"], "partial")
        self.assertTrue((out / "run.json").exists())


if __name__ == "__main__":
    unittest.main()
