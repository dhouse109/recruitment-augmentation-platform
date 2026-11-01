# `evaluation/` — Slice 0 offline deterministic evaluation runner (PR-S3b)

`rap_evaluation` runs the merged Slice 0 engine (`baseline/rap_baseline`) on **four pinned golden cases**
(g002, g003, g008 and g025), validates each **generated** `EligibilityResult` with the contract's
`check_eligibility_result`, and compares it with the case's **proposed, unadjudicated** label. The other
22 pinned golden cases are recorded as `not_run`. Design, audit and limits:
[`docs/evaluation/slice-0-offline-runner.md`](../docs/evaluation/slice-0-offline-runner.md).

## What a run means

| It establishes | It does not establish |
|---|---|
| The engine executed on pinned synthetic golden inputs: evidence tier **T3**, basis `deterministic_baseline_execution` | Correctness, accuracy, safety or usefulness |
| Per-step **agreement or disagreement with proposed labels** on 4 cases, which are 3 distinct assessments (g002 and g008 share one scenario, F3) | Any metric, gate result, comparison or promotion evidence (none is computed) |
| g025's `context_validation` prerequisite ran on the reference validator (**T2**) | Drupal authorization, permissions, currentness or context completeness (**not T4**; the source authority is a fixture mock) |
| The execution state machine (SM1–SM3), cross-artifact bindings X1–X9 and the recorded source-gate evidence (G1) held at publication | A trusted attestation (no trusted evaluation-record service exists); a reproducible fixture-mock answer is not external authority evidence |

The run status is always **`partial`** (no `completed_at`): 4 of 26 pinned cases were executed, so the run is
ineligible for comparisons and promotion. The nominal held-out case file is never opened.

## Commands (from `evaluation/`)

```bash
export PYTHONPATH=../contracts:../baseline           # no new dependencies: contracts/requirements.txt only
python -m unittest discover -s tests -v              # runner tests
python -m rap_evaluation run --as-of 2026-11-01T00:00:00Z --out "$T/r1"     # requires a clean git tree
python -m rap_evaluation verify-repeat "$T/r1" "$T/r2"                      # PASS | NOT_INDEPENDENT | NOT_COMPARABLE | DETERMINISM_FAILURE
python -I tests/tools/mutations.py                    # runner mutations (from any directory)
```

`--out` defaults to `evaluation/out/<execution id>/`, which is git-ignored. **Artifacts are never committed**
(decision E8).

Exit codes: `0` success or `PASS`; `1` a `verify-repeat` verdict other than `PASS`; `2` usage; `3` admission
abort (nothing written, output directory not created); `4` runner or binding failure (nothing published).

## Output (one directory per run)

| File | Content |
|---|---|
| `run.json` | `EvaluationRun` (contract `0.2.0-dev.foundations.6`): `deterministic_baseline`, `regression`, `partial` |
| `observations.json` | 26 `CaseObservation`s: 4 `executed`, 22 `not_run` |
| `coverage.json` | Runner-local coverage: 26 pinned, 4 executed, 6 executed steps (5 engine T3, 1 validator T2), 5 engine invocations, 3 distinct assessments; the class and reason of each `not_run` case |
| `sidecar.json` | Runner-local, internal: one entry per engine invocation with the generated result bytes, input fingerprint, output digest, provenance, findings and explanation digests, refusal stage and code, wall-clock times |
| `identity.json` | Execution id, configuration fingerprint, specification and its digest, normalized output digest |
