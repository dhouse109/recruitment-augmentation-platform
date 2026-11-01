"""TEST-ONLY failure-first mutation harness for the PR-S3b runner (acceptance B11).

Each mutation disables one runner invariant by an exact, single-occurrence text
replacement in a scratch copy of the repository, runs the evaluation suite
there, and classifies the result. The working tree is never modified. The
scratch copy EXCLUDES the nominal held-out case file (``*held-out*``): it is
never copied, opened or read, not even by mutants.

Classification follows the PR-S2 review-repair R1 rules (the classifier below
is a copy of ``baseline/tests/tools/mutations.py:classify``; the evaluation
suite does not import baseline test tooling): a mutation is CAUGHT only when
the suite ran to completion, ran exactly the number of tests the loader
discovers in the unmutated copy, reported genuine failure blocks consistent
with its summary, and every discriminating test in ``must_fail`` is among
them. A timeout or crash, a missing or ambiguous count, an incomplete run, an
import failure or a missing anchor is a HARNESS_ERROR, never a detection. Two
controls (a no-op edit and an import-breaking edit) must classify as
NOT_CAUGHT and HARNESS_ERROR before any mutation is judged.
Exit status: 0 all caught; 1 some not caught; 2 any harness error.

    python -I evaluation/tests/tools/mutations.py [--only R05,R17]
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
P = "evaluation/rap_evaluation/"
EX, AR, ID, SC, AD, FX, DF, RU = (P + n for n in ("execute.py", "artifacts.py", "identity.py", "scope.py",
                                                  "admission.py", "fixtures.py", "definitions.py", "run.py"))

MUTATIONS = [
    ("R01", "observation taken from the label instead of the generated result",
     [(EX, "decision=result.decision, rule_outcomes=rule_view(result))",
       "decision=step.expected.decision, rule_outcomes=step.expected.rule_outcomes)")],
     ["test_flipping_expectations_changes_only_match_statuses", "test_removed_participation_is_assessed_and_mismatched"]),
    ("R02", "validator not run on the generated result",
     [(EX, "    try:\n        check_eligibility_result(result, scope.eligibility)\n    except ContractViolation as exc:\n"
           "        return ExpectedResult.VIOLATION, exc.code\n",
       "    try:\n        pass\n    except ContractViolation as exc:\n        return ExpectedResult.VIOLATION, exc.code\n")],
     ["test_order_and_objects"]),
    ("R03", "label content read beyond the key",
     [(SC, "        return LabelKey(label_id=raw[\"id\"],", "        raw[\"decision\"]\n        return LabelKey(label_id=raw[\"id\"],")],
     ["test_label_records_are_read_only_through_their_key_fields"]),
    ("R04", "layer integrity skipped",
     [(FX, "        if actual != pin.sha256:\n", "        if False:\n")], ["test_tampered_layer"]),
    ("R05", "case pin check skipped",
     [(FX, "        check_manifest_cases(manifest, cases)\n", "        pass\n")],
     ["test_tampered_case_content", "test_tampered_label_expectation"]),
    ("R06", "a non-allowed fixture file is opened (stand-in for the held-out file, which is never touched)",
     [(FX, "    golden = read_allowed(fixture_dir, GOLDEN_FILE)\n",
       "    open(Path(fixture_dir) / \"evaluation-definitions-v2-v0.2.0-dev.json\", encoding=\"utf-8\").close()\n"
       "    golden = read_allowed(fixture_dir, GOLDEN_FILE)\n")],
     ["test_only_the_allowed_fixture_files_are_read"]),
    ("R07", "reference_validator basis on engine steps",
     [(EX, "ENGINE_BASIS = ObservationBasis.DETERMINISTIC_BASELINE_EXECUTION", "ENGINE_BASIS = ObservationBasis.REFERENCE_VALIDATOR")],
     ["test_step_bases_and_generated_ids"]),
    ("R08", "engine refusal mapped to a validator violation",
     [(EX, "        return ObservedRecord(error_type=f\"engine_{kind}\"), StepStatus.ERRORED, entry\n",
       "        return (ObservedRecord(result=ExpectedResult.VIOLATION, violation_code=outcome.code)\n"
       "                if kind == \"refused\" else ObservedRecord(error_type=f\"engine_{kind}\")), "
       "(StepStatus.MISMATCHED if kind == \"refused\" else StepStatus.ERRORED), entry\n")],
     ["test_superseded_gated_source_is_an_engine_refusal", "test_refusal_is_never_mapped_to_a_validator_violation"]),
    ("R09", "deterministic execution id",
     [(ID, "    return \"evalrun_\" + secrets.token_hex(16)", "    return \"evalrun_\" + \"0\" * 32")],
     ["test_execution_ids_are_random_and_well_formed"]),
    ("R10", "run status completed",
     [(RU, "        completed_at=None, status=\"partial\",", "        completed_at=started_at, status=\"completed\",")],
     ["test_runner_never_emits_completed"]),
    ("R11", "partial artifacts published on failure",
     [(AR, "        if tmp is not None:\n            shutil.rmtree(tmp, ignore_errors=True)\n",
       "        if tmp is not None:\n            os.rename(tmp, out)\n")],
     ["test_failure_during_validation_publishes_nothing", "test_missing_sidecar_entry"]),
    ("R12", "missing held-out (D/E) construction guard",
     [(SC, "    if owner is not None and owner in graph.held_out_candidates:\n", "    if False:\n")],
     ["test_injected_held_out_record_is_refused_before_construction"]),
    ("R13", "run_id not normalized in the output digest",
     [(ID, "        o[\"run_id\"] = NORMALIZED_RUN_ID\n", "")], ["test_two_runs_pass"]),
    ("R14", "engine result cached across invocations",
     [(EX, "    outcome = assess_fn(request, scope.eligibility, authority, scope.capabilities)\n",
       "    memo = _CACHE.get(key.assessment())\n"
       "    outcome = memo if memo is not None else assess_fn(request, scope.eligibility, authority, scope.capabilities)\n"
       "    _CACHE[key.assessment()] = outcome\n"),
      (EX, "WORKFLOW = ", "_CACHE = {}\nWORKFLOW = ")],
     ["test_engine_is_invoked_once_per_engine_step_without_caching"]),
    ("R15", "verify_bindings skipped at publication",
     [(AR, "    verify_bindings(observations, entries, admitted)\n    if docs[COVERAGE_FILE]",
       "    if docs[COVERAGE_FILE]")],
     ["test_substituted_id", "test_declared_fingerprint_is_not_trusted"]),
    ("R16", "result id taken from the sidecar without recomputation (X3)",
     [(AR, "    if result.id != result_id(fp, admitted.as_of):", "    if result.id != e.get(\"result_id\"):")],
     ["test_fabricated_id_with_consistent_sidecar"]),
    ("R17", "declared input fingerprint trusted (X3)",
     [(AR, "        fp = recompute_fingerprint(key, scope, principal, admitted.as_of)\n",
       "        fp = e.get(\"input_fingerprint\")\n")],
     ["test_forged_fingerprint_with_a_consistent_id_is_not_trusted"]),
    ("R18", "dirty tree admitted (A1)",
     [(AD, "    if rev.status != \"recorded\" or rev.dirty is not False:", "    if rev.status != \"recorded\":")],
     ["test_dirty_tree"]),
    ("R19", "approved definitions admitted (A4)",
     [(DF, "    if metrics.status != \"draft\" or policy.status != \"draft\":", "    if False:")],
     ["test_approved_metrics_status"]),
    ("R20", "check_policy_manifest skipped (A4)",
     [(DF, "        check_policy_manifest(policy, golden_manifest)\n", "        pass\n")],
     ["test_policy_manifest_check_failure"]),
    ("R21", "held-out identifier output scan skipped",
     [(AR, "    scan_held_out(texts, admitted.graph.held_out_identifiers)\n", "")],
     ["test_held_out_identifier_in_an_artifact_is_rejected"]),
    ("R22", "steps run after a prerequisite mismatch",
     [(EX, "            halted = True\n", "            halted = False\n")],
     ["test_prerequisite_mismatch_is_inconclusive_and_runs_no_engine"]),
    ("R23", "in-run consistency check skipped",
     [(RU, "        check_in_run_consistency(entries)\n", "")], ["test_in_run_inconsistency_is_a_runner_failure"]),
    ("R24", "key organization check removed (A7)",
     [(AD, "            if not (key.organization_id == cand.organization_id == opp.organization_id):",
       "            if False:")],
     ["test_key_organization_mismatch"]),
    ("R25", "selection check removed (A8)",
     [("evaluation/rap_evaluation/applicability.py", "    if tuple(c.id for c in selected) != SELECTION:", "    if False:")],
     ["test_selection_mismatch"]),
    ("R26", "comparison ignores rule outcomes",
     [(EX, "    return ((observed.result, observed.violation_code, observed.decision) == (exp.result, exp.violation_code, exp.decision)\n"
           "            and sorted(observed.rule_outcomes, key=key) == sorted(exp.rule_outcomes, key=key))",
       "    return (observed.result, observed.violation_code, observed.decision) == (exp.result, exp.violation_code, exp.decision)")],
     ["test_altered_rule_outcome_expectation_is_mismatched"]),
    ("R27", "errored step may carry result bytes (X8)",
     [(AR, "    if (e.get(\"outcome\") not in (\"refused\", \"errored\") or e.get(\"result_json\") is not None\n",
       "    if (e.get(\"outcome\") not in (\"refused\", \"errored\")\n")],
     ["test_errored_step_with_result_bytes"]),
    ("R28", "cross-scope construction guard removed (A6)",
     [(SC, "    if owner is not None and owner not in scope_candidates:\n", "    if False:\n")],
     ["test_injected_other_golden_candidate_record_is_refused"]),
    ("R29", "label id equality not rejected (X4)",
     [(AR, "    if result.id == step.eligibility_result_id or result.id in admitted.graph.label_ids:", "    if False:")],
     ["test_generated_id_equal_to_a_label_id_is_rejected"]),
]

FAIL_LINE = re.compile(r"^(FAIL|ERROR): (\w+) \(([\w.]+)\)")
RAN_LINE = re.compile(r"^Ran (\d+) tests? in [\d.]+s$", re.M)
SUMMARY_LINE = re.compile(r"^(OK|FAILED)(?: \(([^)]*)\))?$", re.M)
CAUGHT, NOT_CAUGHT, HARNESS_ERROR = "CAUGHT", "NOT_CAUGHT", "HARNESS_ERROR"


def classify(returncode: int | None, stderr: str, expected: int) -> dict:
    """Copy of the PR-S2 R1 classifier (``baseline/tests/tools/mutations.py``)."""
    out = {"status": "harness_error", "ran": None, "failures": 0, "errors": 0, "methods": set(), "reason": ""}
    if returncode is None:
        out["reason"] = "runner did not finish (timeout or crash)"
        return out
    ran = RAN_LINE.findall(stderr)
    summaries = SUMMARY_LINE.findall(stderr)
    if len(ran) != 1 or len(summaries) != 1:
        out["reason"] = "missing or ambiguous 'Ran N tests' line or final summary"
        return out
    out["ran"] = int(ran[0])
    verdict, detail = summaries[0]
    counts = dict(re.findall(r"(failures|errors|skipped|expected failures|unexpected successes)=(\d+)", detail or ""))
    hits = [m for m in (FAIL_LINE.match(line) for line in stderr.splitlines()) if m]
    out["failures"] = sum(1 for m in hits if m.group(1) == "FAIL")
    out["errors"] = sum(1 for m in hits if m.group(1) == "ERROR")
    out["methods"] = {m.group(2) for m in hits}
    if out["ran"] != expected:
        out["reason"] = f"ran {out['ran']} tests, expected {expected} (incomplete or altered suite)"
        return out
    if any("_FailedTest" in m.group(3) or "loader" in m.group(3) for m in hits):
        out["reason"] = "a test module failed to import (the mutation broke the code, not an invariant)"
        return out
    if (int(counts.get("failures", 0)), int(counts.get("errors", 0))) != (out["failures"], out["errors"]):
        out["reason"] = "summary counts do not match the reported failure blocks"
        return out
    if verdict == "OK":
        if returncode != 0 or hits:
            out["reason"] = "OK summary with a non-zero exit or failure blocks"
            return out
        out["status"] = "completed_ok"
        return out
    if returncode != 1 or not hits:
        out["reason"] = "FAILED summary without failure blocks or with an unexpected exit code"
        return out
    out["status"] = "completed_failed"
    return out


def _env(root: Path) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHASHSEED")}
    env["PYTHONPATH"] = os.pathsep.join([str(root / "contracts"), str(root / "baseline")])
    return env


def run_suite(root: Path, expected: int) -> dict:
    try:
        proc = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests"], cwd=root / "evaluation",
                              capture_output=True, text=True, env=_env(root), timeout=900)
    except subprocess.TimeoutExpired:
        return classify(None, "", expected)
    result = classify(proc.returncode, proc.stderr, expected)
    result["tail"] = proc.stderr[-800:]
    return result


def discovered_count(root: Path) -> int:
    code = ("import unittest\n"
            "def n(s):\n"
            "    return sum(n(t) if isinstance(t, unittest.TestSuite) else 1 for t in s)\n"
            "print(n(unittest.defaultTestLoader.discover('tests')))\n")
    proc = subprocess.run([sys.executable, "-c", code], cwd=root / "evaluation", capture_output=True, text=True,
                          env=_env(root), timeout=300, check=True)
    return int(proc.stdout.strip())


def apply(root: Path, edits) -> dict | None:
    originals: dict[str, str] = {}
    for path, old, new in edits:
        target = root / path
        originals.setdefault(path, target.read_text(encoding="utf-8"))
        text = target.read_text(encoding="utf-8")
        if text.count(old) != 1:
            restore(root, originals)
            return None
        target.write_text(text.replace(old, new), encoding="utf-8")
    return originals


def restore(root: Path, originals: dict) -> None:
    for path, text in originals.items():
        (root / path).write_text(text, encoding="utf-8")


def judge(result: dict, must_fail: list[str]) -> tuple[str, str]:
    if result["status"] == "harness_error":
        return HARNESS_ERROR, result["reason"]
    if result["status"] == "completed_ok":
        return NOT_CAUGHT, "suite passed"
    absent = [t for t in must_fail if t not in result["methods"]]
    if absent:
        return NOT_CAUGHT, "discriminating test(s) did not fail: " + ",".join(absent)
    return CAUGHT, ""


CONTROLS = [
    ("CTRL-noop", "no-op edit (comment only)", [(EX, "def compare(", "# control: no-op\ndef compare(")], NOT_CAUGHT),
    ("CTRL-import", "edit that breaks module import", [(EX, "def compare(", ")\ndef compare(")], HARNESS_ERROR),
]

IGNORE = shutil.ignore_patterns(".git", "__pycache__", ".venv*", "*held-out*", "out")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", default="")
    args = parser.parse_args()
    only = set(filter(None, args.only.split(",")))
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "repo"
        shutil.copytree(REPO, root, ignore=IGNORE)
        if list(root.rglob("*held-out*")):
            print("HARNESS_ERROR: the held-out case file must not be copied")
            return 2
        expected = discovered_count(root)
        base = run_suite(root, expected)
        print(f"baseline: discovered={expected} ran={base['ran']} status={base['status']} {base['reason']}")
        if base["status"] != "completed_ok":
            print(base.get("tail", ""))
            return 2
        harness_errors = not_caught = 0
        for cid, desc, edits, want in CONTROLS:
            originals = apply(root, edits)
            if originals is None:
                print(f"{cid} | {desc} | HARNESS_ERROR anchor not found exactly once")
                return 2
            result = run_suite(root, expected)
            restore(root, originals)
            status, why = judge(result, [])
            ok = status == want
            print(f"{cid} | {desc} | classified={status} expected={want} | {'OK' if ok else 'CONTROL FAILED'} {why}")
            if not ok:
                return 2
        for mid, desc, edits, must_fail in MUTATIONS:
            if only and mid not in only:
                continue
            originals = apply(root, edits)
            if originals is None:
                harness_errors += 1
                print(f"{mid} | {desc} | HARNESS_ERROR anchor not found exactly once")
                continue
            result = run_suite(root, expected)
            restore(root, originals)
            status, why = judge(result, must_fail)
            harness_errors += status == HARNESS_ERROR
            not_caught += status == NOT_CAUGHT
            print(f"{mid} | {desc} | failures={result['failures']} errors={result['errors']} "
                  f"methods={len(result['methods'])} ran={result['ran']}/{expected} | {status}{(' ' + why) if why else ''}")
        print(f"summary: mutations={len([m for m in MUTATIONS if not only or m[0] in only])} "
              f"harness_errors={harness_errors} not_caught={not_caught}")
        return 2 if harness_errors else (1 if not_caught else 0)


if __name__ == "__main__":
    raise SystemExit(main())
