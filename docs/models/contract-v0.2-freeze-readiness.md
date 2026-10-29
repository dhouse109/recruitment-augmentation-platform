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
| D-004.12 evaluation, adjudication, held-out | `evaluation.py`, `adjudication.py`, `promotion.py` (#7; adjudication integrity F4 PR-B) | T1/T2 (contracts, conformance harness) | all 31 | Executed no-model baseline (T3), human adjudication, trusted custody, a recorded promotion decision |

Every decision has a reference contract and T2 evidence. **No decision has T3 or T4 evidence.**

## Open decisions carried forward

| ID | Question | Status |
|---|---|---|
| O3 | Must `ClaimVocabulary` (like `PolicySet`) carry its own authoritative source reference? | Open |
| O4 | Additional requirement kinds for the pilot (schedule windows, location mode)? | Open; needs fairness/accommodation review |
| O5 (remainder) | How rule outcomes cite opportunity-subject evidence directly | Partly resolved in PR #6 (recommendations may cite it) |
| PR #7 drafts | Approve or revise the draft metric definitions, safety-gate policy and reviewer rubric | F4 policy decisions (B1–B5, N1–N3) and PR-A decisions (D1–D5) approved 2026-10-29 ([record](../evaluation/F4-definitions-decision-record.md)); draft definitions v2 added by PR-A (PR #10, merged 2026-10-29); adjudication integrity and draft rubric v2 added by F4 PR-B. **No definition or rubric is approved** (every version remains `draft`); execution-semantics and research-selection contracts (proposed PR-C to PR-F) are not authorized |
| Custody | Where genuine held-out labels live and who authors them | Owner decision before any held-out run |

## Compatibility summary

- PR #4–#6 schema bodies are pinned by digest (`Pr4/Pr5/Pr6CompatibilityTests`); only `$id` and `x-contract-version` changed for the 25 existing schemas; 11 schemas are new in PR #7.
- PR #4–#6 fixture files are unchanged and are now content-pinned by the evaluation manifests.
- No existing model class or validator changed in PR #7.
- F4 PR-B (`0.2.0-dev.foundations.5`) intentionally changes `AdjudicationRecord`, `ReviewerRubric` and `DistributionValue`, and so the `adjudication-record`, `reviewer-rubric` and `run-comparison` bodies; the other 33 bodies are pinned by digest (`Pr4/Pr5/Pr6/Pr7CompatibilityTests`). Both committed copies of rubric v1 still validate.
- JSON Schema cannot express cross-record rules, case grammar, value-only-when-observed, zero-tolerance completeness or promotion strictness; these are Python-only and documented as such in `test_json_schema_conformance.py`.

## Freeze-readiness checklist

| # | Criterion | Status |
|---|---|---|
| 1 | Every D-004 decision has a reference contract, schema and positive/negative tests | **Met** |
| 2 | Schema generation reproducible; drift none; prior schema bodies unchanged except documented, intentional changes | **Met** (pinned Pydantic 2.13.5). F4 PR-B intentionally changes three evaluation bodies (`adjudication-record`, `reviewer-rubric`, `run-comparison`); every other body is pinned by digest |
| 3 | Independent JSON Schema conformance for every exported schema | **Met** (dev requirements) |
| 4 | Accepted ADR vocabulary used throughout code and fixtures | **Met** in code and fixtures; proposed docs synchronized in F1 (2026-10-29) |
| 5 | At least one real producer (engine/adapter) round-trips its outputs through the contracts | **Not met** — no eligibility engine, recommendation engine, verifier or adapter exists |
| 6 | Open decisions O3, O4, O5-remainder dispositioned or explicitly deferred to a later version | **Not met** (owner decision) |
| 7 | Draft evaluation definitions (metrics, gate policy, rubric) approved | **Not met** — F4 policy decisions recorded (2026-10-29), draft definitions v2 added (PR #10) and draft rubric v2 added (F4 PR-B); every definition and rubric version remains `draft` (owner decision) |
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
| Draft comparison flags or gate policy adopted without review | Medium | Medium | All definitions `status: draft`; gate requires an approved policy; F4 decisions recorded and v2 drafts added (PR #10, F4 PR-B) | Owner approval of definitions pending |

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

### F4 PR-B evidence (adjudication integrity)

Fresh clone of branch `contracts/f4-adjudication-integrity` at code commit `32b26676ac7d578682f1978be0597eb443f0da1b` (base `main` @ `089f52bd524545e38a85c0adec26b298a4800504`; later commits change documentation only), Python 3.13.18, `pydantic==2.13.5`, `jsonschema==4.26.0` (dev) and `pydantic==2.13.5` without `jsonschema` (runtime). `CONTRACT_VERSION` is `0.2.0-dev.foundations.5`. The suite grows from 432 to 460 test methods: `test_adjudication.py` is rewritten (8 to 31 methods), and `test_evaluation_contracts.py`, `test_json_schema_conformance.py` and `test_schemas.py` gain 1, 1 and 3 methods.

| Command (from `contracts/`) | Result |
|---|---|
| `python -m rap_contracts.schema_export --check` | `schema drift: NONE` |
| `python -m unittest discover -s tests` (dev requirements) | **460 tests, OK, 0 skipped, 0 failures** |
| `python -m unittest discover -s tests` (runtime requirements only) | **460 tests, OK, 17 skipped** (JSON Schema conformance, as designed) |
| `python -m unittest discover -s tests -p 'test_adjudication.py'` | 31 tests, OK |
| `python -m unittest discover -s tests -p 'test_evaluation*.py'` | 62 tests, OK |
| `python -m unittest discover -s tests -p 'test_json_schema_conformance.py'` | 17 tests, OK |
| `python -m unittest discover -s tests -p 'test_schemas.py'` | 17 tests, OK |
| `python -m unittest discover -s tests -p 'test_promotion_gates.py'` / `'test_dataset_partition.py'` | 49 / 18 tests, OK |

Against `main`: 50 paths change (3 contract modules, all 36 regenerated schemas, 1 new draft fixture, 5 test files, 5 documentation files). Schema bodies change only for `adjudication-record`, `reviewer-rubric` and `run-comparison`; the other 33 are byte-for-byte equal in body and carry the new `$id` and `x-contract-version`. Unchanged: `evaluation.py`, `review.py`, `schema_export.py`, `test_promotion_gates.py`, `test_dataset_partition.py`, both definitions files (v1 SHA-256 `94452315…6957`), every case, layer and manifest, both requirements files, `docs/decisions/` and `docs/evaluation/`. No fixture contains `"status": "approved"`. The PR #7 and PR #10 evidence above is unchanged.

**Failure-first baseline** (synthetic probes on `089f52bd`; details in [`contract-v0.2-adjudication-integrity.md`](contract-v0.2-adjudication-integrity.md#failure-first-evidence-baseline-089f52bd)): records with one reviewer per dimension, partial dimension coverage, arbitrary final labels and an un-adjudicated disagreement were accepted and `reportable()` returned True for typed-in trusted values; a third reviewer counted as independent; per-dimension resolution, justified N/A and missing-output counts were unrepresentable; `recorded_discussion` was accepted; records for different outputs of one case were indistinguishable.

**Mutation evidence** (disposable copies of the code commit; never committed). Each mutation was applied alone and the full dev suite run:

| Mutation | Detected by |
|---|---|
| Accept primary labels from undesignated reviewers | `test_exactly_two_designated_primaries` |
| Trust declared results without recomputation | `test_declared_results_must_follow_from_labels`, `test_adjudication_integrity_conformance` |
| Skip full rubric-dimension coverage | `test_every_rubric_dimension_needs_a_result` |
| Allow an adjudicator label when the primaries agree | `test_unauthorized_resolutions_rejected` |
| Accept N/A without the matching item expectation | `test_na_requires_the_matching_pinned_expectation` |
| Ignore the conflict register's conflicts | `test_each_conflict_reason_disqualifies_a_reviewer` |
| Let structural eligibility become genuine reportability | `test_forged_trusted_metadata_is_never_genuinely_reportable`, `test_genuine_reportability_cannot_be_declared`, `test_each_conflict_reason_disqualifies_a_reviewer` |
| Drop missing outputs from coverage | `test_all_presence_categories_reconcile`, `test_no_score_is_imputed_from_missing_or_unresolved_items`, `test_usefulness_is_never_measured_without_a_trusted_service` (the coverage validator itself rejects the result) |
| Dimension blocks need not account for every genuinely reportable record | `test_usefulness_distribution_populations_and_coverage` |
| Allow `recorded_discussion` | `test_cardinality_and_disagreement_policy_are_fixed`, `test_adjudication_integrity_conformance`, schema drift tests |
| Unanimous N/A ignores the reason (E4) | `test_na_disagreements_need_adjudication` |
| Count one produced output through two slots | `test_duplicate_items_and_double_counted_outputs_rejected`, `test_orphan_duplicate_and_misattached_records_raise` |
| Attach records to absent or failed outputs | `test_records_attach_only_to_produced_outputs`, `test_orphan_duplicate_and_misattached_records_raise` |
| Coverage need not reconcile presence counts | `test_usefulness_distribution_populations_and_coverage`, `test_adjudication_integrity_conformance` |
| Remove the explicit "observed needs a genuinely reportable record" clause | **Not detected — equivalent mutant.** The clause is implied by the dimension-total and scored-anchor checks together (detected separately above); it is kept as a defensive check. |

The first mutation initially survived because the third-primary case was also rejected by result recomputation; commit `32b26676` adds a case whose declared result matches the derivation, isolating the designation rule.

These are synthetic, contract-level checks. Reviewer identity, role, conflict and attestation values in the tests are structural claims, not authentication; nothing is genuinely reportable, and no adjudication has occurred.

### F4 PR-B review repairs (F1–F3)

Independent review of branch head `84303ad0` raised three findings, each reproduced on that head before repair (details and regression tests in [`contract-v0.2-adjudication-integrity.md`](contract-v0.2-adjudication-integrity.md#review-repairs-f1f3)):

- **F1:** disputed and unresolved records with trusted-looking claims were `structurally_eligible`. They now carry `adjudication_not_final`.
- **F2:** an observed usefulness value could include disputed and unresolved counts in a measured dimension. Those fields were removed from the measurement and remain diagnostic only.
- **F3:** derivation accepted items with an unpinned case hash or an out-of-range replicate. It now requires a manifest pinned by the run and applies `check_review_items`.

Fresh clone of code commit `3124d9ab66145727d5389232808ff64f77cc6cc6` (repairs `ade068c0`, test isolation `3124d9ab`; later commits change documentation only), same environments as above:

| Command (from `contracts/`) | Result |
|---|---|
| `python -m rap_contracts.schema_export --check` | `schema drift: NONE` |
| `python -m unittest discover -s tests` (dev requirements) | **464 tests, OK, 0 skipped, 0 failures** |
| `python -m unittest discover -s tests` (runtime requirements only) | **464 tests, OK, 17 skipped** |
| `-p test_adjudication.py` / `'test_evaluation*.py'` / `test_json_schema_conformance.py` / `test_schemas.py` | 34 / 63 / 17 / 17, OK |
| The four F1–F3 regression tests | 4 tests, OK |

The repair commits change 6 files, all inside the PR-B manifest. Against `main` the branch still changes 50 paths, and still exactly the `adjudication-record`, `reviewer-rubric` and `run-comparison` schema bodies. Against `84303ad0` only the `run-comparison` body changes (digest `9e90f184…` to `b774e704…`), because the F2 repair removes two fields from the measurement block. No fixture, case, manifest, ADR or other contract module changed.

**Mutation evidence** (disposable copies of `3124d9ab`): 20 mutants were run, the 15 above plus 5 for the repairs, and 19 were detected.

| Repair mutant | Detected by |
|---|---|
| Disputed or unresolved records can be structurally eligible | `test_disputed_or_unresolved_adjudication_is_not_structurally_eligible`, `test_only_finalized_records_count_as_structurally_eligible` |
| Measured dimensions carry disputed and unresolved fields (not counted) | `test_measurement_excludes_disputed_and_unresolved`, schema drift tests |
| Restore the pre-repair measurement (fields counted in totals) | `test_measurement_excludes_disputed_and_unresolved`, schema drift tests |
| Derivation skips the run's manifest pin | `test_derivation_reuses_pinned_item_checks` |
| Derivation skips the pinned item checks | `test_derivation_reuses_pinned_item_checks`, `test_orphan_duplicate_and_misattached_records_raise` |

The only survivor is the equivalent mutant documented above. The first F2 test passed under the "fields not counted" mutant because its payloads were also rejected by the total check. Commit `3124d9ab` adds balanced-total cases so that only the field rule can reject them.
