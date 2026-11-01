"""Command line: ``python -m rap_evaluation run --as-of T [--out DIR]`` and ``verify-repeat A B``.

Exit codes: 0 success (or PASS); 1 a verify-repeat verdict other than PASS;
2 usage; 3 admission abort (nothing written); 4 runner or binding failure
(nothing published). Diagnostics are structured JSON on stderr.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from rap_contracts.evaluation import CodeRevision

from . import EXIT_ADMISSION, EXIT_OK, EXIT_RUNNER, EXIT_USAGE, EXIT_VERDICT, AdmissionAbort, RunnerFailure
from .admission import RunConfig
from .fixtures import REPO
from .identity import PASS, new_execution_id, verify_repeat
from .run import run_evaluation

DEFAULT_OUT_DIR = REPO / "evaluation" / "out"  # git-ignored; artifacts are never committed (E8)


def read_code_revision(repo: Path = REPO) -> CodeRevision:
    """Only the CLI reads git. A missing git or repository makes the revision unavailable (an A1 abort)."""
    try:
        commit = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True,
                                check=True, timeout=30).stdout.strip()
        status = subprocess.run(["git", "-C", str(repo), "status", "--porcelain"], capture_output=True, text=True,
                                check=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return CodeRevision(status="unavailable")
    return CodeRevision(status="recorded", commit=commit, dirty=bool(status.strip()))


def _parse_as_of(text: str):
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _diag(**fields) -> None:
    print(json.dumps(fields, sort_keys=True), file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rap_evaluation")
    sub = parser.add_subparsers(dest="command", required=True)
    run_p = sub.add_parser("run")
    run_p.add_argument("--as-of", required=True)
    run_p.add_argument("--out", default=None)
    rep = sub.add_parser("verify-repeat")
    rep.add_argument("a")
    rep.add_argument("b")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return EXIT_USAGE if exc.code else EXIT_OK

    if args.command == "run":
        as_of = _parse_as_of(args.as_of)
        if as_of is None:
            _diag(phase="admission", check="A1", code="as_of_invalid", detail=args.as_of)
            return EXIT_ADMISSION
        run_id = new_execution_id()
        out = Path(args.out) if args.out else DEFAULT_OUT_DIR / run_id
        config = RunConfig(as_of=as_of, out=out, code_revision=read_code_revision())
        try:
            published = run_evaluation(config, run_id=run_id)
        except AdmissionAbort as exc:
            _diag(phase="admission", check=exc.check, code=exc.code, detail=exc.detail)
            return EXIT_ADMISSION
        except RunnerFailure as exc:
            _diag(phase="execution", code=exc.code, detail=exc.detail)
            return EXIT_RUNNER
        print(json.dumps({"published": str(published), "execution_id": run_id, "status": "partial"}))
        return EXIT_OK

    try:
        report = verify_repeat(Path(args.a), Path(args.b))
    except AdmissionAbort as exc:
        _diag(phase="verify-repeat", check=exc.check, code=exc.code, detail=exc.detail)
        return EXIT_ADMISSION
    except RunnerFailure as exc:
        _diag(phase="verify-repeat", code=exc.code, detail=exc.detail)
        return EXIT_RUNNER
    print(json.dumps(report, sort_keys=True))
    return EXIT_OK if report["verdict"] == PASS else EXIT_VERDICT


if __name__ == "__main__":
    raise SystemExit(main())
