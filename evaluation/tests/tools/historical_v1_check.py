"""E11b (F3, RAP-F3-PLAN-2026-11-04 rev. 1.1): reproducible historical-checkout verification. TEST-ONLY tool.

Establishes, with GENUINE historical runner output rather than a simulated one:

1. ``git archive <commit>`` of the pre-F3 tree (default ``653642e9``: runner 0.1.0, golden v1) is extracted into a
   temporary directory, EXCLUDING the nominal held-out case fixture (``*/evaluation-nominal-held-out-*``), which is
   therefore never materialized, copied or opened. The contract schema ``held-out-gate-attestation`` is kept.
2. The historical runner produces two runs (its own Python API; a recorded clean ``CodeRevision`` naming the
   commit is injected, as the runner tests do).
3. The historical runner re-verifies its own two runs: verdict PASS (historical runs remain reproducible at
   their recorded commit).
4. The CURRENT runner (golden v2) refuses to re-verify those historical runs, both paired with each other and
   paired with a fresh current run: exit 4 with a binding failure (``binding_p1``) and NO verdict. Runs against
   golden v1 and golden v2 are not comparable, by construction.

Every runner invocation is a separate process (no module mixing). Nothing is written inside the repository.

Exit status: 0 PASS; 1 FAIL (an expectation was not met); 2 harness error; 3 SKIPPED (the commit is not in local
history, e.g. a shallow clone). SKIPPED is reported with its reason and is not a pass.

    python -I evaluation/tests/tools/historical_v1_check.py [--commit SHA]
"""

from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
DEFAULT_COMMIT = "653642e9d6e87b0a773cf5d577ba8bb43754f1fe"
HELD_OUT_PATHSPEC = ":(exclude)*/evaluation-nominal-held-out-*"
AS_OF = "2026-11-01T00:00:00+00:00"

PRODUCE = """
import json, sys
from datetime import datetime
from pathlib import Path
from rap_contracts.evaluation import CodeRevision
from rap_evaluation import EXECUTED_BY
from rap_evaluation.admission import RunConfig
from rap_evaluation.run import run_evaluation
commit, as_of, outs = sys.argv[1], datetime.fromisoformat(sys.argv[2]), sys.argv[3:]
rev = CodeRevision(status="recorded", commit=commit, dirty=False)
for out in outs:
    run_evaluation(RunConfig(as_of=as_of, out=Path(out), code_revision=rev))
print(json.dumps({"executed_by": EXECUTED_BY}))
"""

VERIFY = """
import json, sys
from rap_evaluation.identity import verify_repeat
print(json.dumps({"verdict": verify_repeat(sys.argv[1], sys.argv[2])["verdict"]}))
"""


def _env(root: Path) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHASHSEED")}
    env["PYTHONPATH"] = os.pathsep.join(str(root / p) for p in ("contracts", "baseline", "evaluation"))
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def _py(root: Path, code: str, *args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-B", "-c", code, *args], cwd=cwd, env=_env(root),
                          capture_output=True, text=True, timeout=900)


def _cli(root: Path, *args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-B", "-m", "rap_evaluation", *args], cwd=cwd, env=_env(root),
                          capture_output=True, text=True, timeout=900)


def extract(commit: str, dest: Path) -> None:
    archive = subprocess.run(["git", "-C", str(REPO), "archive", "--format=tar", commit, "--", ".", HELD_OUT_PATHSPEC],
                             capture_output=True, timeout=300)
    if archive.returncode != 0:
        raise RuntimeError("git archive failed: " + archive.stderr.decode(errors="replace").strip())
    with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as tar:
        tar.extractall(dest, filter="data")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--commit", default=DEFAULT_COMMIT)
    args = parser.parse_args()
    report: dict = {"commit": args.commit, "checks": {}}

    known = subprocess.run(["git", "-C", str(REPO), "cat-file", "-e", f"{args.commit}^{{commit}}"], capture_output=True)
    if known.returncode != 0:
        report["verdict"] = "SKIPPED"
        report["reason"] = f"commit {args.commit} is not in local git history (shallow or partial clone?)"
        print(json.dumps(report, indent=2))
        return 3

    tmp = Path(tempfile.mkdtemp(prefix="rap-e11b-"))
    try:
        hist, runs = tmp / "historical", tmp / "runs"
        hist.mkdir()
        runs.mkdir()
        extract(args.commit, hist)
        fixtures = hist / "contracts" / "fixtures"
        report["checks"]["held_out_case_fixture_absent"] = not list(fixtures.glob("*held-out*"))
        report["checks"]["held_out_gate_attestation_schema_present"] = (
            hist / "contracts" / "schemas" / "held-out-gate-attestation.schema.json").is_file()

        produced = _py(hist, PRODUCE, args.commit, AS_OF, str(runs / "v1a"), str(runs / "v1b"), cwd=tmp)
        if produced.returncode != 0:
            report["error"] = "historical runner failed: " + produced.stderr.strip()[-2000:]
            print(json.dumps(report, indent=2))
            return 2
        report["historical_runner"] = json.loads(produced.stdout.strip().splitlines()[-1])["executed_by"]

        own = _py(hist, VERIFY, str(runs / "v1a"), str(runs / "v1b"), cwd=tmp)
        report["historical_verify_repeat"] = json.loads(own.stdout.strip().splitlines()[-1])["verdict"] if own.returncode == 0 else f"error: {own.stderr.strip()[-500:]}"
        report["checks"]["historical_runs_reproducible_at_their_commit"] = report["historical_verify_repeat"] == "PASS"

        head = subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        current = _py(REPO, PRODUCE, head, AS_OF, str(runs / "v2"), cwd=tmp)
        if current.returncode != 0:
            report["error"] = "current runner failed: " + current.stderr.strip()[-2000:]
            print(json.dumps(report, indent=2))
            return 2
        report["current_runner"] = json.loads(current.stdout.strip().splitlines()[-1])["executed_by"]

        for label, pair in (("v1a_v1b", ("v1a", "v1b")), ("v1a_v2", ("v1a", "v2"))):
            proc = _cli(REPO, "verify-repeat", str(runs / pair[0]), str(runs / pair[1]), cwd=tmp)
            diag = proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else ""
            try:
                code = json.loads(diag).get("code")
            except ValueError:
                code = None
            report[f"current_verify_repeat_{label}"] = {"exit": proc.returncode, "code": code,
                                                        "verdict_printed": "verdict" in proc.stdout}
            report["checks"][f"current_runner_rejects_{label}"] = (
                proc.returncode == 4 and code == "binding_p1" and "verdict" not in proc.stdout)

        report["checks"]["runner_versions_differ"] = report["historical_runner"] != report["current_runner"]
        ok = all(report["checks"].values())
        report["verdict"] = "PASS" if ok else "FAIL"
        print(json.dumps(report, indent=2))
        return 0 if ok else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
