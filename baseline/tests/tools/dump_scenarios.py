"""TEST-ONLY scenario dump for PR-S2 acceptance A4/A13 (test-local synthetic data only).

Runs a fixed set of synthetic scenarios against the code under ``--code-root`` and
prints one canonical JSON line per scenario. Run it against a checkout of the PR-S1
base commit and against the PR-S2 head, then diff the outputs: result bytes,
provenance bytes and refusal/error stage, code, detail and authority-call counts
must be identical.

The scenario definitions (``g12_cases.py``) are read from THIS script's directory,
so the procedure works even though they exist only in the PR-S2 branch; the engine,
contracts and ``builders.py`` are imported from ``--code-root``.

    python -I baseline/tests/tools/dump_scenarios.py --code-root <checkout> [--artifacts]

``--artifacts`` (PR-S2 code only) also emits findings and explanation artifacts, for
the cross-process ``PYTHONHASHSEED`` determinism check.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
TESTS = HERE.parent


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--code-root", required=True, type=Path)
    parser.add_argument("--artifacts", action="store_true")
    args = parser.parse_args()
    root = args.code_root.resolve()
    sys.path[:0] = [str(root / "contracts"), str(root / "baseline"), str(root / "baseline" / "tests"), str(TESTS)]

    from builders import ANA, AS_OF, BEN, DATA, EASTERN, OPS, OTHER, OTHER_PRINCIPAL, WEB, World, run  # noqa: E402
    from g12_cases import CASES  # noqa: E402  (from this script's tree)
    from rap_baseline import Assessed  # noqa: E402

    scenarios = [(name, fn, {}) for name, fn in CASES.items()]
    for cand in (ANA, BEN):
        for opp in (DATA, WEB, OPS, OTHER):
            scenarios.append((f"sweep:{cand}:{opp}", lambda c=cand: (World(), c, {}), {"opp": opp}))
    for label, kw in (("as_of+1h", {"as_of": AS_OF + timedelta(hours=1)}), ("as_of_utc-5", {"as_of": AS_OF.astimezone(EASTERN)}),
                      ("other_principal", {"principal": OTHER_PRINCIPAL})):
        scenarios.append((f"C02:{label}", CASES["C02"], kw))

    for name, fn, extra in scenarios:
        w, cand, kw = fn()
        extra = dict(extra)
        opp = extra.pop("opp", DATA)
        out, auth = run(w, cand, opp, **{**kw, **extra})
        line = {"scenario": name, "outcome": type(out).__name__}
        if isinstance(out, Assessed):
            line["result"] = json.loads(out.result.model_dump_json())
            line["provenance"] = out.provenance.canonical()
            if args.artifacts:
                from rap_baseline import explanation, findings  # noqa: E402
                line["findings"] = findings.artifact_canonical(out.findings)
                line["explanation"] = explanation.artifact_canonical(out.explanation)
        else:
            line.update(stage=out.stage.value, code=out.code, detail=out.detail, authority_calls=out.authority_calls)
        print(json.dumps(line, sort_keys=True, ensure_ascii=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
