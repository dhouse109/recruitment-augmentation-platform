# Contract v0.2 Recommendation Verification and Human Review Foundations — Traceability, Evidence and Limits

**Document ID:** RAP-CONTRACT-002-R  
**Contract version:** `0.2.0-dev.foundations.3` — **partial development version; proposed; NOT frozen**  
**PR:** #6 (Recommendation Verification and Human Review Foundations)  
**Base:** `main` @ `d780ac1946a2c15bf698a1d9d5af02fbe470c976` (merge of PR #5)  
**Scope:** D-004.03, D-004.04, D-004.08, D-004.09 only  
**Code:** [`contracts/`](../../contracts/README.md) — `rap_contracts/recommendation.py`, `rap_contracts/review.py`; test double `tests/review_double.py`  
**Prior increments:** [`contract-v0.2-foundations.md`](contract-v0.2-foundations.md), [`contract-v0.2-eligibility-evidence.md`](contract-v0.2-eligibility-evidence.md)

This PR contains **no** Drupal review-write service, authentication infrastructure, persistence, production audit storage, UI, recommendation or eligibility engine, agents, retrieval infrastructure, CI change or paid inference. **Approval for follow-up authorizes investigation or outreach planning only.** No contract action represents placement, hiring, admission, an offer or rejection, and no action sends communications.

## Vocabulary precedence

At the time of PR #6, `domain.md` and the pilot spec (both *proposed*) listed `reject_suggestion`. Accepted **ADR-0004 D-004.04** uses `dismiss_suggestion`, and the ADR governs:

- `ReviewAction` contains only `approve_for_follow_up`, `request_information` and `dismiss_suggestion`.
- `reject_suggestion` is rejected by both validators.
- The older documents were not edited in this PR.

*Editorial note (2026-10-29, F1):* `domain.md`, the pilot spec and PROJECT-FOUNDATION were later brought into line with ADR-0004 in the F1 documentation sync. The discrepancy report above is kept as historical record. The reference contracts are unchanged and still reject `reject_suggestion` (see the test evidence below).

## Owner decisions applied (2026-10-28)

| # | Decision | Encoded as |
|---|---|---|
| 1 | Application lineage for pilot follow-up, without a universal prerequisite | `Recommendation.context: ApplicationContext` (an explicit binding with `kind: "application"`, the application id and its exact `SourceReference`). The pilot gate is `PILOT_REVIEWABLE_CONTEXT_KINDS = {"application"}` plus `check_application_context`, which requires an application that is the candidate's own, in the same org, **submitted**, at the pinned version, and targeting the opportunity or its program. **No other context kind is representable**, so discovery without an application cannot silently become reviewable. `EligibilityResult` is unchanged |
| 2 | ADR-0004 actions only; approve = follow-up only; terminal states; exhaustive transitions | `ReviewAction` (3 values); `TRANSITIONS` (12 legal pairs); terminal `approved_for_follow_up`/`dismissed`/`obsolete`; `TransitionTests.test_exhaustive_transition_matrix` covers all 7 × 6 pairs |
| 3 | Verification = substantive checks; a different component id is necessary, not sufficient | `VerificationResult` has 7 required check codes, an outcome derived from them, and recorded source checks, with no score/confidence/agreement fields. `accept_verification` requires a distinct verifier **and** exact dependency coverage **and** `passed` **and** recomputes `check_recommendation`. Anything not accepted → `escalated` |
| 4 | Approval fully revalidated live; dismissal and info requests safe without freshness | Approve: verification acceptance + `check_recommendation` (application status, eligibility, policy pin, citations) + a live current-and-allowed check of **every** dependency for the reviewer. `request_information` / `dismiss_suggestion`: authenticated + authorized only; no source reads, no outbound effects, no claim changes |
| E1 | Reviewer principal entirely server-derived | Commands have no identity/role/`actor_type`/org fields (`extra=forbid`). `AuthenticatedPrincipal` / `ReviewerGrant` come only from `Authenticator` / `Authorizer` |
| E2 | Separate pure evaluation from I/O | `evaluate_review` / `evaluate_correction` are pure. Authentication, authorization, authority calls (`collect_live_checks`) and storage are in the boundary (protocols; test double) |
| E3 | Fingerprint binds the complete semantic command | `review_fingerprint`: command (incl. reason vocabulary id **and version**, comment, verification id) + trusted reviewer + org + recommendation pins (eligibility result, policy, application ref, opportunity ref). The idempotency key itself is excluded |
| E4 | Authenticate/authorize a retry; replay without re-execution | The boundary order puts authentication and authorization **before** the idempotency lookup. A replay returns `status: replayed` with the original decision and event ids, adds nothing, makes no authority calls, and is logged separately from new approvals |
| E5 | Corrections are new linked records; no reversal | `ReviewCorrectionCommand` has no action/status fields. A correction adds a decision (`corrects_decision_id`, required `correction_note`) and a `review_decision_corrected` event (`prior_event_id`). Prior records are untouched, the status is unchanged, and only the latest decision in a chain can be corrected |
| E6 | Comments outside matching, evidence, chunks and prompts | Comments live only on `ReviewDecision`; `AuditEvent` has no free-text fields. `REVIEW_CONTENT_ENTITY_TYPES` blocks review records as `EvidenceRecord` sources and as retrieval chunks. The regex/token screen is documented as defense-in-depth |
| E7 | Cite candidate/opportunity evidence and published requirements; retrieved text is not proof (partial O5) | `Recommendation.evidence_ids` may cite candidate- or opportunity-subject `EvidenceRecord`s; `requirement_ids` cite published requirements. There is no chunk-id field, so retrieved text cannot be cited as proof |
| E8 | O3, O4 stay open | Unchanged |
| R1 | Review: verify the underlying eligibility result's rule support, not only its `eligible` status; do not trust caller-supplied context | `check_recommendation` — used by `accept_verification` and again at approval — now runs `validate_recommendation_inputs(ctx)` and then PR #5 `check_eligibility_result` on the linked result. `validate_recommendation_inputs` re-applies the existing validators to the whole supplied `RecommendationContext`: record set and source versions (PR #4), evidence provenance, claims, participation, policy sets, published requirements, and every eligibility result's rule support (PR #5). It also rejects a mislabelled eligibility index. `RecommendationContext` now carries adapter capabilities for these checks. This is deterministic support validation only: no new policy logic and no engine. Live authority/freshness checks remain separate |

## Check order at the write boundary

1. **Authenticate:** `Authenticator.authenticate(credential)` → else `unauthenticated`.
2. **Resolve the target.** A missing target gives `not_permitted`, identical to an unauthorized one.
3. **Authorize** (`check_reviewer_authority`):
   - the principal must be human → else `machine_origin_forbidden`;
   - a grant must cover the org and either the opportunity's program or the whole org (`program_id=None`) → else `scope_not_permitted`;
   - that grant must carry the role `program_coordinator` → else `role_not_permitted`.
4. **Idempotency:**
   - same key + same fingerprint → **replay**;
   - same key + different fingerprint (including a different reviewer) → `idempotency_conflict`.
5. **Pure evaluation:**
   - transition legality → `invalid_state`;
   - reason and comment rules → `invalid_command`;
   - the command must reference the current verification;
   - **approve only:** verification acceptance and recommendation checks (both re-run the deterministic prerequisite validation and PR #5 eligibility support — R1), then the live recheck of every dependency → `review_stale`.
6. **Commit together:** decision, event, recommendation status and idempotency record. Rejected commands commit nothing and do not consume the key.

## Evidence levels

- **Schema** — Pydantic and, where expressible, JSON Schema validated independently with `jsonschema`.
- **Invariant / Pure** — deterministic Python functions with no I/O.
- **Mock boundary** — exercised through `tests/review_double.py` with mock authenticator, authorizer and source authority.
- **Not established** — requires the Drupal review-write service and integration tests.

## Traceability matrix

### D-004.03 — Human review authority

| Requirement | Code | Tests | Level |
|---|---|---|---|
| Only an authenticated human coordinator records review actions | `check_reviewer_authority`, `REVIEW_ROLE` | `AuthorityTests.test_unauthenticated` (4 credentials), `test_machine_origin_with_coordinator_grant_rejected`, `test_wrong_role_and_wrong_program_and_wrong_org` | Pure + Mock boundary |
| Client identity/role/`actor_type` never authorizes | Commands `extra=forbid`; principal from `Authenticator` | `test_client_supplied_identity_cannot_be_submitted` (6 fields), conformance "client reviewer id"/"client actor type" | Schema (both validators) |
| Org- and program-scoped grants | `ReviewerGrant(program_id=None` = org-wide) | `test_org_wide_grant_may_approve`, `test_other_org_coordinator_approves_own_org`, wrong program/org cases | Pure + Mock boundary |
| Approval = follow-up only; no placement/hire/offer/admission/rejection | `ReviewAction` (3); no such fields or statuses | `test_action_vocabulary_is_follow_up_only` (7 legacy/forbidden actions), `test_no_placement_or_free_text_fields` | Schema |
| Model output cannot assert approval | Service principals rejected; `Recommendation`/`VerificationResult` carry no decision fields | `test_machine_origin_…`, `test_verification_is_not_authorization` | Schema + Pure |
| Non-disclosure of targets | External codes | `test_nonexistent_and_unauthorized_targets_are_indistinguishable` | Mock boundary |

### D-004.04 — Verification and escalation

| Requirement | Code | Tests | Level |
|---|---|---|---|
| Recommendation bound to candidate, opportunity, eligibility, policy, evidence, application | `Recommendation`, `check_recommendation` | `RecommendationShapeTests` (4), `RecommendationGroundingTests` (9) | Schema + Invariant |
| Pilot application lineage | `check_application_context` | `ApplicationLineageTests` (6): withdrawn/closed/draft own application, other candidate's application, version mismatch, single-opportunity application cannot support another, program-level application allowed | Invariant |
| Substantive verification; no scores; distinct verifier necessary not sufficient | `VerificationResult`, `derive_outcome`, `accept_verification` | `VerificationTests` (10) incl. `test_passed_verification_accepted_only_after_recompute`, `test_same_component_is_not_independent`, `test_source_coverage_must_be_exact`, `test_scores_agreement_and_missing_checks_rejected` | Schema + Pure |
| Failed/stale/unresolved → escalation, never `ready_for_review` | `apply_verification`, `TRANSITIONS` | `test_not_passed_outcomes_escalate_never_ready`, `VerificationGateTests` (3) | Pure + Mock boundary |
| Legal transitions; terminal states cannot reopen | `TRANSITIONS`, `next_status` | `TransitionTests` (4: exhaustive 42-pair matrix, terminal, approve-only-from-ready, no human trigger reaches ready), `TerminalStateTests` (2) | Pure |
| Approval revalidates sources, application, policy, eligibility and access | `evaluate_review` + `collect_live_checks` | `LiveRecheckTests` (4: seven source-change/revocation cases, authority error, withdrawn application in records, eligibility removed), `test_live_recheck_runs_for_every_dependency_for_this_reviewer` | Mock boundary |
| Escalation path: request information / dismiss | Transitions from `escalated`/`needs_information` | `EscalationPathTests` (4) incl. dismissal with withdrawn/denied sources and unauthorized escalation | Mock boundary |
| Verification ≠ authorization | No reviewer/decision fields on `VerificationResult` | `test_verification_is_not_authorization` | Schema |
| Linked eligibility result's rule outcomes supported by cited inputs (R1) | `check_recommendation` → `check_eligibility_result` (PR #5) | `EligibilitySupportIntegrationTests` (4): `qualification_declared` → `qualification_independently_verified` with no verification evidence is rejected by PR #5 (`unsupported_outcome`). The verification is not accepted and escalates. Approval is rejected whether the records change before verification (`invalid_state`) or after it (`review_stale`), with no decision, event, status change or idempotency record, and the key stays reusable | Invariant + Support + Mock boundary |
| Caller-supplied context validated before use (R1) | `validate_recommendation_inputs` | `ContextPrerequisiteTests` (3): fixture context valid; policy version conflict, unresolved claim conflict, evidence provenance, requirement source version and claim-vocabulary conflict each rejected by both `validate_recommendation_inputs` and `check_recommendation`; mislabelled eligibility index rejected | Invariant + Support |

### D-004.08 — Idempotency and audit

| Requirement | Code | Tests | Level |
|---|---|---|---|
| Same key + same semantic payload → prior outcome, no duplicate effects | `review_fingerprint`, `check_replay` | `test_same_key_same_payload_replays_without_effects` | Mock boundary |
| Same key + conflicting payload fails; prior intact | `check_replay` | `test_conflicting_payload_reuse_fails_and_prior_is_intact` (reason, comment, action) | Mock boundary |
| Different reviewer cannot replay or reuse a key | Fingerprint binds trusted reviewer | `test_different_reviewer_cannot_replay_or_reuse_key`, `test_fingerprint_binds_vocabulary_version_pins_and_reviewer` | Pure + Mock boundary |
| Retry re-authenticated and re-authorized | Boundary order | `test_replay_requires_current_authentication_and_authorization` | Mock boundary |
| Rejected commands do not consume keys | Commit only on success | `test_rejected_commands_do_not_consume_the_key` | Mock boundary |
| Audit preserves reviewer, action, reason, sources, lineage | `AuditEvent` | `test_coordinator_approves_verified_eligible_recommendation`, `test_audit_event_lineage_rules`, `test_approval_decision_must_record_rechecked_sources` | Schema + Mock boundary |
| Corrections are new linked events; prior records unmodified; no reversal | `evaluate_correction` | `CorrectionTests` (5) | Pure + Mock boundary |
| Write-service interface; future Drupal duties documented | `ReviewWriteService` protocol docstring | — | **Not established** (see below) |

### D-004.09 — Structured review reasons

| Requirement | Code | Tests | Level |
|---|---|---|---|
| Versioned, controlled vocabulary; one definition per (id, version) | `ReviewReasonVocabulary`, `index_reason_vocabularies` | `test_vocabulary_version_conflict` | Schema + Invariant |
| Every action needs a permitted code for that action | `check_reason` | `test_unknown_code_vocabulary_and_foreign_vocabulary`, `test_reason_must_fit_action` | Pure |
| Routine approval without free text | `meets_published_criteria` (comment optional) | `test_coordinator_approves_verified_eligible_recommendation` | Pure |
| Explanation required for dismissals, exceptions, catch-alls | `CommentRule`; the vocabulary rejects any dismissal reason that doesn't require a comment | `test_conditional_comments`, `test_vocabulary_rules` | Schema + Pure |
| No accusations/sensitive data/AI-invented codes as authoritative reasons | Code allowlist; restricted + accusatory token screen on codes and comments; email/phone screen | `test_comment_screen_rejects_sensitive_accusatory_and_contact_text` (6), `test_vocabulary_rules` (5), unknown `ai_suggested_strong_fit` | Pure — **screen is not exhaustive** |
| Comments separate from matching inputs and prompts | `AuditEvent` has no free text; `REVIEW_CONTENT_ENTITY_TYPES` | `AuditAndCommentIsolationTests` (4) | Schema + Pure + Mock |

## Required scenarios → tests

| Scenario | Test |
|---|---|
| Verified, eligible recommendation approved by an authorized coordinator | `AuthorizedApprovalTests.test_coordinator_approves_verified_eligible_recommendation` |
| Failed or stale verification blocked from normal approval | `VerificationGateTests.test_escalated_recommendation_cannot_be_approved`, `test_stale_or_unresolved_verification_escalates` |
| Missing information routed through authorized escalation | `EscalationPathTests.test_request_information_on_escalated_without_freshness_or_side_effects`, `test_needs_information_then_dismiss` |
| Unauthenticated, machine-origin, wrong-role, cross-organization | `AuthorityTests` |
| Candidate/opportunity source changed after verification | `LiveRecheckTests.test_source_changes_and_revocations_after_verification_block_approval` (opportunity, profile) |
| Policy or eligibility version changed before review | same (policy superseded), `test_eligibility_changed_before_review_blocks_approval` |
| Permission revoked after an earlier successful check | same (profile access denied); `IdempotencyTests.test_replay_requires_current_authentication_and_authorization` |
| Duplicate retry, same key and payload | `IdempotencyTests.test_same_key_same_payload_replays_without_effects` |
| Conflicting key reuse | `test_conflicting_payload_reuse_fails_and_prior_is_intact`, `test_different_reviewer_cannot_replay_or_reuse_key` |
| Audit correction as a new event | `CorrectionTests.test_correction_is_a_new_linked_decision_and_event` |
| Unknown codes, missing explanations, forbidden actions | `ReasonTests`, `test_action_vocabulary_is_follow_up_only` |
| Invalid application lineage, withdrawn applications | `ApplicationLineageTests`, `LiveRecheckTests` (application withdrawn) |
| Reopening terminal recommendations | `TransitionTests.test_terminal_statuses_cannot_reopen`, `TerminalStateTests` |
| PR #4 / #5 compatibility | `Pr4CompatibilityTests`, `Pr5CompatibilityTests`, all prior suites |

## Compatibility with PRs #4 and #5

- **Schemas:** each of the 17 existing schemas changes in exactly two lines, `$id` and `x-contract-version` (`git diff --numstat d780ac1`: `2 2` × 17). The 8 new schemas are additions.
  - `Pr4CompatibilityTests` and `Pr5CompatibilityTests` pin SHA-256 digests of all 17 schema bodies (excluding those two keys) as merged on `main`.
- **Code:** the PR deletes only **2 lines** in total, both in `models.py` (the version label and its comment).
  - `evidence.py` is additive: a review-content exclusion in `check_evidence_records` and `admit_chunks`, plus one new internal `DenialCode`.
  - The PR #4/#5 fixtures are unchanged. Existing test modules only gained appended classes, and every prior test passes.
- **Implications:** `$id`s move to `…/0.2.0-dev.foundations.3/…`. Semver precedence orders `foundations < foundations.2 < foundations.3`.

## Guarantees NOT established — future Drupal review-write service requirements

1. **Authentication.** Principals must come from the authenticated Drupal session or a secure delegation. Mock credential strings are not authentication.
2. **Authorization.** Grants must derive from Drupal roles and permissions for the organization and program. The mock authorizer is a dict.
3. **Atomicity.** The decision, event, recommendation status and idempotency record must commit in **one transaction**. The test double performs sequential dict and list writes.
4. **Concurrency-safe idempotency.** A database-enforced unique key, safe under concurrent submissions, is required. The single-threaded double cannot demonstrate this, nor races between two keys approving the same recommendation.
5. **Durable append-only audit.** Events must be stored durably, append-only and tamper-evident, under a future retention policy. A Python list proves none of this.
6. **Live source authority.** The mock reports configured states only; real revision, permission and withdrawal checks need Drupal.
7. **Time of check vs time of use.** The live recheck and the commit must be atomic relative to source changes; this is not demonstrated.
8. **Communications.** No outbound outreach exists. Any future outreach or substantive display of candidate information needs its own authorization and source-validity checks (decision 4).
9. **Free-text screening.** The token and regex screens cannot detect every accusation, sensitive detail or contact pattern; they will also produce false positives.
10. **Engines.** Recommendations and verifications in the fixture are hand-authored labels. No recommendation generator or verifier ran.
11. **Non-Python consumers.**
    - JSON Schemas now carry the outcome/decision/error consistency, audit lineage, correction pairing and claim-state rules.
    - They do **not** carry: verification-outcome derivation from checks, vocabulary-dependent comment rules, the dismissal-comment invariant, the transition table, or authority checks. Tests document these gaps.

## Decisions N1–N6 (owner-approved 2026-10-28)

These were reversible defaults; the owner approved them with the qualifications below.

| # | Decision | Encoding |
|---|---|---|
| N1 | Rejected commands produce **no** review audit event. **Future Drupal security logging must record denied attempts separately.** | No `AuditEvent` for rejections. The test double's internal `rejection_log` is test-only and is not that security log |
| N2 | Historical approvals remain recorded. **Any later outbound action requires independent, current authorization.** | `approved_for_follow_up` is terminal; no outbound actions exist in this contract |
| N3 | Another appropriately authorized coordinator may create a linked correction **without changing the original record** | `evaluate_correction` attributes the corrector; prior decision/event unchanged (`test_correction_is_a_new_linked_decision_and_event`) |
| N4 | One service-wide idempotency namespace | `InMemoryReviewService.idempotency` keyed by key only; a cross-reviewer collision fails closed (`test_different_reviewer_cannot_replay_or_reuse_key`) |
| N5 | An authorized idempotent replay returns the prior committed outcome **without re-executing** the review | `test_same_key_same_payload_replays_without_effects` (no new decision/event/authority calls), `test_replay_requires_current_authentication_and_authorization` |
| N6 | Opportunities without a program require an **organization-wide** coordinator grant | `check_reviewer_authority`: a grant covers only if `program_id is None` or matches; for a program-less opportunity only `program_id=None` grants match |

## Open decisions carried forward

- **O2** — resolved for recommendations by decision 1 (application context binding). `EligibilityResult` remains unlinked, consistent with PR #5.
- **O5** — partially resolved by E7. Recommendations may cite opportunity-subject evidence and published requirements. How rule outcomes cite opportunity evidence remains open.
- **O3, O4** — open.

## Test evidence

**Current run (after R1):** fresh `git clone` of branch `contracts/v0.2-review` at commit `374b95d06e8c3160d3cd470e97b808f384ee9e25`; new virtualenvs; Python 3.13.17 (Linux).

*Runtime requirements only* (`contracts/requirements.txt`):

```text
$ python -m pip freeze
annotated-types==0.8.0
pydantic==2.13.5
pydantic_core==2.46.5
typing-inspection==0.4.4
typing_extensions==4.16.0

$ python -m rap_contracts.schema_export --check
schema drift: NONE

$ python -m unittest discover -s tests
Ran 288 tests in 1.189s

OK (skipped=12)
```

The 12 skips are the JSON Schema conformance tests (4 from PR #4, 5 from PR #5, 3 new), skipped with a visible reason when the dev dependency is absent.

*Development requirements* (`contracts/requirements-dev.txt`):

```text
$ python -m pip freeze
annotated-types==0.8.0
attrs==26.1.0
jsonschema==4.26.0
jsonschema-specifications==2025.9.1
pydantic==2.13.5
pydantic_core==2.46.5
referencing==0.37.0
rpds-py==2026.9.1
typing-inspection==0.4.4
typing_extensions==4.16.0

$ python -m rap_contracts.schema_export --check
schema drift: NONE

$ python -m unittest discover -s tests -v
...
Ran 288 tests in 1.543s

OK
```

- **Per module:**

  | Module | Tests |
  |---|---|
  | `test_identity` | 16 |
  | `test_records` | 37 |
  | `test_source_versions` | 18 |
  | `test_schemas` | 10 (+2 PR #5 compatibility) |
  | `test_json_schema_conformance` | 12 (+3) |
  | `test_claims` | 40 |
  | `test_eligibility` | 46 |
  | `test_evidence` | 23 |
  | `test_recommendation` (new) | 33 |
  | `test_review` (new) | 53 (incl. 7 for R1) |

- All 288 tests reported `ok`; none failed, errored or skipped. Many tests iterate subTests.
- PRs #4 and #5 contributed 197 tests; this PR adds 91.
- Only Python 3.13.17 was tested. `jsonschema` is the only pinned dev dependency.
- The conformance tests also validate records **generated by the test double**: a recorded, a replayed, a rejected and a correction outcome, plus their decisions and events.
- **R1 regression evidence.** The 7 R1 tests were run against the unfixed code (`3dd1312`) first:
  - PR #5's verifier already rejected the mislabelled result.
  - PR #6, however, **accepted the verification and approved the recommendation** (3 failures).
  - The prerequisite-validation function did not yet exist (7 errors).

  After the fix, all 7 pass.
- **PR #4/#5 compatibility (re-verified at `374b95d`):**
  - No schema file changed in the R1 fix.
  - The 17 existing schemas still differ from `main` only in `$id`/`x-contract-version` (`2 2` × 17).
  - PR #4/#5 code (`invariants.py`, `source_checks.py`, `claims.py`, `eligibility.py`), fixtures and test modules are unchanged versus `main`.
  - `Pr4CompatibilityTests` and `Pr5CompatibilityTests` pass.

**Previous run (superseded):** commit `36d2701` — 281 tests OK (runtime-only: 12 skipped), drift NONE.

**Supplementary local checks (not committed tooling):**

- **pyflakes**, run from a scratch virtualenv only: clean on `rap_contracts/` and `tests/`.
- **Mutation checks.** On scratch copies, each of the 19 safeguards below was disabled individually, and every one caused at least one test failure (failing-test counts in brackets):
  - machine-origin check [4];
  - coordinator role check [4];
  - program scope check [6];
  - conflicting-key replay [5];
  - reviewer dropped from fingerprint [2];
  - live recheck skipped [7];
  - verifier-independence check [1];
  - verification report trusted without recompute [1];
  - failed verification reaches `ready_for_review` [11];
  - escalated recommendations approvable [5];
  - required comment not enforced [2];
  - comment screen removed [6];
  - superseded decision correctable [1];
  - correction reverses status [1];
  - application status not checked [4];
  - review content admitted to chunks [1];
  - stale verification id accepted [1];
  - inferred claim accepted as support [1];
  - dismissal-comment rule not enforced in the vocabulary [2].
- **R1 mutation checks:**
  - **Caught:**
    - context validation call removed [5];
    - claim checks removed [2];
    - evidence provenance removed [2];
    - policy-set checks removed [2];
    - requirement checks removed [2];
    - eligibility index-key check removed [1];
    - **both** eligibility support checks removed [3].
  - **Survived [0], by design:** removing *only* the explicit linked-result call, or *only* the all-results call inside `validate_recommendation_inputs`. These two layers are deliberately redundant, and each alone rejects the R1 case. The explicit call keeps the linked result verified even if context validation is narrowed later.
- **Defects found and fixed:**
  - `recommendation_source_refs` raised a bare `KeyError` when an eligibility result was missing, so the boundary would have crashed instead of failing closed. It now raises `unknown_reference`, which `approval_dependencies` converts to `review_stale`. Regression test: `test_eligibility_changed_before_review_blocks_approval`.
  - The `ReviewOutcome` JSON Schema forbade audit ids on rejections, but the Pydantic validator did not. Both now agree, which the conformance case "rejected with events" checks.
  - **Review finding R1:** recommendation acceptance and approval checked only the linked result's `eligible` decision and pins, not its rule-outcome support, and trusted the supplied context.

<details>
<summary>Full verbose test output (dev requirements, commit 374b95d)</summary>

```text
test_code_outside_vocabulary_rejected (test_claims.AllowlistAndSensitiveFieldTests) ... ok
test_retrieval_request_cannot_carry_sensitive_fields (test_claims.AllowlistAndSensitiveFieldTests) ... ok
test_sensitive_context_case_stores_nothing_sensitive (test_claims.AllowlistAndSensitiveFieldTests) ... ok
test_unsupported_claim_types_and_extra_fields_rejected (test_claims.AllowlistAndSensitiveFieldTests) ... ok
test_vocabulary_screens_restricted_terms (test_claims.AllowlistAndSensitiveFieldTests) ... ok
test_wrong_or_foreign_vocabulary_rejected (test_claims.AllowlistAndSensitiveFieldTests) ... ok
test_availability_bounds (test_claims.ClaimStateTests) ... ok
test_contested_rules (test_claims.ClaimStateTests) ... ok
test_declared_and_inferred_require_evidence (test_claims.ClaimStateTests) ... ok
test_fixture_claims_cover_all_types_and_states (test_claims.ClaimStateTests) ... ok
test_inferred_requires_producer_and_only_inferred_may_name_one (test_claims.ClaimStateTests) ... ok
test_unknown_with_fabricated_value_rejected (test_claims.ClaimStateTests) ... ok
test_value_kind_and_subject_code_must_match_type (test_claims.ClaimStateTests) ... ok
test_conflicting_availability_detected (test_claims.ConflictTests) ... ok
test_conflicting_declared_claims_must_be_contested (test_claims.ConflictTests) ... ok
test_contested_or_unknown_cannot_coexist_with_declared_value (test_claims.ConflictTests) ... ok
test_corroborating_declared_claims_allowed (test_claims.ConflictTests) ... ok
test_experience_duration_conflict_is_deterministic (test_claims.ConflictTests) ... ok
test_inference_never_conflicts_with_or_overrides_a_fact (test_claims.ConflictTests) ... ok
test_candidate_statement_must_come_from_own_profile_or_application (test_claims.EvidenceProvenanceTests) ... ok
test_claim_cannot_rest_on_authority_record (test_claims.EvidenceProvenanceTests) ... ok
test_claim_citing_missing_or_other_candidates_evidence_rejected (test_claims.EvidenceProvenanceTests) ... ok
test_cross_org_evidence_rejected (test_claims.EvidenceProvenanceTests) ... ok
test_verification_source_cannot_be_an_identity_type (test_claims.EvidenceProvenanceTests) ... ok
test_verification_sources_fail_closed_until_explicitly_authorized (test_claims.EvidenceProvenanceTests) ... ok
test_identity_fields_immutable (test_claims.InferredPromotionTests) ... ok
test_inference_cannot_overwrite_a_declared_claim (test_claims.InferredPromotionTests) ... ok
test_inferred_cannot_be_relabeled (test_claims.InferredPromotionTests) ... ok
test_inferred_reupdate_allowed (test_claims.InferredPromotionTests) ... ok
test_candidate_authority_evidence_must_be_declared_participation_authority (test_claims.ParticipationTests) ... ok
test_conflicting_participation_records_rejected (test_claims.ParticipationTests) ... ok
test_fixture_participations_valid (test_claims.ParticipationTests) ... ok
test_participation_is_not_a_claim_type (test_claims.ParticipationTests) ... ok
test_participation_requires_authority_record_evidence (test_claims.ParticipationTests) ... ok
test_conflict_detected_regardless_of_order (test_claims.VocabularyVersionIntegrityTests) ... ok
test_conflicting_definition_rejected_by_claim_checks (test_claims.VocabularyVersionIntegrityTests) ... ok
test_conflicting_definition_rejected_by_requirement_checks (test_claims.VocabularyVersionIntegrityTests) ... ok
test_identical_duplicate_and_new_version_allowed (test_claims.VocabularyVersionIntegrityTests) ... ok
test_same_id_and_version_in_another_org_rejected (test_claims.VocabularyVersionIntegrityTests) ... ok
test_standalone_index_reports_conflict (test_claims.VocabularyVersionIntegrityTests) ... ok
test_decision_must_follow_outcomes (test_eligibility.DecisionConsistencyTests) ... ok
test_fail_dominates_unknown (test_eligibility.DecisionConsistencyTests) ... ok
test_one_outcome_per_rule (test_eligibility.DecisionConsistencyTests) ... ok
test_unknown_reason_codes_cannot_express_integrity_failures (test_eligibility.DecisionConsistencyTests) ... ok
test_active_rule_is_pass_fail_only_per_o1 (test_eligibility.FixtureCaseTests) ... ok
test_all_fixture_results_valid_and_supported (test_eligibility.FixtureCaseTests) ... ok
test_expected_decisions (test_eligibility.FixtureCaseTests) ... ok
test_rule_case_catalog (test_eligibility.FixtureCaseTests) ... ok
test_authority_error_fails_closed (test_eligibility.IntegrityGateTests) ... ok
test_failures_raise_rather_than_becoming_unknown (test_eligibility.IntegrityGateTests) ... ok
test_gate_covers_every_dependency (test_eligibility.IntegrityGateTests) ... ok
test_other_principal_denied (test_eligibility.IntegrityGateTests) ... ok
test_conflicting_or_duplicate_results_for_same_key_rejected (test_eligibility.NoCandidateLevelRejectionTests) ... ok
test_ineligible_for_one_opportunity_leaves_others_unchanged (test_eligibility.NoCandidateLevelRejectionTests) ... ok
test_no_candidate_level_fields_or_values (test_eligibility.NoCandidateLevelRejectionTests) ... ok
test_active_status_support (test_eligibility.OutcomeSupportTests) ... ok
test_availability_support (test_eligibility.OutcomeSupportTests) ... ok
test_citing_another_candidates_claim_rejected (test_eligibility.OutcomeSupportTests) ... ok
test_declared_versus_verified_distinction (test_eligibility.OutcomeSupportTests) ... ok
test_inferred_lacks_cannot_fail (test_eligibility.OutcomeSupportTests) ... ok
test_inferred_or_contested_cannot_support_pass_or_fail (test_eligibility.OutcomeSupportTests) ... ok
test_missing_qualification_cannot_fail (test_eligibility.OutcomeSupportTests) ... ok
test_not_evidenced_is_valid_when_no_source_backed_claim_exists (test_eligibility.OutcomeSupportTests) ... ok
test_participation_support (test_eligibility.OutcomeSupportTests) ... ok
test_unknown_reason_must_match_inputs (test_eligibility.OutcomeSupportTests) ... ok
test_opportunity_version_must_be_pinned_exactly (test_eligibility.PolicyVersionTests) ... ok
test_policy_must_cover_opportunity_and_org (test_eligibility.PolicyVersionTests) ... ok
test_policy_rule_shape (test_eligibility.PolicyVersionTests) ... ok
test_policy_version_mismatch (test_eligibility.PolicyVersionTests) ... ok
test_policy_versions_are_immutable (test_eligibility.PolicyVersionTests) ... ok
test_program_scoped_policy_cannot_assess_outside_its_program (test_eligibility.PolicyVersionTests) ... ok
test_rule_version_or_set_mismatch (test_eligibility.PolicyVersionTests) ... ok
test_job_result_uses_same_contracts_with_independent_policy (test_eligibility.PortabilityTests) ... ok
test_matching_program_b_rule_is_accepted (test_eligibility.ProgramScopeTests) ... ok
test_participation_rule_rejected_for_opportunity_without_program (test_eligibility.ProgramScopeTests) ... ok
test_policy_rule_program_must_match_policy_scope (test_eligibility.ProgramScopeTests) ... ok
test_program_a_participation_rejected_for_program_b_opportunity (test_eligibility.ProgramScopeTests) ... ok
test_program_scoped_policy_for_a_rejected_for_program_b_opportunity (test_eligibility.ProgramScopeTests) ... ok
test_rejected_even_when_candidate_also_participates_in_program_b (test_eligibility.ProgramScopeTests) ... ok
test_conflicting_or_duplicate_requirements_rejected (test_eligibility.RequirementTests) ... ok
test_cross_org_requirement_rejected (test_eligibility.RequirementTests) ... ok
test_fixture_requirements_valid (test_eligibility.RequirementTests) ... ok
test_qualification_code_must_be_in_vocabulary (test_eligibility.RequirementTests) ... ok
test_requirement_may_come_from_covering_policy_source (test_eligibility.RequirementTests) ... ok
test_requirement_must_pin_opportunity_source_version (test_eligibility.RequirementTests) ... ok
test_requirement_shape (test_eligibility.RequirementTests) ... ok
test_authority_error_fails_closed (test_evidence.AdmissionTests) ... ok
test_authorized_current_chunk_admitted_as_untrusted_data (test_evidence.AdmissionTests) ... ok
test_cross_org_chunk_denied_before_authority_or_store (test_evidence.AdmissionTests) ... ok
test_guessed_chunk_id_denied_without_any_lookup (test_evidence.AdmissionTests) ... ok
test_mixed_request_admits_only_allowed_chunks (test_evidence.AdmissionTests) ... ok
test_revoked_access_denied_even_with_permissive_metadata (test_evidence.AdmissionTests) ... ok
test_stale_index_entry_denied (test_evidence.AdmissionTests) ... ok
test_store_failure_fails_closed (test_evidence.AdmissionTests) ... ok
test_tampered_content_never_exposed (test_evidence.AdmissionTests) ... ok
test_unknown_principal_denied (test_evidence.AdmissionTests) ... ok
test_withdrawn_and_deleted_sources_denied (test_evidence.AdmissionTests) ... ok
test_wrong_version_kind_denied (test_evidence.AdmissionTests) ... ok
test_evidence_record_shape (test_evidence.CitationTests) ... ok
test_invalid_citations_rejected (test_evidence.CitationTests) ... ok
test_valid_citations_resolve (test_evidence.CitationTests) ... ok
test_every_denial_mode_produces_the_same_external_shape (test_evidence.ExternalIndistinguishabilityTests) ... ok
test_response_lists_unavailable_ids_in_sorted_order_without_reasons (test_evidence.ExternalIndistinguishabilityTests) ... ok
test_chunk_hashes_match_store_except_tampered (test_evidence.FixtureTests) ... ok
test_chunk_scope_and_shape (test_evidence.FixtureTests) ... ok
test_request_shape (test_evidence.FixtureTests) ... ok
test_embedded_json_is_not_interpreted (test_evidence.PromptInjectionTests) ... ok
test_injected_text_admitted_verbatim_as_untrusted_data_only (test_evidence.PromptInjectionTests) ... ok
test_text_claiming_authorization_cannot_override_denial (test_evidence.PromptInjectionTests) ... ok
test_application_for_candidate_in_other_org_rejected (test_identity.CrossOrganizationReferenceTests) ... ok
test_application_targeting_other_org_opportunity_rejected (test_identity.CrossOrganizationReferenceTests) ... ok
test_fixture_record_set_is_consistent (test_identity.CrossOrganizationReferenceTests) ... ok
test_profile_for_candidate_in_other_org_rejected (test_identity.CrossOrganizationReferenceTests) ... ok
test_record_source_ref_in_other_org_rejected_at_model_level (test_identity.CrossOrganizationReferenceTests) ... ok
test_attribute_assignment_blocked (test_identity.IdentityImmutabilityTests) ... ok
test_identity_source_change_rejected (test_identity.IdentityImmutabilityTests) ... ok
test_organization_change_rejected (test_identity.IdentityImmutabilityTests) ... ok
test_reprojection_with_same_identity_allowed (test_identity.IdentityImmutabilityTests) ... ok
test_candidate_id_reused_across_orgs_rejected (test_identity.IdentityMappingTests) ... ok
test_fixture_identities_are_valid (test_identity.IdentityMappingTests) ... ok
test_identity_source_must_be_declared_identity_type (test_identity.IdentityMappingTests) ... ok
test_same_account_gets_distinct_candidates_in_two_orgs (test_identity.IdentityMappingTests) ... ok
test_second_candidate_for_same_account_in_same_org_rejected (test_identity.IdentityMappingTests) ... ok
test_personal_data_shaped_and_mistyped_ids_rejected (test_identity.PortableIdTests) ... ok
test_unknown_fields_rejected (test_identity.PortableIdTests) ... ok
test_all_extended_fixture_records_accepted (test_json_schema_conformance.EligibilityEvidenceConformanceTests) ... ok
test_documented_gaps_python_only (test_json_schema_conformance.EligibilityEvidenceConformanceTests) ... ok
test_malformed_claims_rejected_by_both (test_json_schema_conformance.EligibilityEvidenceConformanceTests) ... ok
test_malformed_eligibility_rejected_by_both (test_json_schema_conformance.EligibilityEvidenceConformanceTests) ... ok
test_malformed_retrieval_and_evidence_rejected_by_both (test_json_schema_conformance.EligibilityEvidenceConformanceTests) ... ok
test_all_synthetic_fixture_records_accepted (test_json_schema_conformance.JsonSchemaConformanceTests) ... ok
test_committed_schemas_are_valid_draft_2020_12 (test_json_schema_conformance.JsonSchemaConformanceTests) ... ok
test_documented_gap_cross_field_org_equality_not_in_json_schema (test_json_schema_conformance.JsonSchemaConformanceTests) ... ok
test_malformed_submission_and_target_cases_rejected (test_json_schema_conformance.JsonSchemaConformanceTests) ... ok
test_documented_gaps_python_only (test_json_schema_conformance.ReviewConformanceTests) ... ok
test_fixture_and_service_generated_records_accepted (test_json_schema_conformance.ReviewConformanceTests) ... ok
test_malformed_review_records_rejected_by_both (test_json_schema_conformance.ReviewConformanceTests) ... ok
test_application_targeting_single_opportunity_cannot_support_another (test_recommendation.ApplicationLineageTests) ... ok
test_job_application_supports_its_own_opportunity (test_recommendation.ApplicationLineageTests) ... ok
test_own_withdrawn_closed_or_draft_application_rejected (test_recommendation.ApplicationLineageTests) ... ok
test_pinned_application_version_must_match (test_recommendation.ApplicationLineageTests) ... ok
test_program_level_application_supports_other_program_opportunity (test_recommendation.ApplicationLineageTests) ... ok
test_withdrawn_draft_or_other_candidates_application_rejected (test_recommendation.ApplicationLineageTests) ... ok
test_cross_org_record_rejected (test_recommendation.RecommendationGroundingTests) ... ok
test_dependencies_cover_application_policy_and_evidence (test_recommendation.RecommendationGroundingTests) ... ok
test_eligibility_for_other_pair_rejected (test_recommendation.RecommendationGroundingTests) ... ok
test_evidence_must_be_about_candidate_or_opportunity_in_scope (test_recommendation.RecommendationGroundingTests) ... ok
test_inferred_or_contested_claim_cannot_support (test_recommendation.RecommendationGroundingTests) ... ok
test_must_rest_on_eligible_result (test_recommendation.RecommendationGroundingTests) ... ok
test_policy_pin_must_match_eligibility (test_recommendation.RecommendationGroundingTests) ... ok
test_published_requirements_and_opportunity_evidence_may_be_cited (test_recommendation.RecommendationGroundingTests) ... ok
test_supporting_claims_must_be_declared_and_fully_cited (test_recommendation.RecommendationGroundingTests) ... ok
test_fixture_recommendations_valid (test_recommendation.RecommendationShapeTests) ... ok
test_no_placement_or_free_text_fields (test_recommendation.RecommendationShapeTests) ... ok
test_requires_context_claims_and_evidence (test_recommendation.RecommendationShapeTests) ... ok
test_unapproved_context_kinds_not_representable (test_recommendation.RecommendationShapeTests) ... ok
test_approval_only_from_ready_for_review (test_recommendation.TransitionTests) ... ok
test_exhaustive_transition_matrix (test_recommendation.TransitionTests) ... ok
test_no_human_trigger_reaches_ready_for_review (test_recommendation.TransitionTests) ... ok
test_terminal_statuses_cannot_reopen (test_recommendation.TransitionTests) ... ok
test_not_passed_outcomes_escalate_never_ready (test_recommendation.VerificationTests) ... ok
test_outcome_derivation (test_recommendation.VerificationTests) ... ok
test_passed_verification_accepted_only_after_recompute (test_recommendation.VerificationTests) ... ok
test_same_component_is_not_independent (test_recommendation.VerificationTests) ... ok
test_scores_agreement_and_missing_checks_rejected (test_recommendation.VerificationTests) ... ok
test_source_coverage_must_be_exact (test_recommendation.VerificationTests) ... ok
test_stale_source_forces_stale_outcome (test_recommendation.VerificationTests) ... ok
test_verification_cannot_move_a_reviewed_recommendation (test_recommendation.VerificationTests) ... ok
test_verification_for_other_recommendation_rejected (test_recommendation.VerificationTests) ... ok
test_verification_is_not_authorization (test_recommendation.VerificationTests) ... ok
test_one_candidate_two_independent_applications (test_records.IndependentApplicationTests) ... ok
test_withdrawing_one_application_leaves_the_other_untouched (test_records.IndependentApplicationTests) ... ok
test_full_transition_matrix (test_records.LifecycleTests) ... ok
test_immutable_application_fields (test_records.LifecycleTests) ... ok
test_reopen_via_update_rejected (test_records.LifecycleTests) ... ok
test_status_submission_coupling (test_records.LifecycleTests) ... ok
test_submission_timestamps_must_be_timezone_aware (test_records.LifecycleTests) ... ok
test_submission_version_kind_must_match_application_source (test_records.LifecycleTests) ... ok
test_withdrawn_and_closed_are_terminal (test_records.LifecycleTests) ... ok
test_authority_error_fails_closed (test_records.PinnedEvidenceResolutionTests) ... ok
test_authority_substituting_newer_profile_rejected (test_records.PinnedEvidenceResolutionTests) ... ok
test_deleted_pinned_version_fails_closed (test_records.PinnedEvidenceResolutionTests) ... ok
test_draft_has_no_submission_evidence (test_records.PinnedEvidenceResolutionTests) ... ok
test_no_longer_authorized_fails_closed (test_records.PinnedEvidenceResolutionTests) ... ok
test_pinned_superseded_version_resolves_without_substitution (test_records.PinnedEvidenceResolutionTests) ... ok
test_unavailable_pinned_version_fails_closed_without_fallback (test_records.PinnedEvidenceResolutionTests) ... ok
test_unknown_principal_fails_closed (test_records.PinnedEvidenceResolutionTests) ... ok
test_withdrawn_application_is_not_active_evidence (test_records.PinnedEvidenceResolutionTests) ... ok
test_withdrawn_pinned_version_fails_closed (test_records.PinnedEvidenceResolutionTests) ... ok
test_complete_fixture_set_contains_every_pinned_version (test_records.PinnedVersionMembershipTests) ... ok
test_complete_set_missing_pinned_version_rejected (test_records.PinnedVersionMembershipTests) ... ok
test_complete_set_pinning_nonexistent_version_rejected (test_records.PinnedVersionMembershipTests) ... ok
test_partial_set_defers_to_resolver_which_fails_closed (test_records.PinnedVersionMembershipTests) ... ok
test_partial_set_resolves_when_authority_still_retains_pinned_version (test_records.PinnedVersionMembershipTests) ... ok
test_unknown_mode_rejected (test_records.PinnedVersionMembershipTests) ... ok
test_job_opportunity_uses_same_contracts (test_records.PortabilityTests) ... ok
test_pinning_another_candidates_profile_rejected (test_records.SubmissionPreservationTests) ... ok
test_profile_ref_that_does_not_locate_the_named_profile_rejected (test_records.SubmissionPreservationTests) ... ok
test_profile_revision_does_not_mutate_submitted_snapshot (test_records.SubmissionPreservationTests) ... ok
test_profile_versions_must_share_owner_and_source_entity (test_records.SubmissionPreservationTests) ... ok
test_removing_submission_rejected (test_records.SubmissionPreservationTests) ... ok
test_rewriting_pinned_profile_to_newer_revision_rejected (test_records.SubmissionPreservationTests) ... ok
test_submission_added_only_by_draft_to_submitted (test_records.SubmissionPreservationTests) ... ok
test_empty_target_rejected (test_records.TargetTests) ... ok
test_opportunity_outside_targeted_program_rejected (test_records.TargetTests) ... ok
test_unknown_target_rejected (test_records.TargetTests) ... ok
test_valid_target_shapes (test_records.TargetTests) ... ok
test_approval_decision_must_record_rechecked_sources (test_review.AuditAndCommentIsolationTests) ... ok
test_audit_event_lineage_rules (test_review.AuditAndCommentIsolationTests) ... ok
test_audit_events_carry_no_free_text (test_review.AuditAndCommentIsolationTests) ... ok
test_review_content_never_becomes_evidence_or_retrieval_context (test_review.AuditAndCommentIsolationTests) ... ok
test_client_supplied_identity_cannot_be_submitted (test_review.AuthorityTests) ... ok
test_machine_origin_with_coordinator_grant_rejected (test_review.AuthorityTests) ... ok
test_nonexistent_and_unauthorized_targets_are_indistinguishable (test_review.AuthorityTests) ... ok
test_unauthenticated (test_review.AuthorityTests) ... ok
test_wrong_role_and_wrong_program_and_wrong_org (test_review.AuthorityTests) ... ok
test_action_vocabulary_is_follow_up_only (test_review.AuthorizedApprovalTests) ... ok
test_coordinator_approves_verified_eligible_recommendation (test_review.AuthorizedApprovalTests) ... ok
test_live_recheck_runs_for_every_dependency_for_this_reviewer (test_review.AuthorizedApprovalTests) ... ok
test_org_wide_grant_may_approve (test_review.AuthorizedApprovalTests) ... ok
test_other_org_coordinator_approves_own_org (test_review.AuthorizedApprovalTests) ... ok
test_fixture_context_validates (test_review.ContextPrerequisiteTests) ... ok
test_invalid_policy_claims_evidence_and_requirements_rejected (test_review.ContextPrerequisiteTests) ... ok
test_mislabelled_eligibility_index_rejected (test_review.ContextPrerequisiteTests) ... ok
test_correction_authority_and_idempotency (test_review.CorrectionTests) ... ok
test_correction_cannot_change_or_reverse_the_action (test_review.CorrectionTests) ... ok
test_correction_is_a_new_linked_decision_and_event (test_review.CorrectionTests) ... ok
test_correction_requires_note_and_screens_text (test_review.CorrectionTests) ... ok
test_only_latest_decision_in_chain_can_be_corrected (test_review.CorrectionTests) ... ok
test_inconsistent_context_after_verification_blocks_approval (test_review.EligibilitySupportIntegrationTests) ... ok
test_inconsistent_context_before_verification_blocks_approval (test_review.EligibilitySupportIntegrationTests) ... ok
test_pr5_support_verifier_rejects_the_inconsistent_result (test_review.EligibilitySupportIntegrationTests) ... ok
test_verification_cannot_be_accepted_and_recommendation_escalates (test_review.EligibilitySupportIntegrationTests) ... ok
test_dismissal_allowed_even_when_sources_are_stale_or_withdrawn (test_review.EscalationPathTests) ... ok
test_needs_information_then_dismiss (test_review.EscalationPathTests) ... ok
test_request_information_on_escalated_without_freshness_or_side_effects (test_review.EscalationPathTests) ... ok
test_unauthorized_escalation_rejected (test_review.EscalationPathTests) ... ok
test_conflicting_payload_reuse_fails_and_prior_is_intact (test_review.IdempotencyTests) ... ok
test_different_reviewer_cannot_replay_or_reuse_key (test_review.IdempotencyTests) ... ok
test_fingerprint_binds_vocabulary_version_pins_and_reviewer (test_review.IdempotencyTests) ... ok
test_rejected_commands_do_not_consume_the_key (test_review.IdempotencyTests) ... ok
test_replay_requires_current_authentication_and_authorization (test_review.IdempotencyTests) ... ok
test_same_key_same_payload_replays_without_effects (test_review.IdempotencyTests) ... ok
test_authority_error_blocks_approval (test_review.LiveRecheckTests) ... ok
test_eligibility_changed_before_review_blocks_approval (test_review.LiveRecheckTests) ... ok
test_source_changes_and_revocations_after_verification_block_approval (test_review.LiveRecheckTests) ... ok
test_withdrawn_application_in_records_blocks_approval (test_review.LiveRecheckTests) ... ok
test_comment_screen_rejects_sensitive_accusatory_and_contact_text (test_review.ReasonTests) ... ok
test_comment_shape (test_review.ReasonTests) ... ok
test_conditional_comments (test_review.ReasonTests) ... ok
test_reason_must_fit_action (test_review.ReasonTests) ... ok
test_unknown_code_vocabulary_and_foreign_vocabulary (test_review.ReasonTests) ... ok
test_vocabulary_rules (test_review.ReasonTests) ... ok
test_vocabulary_version_conflict (test_review.ReasonTests) ... ok
test_outcome_and_decision_round_trip (test_review.SchemaRoundTripTests) ... ok
test_dismissed_cannot_be_approved (test_review.TerminalStateTests) ... ok
test_terminal_recommendations_cannot_be_reopened_or_re_reviewed (test_review.TerminalStateTests) ... ok
test_command_must_reference_current_verification (test_review.VerificationGateTests) ... ok
test_escalated_recommendation_cannot_be_approved (test_review.VerificationGateTests) ... ok
test_stale_or_unresolved_verification_escalates (test_review.VerificationGateTests) ... ok
test_pr4_fixture_and_capabilities_still_valid (test_schemas.Pr4CompatibilityTests) ... ok
test_pr4_schema_bodies_unchanged (test_schemas.Pr4CompatibilityTests) ... ok
test_pr5_fixture_still_valid (test_schemas.Pr5CompatibilityTests) ... ok
test_pr5_schema_bodies_unchanged (test_schemas.Pr5CompatibilityTests) ... ok
test_committed_schemas_match_generated_output (test_schemas.SchemaDriftTests) ... ok
test_drift_is_detected (test_schemas.SchemaDriftTests) ... ok
test_generation_is_deterministic (test_schemas.SchemaDriftTests) ... ok
test_running_pinned_pydantic (test_schemas.SchemaDriftTests) ... ok
test_development_label (test_schemas.SchemaIdentityTests) ... ok
test_ids_are_stable_versioned_and_unique (test_schemas.SchemaIdentityTests) ... ok
test_additional_method_can_be_registered_without_contract_change (test_source_versions.CapabilityCheckTests) ... ok
test_capabilities_cannot_declare_both_kinds_for_one_type (test_source_versions.CapabilityCheckTests) ... ok
test_malformed_sha256_token_rejected (test_source_versions.CapabilityCheckTests) ... ok
test_native_revision_claimed_for_snapshot_only_type_rejected (test_source_versions.CapabilityCheckTests) ... ok
test_snapshot_substituted_for_available_native_revision_rejected (test_source_versions.CapabilityCheckTests) ... ok
test_undeclared_entity_type_fails_closed (test_source_versions.CapabilityCheckTests) ... ok
test_undeclared_source_system_fails_closed (test_source_versions.CapabilityCheckTests) ... ok
test_unregistered_snapshot_method_rejected (test_source_versions.CapabilityCheckTests) ... ok
test_current_and_allowed_passes (test_source_versions.FreshnessAndAccessSeparationTests) ... ok
test_historical_gate_accepts_superseded_but_not_missing_or_denied (test_source_versions.FreshnessAndAccessSeparationTests) ... ok
test_newly_inaccessible_source_rejected (test_source_versions.FreshnessAndAccessSeparationTests) ... ok
test_version_and_access_are_independent (test_source_versions.FreshnessAndAccessSeparationTests) ... ok
test_well_formed_token_does_not_imply_current_or_allowed (test_source_versions.FreshnessAndAccessSeparationTests) ... ok
test_canonicalization_ignores_key_order (test_source_versions.SnapshotMethodTests) ... ok
test_fixture_tokens_reproduce_from_declared_payloads (test_source_versions.SnapshotMethodTests) ... ok
test_all_fixture_refs_match_declared_capabilities (test_source_versions.VersionKindRepresentationTests) ... ok
test_both_version_kinds_validate (test_source_versions.VersionKindRepresentationTests) ... ok
test_malformed_versions_rejected (test_source_versions.VersionKindRepresentationTests) ... ok

----------------------------------------------------------------------
Ran 288 tests in 1.543s

OK
```

(Fully qualified test IDs shortened to `module.Class` for width.)

</details>

## Out of scope (deferred)

- D-004.12 evaluation fixtures.
- The recommendation and eligibility engines.
- The real Drupal write service, authentication, persistence, UI, outbound communications.
- Agents, LangGraph, Temporal, LangFuse, live RAG, hosted infrastructure, paid inference.

## Freeze status

**Not frozen.** D-004.12 remains, as do the open decisions above and integration-stage gates. A freeze requires an explicit owner decision.
