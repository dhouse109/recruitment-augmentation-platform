# F3 — Golden Scenario Separation for g002 and g008: Decision Record

**Document ID:** RAP-F3-2026-11-04
**Authorization:** AR-F3 (owner, 2026-11-04), implementing RAP-F3-PLAN-2026-11-04 **revision 1.1** (decisions
F3-D1 to F3-D5), plus **owner scope amendment 1** (2026-11-04)
**Base:** `main` @ `653642e9d6e87b0a773cf5d577ba8bb43754f1fe` (PR #19 merged; no open PRs at start)
**Contract:** `0.2.0-dev.foundations.6`, proposed, **not frozen**; **unchanged** by F3 (no model, schema or version change)
**Data:** synthetic only. The nominal held-out case fixture is never read by the runner.

> F3 separates two golden cases that previously executed the identical step. It changes no label's review status:
> both revised labels are **proposed** and **not adjudicated**. F3 only makes the owner's B3 review of those two
> labels possible; it does not perform it.

## 1. Problem

In golden **v1**, `evalcase_g002` and `evalcase_g008` had byte-identical scopes, steps and expectations: one target
`eligibility_support` step on the shared label `eligibility_b_data` (candidate B × `opportunity_demo_data`), with
**both** availability (`availability_not_declared`) and qualification (`qualification_contested`) unknown. Neither
case isolated its titled behavior, and the runner recorded them as one distinct assessment.

## 2. Decisions applied

| ID | Decision |
|---|---|
| F3-A / F3-D1 | Minimal isolation through a **self-contained 26-case golden v2**: 24 cases are byte-identical copies of golden v1; only g002 and g008 are revised (version 2). Golden v1 is preserved unchanged. |
| F3-H / F3-D2 | Option **P1**: a new definitions file holds draft metric definitions **v1** (byte-equal copy), draft safety-gate policy **v3** (pins golden v2; otherwise identical to policy v1) and reviewer rubric v1 (byte-equal copy). Definitions v1/v2 are unchanged; draft metrics v2 remain non-default. |
| F3-D3 | Runner rule **B1-a, L1–L5**: the only newly admitted `include_records` exception is a case-local `eligibility_results` label that a step of the same case names. It is a reference only (§5). |
| F3-D4 | g002 v2 = B × web; g008 v2 = new synthetic candidate G × data (§3). |
| F3-D5 | The runner migrates to golden v2 only. v1 runs are reproducible only at their recorded commit and are **not comparable** with v2 runs (§7). |
| Recorded choice | `contract_version` `0.2.0-dev.foundations.6` in the golden v2 document, its manifest and the new definitions file (§4). |
| VB-1–VB-6 | Contract-level held-out partition/leakage tests are a bounded verification activity (§6). |
| Amendment 1 | `evaluation/tests/test_scope.py` and `evaluation/tests/test_negative.py` added to the manifest (§8). |

## 3. Scenarios

| Case | Key | Non-pass rules | Decision | Label (case-local) |
|---|---|---|---|---|
| g002 v2 | `candidate_demo_b` × `opportunity_demo_web` × `policy_demo_pilot` v1 | PILOT-AVAIL-003 `unknown / availability_not_declared` | `needs_information` | `eligibility_b_web` |
| g008 v2 | `candidate_demo_g` × `opportunity_demo_data` × `policy_demo_pilot` v1 | PILOT-SKILL-004 `unknown / qualification_contested` | `needs_information` | `eligibility_g_data` |

**g002 v2** adds no source record. The web opportunity publishes a 10 h requirement and **no** mandatory
qualification, so the qualification rule passes (`no_mandatory_qualification`) and B's contested python claim is
never selected; B's availability claim is `unknown`.

**g008 v2** uses a new wholly synthetic candidate with a declared 15 h availability (the requirement is 12 h; 15
is deliberately not the boundary) and one contested python claim. Its two alternatives (`has`, `lacks`) are **two
candidate statements from separate fields (`skills.python`, `answers.screening_python`) of one profile revision**
(`candidate_profile/5007@701`), not independent sources. This matches PILOT-T010 ("Candidate profile has
conflicting qualification evidence"). No application was added: none is structurally required, and adding one
merely to create a second source was explicitly declined.

### Case-local record inventory (11 records)

| Kind | Records |
|---|---|
| `candidates` | `candidate_demo_g` (identity source fixture `user/9007`) |
| `profiles` | `profile_demo_g` (`candidate_profile/5007@701`) — required: `candidate_statement` evidence must come from the candidate's own profile or application in the record set |
| `evidence` | `evidence_g_profile_hours`, `evidence_g_profile_python`, `evidence_g_profile_screening` (candidate statements, `5007@701`); `evidence_g_enrollment` (authority record, `program_enrollment/6007@607`) |
| `claims` | `claim_g_availability` (declared, 15 h); `claim_g_python` (contested: `has` / `lacks`) |
| `participations` | `participation_g` (`program_demo_001`, confirmed) |
| `eligibility_results` | `eligibility_g_data` (G-owned label); `eligibility_b_web` (B-owned label) |

That is 9 non-label G records + 1 G label + 1 B-web label = **11**. `evalcase_g008.scope.include_records` lists
the 10 G-owned records; `evalcase_g002.scope.include_records` lists `eligibility_b_web`.

### Case metadata

Both cases keep their `id`, `legacy_label` (`EVAL-G002`, `EVAL-G008`), `origin: seed_proposal`, pilot test
references (PILOT-T002, PILOT-T010), `review_status: proposed` and `adjudication_status: not_adjudicated`. The
`origin_ref` reads "RAP-EVAL-001 v0.1.0 EVAL-G00x; F3 revision of v1 (RAP-F3-PLAN-2026-11-04)", and
`authored_by` is `ai-assisted-authoring/0.2.0-dev.foundations.6`. The g008 title no longer says "sources".

## 4. Versions and pins

| Item | Value |
|---|---|
| Golden v2 manifest | `evalset_golden` v2, root `sha256:3bd060439f58ce4d28e5272d5169135fc93526d5cec8a78de3a8dc4dfbd4d25e` |
| Golden v2 `case_records_sha256` | `sha256:78b9bd2cb851057170a18216e15178002184d425d5ed87d4b041b3370c237d04` |
| g002 v2 case hash | `sha256:dbacee10babc7ef14532473cd6c05517cc6d9eeff57469f0f7b6b00f1609b3f1` |
| g008 v2 case hash | `sha256:e9f267192ff7d509258a252ff6a9c1d82198764772379087e8f9416b0fa19efe` |
| Other 24 case pins | identical to golden v1 |
| Layer pins | identical (3 base layers) |
| Draft safety-gate policy | `evaldefs_safety_gate` v3 → `evaldefs_metrics` v1 and `evalset_golden` v2; held-out pin unchanged (`evalset_nominal_held_out` v1) |
| Golden v1 / policy v1 / policy v2 | unchanged; v1 root `sha256:5baf87b7…` |

**`contract_version`.** The golden v2 document, its manifest and the new definitions file record
`0.2.0-dev.foundations.6`, the version the content was authored and validated against (precedent: rubric v2
records its authoring version `.foundations.5`). The field is outside the manifest root and every case hash, so it
does not affect the 24 unchanged pins; it does enter the runner's specification identity. Historical files keep
`.foundations.4`. Tests assert these literals (C13, E13), not the installed version, so a future contract bump
cannot silently imply that v2 was re-authored.

**Policy versions are not a linear supersession.** Policy v2 pins metrics v2 and golden v1; policy v3 pins metrics
v1 and golden v2. Nothing is approved; every status stays `draft`.

## 5. Runner changes (runner 0.2.0)

- **A2:** the golden file is `evaluation-golden-v2-v0.2.0-dev.json` and the definitions file is
  `evaluation-definitions-golden-v2-v0.2.0-dev.json`. Still exactly five allowed files; golden v1, definitions v1/v2
  and the held-out case file are never read.
- **A4:** `POLICY_PIN` is `evaldefs_safety_gate` v3; `METRICS_PIN` stays v1 (decision E7 unchanged).
- **Case-local labels (A5–A7):**

| Rule | Requirement | Abort |
|---|---|---|
| L1 | An included id resolves to exactly one case record | `A5 include_record_unresolvable` |
| L2 | Its owner is in the case's scope | `A5 include_record_out_of_scope` |
| L3 | An included label is the `eligibility_result_id` of an `eligibility_support` step of the same case | `A6 include_label_not_step_referenced` |
| L4 | An included label is a reference only: never constructed, never in the eligibility context, never given to the engine; only `LABEL_KEY_FIELDS` are read | (tests and mutations R36, R37) |
| L5 | A step label resolved from `case_records` is declared in the case's `include_records` | `A7 label_not_declared_in_scope` |

  Chunks, recommendations and verifications in `include_records` are still refused
  (`A6 include_record_kind_not_supported`).
- **Coverage** is `rap-evaluation.coverage/2`: the obsolete `f3_shared_scenario` field is removed and a statement
  records that v1 runs are not comparable. `SELECTION_VERSION` stays 1 (case ids and classes unchanged; case
  versions are bound by the manifest pin).
- `RUNNER_VERSION` is `0.2.0` (`executed_by` and the specification identity change).

## 6. Held-out guarantees and verification boundary

**Runner enforcement (every run):**

| Id | Guarantee | Scope |
|---|---|---|
| RH-1 | The nominal held-out case file is never opened (A2 allowlist; separation tests; the mutation harness copy excludes it) | Whole runner |
| RH-2 | No held-out-owned record is constructed, given to the engine or validator, or included | Records the runner can see: base layers and golden case records |
| RH-3 | The **S1** output scan rejects held-out-owned identifiers in artifacts | **Only** identifiers derived from runner-visible held-out-owned records (currently candidates D and E and their base-layer records) |
| RH-4 | No information flows from the held-out case file into runner outputs | Follows from RH-1 |

S1 does **not** cover identifiers that exist only in the held-out case file (held-out case ids, legacy labels,
held-out case records such as candidate F's, held-out prose); the runner never sees them. A coincidental collision
between new golden content and such identifiers is detectable only by contract-level tests.

**Contract-level partition and leakage tests** (`contracts/tests/test_dataset_partition.py` and
`contracts/tests/test_golden_v2_f3.py` C8–C11) read the **nominal, exposed** held-out fixture at test time. Running
them is a **bounded verification activity** (VB-1–VB-6): read-only; pass/fail output (on failure, only the colliding
identifiers); not an input to scenario design, label authoring, selection or tuning; no runner access; the held-out
set stays nominal, exposed and not custodied. They are evidence about committed text, not custody, blinding or
confidentiality proof.

## 7. Historical reproducibility and non-comparability

`verify-repeat` re-admits each run directory against the **current** fixtures, so the current runner refuses a
golden-v1 run with a binding failure `P1` (exit 4) and **no verdict** — it is not a `NOT_COMPARABLE` verdict.

- **E11a** (`evaluation/tests/test_f3_scenarios.py`, always runs): a v2 run repinned to golden v1 is rejected
  (`BindingFailure` P1; CLI exit 4, no verdict). Narrow claim: it does not exercise historical runner code.
- **E11b** (`evaluation/tests/tools/historical_v1_check.py`, scripted): `git archive 653642e9` with
  `:(exclude)*/evaluation-nominal-held-out-*` (the held-out case fixture is never materialized; the
  `held-out-gate-attestation` schema is kept); the historical runner 0.1.0 produces two genuine runs and
  re-verifies them as **PASS**; the current runner 0.2.0 rejects them, paired with each other and paired with a
  current run (exit 4, `binding_p1`, no verdict). Exit 3 = SKIPPED (commit not in local history), which is not a
  pass.

Historical runs remain reproducible only at their recorded commit.

## 8. Owner scope amendment 1 (2026-11-04)

Revision 1.1 §5 omitted two existing test files coupled to the F3 data. Work stopped at the STOP condition; the
owner approved option (a):

| File | Change |
|---|---|
| `evaluation/tests/test_scope.py` | `candidate_demo_g` added to the `GOLDEN` constant and to the assertion that golden candidates are not held-out identifiers |
| `evaluation/tests/test_negative.py` | The X9 negative `test_steps_sharing_a_key_with_different_bytes` retargeted from `evalcase_g008/s1` to `evalcase_g025/s2` (the remaining shared key, A × ops); the stale shared-key comment in the X3 forged-fingerprint test corrected. No assertion removed or weakened; R17 (whose only discriminating test is that X3 test) remains CAUGHT. |

## 9. Evidence summary

| Suite / check | Result |
|---|---|
| Contract suite (dev requirements) | 506 tests OK (482 at base + 24 new in `test_golden_v2_f3.py`) |
| Baseline suite | 236 tests OK (unchanged) |
| Runner suite | 200 tests OK (175 at base + 25 new in `test_f3_scenarios.py`) |
| Schema drift | NONE (36 schemas) |
| Mutations | R01–R39, all CAUGHT required (R35–R39 new) |
| E11b | PASS |

Exact commands, environments and final-commit results are recorded in the PR.

## 10. Limitations

- Labels are **proposed and unadjudicated**; agreement with them is not correctness (F4/B3 unchanged).
- The source authority is a fixture mock (not T4).
- The nominal held-out set is exposed and not custodied.
- g003 s1 and g025 s2 still share A × ops (by design; not F3).
- G12a–c, TD-1, O3–O5, PR-C to PR-F, the root `README.md` and contract freeze are outside F3.
- Observation, not changed: the mutation harness's `*held-out*` ignore pattern also drops the
  `held-out-gate-attestation` schema from its scratch copy; the runner suite does not need it.
