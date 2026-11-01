# Slice 0 PR-S2 — Deterministic Evidence-Grounded Explanations: Design, Evidence and Limits

**Document ID:** RAP-SLICE0-PR-S2
**Scope:** PR-S2 only. It adds runtime-local structured findings, independent findings verification (L1), metadata-only projection-selection verification (L2) and a deterministic explanation to `baseline/rap_baseline`, plus tests.
**Authorization:** owner, 2026-11-01. The authorization covers:
- decisions D1–D4, approved, with a qualification to D4;
- D5 and D6, accepted;
- AR-1, implementation of the single PR in plan rev. 2.2 §10.

**No merge** is authorized. Also not authorized: contract changes, a Contract v0.2 freeze, PR-S3, Drupal integration, reviewer presentation, CI, deployment, real applicant data and paid inference.
**Design source:** RAP-SLICE0-PR-S2-PLAN-2026-10-31, revision 2.2. It is a shared packet document, not a repository file.
**Base:** `main` @ `dbeee9ab1e6e6b84144f16c5dc13f3e4ae3334f0` (merge of PR #13). Contract `0.2.0-dev.foundations.5` is **unchanged and not frozen**.
**Data:** synthetic only. Tests use test-local `*_s1_*` records. No contract fixture file, golden case or nominal held-out record is read.

## 1. Approved decisions

| ID | Decision | Where |
|---|---|---|
| D1 | Architecture B: runtime-local structured findings in `baseline/`, with independent findings verification (L1) and metadata-only projection-selection verification (L2). A portable findings contract is deferred to the PR-S3 contract revision. | `findings.py`, `findings_check.py`, `selection_check.py` |
| D2 | **SD-6 is superseded.** No explanation is derived from `EligibilityResult` citations alone. SD-6 was proposed in Slice 0 plan §4.4 and never approved. | `explanation.py` reads only the verified findings artifact |
| D3 | G12a–c stay open limitations of **result-level citations**. Findings account for the omitted material. `EligibilityResult`, SD-18, `REASON_CODES` and result identity are unchanged. | `rules.build_findings`; §4 |
| D4 | Every selected inferred claim and contested alternative in the admitted projection is accounted for, as a `non_decision_input` with evidence attribution. **Owner qualification:** selected evidence may come from another application, and it is attributed. Unrelated application records never become contributions. The existing projection and source-gating rules are unchanged. | §3; `test_findings.py` |
| D5 | Fixed, versioned templates (`explain-templates/1`); no generated prose | `explanation.py` |
| D6 | A selection, findings or explanation verification failure is `Errored` for the whole assessment. No partial `Assessed` is returned. | `engine.py` |

## 2. Execution order (PR-S1 phases P0–P11 unchanged)

| Phase | Step | Failure → | Authority calls |
|---|---|---|---|
| P0–P2 | PR-S1: request, targets, metadata projection | PR-S1 outcomes | 0 |
| **P2b** | `selection_check.verify_selection(supplied, targets, projected)`: L2 | `Errored(selection, projection_selection_mismatch)` | **0** |
| P3–P11 | PR-S1: organization guard, structure, source gate, phase-2 validation, `DecisionInputs`, **`rules.evaluate(inputs)`**, result, post-check, provenance | PR-S1 outcomes | PR-S1 |
| **P12** | `rules.build_findings(inputs, result.rule_outcomes)` → findings artifact | `Errored(findings, findings_construction_failed \| unexpected_exception)` | 0 |
| **P13** | `findings_check.verify_findings(findings, result, projected, provenance, ENGINE)`: L1 | `Errored(findings, findings_verification_failed)`; `detail` starts with the subcode | 0 |
| **P14** | `explanation.build_explanation(findings)`, with its self-check | `Errored(explanation, explanation_verification_failed \| unexpected_exception)` | 0 |

`rules.evaluate` and `rules.EVALUATORS` are unchanged, so every existing fault-injection point keeps its behaviour. `build_findings` does not go through `EVALUATORS` and does not call `claims.values_conflict`. P2b never fails on a correct projection, so PR-S1 refusal precedence is unchanged. A4 checks this byte for byte.

## 3. Findings model

There are three levels:
1. **Subject finding**: one per rule subject.
2. **Contribution**: one per selected claim or participation relevant to that subject.
3. **Evidence attribution**: one per evidence record of the input.

| Rule kind | Subjects | Relevant inputs |
|---|---|---|
| opportunity status | `opportunity_status`, attributed to `opportunity_ref` | none |
| participation | `program_participation(program_id)` | the candidate's participations in that program |
| availability | `weekly_hours`, with the 0 or 1 hours requirement | every selected availability claim |
| qualification | `no_mandatory_qualification`, or one `qualification(requirement, skill_code)` per requirement | every selected skill claim for that code, in any state |

**Statuses** form a closed vocabulary per kind. A code is *verification-backed* iff some declared claim for it has evidence with basis `independent_verification`.

**Determinative inputs `Det(s)`:**
- declared claims for decided statuses;
- non-declared claims for undetermined statuses;
- participations for recorded participation statuses;
- otherwise none.

**Subject roles:** `decisive`, `uncited_nonpass`, `uncited_satisfied`.

**Contribution roles:**
- `cited`;
- `uncited_material` (non-pass, in `Det`);
- `uncited_satisfying` (pass, in `Det`);
- `context` (not in `Det`).

**`rule_standing`:**
- `decision_input` for declared claims and participation records;
- `non_decision_input` for inferred, contested and unknown claims.

`rule_standing` is separate from `claim_state` and from evidence `basis`. `decision_input` means the contract lets the input decide a pass or fail. It does **not** mean true, verified or Drupal-authoritative.

**Evidence relations:**
- `support`;
- `alternative_support`, with the alternative index and its reading;
- `inference_input`: the producer `inferred_by` is recorded, and the evidence is never described as stating the inferred value;
- `authority_record`.

**`information_gap`** describes what is missing, never who is at fault:
- `no_source_backed_value`;
- `only_inferred_signal`;
- `conflicting_sources`: names no responsible party;
- `opportunity_requirement_unpublished`: asks nothing of the candidate;
- `no_participation_record`.

### Accounting invariant (I1–I11)

1. **I1 Rule alignment.** Rule keys, results and reason codes equal the result, in policy order.
2. **I2–I3 Subjects and requirements.** Subjects partition each rule's subjects and its requirements.
3. **I4 Inputs.** Each subject's contributions equal its relevant inputs exactly. Their union equals every selected claim and participation.
4. **I5 Evidence.** Each contribution's attributions equal its evidence ids, with the exact basis, source reference and field path. Their union equals the admitted evidence.
5. **I6 Citations.** Cited contributions equal the result's citations.
6. **I7 Exact precedence.** The **exact** SD-4 reason code and **exact** SD-5 citation sets are recomputed and must be equal.
7. **I8 Roles.** Roles, standing, relations and gaps are recomputed.
8. **I9 Scope.** Every id resolves in the admitted projection, in the assessed organization, candidate and opportunity.
9. **I10 Closure.** The findings' source references **equal** the gated set.
10. **I11 Identity.** As in §5.

## 4. G12 accounting (executed)

| Case | Result citations (unchanged) | Findings |
|---|---|---|
| C02 **G12a** | `S1-SKILL-004` fail `…by_verification`, citing spreadsheets only | python `contradicted_declared`, `uncited_nonpass`; its claim is `uncited_material` |
| C03 **G12b** (not evidenced) | same outcome, same output digest | python `not_evidenced`, `uncited_nonpass`, gap `no_source_backed_value` |
| C04 **G12b** (contested) | fail `…by_declaration`, citing spreadsheets | python `contested`, `uncited_nonpass`. The contested claim is `uncited_material` and `non_decision_input`, with both alternatives attributed. |
| C05 **G12b** (inferred) | fail `…by_declaration` | python `only_inferred`, `uncited_nonpass`, with an `inference_input` attribution |
| C06 **G12c** | fail `…by_verification`, citing the verification claim | python `contradicted_verified`, decisive. The statement-backed claim is `uncited_material`. |
| C09 G12a+c | same output digest as C02 | both omissions surfaced |
| C10 control | both codes cited | no uncited material |

C02, C03 and C09 have equal `rule_outcomes` and an equal output digest, but different input fingerprints and result ids. Their findings content digests and explanations differ pairwise (ID5).

## 5. Identity

| Object | Digest or id | Excludes |
|---|---|---|
| Findings content | `content_digest` over `rap-baseline.findings-content/1`, `findings/1` | result id, fingerprint, output digest, `as_of`, principal, authority answers, producer id |
| Findings artifact | `findings_id = "findings_" + hex40(sha256(result_id, content_digest))` | principal, `checked_at` |
| Explanation content | `explanation_content_digest` over statements, typed params, limitations and `rendered_body`, where the body holds `⟦as_of⟧` exactly once | every id and timestamp |
| Explanation artifact | `explanation_id` over (`findings_id`, content digest, template version); `rendered_text` is the body with the slot filled from the UTC `as_of`; `rendered_text_digest` | principal |

**Unchanged from PR-S1:**
- the input fingerprint;
- `evaluated_by`;
- `sd4-precedence/1` and `sd5-citations/1`;
- the result id, output digest and provenance.

**Version pinning.** Artifact byte determinism holds only under these pinned versions:
- `rap-baseline.findings/0.1.0`;
- `rap-baseline.explanation/0.1.0`;
- `findings/1`;
- `explain-templates/1`.

Any other version is `Errored`, never a silently different artifact.

## 6. Verification boundary

**L1 (`findings_check`)** receives the findings artifact, the result, the **admitted projection**, the engine-held P11 provenance and the engine-held `EngineIdentity`. Its steps:
- **Step 1.** It recomputes the input fingerprint, output digest and result id with `identity`. It requires the provenance to agree, and only then compares the findings header.
- **Step 2.** It recomputes statuses and the exact SD-4/SD-5 outcome.
- **Steps 3–5.** Scope, closure and accounting.

It imports only `rap_contracts`, `identity` and `findings`, and it makes no authority call. Its independence is code-level: the same author wrote the producer and the verifier. Its discriminating power is demonstrated by mutations (§8), not assumed.

**L2 (`selection_check`)** reads only the metadata inventory in `selection_check.INVENTORY`. That inventory includes application `target.opportunity_id` and `target.program_id`, opportunity and policy programs, rule programs, requirement and claim vocabulary pins and evidence keys. L2 re-derives the selection with its own code, without calling `inputs.project`. It requires each projected collection to hold exactly the expected records, as the **same objects**, in supplied order.

| Level | Statement | Established by | Tier |
|---|---|---|---|
| L1 | Findings account for every decision-relevant record of the admitted projection | P13 | engineering test |
| L2 | The projection equals the selection rules applied to the supplied context | P2b | engineering test |
| L3 | The supplied context contains every relevant Drupal record | not verifiable here; carried as `context_completeness_asserted_by_adapter` | T4 only |

**Gaps closed (observed at the base commit; they are not defects in correct code):**

| Fault | Behaviour at `dbeee9ab` | With PR-S2 |
|---|---|---|
| N1–N3: supportable but precedence- or citation-incorrect outcome | `Assessed` | `Errored` |
| N5: an uncited input's source left out of the gate | `Assessed` | `Errored` via I10 |
| N8a, N8e, N8f, N8g: projection omissions or additions | silently `Assessed` | `Errored(selection)` with 0 authority calls |
| N8b–N8d | misreported as data refusals | `Errored(selection)` with 0 authority calls |

## 7. Explanation

`explain-templates/1` maps every reachable key. The key families are:
- **decision**: 3 keys;
- **rule**: 3 keys;
- **subject** (kind, status, role): 25 keys;
- **contribution** (role, standing): 7 keys;
- **attribution** (relation, basis): 7 keys;
- **gap**: 5 keys;
- **limitation**: 6 keys.

Every other combination is listed in `UNREACHABLE`. The coverage test requires `TEMPLATES` and `UNREACHABLE` to partition each family's full product, and the case matrix plus sweep to reach every mapped key.

Ids, field paths and source locators are inserted as quoted, escaped data, never as templates. Every explanation carries these limitations:
- `opportunity_and_policy_scoped`;
- `context_completeness_asserted_by_adapter`;
- `synthetic_source_authority`;
- `not_authorized_for_presentation`;
- `recheck_sources_before_action`.

It also carries `non_decision_inputs_present` when relevant. Skill codes are rendered only (O3). No opportunity-subject evidence is cited and no opportunity text is quoted (O5). `Refused` and `Errored` carry no findings and no explanation.

## 8. Test evidence

All runs were manual, from a fresh checkout, on Python 3.13.18. No CI is configured.

| Suite | Dev (`requirements-dev.txt`: pydantic 2.13.5, jsonschema 4.26.0) | Runtime-only (`requirements.txt`: pydantic 2.13.5) |
|---|---|---|
| contracts | 464 pass | 464 pass, 17 skipped |
| `schema_export --check` | drift NONE (36 schemas) | drift NONE |
| baseline | **220 pass** | **220 pass** |

**Baseline test breakdown.** The 115 PR-S1 tests all still pass, run by their exact ids. The only change to them is the approved AST-scan extension in `test_gate_ordering.py`.

| Module | Tests | Change |
|---|---|---|
| `test_gate_ordering.py` | 22 | 1 added |
| `test_label_blindness.py` | 13 | 2 added |
| `test_g12_matrix.py` | 27 | new |
| `test_findings_check.py` | 17 | new |
| `test_selection_check.py` | 15 | new |
| `test_explanation.py` | 24 | new (10 added by review repair R2) |
| `test_findings.py` | 8 | new |
| `test_mutation_harness.py` | 11 | new (review repair R1) |

**Cross-commit comparison (A4).** `tests/tools/dump_scenarios.py` was run against a checkout of `dbeee9ab` and against this branch. It covers 30 scenarios: C01–C19, an 8-scenario candidate × opportunity sweep, and three C02 identity variants. Result bytes, provenance bytes and refusal stage, code, detail and authority-call counts are **identical**: the diff is empty. Provenance byte equality assumes equivalent recorded authority answers; the synthetic authority returns fixed `checked_at` and `checked_by` values.

**Failure-first mutations.** `tests/tools/mutations.py` applies each mutation to a scratch copy and runs the full suite. A mutation counts as caught only under these conditions (review repair R1):
- the suite completed;
- it ran exactly the 220 tests the loader discovers in the unmutated copy;
- it reported genuine failure blocks consistent with its summary, with no module import failure;
- every listed discriminating test is among the failures.

A runner timeout or crash, a missing or ambiguous test count, a resized run, an import failure or a missing anchor is a **harness error**, never a detection.

Two controls run first and are classified as required:
- a no-op edit → not caught;
- an import-breaking edit → harness error (it ran 26 of 220 tests).

All **46** mutations are caught, with 0 harness errors and 0 not caught. The **PR-S2 count** column is test failures + test errors (failing test methods). Subtests are included, and failures and errors are reported separately since R1. The PR-S1 column is the total recorded in the PR-S1 document. All counts are from the 220-test suite.

| # | Mutation | PR-S1 count | PR-S2 count |
|---|---|---|---|
| M01 | P6 before the gate | 5 (4) | 5 + 0 (4) |
| M02 | gate failures ignored | 62 (5) | 63 + 0 (6) |
| M03 | contested-alternative evidence not gated | 29 (19) | 28 + 19 (32) |
| M04 | inferred evidence not gated | 11 (5) | 14 + 12 (14) |
| M05 | P6 on the full context | 4 (4) | 4 + 0 (4) |
| M06 | projection organization guard removed | 6 (6) | 7 + 0 (7) |
| M07 | P1 organization checks removed | 1 (1) | 2 + 0 (2) |
| M08 | result id omits the fingerprint | 13 (2) | 29 + 0 (4) |
| M09 | `as_of` not normalized | 2 (2) | 2 + 0 (2) |
| M10 | nested `captured_at` not normalized | 2 (2) | 2 + 0 (2) |
| M11 | principal in the fingerprint | 1 (1) | 107 + 129 (116) |
| M12 | declaration preferred over verification | 2 (2) | 28 + 36 (37) |
| M13 | full mixed-basis lacks set cited | 1 (1) | 28 + 36 (37) |
| M14 | `not_evidenced` before `only_inferred` | 2 (2) | 1 + 0 (1) |
| M15 | inferred treated as declared | 8 (6) | 13 + 18 (17) |
| M16 | `not_declared` before `contested` | 2 (2) | 3 + 0 (3) |
| M17 | unpublished hours checked late | 1 (1) | 1 + 0 (1) |
| M18 | post-check removed | 6 (6) | 7 + 1 (8) |
| M19 | provenance subset check removed | 2 (2) | 2 + 0 (2) |
| M20 | deterministic ordering removed | 19 (9) | 59 + 38 (64) |
| M21 | gate checks only opportunity and policy | 136 (62) | 185 + 129 (128) |
| M22 | conflicting participation evaluated | 1 (1) | 1 + 0 (1) |
| M23 | P10 exceptions escape | 2 (2) | 2 + 0 (2) |
| M24 | P11 exceptions escape | 2 (2) | 2 + 0 (2) |
| M25 | builders open a contract file | 1 (1) | 2 + 0 (2) |
| M26 | drop `uncited_material` | — | 16 + 51 (40) |
| M27 | merge G12c claims | — | 57 + 56 (73) |
| M28 | omit alternative index | — | 21 + 19 (31) |
| M29 | inferred relation as `support` | — | 15 + 18 (18) |
| M30 | L1 imports producer classification | — | 1 + 0 (1) |
| M31 | L1 reads the supplied context | — | 107 + 129 (116) |
| **M32** | **I10 weakened to the result-dependency subset (N5 discriminates)** | — | 3 + 0 (3) |
| M33 | findings on `Refused` | — | 4 + 0 (1) |
| M34 | engine identity changed | — | 15 + 0 (1) |
| M35 | `as_of` in the content digest | — | 107 + 129 (116) |
| M36 | gap mapping swapped | — | 24 + 26 (34) |
| M37 | template interpolates `field_path` | — | 1 + 0 (1) |
| M38 | L2 removed | — | 15 + 0 (10) |
| M39 | I7 relaxed to supportability (N1–N3 discriminate) | — | 3 + 0 (3) |
| M40 | findings routed through `EVALUATORS` | — | 1 + 0 (1) |
| M41 | `as_of` rendered into the body | — | 97 + 129 (107) |
| M42 | L1 trusts provenance without recomputing it (N10 discriminates) | — | 2 + 0 (1) |
| M43 | L2 compares ids, not identity (N8h discriminates) | — | 3 + 0 (2) |
| M44 | L2 ignores application targets | — | 26 + 5 (19) |
| M45 | explanation drops `uncited_material` statements and its completeness self-check (R2) | — | 16 + 0 (11) |
| M46 | P14 completeness self-check removed (R2; omission tests discriminate) | — | 5 + 0 (5) |

**Earlier mutation run superseded.** The first PR #14 run (head `2ee2594`) had two defects: it could count an incomplete run, or a run with no test count, as caught. Its M24 edit was such a case: it broke module import, and only 15 tests ran. **That run is superseded by this table.**

**Notes on the PR-S1 rows:**
- The PR-S1 mutation scripts were not committed, so M01–M25 are re-created from their descriptions. Exact counts can differ for that reason alone.
- Higher counts mostly reflect the new L1, matrix and identity tests catching the same fault.
- **M14 is lower** (1 vs 2). In the re-created mutation, only `test_q7_inferred_only_beats_not_evidenced` combines an inferred-only code with an unevidenced code. No PR-S2 matrix case does. The count is non-zero, and the fault is caught.
- **M11** is re-created as a corrupted fingerprint string. L1 then rejects every assessment, which explains its large count.
- **M24** in the first run removed the only `except` clause, which is a syntax error. It is now re-created by narrowing that clause, and it is caught by the same two tests (from PR-S1's own review repair R2) that PR-S1 recorded.

## 9. Deviations from plan rev. 2.2

1. **L1 receives the engine-held `EngineIdentity`.** The plan rebuilt it from the provenance's version fields. PR-S1 provenance records `rule_table_version` and `citation_policy_version` from `rules` constants, while the input fingerprint covers `engine.ENGINE`. The existing PR-S1 test `test_engine_identity_is_part_of_the_fingerprint` patches only the latter. With the plan's construction, L1 rejected that test's assessments. L1 still recomputes the fingerprint, digest and id; only the source of the engine identity changed.

   This also records a **latent PR-S1 provenance inconsistency**: those provenance fields are not bound to the identity actually fingerprinted. P11 is left unchanged, as required. It is **deferred technical debt TD-1** (§11).
2. **Template keys** are split into contribution (role, standing) and attribution (relation, basis), giving 7 + 7 reachable keys. A contribution can carry several attributions with different bases (C07), so one key per contribution could not name them all.
3. **Two supporting test-only files beyond the manifest:**
   - `tests/g12_cases.py` holds the C01–C19 definitions, shared by the matrix tests and the dump tool;
   - `tests/tools/mutations.py` makes the failure-first evidence reproducible.
4. **Additional negative tests:**
   - N3b: citing both G12c claims is rejected at P10;
   - extra L2 collections: requirement, profile, program, substituted evidence, reordering and substituted policy;
   - a demonstration that L1's I10 also catches a *partial* projection omission. A *coherent* omission (record and evidence removed together) is caught only by L2.

5. **Review repairs (2026-11-01, PR #14 review):**
   - **R1, mutation-harness reliability:** the classification rules and controls in §8, plus the unit tests in `tests/test_mutation_harness.py`.
   - **R2, explanation completeness:** the P14 self-check now requires a one-to-one, in-order correspondence between the verified findings and the explanation, covering every rule, subject, applicable information gap, contribution and evidence attribution, each with its reference and identifying params. It also requires one rendered line per statement and limitations that match the findings. Any omission or wrong reference is `Errored(explanation, explanation_verification_failed)`.
   - **R2 tests:** an independent test-side checker covers the full matrix and sweep, with C06/G12c checked explicitly. Negative tests cover an omitted uncited contribution, gap, attribution, rule and rendered line, and a wrong reference. Mutations M45–M46 also cover it.

## 10. Guarantees NOT established

1. **G12 at the result level.** `EligibilityResult` citations remain non-exhaustive for a failing qualification. Only explanations are exhaustive.
2. **Drupal authorization, currentness and completeness (L3).** The source authority is synthetic. Absence-based findings assume a complete supplied context. These are **T4 only**.
3. **Presentation.** Explanations are internal artifacts. Per-viewer re-authorization, currentness re-checks before action, reviewer UI and Drupal mapping are not implemented.
4. **Evaluation evidence.** There is no evaluation run, case observation, metric, accuracy, reviewer usefulness, or T3/T4 evidence. PR-S3 is not authorized. Findings are runtime-local and have no portable contract, so PR-S3 will need a contract revision.
5. **O3 and O5** remain open. Vocabularies are ungated (codes only), and no opportunity-subject evidence is cited.
6. **Verifier independence** is code-level and single-author. It is not organizational independence.
7. **Fairness or legal appropriateness** of the fictional rules and of the template wording.

## 11. Deferred technical debt

| ID | Item | Why deferred | Proposed resolution (needs separate authorization) |
|---|---|---|---|
| **TD-1** | **PR-S1 provenance version fields are not bound to the fingerprinted engine identity.** `AssessmentProvenance.rule_table_version` and `citation_policy_version` come from `rules.RULE_TABLE_VERSION` and `rules.CITATION_POLICY_VERSION`, while the input fingerprint and result id cover `engine.ENGINE`. They agree in normal operation, but nothing enforces it. PR-S1's `test_engine_identity_is_part_of_the_fingerprint` changes only `ENGINE`, and provenance then states versions that were not fingerprinted. L1 therefore takes the engine-held `EngineIdentity` (deviation 1) and still recomputes the fingerprint, output digest and result id. It does **not** check the provenance version fields. | Fixing it changes P11 (PR-S1 provenance semantics). PR-S2 is required to leave P0–P11, result identity and contracts unchanged. | In a separately authorized PR, record the provenance versions from the same `EngineIdentity` the fingerprint covers, or assert equality at P11. Then let L1 also compare the provenance version fields. Expected impact: no result-id change in normal operation; the PR-S1 identity test would need its expectation restated. |
