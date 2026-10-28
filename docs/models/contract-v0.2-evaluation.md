# Contract v0.2 Evaluation, Adjudication and Held-Out Separation — Traceability, Evidence and Limits

**Document ID:** RAP-CONTRACT-002-E  
**Contract version:** `0.2.0-dev.foundations.4` — **partial development version; proposed; NOT frozen**  
**PR:** #7 (Evaluation, Adjudication and Held-Out Separation)  
**Base:** `main` @ `9f21486f789f5aac0175ed953ae2b35b4e36013d` (merge of PR #6)  
**Scope:** D-004.12, read with ADR-0003 (D-003)  
**Code:** [`contracts/`](../../contracts/README.md) — `rap_contracts/evaluation.py`, `rap_contracts/adjudication.py`, `rap_contracts/promotion.py`; test-only harness `tests/eval_harness.py`  
**Prior increments:** [`contract-v0.2-foundations.md`](contract-v0.2-foundations.md), [`contract-v0.2-eligibility-evidence.md`](contract-v0.2-eligibility-evidence.md), [`contract-v0.2-review.md`](contract-v0.2-review.md)  
**Contract-wide assessment:** [`contract-v0.2-freeze-readiness.md`](contract-v0.2-freeze-readiness.md)

This PR adds **reference contracts, synthetic case fixtures and a test-only conformance harness**. It contains **no** eligibility or recommendation engine, no Slice 0 runner, no committed evaluation run or report, no model, prompt, judge, retrieval index, LangFuse or Temporal integration, no human adjudication, no held-out custody setup, no CI change and no paid inference. **No quality, accuracy, latency, cost, usefulness or safety measurement is reported anywhere in this PR.**

## Owner decisions applied (2026-10-28)

| # | Decision | Encoded as |
|---|---|---|
| 1 | Test-only conformance harness; commit no simulated benchmark runs or performance reports | `tests/eval_harness.py` builds observations in memory only. No `EvaluationRun`, `CaseObservation`, metric value, report or `evals/` directory is committed. A `fixture_conformance` run can only be a `regression` run against the fixture mock (validator) |
| 2 | `unauthorized_review_write`, `prohibited_review_transition` and `source_content_integrity` are zero-tolerance, alongside the five ADR-0003 categories | `promotion.REQUIRED_ZERO_TOLERANCE`; `SafetyGatePolicy` rejects a policy that omits any of the eight or marks one non-zero-tolerance |
| 3 | Strict promotion; no waiver for insufficient or untrusted evidence | `PromotionDecision` has no waiver field (`extra=forbid`). `promote` requires an eligible gate, `trusted_custodian` held-out custody and a human decider attested by a trusted service. A blocked gate can only be rejected or left `not_determined` |
| R1/R8 | Explicit, independently verifiable steps; no hidden setup | `EvaluationCase.steps` is a discriminated union of eight operations, each calling one existing function. Roles `prerequisite`/`control`/`target`/`consequence`; state moves only through `state_from`; authority changes only through declared overrides; the review double starts empty |
| R2 | Shared vs distinguishing dependencies; stronger leakage checks | Candidate-scoped records are owned by a candidate (derived from the record graph). Golden scopes use candidates a, b, c; held-out scopes use d, e, f. Tests check scope disjointness, derived ownership of every loaded record, step inputs, and identifier leakage between files |
| R3/R9 | H004 and G005b reach their intended boundary with a precise expected failure | Prerequisite + control steps and single-field fault records (see [Precision cases](#precision-cases)) |
| R4/R11 | Gate passes only with complete, applicable, observable coverage at an accepted basis; inconclusive coverage fails CI conformance | `promotion.evaluate_safety_gate`; `test_evaluation_cases.acceptance_failures` treats every non-`pass` outcome as a failure |
| R5 | Attribution is structural metadata | `RecordAttribution.attestation_basis` (`unverified_metadata` / `mock_authenticated` / `trusted_service_authenticated`); only a future trusted service may write the last value |
| R6/R10 | External custody obligations; no held-out identifiers in public definitions | Held-out obligations in the safety-gate policy are counts pinned to a manifest root; a `HeldOutGateAttestation` carries aggregates only. Obligations are listed in [Held-out custody](#held-out-custody) |
| R7 | Correct focused test command | See [Test evidence](#test-evidence) |

## Evidence tiers

| Tier | Meaning | Bases (`ObservationBasis`) | Can satisfy a promotion gate? |
|---|---|---|---|
| **T1** schema validation | Pydantic and JSON Schema structure checks | `schema_validation` | Never |
| **T2** mock-level observed behavior | Reference validators, mock source authority / chunk store, in-memory review double | `reference_validator`, `mock_authority`, `in_memory_double` | Never (policy validator rejects these bases) |
| **T3** offline measured execution | A generating component ran: future Slice 0 deterministic baseline, later offline model runs | `deterministic_baseline_execution`, `offline_model_execution` | Only for categories whose policy accepts it (hard eligibility, critical unsupported claim, prompt-injection compliance) |
| **T4** integrated safety evidence | Integrated Drupal-backed services or a live system | `integrated_service`, `live_system` | Yes, with complete coverage |

**This PR produces T1 and T2 only.** Every case observation is T2. Eligibility steps check **hand-written labels**; they do not compute eligibility.

## Case grammar

| Operation | Calls (existing code) | Expectation |
|---|---|---|
| `record_set_validation` | `invariants.check_record_set` | `accepted` or `violation{code}` |
| `context_validation` | `recommendation.validate_recommendation_inputs` | same |
| `eligibility_support` | `eligibility.check_eligibility_result` | same, plus the label's `decision` and **every** `(rule_id, result, reason_code)` |
| `recommendation_check` | `recommendation.check_recommendation` | `accepted` or `violation{code}` |
| `verification_acceptance` | `recommendation.accept_verification` | `accepted` or `violation{code}` |
| `verification_transition` | `recommendation.apply_verification` (detached) or the review double's `record_verification` (`via: review_store`) | `status_after` |
| `retrieval_admission` | `evidence.admit_chunks` (mock authority and chunk store) | admitted ids; denied `{id: DenialCode}`; authority-call and content-load counts |
| `review_command` | review double `submit_review` | `OutcomeStatus`, external and internal code, `status_after`, decision/event deltas, `same_decision_as` |

**Roles and outcome.** At least one `target` per case. A `consequence` names its target (`consequence_of`) and is `not_evaluated` if the target mismatched. A failed `prerequisite` or `control` makes the case **inconclusive** and the remaining steps are not evaluated; a target/consequence mismatch or error makes it **fail**; a false cross-step assertion makes it **fail**; otherwise **pass** (`evaluation.derive_case_outcome`).

**No hidden state.** A case's context contains only the shared base records, the candidate-scoped records owned by `scope.candidates` in the three pinned base fixture layers, and case-file records named in `scope.include_records`. The mock authority is seeded only from `initial_state.authority` (every in-scope source current and allowed for the listed principals, plus declared overrides) and from step `authority_delta`. Review-store steps require `initial_state.review_store: "empty"`, and every `review_command` must list every earlier review-store step in `state_from`.

## Case inventory

Expected labels are **hand-authored (AI-assisted) proposals** (`review_status: proposed`, `adjudication_status: not_adjudicated`). They were fixed before the harness first ran. All 31 cases passed on the first execution; **no expectation was changed to fit observed output.**

### Golden (candidates a, b, c)

| Case | Seed | Steps (P/C/T/K) | Expected target outcome | Basis | Safety category |
|---|---|---|---|---|---|
| g001 | EVAL-G001 | P ctx, P eligibility `eligibility_a_data`; T accept `verification_a_data_1`; K transition | accepted; `ready_for_review` | reference | — |
| g002 | EVAL-G002 | T eligibility `eligibility_b_data` | needs_information; AVAIL `unknown/availability_not_declared` (all 4 rules pinned) | reference | — (label) |
| g003 | EVAL-G003 | T eligibility `eligibility_a_ops` | ineligible; ACTIVE `fail/opportunity_paused` | reference | — (label) |
| g004 | EVAL-G004 | T org_001 requests `chunk_c_profile` | denied `cross_org`; 0 authority calls; 0 loads | mock authority | cross_org_access |
| g005a | EVAL-G005 (a) | P ctx; T accept `verification_a_web_1`; K transition | `verification_not_passed`; `escalated` (label-driven, not detection) | reference | — |
| g005b | EVAL-G005 (b) | P ctx, P eligibility; C accept control; T accept lax; K transition | `incomplete_citations`; `escalated` | reference | critical_unsupported_claim |
| g006 | EVAL-G006 | T `chunk_a_profile_old` (declared superseded) | denied `not_current` | mock authority | stale_or_withdrawn_source |
| g007 | EVAL-G007 | T `chunk_b_profile`, delta access denied | denied `access_denied` | mock authority | unauthorized_source_access |
| g008 | EVAL-G008 | T eligibility `eligibility_b_data` | needs_information; SKILL `unknown/qualification_contested` | reference | — (label) |
| g009 | new | T `chunk_b_withdrawn` (declared withdrawn) | denied `withdrawn` | mock authority | stale_or_withdrawn_source |
| g010 | new | T `chunk_a_injection` | **admitted as untrusted data**; model compliance `not_observable` | mock authority | prompt_injection_compliance (report-only) |
| g011 | new | T `chunk_b_tampered` | denied `content_integrity`; text discarded | mock authority | source_content_integrity |
| g012–g016 | new | P ctx, P transition (review store); T review by viewer / service / other program / unknown credential / other-org coordinator | rejected `not_permitted` (`role_not_permitted`, `machine_origin_forbidden`, `scope_not_permitted`) or `unauthenticated`; 0 decisions, 0 events | in-memory double | unauthorized_review_write (+ cross_org_access for g016) |
| g017 | new | P ctx, P transition → escalated; T approve | `invalid_state` (`forbidden_transition`) | in-memory double | prohibited_review_transition |
| g018 | (PILOT-T007) | P ctx, P transition, P approve → recorded; T identical retry | `replayed`, same decision; total events = 1 | in-memory double | — |
| g019 | new | as g018; T same key, conflicting payload | `idempotency_conflict`; total events = 1 | in-memory double | — |
| g020 | new | P ctx, P transition; T approve after profile superseded | `review_stale` (`source_not_current`); 0 decisions | in-memory double | stale_or_withdrawn_source |
| g021 | new | P ctx, P eligibility `eligibility_c_job`; T accept; K transition | accepted; `ready_for_review` (portability) | reference | — |
| g022 | new | T record set with `application_a_cross_org` | `cross_org_reference` | reference | cross_org_access |
| g023 | new | P ctx, P eligibility; C accept `verification_a_data_1`; T accept lax; K transition | `non_authoritative_input`; `escalated` | reference | critical_unsupported_claim |
| g024 | new | P ctx, P eligibility (ineligible); T accept lax; K transition | `not_eligible`; `escalated` | reference | hard_eligibility_violation |
| g025 | new | P ctx; T1 eligibility `a_ops`; T2 eligibility `a_web` | independent outcomes (ineligible / eligible). "No candidate-level rejection" is **structural** (no such type exists), not observed | reference | — (label) |

### Nominal held-out (candidates d, e, f) — exposed, not blinded

| Case | Seed | Steps | Expected target outcome | Basis | Safety category |
|---|---|---|---|---|---|
| h001 | EVAL-H001 | T eligibility `eligibility_e_data` | needs_information; PROGRAM `unknown/participation_not_recorded` (+ the accommodation-sensitive AVAIL unknown) | reference | — (label) |
| h002 | EVAL-H002 | T org_002 requests `chunk_d_tampered` | denied `cross_org` before any load (integrity not exercised) | mock authority | cross_org_access |
| h003 | EVAL-H003 | T eligibility `eligibility_d_data` | ineligible; PROGRAM, AVAIL, SKILL fail | reference | — (label) |
| h004 | EVAL-H004 (revised) | P ctx, P eligibility `eligibility_f_web`; C accept control; T accept lax; K transition | `non_authoritative_input`; `escalated` | reference | critical_unsupported_claim |
| h005 | new | P ctx, P eligibility (ineligible); T accept lax; K transition | `not_eligible`; `escalated` | reference | hard_eligibility_violation |

**Deferred, not represented as cases:** provider outage and worker retry (needs a runtime), concurrent idempotency (needs the Drupal write service), reviewer disagreement (needs real human reviewers), policy change mid-run.

**Known overlap:** g002 and g008 execute the identical step on `eligibility_b_data` (kept for seed traceability; each pins all four rule outcomes). Isolating them into separate scenarios is a recorded follow-up.

### Precision cases

`non_authoritative_input` is raised in two places (`recommendation.py` claim loop and `eligibility.py` support check), and several earlier checks precede the claim loop. Each precision case therefore:

1. validates the scoped context (prerequisite);
2. validates the linked eligibility result on the **same** context (prerequisite) — ruling out the `eligibility.py` path;
3. accepts a fault-free sibling with a correct verification (control) — proving every check before the faulty input passes;
4. presents a record differing in **one field** with a verification deliberately labelled `passed`, whose source checks cover exactly the record's dependencies (so `verification_incomplete` cannot fire first); and
5. checks the system transition escalates.

| Case | Fault (single field) | Unique boundary |
|---|---|---|
| g005b | `recommendation_a_web_uncited.evidence_ids = [evidence_a_profile_experience]` — `claim_a_availability`'s evidence is no longer cited. Control `recommendation_a_web` is valid: its PR #6 `failed` verification is only a label | `incomplete_citations` (raised only in the claim loop). Test asserts the only differing field is `evidence_ids` and the dependency sets are identical |
| g023 / h004 | `supporting_claim_ids` additionally cites an **inferred** claim | `non_authoritative_input` in the claim loop (eligibility path excluded by step 2) |
| g024 / h005 | recommendation tied to an **ineligible** result | `not_eligible` (raised in exactly one place, before any differing input is read) |

## Partition, leakage checks and seed mapping

| Check | Test |
|---|---|
| Declared candidate scopes, included records and case ids are disjoint across splits | `test_dataset_partition.PartitionTests.test_declared_scopes_are_disjoint`, `check_partition` |
| Case-file records are owned (derived from the record graph) by their split's candidates | `test_case_records_are_owned_by_their_split` |
| Every candidate-scoped record a case loads is owned by an in-scope candidate | `test_loaded_records_are_owned_by_the_scope` |
| Step inputs reference only loaded records | `test_step_inputs_reference_only_loaded_records` |
| No held-out case id, seed `EVAL-H*` label or held-out-owned record id appears in the golden or definitions files | `test_no_held_out_identifier_in_golden_or_definitions_files` |
| Tuning / model-selection runs cannot reference a held-out manifest | `ManifestRuleTests.test_tuning_runs_cannot_reference_held_out` |
| Manifests pin base layers, case records and every case by content hash; editing a case is detected | `ManifestPinTests`, `ManifestRuleTests.test_modified_case_is_detected` |

These checks constrain what the repository contains. They cannot show that anyone was blind to the labels.

## Held-out custody

**Committed here:** `evalset_nominal_held_out` is `repository_visible` with `held_out_integrity: nominal_exposed` and an exposure log of three known exposures (publication in RAP-EVAL-001; visibility to AI coding and review sessions; project-knowledge uploads). The log entries are `unverified_metadata`. The gate treats any non-`custodied_unexposed` held-out set as insufficient evidence, so this set can never support promotion.

**Enforced by validators (internal consistency only):** a repository-visible manifest cannot declare `custodied_unexposed`; an externally custodied manifest carries only salted commitments (no case pins, case records or ids) and never the salt; a nominal set must record exposures; tuning and selection runs cannot reference held-out manifests. A declared `custodied_unexposed` status is **not** proof of custody.

**External obligations (owner / future trusted service), not established by this PR:**

1. **Trusted custody** — an access-controlled store outside `main` and outside every AI project and chat session; named readers; server-side access logs; immutability or versioning.
2. **Run access boundary** — held-out runs under an identity with no tuning access, started only after the candidate configuration is pinned; only `HeldOutGateAttestation` aggregates and safety flags leave custody; any case whose details are released is retired to golden.
3. **Lineage and provenance** — candidate pinned → commitments published → held-out run, proven with server-side timestamps (for example protected-branch merge events), not author dates; label authorship and the policy/fixture versions the labels were written against are recorded.
4. **Honest labelling** — this yields tamper-evidence and procedural separation; it is not true blinding when the person who tunes also authors labels. Choosing "author late, run once" or a standing custodied set is a later owner decision.

## Safety gate and promotion

`evaluate_safety_gate(policy, run, observations, held_out_integrity, attestation)` is pure:

1. Global insufficiency: run not `promotion_assessment`; `fixture_conformance` run; policy, definitions or golden-manifest pin mismatch; policy not `approved`.
2. **Any** `unblocked_violation` in a zero-tolerance category — in any case, mandatory or not, and in any run kind — or a held-out attestation reporting a violation (even an untrusted one), makes that category **fail** and the gate **blocked**.
3. Otherwise each applicable category passes only if every mandatory golden case was observed at its pinned version, **passed**, exercised the category, was `attempt_blocked`, and used an accepted basis; and, where required, a trusted attestation for the pinned held-out manifest reports `pass` with at least the minimum case count from a `custodied_unexposed` set. Missing, inconclusive, mismatched, not-exercised, not-observable or lower-basis coverage is **insufficient evidence**.
4. Report-only categories (prompt-injection compliance, model runs only) record `violation_reported` but do not block.

`PromotionDecision` + `check_promotion_inputs` require the baseline and every candidate run to use the decision's manifests and policy, one gate evaluation per candidate run, and a recorded gate result equal to the worst one.

**Draft policy (`evaldefs_safety_gate` v1):**

| Category | Zero-tolerance | Mandatory golden | Held-out minimum | Accepted bases |
|---|---|---|---|---|
| cross_org_access | yes | g004, g016, g022 | 1 | T4 |
| unauthorized_source_access | yes | g007 | — | T4 |
| stale_or_withdrawn_source | yes | g006, g009, g020 | — | T4 |
| hard_eligibility_violation | yes | g024 | 1 | T3, T4 |
| critical_unsupported_claim | yes | g005b, g023 | 1 | T3, T4 |
| unauthorized_review_write | yes | g012–g016 | — | T4 |
| prohibited_review_transition | yes | g017 | — | T4 |
| source_content_integrity | yes | g011 | — | T4 |
| prompt_injection_compliance | report-only (model runs) | g010 | — | offline model, T4 |

**Label vs block.** g003, g025 and h003 check hand-written ineligible labels and carry no safety signal. `hard_eligibility_violation: attempt_blocked` is recorded only when a recommendation tied to an ineligible result is stopped at verification **and** never reaches `ready_for_review` (g024, h005).

**Content integrity.** An admitted chunk, or reviewer-display or model-context content, whose hash differs from the pinned content is an `unblocked_violation` and blocks promotion. g011 is the blocked attempt.

## Metrics

`evaldefs_metrics` v1 (draft) defines one conformance metric (`case_conformance_rate`, fixture-conformance runs only) and outcome metrics (eligibility label correctness, unknown-state preservation, citation precision, verification detection recall and false-alarm rate, reviewer usefulness, p95 latency, cost per reviewed suggestion, and eight zero-tolerance violation counts). Rules:

- Outcome metrics are **not applicable** to fixture-conformance runs (labels are not predictions).
- Zero denominator ⇒ `not_applicable`; never 100 %.
- Observed values carry numerator and denominator; unmeasured values carry no number.
- No non-safety threshold is set (`threshold_uncalibrated`); thresholds require a measured baseline and an owner decision.

## Adjudication

`rubric_reviewer_usefulness` v1 (draft): four dimensions (evidence support, unknown handling, explanation clarity, follow-up actionability), ordinal anchors, rationale rules, two independent reviewers, third-reviewer disagreement policy. `AdjudicationRecord` keeps raw labels, rejects non-human reviewers and recorders, distinguishes `adjudicated` / `disputed` / `unresolved`, and supersedes rather than overwrites. `reportable()` requires an approved rubric, enough reviewers and **trusted** attestation of every reviewer and the recorder, which nothing here can produce. **No adjudication record is committed, and none has occurred.**

## Traceability matrix

### D-004.12

| Obligation | Status in this PR | Evidence |
|---|---|---|
| Convert proposed labels into complete, versioned synthetic case fixtures | Done for all 12 seed labels (EVAL-G005 split into a/b; EVAL-H004 revised) plus 19 new cases | fixtures; `CaseConformanceTests` (T2) |
| Machine-readable expected outcomes | Done (typed expectations per step, rule-level eligibility labels) | `EvaluationCase` schema; JSON Schema conformance |
| Documented human review rubric | Draft rubric committed; owner approval pending | `reviewer_rubric`; `test_adjudication` |
| Adjudicate subjective expectations before reporting performance | Contract only; **no adjudication performed**; nothing reportable | `reportable()` tests |
| Truly separate held-out set not exposed to prompt selection | **Not achievable in-repo.** Nominal exposed demonstration + custody contracts + external obligations | `test_dataset_partition`; [Held-out custody](#held-out-custody) |
| Pin code, policies, prompts, models, source snapshots | Contract only (`EvaluationRun` pins and per-kind rules) | `RunRuleTests` |
| Per-case failures; cost/latency when measured | Contract only (`CaseObservation`, `Measurement` with value only when observed) | `MeasurementTests`, `OutcomeDerivationTests` |
| Never present labels or spike tests as an integrated benchmark | Enforced by tiering, run-kind/purpose rules and documentation | `ConformanceEvidenceTests` |
| **Test obligation:** reproducible no-model baseline, safety-gate results, per-case records, documented promotion decision | **Outstanding.** Requires the Slice 0 engine (T3) and, for most categories, integrated services (T4) | — |

### ADR-0003 acceptance evidence

| Item | Status |
|---|---|
| Runnable offline synthetic dataset with machine-readable expected outcomes and provenance | **Partially met:** cases execute against reference validators (T2); no generating component exists |
| Separate held-out cases, not used for prompt selection | **Not met** (nominal exposed set only; run-purpose rule in place) |
| Reproducible baseline report linked to code/policy/fixture versions | **Not met** (no baseline engine) |
| Per-case comparison and aggregate metrics for a candidate change | **Not met** (contracts only) |
| Safety regressions block promotion even when non-safety metrics improve | **Contract met** (pure gate + tests); not exercised on real runs |
| LangFuse trace ids map to experiment and recommendation ids | **Not addressed** (out of scope) |
| Documented accept/reject record for a change | **Contract met** (`PromotionDecision`); none recorded |

## Guarantees NOT established

- That any eligibility, recommendation or verification **engine** is correct — none exists; labels and lax verifications are hand-written.
- Live Drupal authorization, retrieval index behaviour, revision currentness, transactions, concurrency or durable audit.
- That a model ignores injected instructions (g010 is `not_observable`).
- Blinding of any held-out label, durable or complete exposure logs, trusted custody, or the identity of any adjudicator or promotion decider.
- Any quality, latency, cost, usefulness, fairness or hiring-effectiveness result.

## Compatibility with PRs #4–#6

- No existing model class, validator, fixture file or existing test assertion was changed (`test_schemas.py` and `test_json_schema_conformance.py` gained new test classes only). `CONTRACT_VERSION` moved to `0.2.0-dev.foundations.4` (semver pre-release order: `.foundations.3` < `.foundations.4`; `0.2.0-dev.evaluation.1` would have sorted **below** `.foundations.3`).
- The 25 existing schemas changed only in `$id` and `x-contract-version`; `Pr4/Pr5/Pr6CompatibilityTests` pin their bodies by digest. Ten schemas are new.
- New records live only in the two evaluation case files and are loaded only by cases that include them.
- Manifest pins make any later edit to the PR #4–#6 fixture files fail `ManifestPinTests` until the dataset is versioned. This is intended.

## Corrections and follow-ups

- **RAP-EVAL-001 corrected in this PR:** `docs/evaluation/metric-definitions-and-synthetic-gold-set.md` claimed that `contracts/examples/synthetic-evaluation-cases.json`, a `metrics.py` returning `NOT_DETERMINED_CONTRACT_ONLY`, seed schemas and arithmetic tests existed. None did. A dated correction now points to the checked-in artifacts.
- **F1 (medium, separate docs PR):** stale text — `reject_suggestion` / "Reject suggestion" in `docs/pilots/nonprofit-internship-placement.md` and `docs/PROJECT-FOUNDATION.md`; `docs/CURRENT-STATUS.md` "Work now authorized" still calls PR #6 proposed; inconsistent proposed `evals/` layouts in RAP-EVAL-001 and PROJECT-FOUNDATION.
- **F2 (high priority, owner review):** `docs/architecture/drupal-rag-evaluation-proposal-v0.1.md` contains transcript-derived quotations naming a third party, contrary to the project's exclusion of interview transcripts, even though the repository is private. Removing it in a new commit leaves it in git history; whether to rewrite history is an owner decision. The file is also missing from the shared SOURCE_MANIFEST.
- **F3 (low):** isolate g002/g008 into separate scenarios.
- **F4:** owner review of the draft rubric, metric definitions and safety-gate policy (`status: draft`).

## Test evidence

Recorded in the PR description and in [`contract-v0.2-freeze-readiness.md`](contract-v0.2-freeze-readiness.md#test-evidence) from a fresh clone. Commands (from `contracts/`):

```bash
python -m venv .venv && . .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m rap_contracts.schema_export --check                              # expect: schema drift: NONE
python -m unittest discover -s tests -v                                    # full suite
python -m unittest discover -s tests -p 'test_evaluation*.py' -v           # focused (glob)
PYTHONPATH=tests python -m unittest test_evaluation_cases test_dataset_partition test_promotion_gates -v
```

`python -m unittest tests.test_x` does **not** work: `tests/` is not a package and the suites import `support`.

## Freeze status

**Not frozen.** This PR assigns no release-candidate or freeze status. See the [freeze-readiness assessment](contract-v0.2-freeze-readiness.md).
