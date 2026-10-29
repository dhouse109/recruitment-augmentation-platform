# Contract v0.2 Adjudication Integrity (F4 PR-B) — Traceability, Evidence and Limits

**Document ID:** RAP-CONTRACT-002-A  
**Contract version:** `0.2.0-dev.foundations.5` — **partial development version; proposed; NOT frozen**  
**Scope:** F4 PR-B, encoding owner decisions B2 and N1 and implementation choices E1–E10 and E12–E14 ([decision record](../evaluation/F4-definitions-decision-record.md)); D-004.12 read with ADR-0003 decision 8  
**Base:** `main` @ `089f52bd524545e38a85c0adec26b298a4800504` (merge of PR #10)  
**Code:** [`contracts/`](../../contracts/README.md) — `rap_contracts/adjudication.py`, `rap_contracts/promotion.py` (`DistributionValue`), `rap_contracts/models.py` (version)  
**Related:** [`contract-v0.2-evaluation.md`](contract-v0.2-evaluation.md), [`contract-v0.2-freeze-readiness.md`](contract-v0.2-freeze-readiness.md)

This increment changes **contracts, schemas, one draft fixture, tests and documentation only**. It adjudicates nothing, commits no adjudication record, review item or conflict register, approves no rubric or definition, and implements no trusted service. **Nothing is genuinely reportable in this contract version.**

## Owner decisions encoded

Approved 2026-10-29 together with the authorization to implement PR-B. B2 and N1 are the Stage A decisions; E-items are the approved implementation choices, with the owner's qualifications.

| Decision | Encoded as |
|---|---|
| B2 two independent primaries per dimension; direct label when they agree; distinct third adjudicator when they disagree; counted `disputed`/`unresolved` otherwise | `AdjudicationRecord.primary_reviewers` (exactly two, distinct), `adjudicator` (distinct), `derive_dimension_result`, `DimensionResult`, `derive_status` |
| B2 conflict rule (configuration authorship or tuning, reference-label authorship; separate IDs insufficient) | `ReviewerConflictRegister` (caller-supplied, not exported) and `assess_reportability` reasons |
| B2 only a trusted service can authenticate roles and attest independence | `ReportabilityAssessment.genuinely_reportable: Literal[False]`; `reportable()` always `False` (E13) |
| N1 / E7 `third_reviewer` only | `DisagreementPolicy` has one value; `recorded_discussion` is rejected |
| E1 one record per produced output | `ReviewSubject(item, output_id)`; `check_record_attachment` |
| E2 replicate as identity only | `ReviewItemKey.replicate`; `check_review_items` (≤ `run.replicates`); no replicate observations |
| E3 / E14 caller-declared review items with presence and status | `ReviewItem(key, expected_presence, output_status, produced_output, applicability_expectations, provenance="caller_declared")` |
| E4 unanimous N/A needs the same reason | `_same_judgment` compares applicability, value and reason |
| E5 adjudicator may choose any anchor or allowed N/A, with rationale | Adjudicator labels require a rationale; the adjudicator's own label becomes the result |
| E6 conflict register as a non-exported input with scope and coverage | `ReviewerConflictRegister.configuration`, `case_id`/`case_version`, `coverage`, `basis` |
| E8 in-place record change at `foundations.5` | `AdjudicationRecord` reshaped; no record or producer existed |
| E9 coverage separate from measurement; derived distributions `not_measured` until a trusted service exists | `UsefulnessCoverage` (diagnostic), `DimensionUsefulness` (measurement), `DistributionValue`, `derive_usefulness_distribution` |
| E10 expectation-grounded N/A | `RubricDimension.not_applicable_reasons: NotApplicableRule(reason, requires_expectation)`; rubric v2 reasons `pinned_case_expects_no_unknown_or_contested_facts` and `pinned_case_expects_no_follow_up`; none for evidence support or clarity |
| E12 exactly two designated primaries | `ReviewerRubric.min_independent_reviewers: Literal[2]`; extra or undesignated primary labels are rejected |
| E13 reportability fails closed | As above; approved in writing by the owner |
| Qualification 3: no duplicate items or double-counted outputs | `duplicate_review_item`, `duplicate_produced_output`, `duplicate_adjudication` |

**Deferred (E11 and others):** safety/privacy concern flag, blinding declaration, supersession-chain validation, deriving output slots and applicability expectations from pinned cases, item-set completeness from observations, replicate observations, the trusted evaluation-record service, more than two primaries or majority rules.

## Contract changes

**Rubric.** Dimensions may declare `not_applicable_reasons`, each bound to the expectation code a review item must carry. `min_independent_reviewers` must be 2 and `disagreement_policy` must be `third_reviewer`. Rubric v1 (both committed copies) still validates unchanged. Draft rubric v2 is `contracts/fixtures/evaluation-rubric-v2-v0.2.0-dev.json`.

**Review items.** `ReviewItemKey` (`run_id`, case id, version and hash, `replicate`, `output_slot`) exists whether or not an output was produced. A `ReviewItem` records `expected_presence` (`expected` / `not_expected`) and `output_status` (`produced` / `absent` / `generation_failed`); `produced_output` is required exactly when an output was produced. Presence categories: `produced_expected`, `produced_unexpected`, `missing`, `correctly_absent`, `generation_failed`. `check_review_items` checks uniqueness, run membership, the case pin against the manifest, and the replicate range.

**Adjudication record.** One record per produced output (`subject: {item, output_id}`), with two designated primaries and an optional designated adjudicator. Each raw label carries a `role` matching the asserted role (`evaluation_reviewer` or `evaluation_adjudicator`), and is either scored or N/A with a reason and rationale. `dimension_results` and `status` are **recomputed** from the raw labels and must match:

| Primary labels on a dimension | Result |
|---|---|
| Both present and identical (same score, or N/A with the same reason) | `scored` / `not_applicable`, derivation `unanimous`; an adjudicator label here is rejected |
| Both present and different, adjudicator label present | The adjudicator's label, derivation `adjudicator_resolution` |
| Both present and different, no adjudicator label | `disputed` |
| One missing | `unresolved`; an adjudicator label here is rejected |

Status: `adjudicated` if every dimension is resolved, otherwise `disputed` if any dimension is disputed, otherwise `unresolved`; a note is required unless adjudicated. `check_adjudication` adds rubric-pin, full dimension coverage, scale, allowed-reason and rationale rules. `check_record_attachment` requires the record to judge a produced output of a known item, and every N/A to cite an expectation the item carries.

**Reportability.** `assess_reportability(record, rubric, items, run, register)` returns `structurally_eligible` and `structural_reasons` (`adjudication_not_final` for any `disputed` or `unresolved` record, `rubric_not_approved`, `role_not_authenticated`, `recorder_not_authenticated`, `conflict_register_missing`, `conflict_register_scope_mismatch`, `conflict_register_incomplete`, `conflict_register_untrusted`, `conflicted_reviewer`), and always `genuinely_reportable: false` with `authority_reasons: ["no_trusted_evaluation_record_service"]`. The model cannot be constructed with `genuinely_reportable: true`.

**Usefulness value.** `DistributionValue` now holds `coverage` (diagnostic: item presence counts; reviewed and unreviewed produced items; genuinely reportable, structurally-eligible-only and structurally ineligible reviews; per-dimension resolution-state counts) and, only when `observed`, per-dimension `dimensions` built from genuinely reportable, finalized records: each holds only score anchors and justified N/A, never disputed or unresolved counts. Every count reconciles; nothing is imputed:

| Population | Representation |
|---|---|
| All scored 0 | Anchor `{value: 0, count: n}` (genuine zeros) |
| A dimension all N/A | No anchors, `not_applicable: n` |
| Every dimension N/A | `not_applicable` with `zero_denominator`, never 0 or 100 % |
| Disputed / unresolved | Counted in diagnostic coverage only; a record with either is never structurally eligible and never enters a measured dimension |
| Missing, failed, correctly absent | Coverage counts only |
| Produced but unreviewed or not genuinely reportable | Coverage counts only |

`derive_usefulness_distribution(definition, items, records, rubric, run, manifest, registers)` requires a manifest the run pins and applies `check_review_items` to every item (uniqueness, run, case version and hash, replicate range). It always returns `not_measured` with fully populated coverage. These checks establish structural consistency only, not item-set completeness, case-derived expectations or execution provenance.

## What is caller-declared or structural (not established)

- **Review items** — completeness, output slots and applicability expectations are caller-declared (`provenance: caller_declared` is the only value). Consistency with a pinned case identity does **not** show that slots or expectations were derived from that case; that needs expected-output fields and generation operations (PR-E / Slice 0) and trusted observations (PR-C / future service).
- **Reviewer identity, roles and independence** — `RecordAttribution` values, asserted roles and designations are claims. A caller-written `trusted_service_authenticated` is not authentication, a role assertion is not a role grant, and distinct principal IDs prove nothing.
- **Conflict registers** — `basis` and `coverage` are claims; a register cannot prove that a list of conflicts is complete.
- **Metric arithmetic and membership** — must eventually be derived by a trusted service from recorded observations.

## Python-only rules

JSON Schema cannot express: result derivation from raw labels, designated-primary membership, adjudicator authorization, full rubric coverage, allowed N/A reasons and their expectations, record attachment, conflict checks, and coverage reconciliation. These are enforced by the Pydantic models and pure check functions and documented in `test_json_schema_conformance.py`.

## Compatibility and versioning

- `CONTRACT_VERSION` moves to `0.2.0-dev.foundations.5`; all 36 schemas are regenerated. Only `adjudication-record`, `reviewer-rubric` and `run-comparison` bodies change; the other 33 change only `$id` and `x-contract-version` and are pinned by digest (`Pr4/Pr5/Pr6/Pr7CompatibilityTests`). No schema is added or removed.
- Both definitions fixtures (v1 and v2) are byte-identical; both copies of rubric v1 validate. No case fixture or manifest changes.
- `reportable()` changes signature and behaviour (always `False`), as approved (E13). `AdjudicationRecord` and `DistributionValue` change shape (E8, E9); no committed record or value used the old shapes.

## Failure-first evidence (baseline `089f52bd`)

Synthetic probes run on the unchanged baseline, each now covered by a regression test in `tests/test_adjudication.py` or `tests/test_evaluation_contracts.py`:

| Probe on `089f52bd` | Baseline result | Regression test |
|---|---|---|
| P1 one reviewer per dimension, 2 of 4 dimensions, contradictory final labels, typed-in trusted values | accepted; `reportable()` **True** | `test_every_rubric_dimension_needs_a_result`, `test_declared_results_must_follow_from_labels`, `test_forged_trusted_metadata_is_never_genuinely_reportable` |
| P2 primaries disagree, arbitrary final value, no adjudicator | accepted; **reportable** | `test_declared_results_must_follow_from_labels` |
| P3 third reviewer counted as an independent reviewer | `independent_reviewers == 3` | `test_exactly_two_designated_primaries` |
| P4 disputed record keeping an agreed dimension | rejected (agreed labels lost) | `test_disagreement_without_adjudicator_is_disputed_and_keeps_agreed_dimensions` |
| P5 justified N/A | rejected (not representable) | `test_unanimous_scores_and_unanimous_na`, `test_na_requires_the_matching_pinned_expectation` |
| P6 rubric with `recorded_discussion` | accepted | `test_cardinality_and_disagreement_policy_are_fixed` |
| P7 usefulness value with missing/failed counts | rejected (not representable) | `test_usefulness_distribution_populations_and_coverage`, `test_all_presence_categories_reconcile` |
| P8 records for different outputs of one case | indistinguishable apart from record id | `ReviewItemTests`, `test_records_attach_only_to_produced_outputs` |

## Review repairs (F1–F3)

Independent review of branch head `84303ad0` found three integrity gaps, each reproduced before repair and now covered by a named regression test:

| Finding | Before repair (`84303ad0`) | Repair | Regression test |
|---|---|---|---|
| F1 disputed or unresolved adjudications counted as structurally eligible | A disputed or unresolved record with every claim trusted-looking was `structurally_eligible: true`; diagnostic coverage counted it as eligible-only | `adjudication_not_final` structural reason | `test_disputed_or_unresolved_adjudication_is_not_structurally_eligible`, `test_only_finalized_records_count_as_structurally_eligible` |
| F2 measured usefulness accepted disputed and unresolved counts | `DimensionUsefulness` carried `disputed` and `unresolved`, and an observed value including them was accepted | Fields removed from the measurement; they remain in `UsefulnessCoverage.dimension_states` | `test_measurement_excludes_disputed_and_unresolved` |
| F3 derivation bypassed pinned item checks | An item with an unpinned case hash, or a replicate beyond the run's count, was accepted | `manifest` argument; must be pinned by the run; `check_review_items` applied | `test_derivation_reuses_pinned_item_checks` |

The F2 repair changes the `run-comparison` schema body again relative to `84303ad0`; relative to `main` the changed bodies remain exactly `adjudication-record`, `reviewer-rubric` and `run-comparison`.

## Test and mutation evidence

Recorded in [`contract-v0.2-freeze-readiness.md`](contract-v0.2-freeze-readiness.md#f4-pr-b-evidence-adjudication-integrity) and the PR description, from a fresh clone.

## Guarantees NOT established

Authentication of any reviewer, adjudicator or recorder; role grants; reviewer independence or blinding; completeness of any conflict register or review-item set; that slots and applicability expectations derive from pinned cases; that any output was produced by the named run; any usefulness measurement. No adjudication has occurred.

## Freeze status

**Not frozen.** This increment assigns no release-candidate or freeze status and approves no rubric or definition.
