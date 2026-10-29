# Contract v0.2 — D-004.01–.12 Traceability and Freeze-Readiness Assessment

**Document ID:** RAP-CONTRACT-002-FR  
**Contract version assessed:** `0.2.0-dev.foundations.4` (PR #7 branch, base `main` @ `9f21486f789f5aac0175ed953ae2b35b4e36013d`)  
**Status:** **ASSESSMENT ONLY.** This document does not freeze Contract v0.2, does not assign release-candidate status and does not authorize application implementation. Only an explicit owner decision can do any of these.

## Evidence tiers used

T1 schema validation · T2 mock-level observed behavior (reference validators, mock authority, in-memory double) · T3 offline measured execution (a generating component ran) · T4 integrated safety evidence (Drupal-backed services or a live system). See [`contract-v0.2-evaluation.md`](contract-v0.2-evaluation.md#evidence-tiers).

## D-004.01–.12 implementation and evidence matrix

| Decision | Reference contract (PR) | Strongest evidence today | Evaluation cases | Outstanding before the decision is demonstrated end to end |
|---|---|---|---|---|
| D-004.01 identity, org scope | `models.py`, `invariants.py` (#4) | T2 | g004, g016, g022, h002 | Drupal account→Candidate mapping and cross-org denial in the live store (T4) |
| D-004.02 profile/application separation | `models.py`, `invariants.py`, `source_checks.py` (#4) | T2 | g022 | Revision retention and submission snapshots in Drupal (T4) |
| D-004.03 human review authority | `review.py` (#6) | T2 (mock authenticator, in-memory double) | g012–g016 | Real authentication, role grants and service-derived identity (T4) |
| D-004.04 verification, escalation, transitions | `recommendation.py`, `review.py` (#6) | T2 | g001, g005a, g005b, g017, g020, g023, g024, h004, h005 | A verifier component (T3) and the write service (T4) |
| D-004.05 opportunity-scoped eligibility | `eligibility.py` (#5) | T2 **on hand-written labels; no engine** | g002, g003, g008, g025, h001, h003 | Slice 0 deterministic eligibility engine (T3) |
| D-004.06 versioned policy rules, unknowns | `eligibility.py` (#5) | T2 on labels; no engine | g002, g003, g008, h001, h003 | Slice 0 engine (T3); real-world rule review before any deployment |
| D-004.07 source version semantics | `models.py`, `source_checks.py` (#4) | T2 (mock authority) | g006, g009, g020 | Live revision and permission revalidation (T4) |
| D-004.08 idempotency and append-only audit | `review.py` (#6) | T2 (in-memory double; single-threaded) | g018, g019 | Atomic, concurrent, durable write service (T4) |
| D-004.09 reason codes, conditional narrative | `review.py` (#6) | T2 | g012–g020 (reason pins exercised) | Write service enforcement (T4) |
| D-004.10 bounded claim vocabulary | `claims.py` (#5) | T2 | g008, g023, h001, h004 | Adapter/source enforcement (T4); O3 vocabulary authority source |
| D-004.11 RAG authorization and currentness | `evidence.py` (#5) | T2 (mock authority and chunk store) | g004, g006, g007, g009, g010, g011, h002 | Real index, live ACL, invalidation (T4); model compliance with injected text (T3/T4) |
| D-004.12 evaluation, adjudication, held-out | `evaluation.py`, `adjudication.py`, `promotion.py` (#7) | T1/T2 (contracts, conformance harness) | all 31 | Executed no-model baseline (T3), human adjudication, trusted custody, a recorded promotion decision |

Every decision has a reference contract and T2 evidence. **No decision has T3 or T4 evidence.**

## Open decisions carried forward

| ID | Question | Status |
|---|---|---|
| O3 | Must `ClaimVocabulary` (like `PolicySet`) carry its own authoritative source reference? | Open |
| O4 | Additional requirement kinds for the pilot (schedule windows, location mode)? | Open; needs fairness/accommodation review |
| O5 (remainder) | How rule outcomes cite opportunity-subject evidence directly | Partly resolved in PR #6 (recommendations may cite it) |
| PR #7 drafts | Approve or revise the draft metric definitions, safety-gate policy and reviewer rubric | F4 policy decisions (B1–B5, N1–N3) and PR-A decisions (D1–D5) approved 2026-10-29 ([record](../evaluation/F4-definitions-decision-record.md)); draft definitions v2 proposed in PR-A. **No definition is approved** (v1 and v2 remain `draft`); adjudication, execution-semantics and research-selection contracts (proposed PR-B to PR-F) are not authorized |
| Custody | Where genuine held-out labels live and who authors them | Owner decision before any held-out run |

## Compatibility summary

- PR #4–#6 schema bodies are pinned by digest (`Pr4/Pr5/Pr6CompatibilityTests`); only `$id` and `x-contract-version` changed for the 25 existing schemas; 11 schemas are new in PR #7.
- PR #4–#6 fixture files are unchanged and are now content-pinned by the evaluation manifests.
- No existing model class or validator changed in PR #7.
- JSON Schema cannot express cross-record rules, case grammar, value-only-when-observed, zero-tolerance completeness or promotion strictness; these are Python-only and documented as such in `test_json_schema_conformance.py`.

## Freeze-readiness checklist

| # | Criterion | Status |
|---|---|---|
| 1 | Every D-004 decision has a reference contract, schema and positive/negative tests | **Met** |
| 2 | Schema generation reproducible; drift none; prior schema bodies unchanged | **Met** (pinned Pydantic 2.13.5) |
| 3 | Independent JSON Schema conformance for every exported schema | **Met** (dev requirements) |
| 4 | Accepted ADR vocabulary used throughout code and fixtures | **Met** in code and fixtures; proposed docs synchronized in F1 (2026-10-29) |
| 5 | At least one real producer (engine/adapter) round-trips its outputs through the contracts | **Not met** — no eligibility engine, recommendation engine, verifier or adapter exists |
| 6 | Open decisions O3, O4, O5-remainder dispositioned or explicitly deferred to a later version | **Not met** (owner decision) |
| 7 | Draft evaluation definitions (metrics, gate policy, rubric) approved | **Not met** — F4 policy decisions recorded (2026-10-29) and draft definitions v2 proposed (PR-A); v1 and v2 definitions remain `draft` (owner decision) |
| 8 | Source hygiene: no transcript-derived or private material in the repository | **Partly met** — current tree redacted (F2 forward redaction, 2026-10-29); earlier copies remain in Git history and GitHub PR refs; history rewriting not authorized |
| 9 | Documentation status consistent with merged state | **Met** as of the F1 documentation sync (2026-10-29); keep current with each PR |
| 10 | Reproducible evidence from a clean checkout, recorded in the PR | **Met** (see below); no CI checks are configured |
| 11 | Explicit owner decision to freeze | **Not given** |

## Assessment

Contract v0.2 is **review-complete at the reference-contract level** (criteria 1–3 and 10) but **not ready for a freeze**. The material gaps are criterion 5 (no producer has yet emitted an `EligibilityResult`, `Recommendation`, `VerificationResult` or `EvaluationRun`, so the shapes are unproven by use), criteria 6–7 (open owner decisions) and criterion 8 (source sanitization: the current tree is redacted, but historical copies remain in Git history and PR refs).

Options for the owner, none of which this PR takes:

- keep v0.2 unfrozen and let the Slice 0 plan exercise it first;
- dispose of O3/O4/O5 and the drafts, then decide; or
- declare an interim status by explicit decision.

## Risk register

| Risk | Likelihood | Impact | Mitigation in place | Residual |
|---|---|---|---|---|
| T2 conformance read as a baseline or safety proof | Medium | High | Tiers, run-kind/purpose rules, policy rejects T1/T2 bases, docs | Communication risk remains |
| AI-authored labels treated as ground truth | Medium | Medium | `review_status: proposed`, no adjudication committed, `reportable()` requires trusted attestation | Owner review of labels pending |
| Nominal held-out treated as blinded | Low | High | `nominal_exposed`, exposure log, gate insufficiency | None in-repo; needs external custody |
| Manifest pin churn on fixture edits | High | Low | Intended; failing test names the drift | Friction |
| Contract shapes change once Slice 0 produces real outputs | Medium | Medium | Not frozen; dev version label | Expected revision |
| Transcript-derived content in repository history | Present in history and PR refs; removed from the current tree | High if the repository is published; moderate while private | F2 forward redaction; repository kept private | History rewrite or fresh redacted repository before any publication — owner decision |
| Single maintainer cannot provide independent dual adjudication | High | Medium | Rubric requires two reviewers; single-reviewer flag | Owner decision on reviewers |
| No CI: evidence depends on manually reported runs | High | Medium | Clean-clone commands in PRs | CI enablement is an owner/spend decision |
| Configuration pins or comparison metric values asserted without real run provenance | Medium | High | Recomputed fingerprints, lineage checks, `run_provenance_basis`, comparison validation against observations | Requires the future trusted run registry |
| Draft comparison flags or gate policy adopted without review | Medium | Medium | All definitions `status: draft`; gate requires an approved policy; F4 decisions recorded and v2 drafts proposed (PR-A) | Owner approval of definitions pending |

## Test evidence

Fresh clone of branch `contracts/v0.2-evaluation` at code commit `6574a02017956219da2a63ad3d98ed5f9709ec7f` (review repairs R1–R7; later commits change documentation only), Python 3.13.18, `pydantic==2.13.5`, `jsonschema==4.26.0`. PR #6 ended at 288 tests; PR #7 now adds 129 (89 initially, 118 after R1–R4, 124 after R5–R6):

| Command (from `contracts/`) | Result |
|---|---|
| `python -m rap_contracts.schema_export --check` | `schema drift: NONE` |
| `python -m unittest discover -s tests` (dev requirements) | **417 tests, OK, 0 skipped** |
| `python -m unittest discover -s tests` (runtime requirements only) | **417 tests, OK, 15 skipped** (JSON Schema conformance, as designed) |
| `python -m unittest discover -s tests -p 'test_evaluation*.py'` | 52 tests, OK |
| `python -m unittest discover -s tests -p 'test_promotion_gates.py'` | 45 tests, OK |
| `python -m unittest discover -s tests -p 'test_json_schema_conformance.py'` | 15 tests, OK (independent JSON Schema conformance) |
| `PYTHONPATH=tests python -m unittest test_evaluation_cases test_dataset_partition test_promotion_gates` | 81 tests, OK |

The 31 evaluation cases and their manifest hashes are byte-identical to the original head `36557e41`; all 31 still pass. No exported schema changed in the R5–R7 repairs.

These are local, manually reported executions; no GitHub CI checks are configured. The PR #7 description repeats them against the final head.

### F4 PR-A evidence (draft definitions v2)

Fresh clone of branch `contracts/f4-definitions-v2` at code commit `52a0c2685cccb65243a0be137bb628ef341afcee` (base `main` @ `f45a9368b24dd10d7f8c7afe51f67da713ebf623`; later commits change documentation only), Python 3.13.18, `pydantic==2.13.5`, `jsonschema==4.26.0`. PR-A adds 15 test methods to the 417 above:

| Command (from `contracts/`) | Result |
|---|---|
| `python -m rap_contracts.schema_export --check` | `schema drift: NONE` |
| `python -m unittest discover -s tests` (dev requirements) | **432 tests, OK, 0 skipped** |
| `python -m unittest discover -s tests` (runtime requirements only) | **432 tests, OK, 16 skipped** (JSON Schema conformance, as designed) |
| `python -m unittest discover -s tests -p 'test_evaluation*.py'` | 61 tests, OK |
| `python -m unittest discover -s tests -p 'test_promotion_gates.py'` | 49 tests, OK |
| `python -m unittest discover -s tests -p 'test_json_schema_conformance.py'` | 16 tests, OK |
| `python -m unittest discover -s tests -p 'test_dataset_partition.py'` | 18 tests, OK |
| `PYTHONPATH=tests python -m unittest test_evaluation_cases test_dataset_partition test_promotion_gates` | 86 tests, OK |

Unchanged against `main`: `rap_contracts/`, all 36 generated schemas (identical tree), every case, layer and v1 definitions fixture (v1 SHA-256 `9445231558c45e4338e7a42d7e31b63e73ef8c122055da8a052a62401d386957`), both requirements files, the ADRs and `CONTRACT_VERSION` (`0.2.0-dev.foundations.4`). No fixture contains `"status": "approved"`.

**Mutation evidence** (disposable copies; never committed):

| Mutation | Tests at `main` (417) | Tests at PR-A (432) |
|---|---|---|
| Gate counts only violations observed at an accepted basis | **OK — not detected** | Fails `BasisIndependentBlockingTests`: both blocking matrices and the report-only recording test |
| Mandatory coverage accepted at any basis | Fails 3 existing tests | Fails the same 3 plus `test_v2_coverage_gaps_and_lower_tier_coverage_never_pass` (reinforcement, not new detection) |
| Held-out case title planted in the v2 file | — | Fails the free-text leakage check (and the v2 inventory check) |
| v2 policy given an extra (T3) accepted basis | — | Fails `test_v2_policy_equals_v1_except_identity` |
| v2 metrics marked `approved` | — | Fails `test_v2_definitions_validate_and_are_drafts` |
| One byte appended to the v1 definitions file | — | Fails `test_v1_definitions_remain_default_and_unchanged` |

These are synthetic, contract-level checks. They are not integrated safety evidence, and the held-out checks are not custody or confidentiality proof.
