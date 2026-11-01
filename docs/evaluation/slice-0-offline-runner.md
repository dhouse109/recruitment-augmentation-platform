# Slice 0 PR-S3b — Offline Deterministic Evaluation Runner: Design, Audit and Limits

**Document ID:** RAP-SLICE0-PR-S3B  
**Authorization:** AR-S3b (owner, 2026-11-01), implementing §9.2 of RAP-SLICE0-PR-S3-PLAN-2026-11-01 **rev. 2.1**  
**Base:** `main` @ `bae5d39efddacf432a0fecc00b6ab16ebd85f72e` (PR #17 merged)  
**Contract:** `0.2.0-dev.foundations.6` (PR-S3a, PR #16), proposed, **not frozen**  
**Code:** [`evaluation/rap_evaluation`](../../evaluation/README.md). No change under `contracts/` or `baseline/`.  
**Data:** synthetic only. No held-out case file is opened. No paid inference.

> A matched step means the engine's generated result was contract-supported and agreed with a **proposed,
> unadjudicated** label. It is not reviewed correctness, accuracy or safety, and the fixture-mock source
> authority is not Drupal authorization (not T4).

## 1. Decisions applied

| ID | Decision | Where |
|---|---|---|
| E1 | Strict scope: g002, g003, g008, g025 | `applicability.py` (class table, selection version 1) |
| E2 = B | Engine steps are `eligibility_support` at basis `deterministic_baseline_execution`, naming the generated result in `ObservedRecord.eligibility_result_id` (PR-S3a). Binding is verified by X1–X9 here, not by the contract | `execute.py`, `artifacts.py` |
| E3 | g025 s1 (`context_validation`) runs on the reference validator at basis `reference_validator` (T2) | `execute.py` |
| E4 | Run status `partial`, never `completed`; no `completed_at` | `run.py` |
| E5 | Shared layers are parsed; held-out-owned records are guarded before construction and scanned for in the output. Parsing is contact (§5) | `scope.py`, `artifacts.py` |
| E7 | Draft v1 metrics and safety policy verified read-only | `definitions.py` |
| E8 | Artifacts are written to an output directory only; `evaluation/out/` is git-ignored | `.gitignore`, `__main__.py` |
| E9 | New top-level `evaluation/rap_evaluation`; the `evals/` layout question stays open | — |
| E12 | Random execution id; deterministic configuration, specification and output identities; `verify-repeat` | `identity.py` |
| SD-15 | A mismatch is recorded as `fail`; labels, fixtures, contracts and the engine are never modified | — |

## 2. Workflow per engine step (plan §2.1)

1. **Key projection (admission A7).** From the label the step names, only `id`, `organization_id`,
   `candidate_id`, `opportunity_id` and `policy` are read. Labels are never constructed as contract models.
2. **Generate.** `rap_baseline.assess(EligibilityRequest(key, principal, as_of), scoped_context,
   FixtureMockAuthority, capabilities)`. `EligibilityContext` has no results field, so the engine cannot receive
   a label.
3. **Validate the generated result** with `check_eligibility_result(result, full admitted scope)`.
4. **Compare** `(result, violation_code, decision, rule outcomes sorted by rule_id)` with the step's expectation.
5. `Refused` / `Errored` → step `errored` with `engine_refused` / `engine_errored`; stage and code go to the
   sidecar; no result id. A refusal is never mapped to a validator `violation`.

**g025 prerequisite (interpretation for review).** The T2 conformance harness validates a context that also
contains the scope's label results. This runner never constructs labels, so `context_validation` runs
`validate_recommendation_inputs` over the **label-free admitted context** (empty eligibility-results map, as the
engine's own phase P6 does). It therefore does not re-check the labels themselves. The observation is recorded at
basis `reference_validator` (T2). If the owner prefers the harness semantics, constructing the scope's labels for
this one T2 step is the alternative; it would relax the "labels are never constructed" rule.

## 3. Admission (A1–A8) and publication

All admission checks run before any engine call. Any failure is exit **3**: no artifact, no output directory.

| Check | Content |
|---|---|
| A1 | Clean recorded commit (CLI reads git; tests inject a `CodeRevision`), installed contract version `.foundations.6`, purpose `regression`, no retrieval/prompt/model/judge pin, one replicate, timezone-aware `as_of`, new output path |
| A2 | Only five files can be opened: the three base layers, the golden file and definitions v1. Any other name is refused before `open`. The held-out file name is never constructed |
| A3 | Golden, repository-visible, `not_applicable` manifest; layer digests, `case_records_sha256` and every case pin (`check_manifest_cases`) |
| A4 | `evaldefs_metrics` v1 and `evaldefs_safety_gate` v1 validate, are `draft`, chain correctly and pass `check_policy_manifest`; digests recorded; held-out manifest pin recorded, never resolved |
| A5 | Owner of every candidate-scoped raw record derived from the record graph. Revisions of one record (for example two revisions of `profile_demo_a`) share an id and must share an owner |
| A6 | Contract models are built only for records owned by an in-scope golden candidate. A held-out-owned record reaching construction is `held_out_construction`; another golden candidate's record is `cross_scope_construction` |
| A7 | Each selected step's label exists once and is in scope; its key's candidate, opportunity, organization and policy pin resolve in the scope; exactly one declared principal |
| A8 | All 26 pinned cases are classified; the selection is exactly the four cases; selected cases have the expected step shape and declare no safety expectations, assertions or review store (stricter than the plan: this runner emits no safety observations) |

**Execution** runs only after A1–A8. Engine refusals and errors become observations. Any other exception is exit
**4** with nothing published. Invocations that share a key must produce byte-identical results (in-run
consistency, exit 4 otherwise).

**Publication** writes to a temporary directory next to `--out`, re-reads every file and checks, in order:
contract re-validation and run fields (P1), the X1–X9 bindings, prerequisite reproduction (P3), coverage (P4), the
held-out identifier scan (S1) and the identity record (P5). Only then is the directory renamed to `--out`.
Any failure removes the temporary directory (and any parent it created).

## 4. Cross-artifact binding (X1–X9)

| Id | Check | How it avoids trusting the sidecar |
|---|---|---|
| X1 | One sidecar entry per evaluated engine step; no missing, orphan or duplicate entry | — |
| X2 | Matched/mismatched: stored bytes parse as `EligibilityResult`, are its canonical serialization, and name the observed id | — |
| X3 | Input fingerprint, result id and output digest | The fingerprint is **recomputed from the admitted scope and key** (engine projection and identity functions: `resolve_targets`, `project`, `build_decision_inputs`, `input_fingerprint`); the id is recomputed from it and `as_of`; the digest from the stored result. Provenance must describe the same result, principal, `as_of` and engine |
| X4 | Generated id ≠ the step's label id and ≠ every fixture label id | — |
| X5 | Sidecar key and request equal the admitted key, principal and `as_of`; the result's key equals the admitted key | — |
| X6 | Observed decision and rule outcomes are the result's; the step status follows from the comparison | — |
| X7 | `check_eligibility_result` on the stored result reproduces the observed verdict | Re-run, not read |
| X8 | Errored steps: a refusal or error with stage and code, no result bytes, matching `error_type` | — |
| X9 | Steps sharing a key carry identical ids and bytes | — |

X3's recomputation is independent of the engine's runtime output but **not of the engine's code**: it uses the
engine's own published projection and identity functions over the admitted scope. `verify-repeat` re-admits the
fixtures at each run's `as_of` and repeats every publication check. None of this is a trusted attestation.

## 5. Separation and the held-out boundary

- The nominal held-out case file is never opened, copied or named (AST and `open`-spy tests; the mutation harness
  excludes it from its scratch copy).
- The shared eligibility layer **does** contain held-out-owned synthetic records (candidates D and E). They are
  parsed, and their owner and identifier fields are read to classify them and to build the output denylist.
  **Parsing is contact.** The guards establish only that no such record is constructed as a model, reaches the
  engine or validator, or appears in an artifact. Avoiding contact entirely needs a derived golden-only layer, a
  fixture change requiring separate authorization (E5).
- The output scan matches whole identifiers, including held-out records' numeric source entity ids. It fails closed:
  a future collision with an unrelated number would abort publication rather than pass.
- No import from `contracts/tests` or `baseline/tests`; only `MetricDefinitionSet`, `SafetyGatePolicy` and
  `check_policy_manifest` are imported from `promotion`; no metric, gate, comparison or promotion function is called.

## 6. Identities and `verify-repeat`

| Identity | Definition |
|---|---|
| Execution | `evalrun_` + 32 random hex characters (unique per run) |
| Configuration | `ConfigurationPin` fingerprint recomputed by the contract: run kind, strategy `rap_baseline_eligibility` v1 {eligibility}, clean commit, contract version, n/a pins |
| Specification | Digest over manifest pin, manifest contract version, layer digests, case-records digest, golden document digest, definitions digests and pins (held-out pin unresolved), class table digest, selection version, UTC `as_of`, principal policy, mock authority id, runner, contract version and configuration fingerprint |
| Normalized output | Digest over the 26 observations (`run_id` normalized), coverage, and every sidecar field except wall-clock times |

Verdicts: `PASS` (distinct execution ids, equal configuration, specification and output); `NOT_INDEPENDENT`
(same execution id); `NOT_COMPARABLE` (configuration or specification differ, e.g. another `as_of` or commit);
`DETERMINISM_FAILURE` (same configuration and specification, different output).

## 7. Observed results (synthetic golden inputs, `as_of` 2026-11-01T00:00:00Z)

| Case | Step | Basis | Status |
|---|---|---|---|
| g002 | s1 (B × data) | T3 | matched |
| g003 | s1 (A × ops) | T3 | matched |
| g008 | s1 (B × data, same scenario as g002, F3) | T3 | matched |
| g025 | s1 `context_validation` | T2 | matched |
| g025 | s2 (A × ops) | T3 | matched |
| g025 | s3 (A × web) | T3 | matched |

All five engine steps returned `Assessed`; the engine admitted the existing fixture layers without any fixture,
label, contract or engine change (risk R-1 did not materialize). **No label disagreement was observed**, so nothing
was entered in the SD-15 register. This is agreement with proposed labels on 4 cases and 3 distinct assessments.
It is not an accuracy figure and must not be aggregated or extrapolated.

## 8. Test and mutation evidence

`evaluation/tests` (156 tests; 1 JSON-Schema test is skipped in the runtime-only environment) cover admission
aborts A1–A8 with no output, definitions, ownership and the construction guards, organization scoping, the
workflow order (spies), execution-phase injections (superseded, withdrawn and denied sources, removed
participation, injected engine error, refusal never mapped to a violation, prerequisite mismatch, altered
expectations), label blindness, every X1–X9 negative, publication checks, identities, all four `verify-repeat`
verdicts, `PYTHONHASHSEED` 0/1/2 and shuffled record order, and static and dynamic separation.

Some negatives isolate one check deliberately: X4 patches the id function to simulate a collision with a label
id, and X9 disables the per-step checks; both are stated in the tests.

`tests/tools/mutations.py` applies 29 single-invariant mutations (R01–R29) in a scratch copy and classifies them
with the PR-S2 R1 rules (controls first). Class-level fixtures are built lazily so a broken fixture fails each test
rather than shrinking the run, which the classifier would treat as a harness error.

## 9. Limitations carried forward

- **F3:** g002 and g008 share one scenario; they are one distinct assessment.
- **F4/B3:** definitions and labels are drafts; labels are proposed and not adjudicated.
- **G12a–c:** open at the result level; citations are recorded in the sidecar but not evaluated (no citation
  expectations exist).
- **O3/O5:** codes only; no opportunity evidence.
- **TD-1:** provenance version fields are not bound to `engine.ENGINE`; the run is bounded by its commit pin.
- **Held-out contact:** the shared layer is parsed (§5).
- **No T4:** the fixture mock is not Drupal; context completeness is asserted by the fixture adapter.
- **No measurement:** latency `not_measured`, cost `not_applicable`; no metric, gate, comparison or promotion.
- The manifest's `contract_version` (`.foundations.4`) lags the installed `.foundations.6` (R-8); recorded as is.
- The pre-existing contract conformance suite (`contracts/tests`) still reads both case splits, as on `main`;
  this runner does not.
