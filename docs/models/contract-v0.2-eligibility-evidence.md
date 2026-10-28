# Contract v0.2 Eligibility and Evidence Foundations — Traceability, Evidence and Limits

**Document ID:** RAP-CONTRACT-002-E  
**Contract version:** `0.2.0-dev.foundations.2` — **partial development version; proposed; NOT frozen**  
**PR:** #5 (Eligibility and Evidence Foundations)  
**Base:** `main` @ `2e63a939487823e40b365b0f9146365574e50733` (merge of PR #4)  
**Scope:** D-004.05, D-004.06, D-004.10, D-004.11 only  
**Code:** [`contracts/`](../../contracts/README.md) — `rap_contracts/eligibility.py`, `claims.py`, `evidence.py`  
**Prior increment:** [`contract-v0.2-foundations.md`](contract-v0.2-foundations.md) (D-004.01/.02/.07)

Pydantic v2 remains the reference-contract tool only, not an application-runtime selection. This PR contains **no eligibility engine**, Drupal adapter, vector store, ingestion pipeline, agents, review workflow, CI change or paid inference.

## Owner decisions applied (2026-10-28)

| # | Decision | Encoded as |
|---|---|---|
| A | Missing, inferred and contested qualifications never produce `ineligible`; only explicit source-backed contradiction can. Declared vs independently verified is preserved | Qualification `fail` requires cited **declared** `lacks` claims; pass/fail reject inferred/unknown/contested inputs (`non_authoritative_input`). Reason codes `qualification_declared` / `qualification_independently_verified` and `…contradicted_by_declaration` / `…contradicted_by_verification`, each checked against `EvidenceRecord.basis` |
| B | Genuinely unknown inputs may be `unknown`; integrity/authorization failures fail closed **before** eligibility | `evidence.require_sources_admissible` + `eligibility_source_refs` raise on denied/stale/withdrawn/deleted/unavailable/errored sources. The reason-code table contains **no** integrity codes (also enforced in JSON Schema) |
| C | Separate versioned `OpportunityRequirement` records; `Opportunity` unchanged | `OpportunityRequirement.source_ref` must equal the opportunity's exact source version or the exact source of a covering policy (`requirement_source_mismatch`) |
| 1 | Corroboration allowed; `contested` only for genuine conflict; inference never overrides | `values_conflict` / `detect_conflicts` (deterministic, sorted, declared-only). Corroborating declared claims pass; conflicting ones must be one `contested` claim (`unresolved_conflict`); a contested model rejects non-conflicting alternatives |
| 2 | Accommodate future authorized verification sources without relaxing scope/provenance/access | `EvidenceBasis.INDEPENDENT_VERIFICATION` accepted only for entity types in `SourceSystemCapabilities.verification_entity_types` (empty by default → `unauthorized_verification_source`); org, subject and version checks unchanged |
| 3 | Whole hours, no arbitrary 80-hour cap; document limits | `hours_per_week` 0–168 (hours in a week). Does **not** represent schedules, schedule compatibility or accommodation handling |
| 4 | Admission fails closed before loading/exposing text; external responses do not reveal existence | Text is loaded only after scope, version-kind and live checks pass. `RetrievalResponse` lists every non-admitted id identically with no reason; specific `DenialCode`s are internal only |
| 5 | Sensitive-context case stores/exposes no medical, disability or accommodation detail | Candidate E: availability is an `unknown` claim with no value or evidence; the source answer is not represented in any claim, evidence locator, chunk or request. A test scans all matching/prompt-reachable fixture sections for restricted terms |
| 6 | Preserve PR #4 compatibility; verify schema differences | See [Compatibility](#compatibility-with-pr-4) |

## Evidence levels

- **Schema** — Pydantic model and, where expressible, the generated JSON Schema (validated independently with `jsonschema`).
- **Invariant** — pure Python cross-record checks.
- **Support** — `check_eligibility_result` confirms a *labeled* outcome is consistent with its cited inputs and with absence conditions in a complete record set. It does not select inputs or compute outcomes.
- **Mock** — exercised against `FixtureSourceAuthority` / `FixtureChunkStore` (in-memory test doubles).
- **Not established** — requires live Drupal integration or later PRs.

## Traceability matrix

### D-004.05 — Opportunity-specific eligibility

| Requirement | Code | Tests | Level |
|---|---|---|---|
| Outcomes `eligible` / `ineligible` / `needs_information` | `EligibilityDecision` | `test_expected_decisions` | Schema |
| Bound to one candidate, one opportunity version, one pinned policy version, all rule outcomes | `EligibilityResult.opportunity_ref`, `PolicyPin`; `check_eligibility_result` | `test_opportunity_version_must_be_pinned_exactly`, `test_policy_version_mismatch`, `test_rule_version_or_set_mismatch` | Schema + Invariant |
| Any fail → ineligible; else any unknown → needs_information; else eligible | `derive_decision`; model validator; JSON Schema `if/then/else` | `test_decision_must_follow_outcomes`, `test_fail_dominates_unknown`, `test_malformed_eligibility_rejected_by_both` | Schema (Pydantic **and** independent validator) |
| Ineligibility is never candidate-level | No candidate-level field/value (extra=forbid); one result per (candidate, opportunity, policy version) | `NoCandidateLevelRejectionTests` (3) | Schema + Invariant — **audit/event effects belong to D-004.08** |
| Ineligible for A does not alter B | Results checked independently; applications untouched | `test_ineligible_for_one_opportunity_leaves_others_unchanged` (A×ops ineligible, A×web/A×data eligible) | Invariant |
| Portability | Independent job policy in `org_demo_002` | `test_job_result_uses_same_contracts_with_independent_policy` | Invariant |

### D-004.06 — Versioned policy rules

| Requirement | Code | Tests | Level |
|---|---|---|---|
| Portable versioned `PolicySet` / `PolicyRule` / `RuleOutcome` | `eligibility.py` | `test_policy_rule_shape` | Schema |
| (id, version) immutable; one source version per pin | `check_policy_sets` (`policy_version_conflict`) | `test_policy_versions_are_immutable` | Invariant |
| Policy scope covers the opportunity | `policy_scope_mismatch` | `test_program_scoped_policy_cannot_assess_outside_its_program`, `test_policy_must_cover_opportunity_and_org` | Invariant |
| Reason code valid for rule kind and result | `REASON_CODES`; JSON Schema `allOf` per (kind, result) | `test_unknown_reason_codes_cannot_express_integrity_failures`, conformance cases | Schema (both validators) |
| Four pilot rules with source-backed pass/fail/unknown | Fixture `rule_cases` (14) over 7 labeled results | `test_rule_case_catalog` (asserts every representable (kind, result) has a case) | Support |
| Outcomes supported by cited inputs | `_verify_support` per rule kind | `OutcomeSupportTests` (10) | Support |
| Missing qualification is not negative evidence | `fail` requires declared `lacks` | `test_missing_qualification_cannot_fail`, `test_inferred_lacks_cannot_fail` | Support |
| Integrity failures fail closed before eligibility | `require_sources_admissible` | `IntegrityGateTests` (4; 5 failure modes) | Mock |
| Published requirements as separate source-pinned records | `OpportunityRequirement`, `check_requirements` | `RequirementTests` (7) | Schema + Invariant |

**Rule-case coverage:**

| Rule | Pass | Fail | Unknown |
|---|---|---|---|
| `PILOT-ACTIVE-001` | A × data | A × ops (paused) | **none — open decision O1** |
| `PILOT-PROGRAM-002` | A × data | D × data (`not_participating`) | E × data (no record) |
| `PILOT-AVAIL-003` | A × data (20 ≥ 12) | D × data (8 < 12) | B × data (not declared); E × data (sensitive context) |
| `PILOT-SKILL-004` | A × data (two corroborating declarations) | D × data (declared "lacks") | B × data (contested); E × data (inferred only) |

### D-004.10 — Candidate claims

| Requirement | Code | Tests | Level |
|---|---|---|---|
| Controlled types: skill, experience, interest, availability, work preference | `ClaimType`; typed values with no free text | `test_fixture_claims_cover_all_types_and_states`, `test_unsupported_claim_types_and_extra_fields_rejected` | Schema |
| Allowlisted codes from a versioned, org-scoped vocabulary | `ClaimVocabulary`, `VocabularyPin`; `check_claims` | `test_code_outside_vocabulary_rejected`, `test_wrong_or_foreign_vocabulary_rejected` | Invariant |
| `declared` / `inferred` / `unknown` / `contested` with state-appropriate provenance | `CandidateClaim` validator + JSON Schema `allOf` | `ClaimStateTests` (7), `test_malformed_claims_rejected_by_both` (13 cases) | Schema (both validators) |
| Evidence from the candidate's own profile/application, or a declared verification source | `check_evidence_records`, `CLAIM_EVIDENCE_BASES` | `EvidenceProvenanceTests` (6) | Invariant |
| Inferred values never silently authoritative | `check_claim_update` (`inferred_promotion`, `inferred_overwrite`); excluded from pass/fail and from conflicts | `InferredPromotionTests` (4), `test_inference_never_conflicts_with_or_overrides_a_fact` | Invariant + Support |
| Conflict detection | `values_conflict`, `detect_conflicts` | `ConflictTests` (6) | Invariant |
| Participation separate from claims | `ProgramParticipation` (authority-record evidence only); absence = unknown | `ParticipationTests` (5) | Schema + Invariant |
| Reject sensitive attributes and demographic proxies | extra=forbid, enum types, vocabulary restricted-term screen, `RetrievalRequest` shape | `AllowlistAndSensitiveFieldTests` (6) | Schema + Invariant — **the screen is not exhaustive** |

### D-004.11 — Evidence and retrieval boundaries

| Requirement | Code | Tests | Level |
|---|---|---|---|
| `EvidenceRecord` tied to exact source version and org | `EvidenceRecord`; `resolve_evidence_ids` | `CitationTests` (3) | Schema + Invariant |
| Derived `RetrievalChunk` tied to exact source version and org | `RetrievalChunk` (pointer is not a URL; content hash) | `FixtureTests` (3) | Schema |
| Reuses PR #4 source-version and source-check mechanisms | `check_version_kind`, `checked`, `require_current_and_allowed` | `test_wrong_version_kind_denied` and all admission tests | Mock |
| Cross-org exposure, guessed IDs | denied before any authority call or text load | `test_cross_org_chunk_denied_before_authority_or_store`, `test_guessed_chunk_id_denied_without_any_lookup` | Mock |
| Revoked access, stale, withdrawn, deleted, authority error, tampered content | per-chunk denial | `AdmissionTests` (12) | Mock |
| Chunk metadata never authorizes | `access_scope_hint` ignored; no self-authorizing fields | `test_revoked_access_denied_even_with_permissive_metadata`, `test_text_claiming_authorization_cannot_override_denial` | Mock |
| Non-disclosure of inaccessible records/chunks | `AdmissionOutcome.external_response` | `ExternalIndistinguishabilityTests` (2: six modes yield identical shape) | Mock |
| Prompt-injection text treated as untrusted data | `AdmittedChunk.trust = "untrusted_data"`; text never parsed | `PromptInjectionTests` (3) | Mock — **cannot show a model ignores injected instructions** |

## Compatibility with PR #4

- **Schemas:** each of the 7 PR #4 schema files changes in exactly two lines, `$id` and `x-contract-version` (`git diff --numstat 2e63a93`: `2 2` for each). `Pr4CompatibilityTests.test_pr4_schema_bodies_unchanged` pins SHA-256 digests of the bodies, excluding those two keys, as merged on `main`.
- **Code:**
  - Only `models.py` changed, with the version label plus two **optional** `SourceSystemCapabilities` fields that default to empty.
  - `SourceSystemCapabilities` is not an exported schema.
  - `invariants.py`, `source_checks.py`, the PR #4 fixture and the PR #4 test modules are unchanged, and all PR #4 tests still pass.
- **Implications:**
  - Schema `$id`s move to `…/schemas/0.2.0-dev.foundations.2/…`.
  - Anything resolving the old `$id`s by string (none exists today) would need updating.
  - Semver pre-release precedence places `0.2.0-dev.foundations.2` after `0.2.0-dev.foundations`.

## Guarantees NOT established by this PR

1. **An eligibility engine.** Results are hand-written expected labels. The support verifier does not choose inputs, so it cannot detect an omitted relevant input, beyond the absence conditions it checks.
2. **Live authorization and freshness.** Every source check runs against an in-memory mock. No Drupal ACL, delegation, revision lookup or permission-change propagation is exercised.
3. **Index behavior.** There is no vector store, embedding, chunking, ingestion, invalidation or rebuild. The "stale index entry" test proves only that admission does not trust the index.
4. **Prompt safety.** Marking text `untrusted_data` does not make a model ignore it. Context assembly and model-side defenses are out of scope.
5. **Side channels.** Indistinguishable response bodies do not address timing, rate limiting or log exposure. Internal `DenialCode`s must be protected wherever they are recorded.
6. **Declared-vs-inferred honesty at the source.** Whether an adapter labels a value as *declared* only when the candidate explicitly stated it is the adapter's responsibility. The contract prevents relabeling and excludes inferences from decisions; it cannot inspect the source text.
7. **Completeness of the restricted-term screen and vocabularies.** These are defense-in-depth. Fairness, legality and accessibility of real criteria require qualified review (D-004.06).
8. **Schedule and accommodation handling.** Whole weekly hours do not establish schedule compatibility, and accommodation processes are not modeled.
9. **Record-set completeness.** Absence-based outcomes (`participation_not_recorded`, `no_mandatory_qualification`, `required_hours_not_published`, `availability_not_declared`) assume the context is complete. Only the authority can establish completeness.
10. **Non-Python consumers.**
    - JSON Schemas now carry the claim-state rules, the reason-code table and the decision derivation.
    - They do not carry cross-record rules: vocabulary membership, conflicts, provenance, outcome support, or scope/version matching. A test documents these gaps.

## Open decisions requiring owner approval

| # | Question | Current encoding (reversible) | Why approval is needed |
|---|---|---|---|
| **O1** | A genuine `unknown` for `PILOT-ACTIVE-001`? `Opportunity.status` is a required authoritative field, and under refinement B status-integrity failures fail closed, so no genuine-unknown input exists in today's contracts | No `unknown` reason code for this rule. Adding one later only widens accepted values, which is additive | Options: (a) accept the rule as pass/fail only; (b) add an unestablished/unpublished status to `Opportunity`, which changes a PR #4 schema; (c) source status from a separate record. **Recommend (a).** |
| O2 | Should `EligibilityResult` link to a specific `Application`? | No link; results are per candidate × opportunity × policy version | Affects how D-004.03/.04 review flows reference eligibility |
| O3 | Must `ClaimVocabulary` and `PolicySet` content carry their own Drupal source references? Policy does today; vocabulary is version-pinned only | Vocabulary has no `source_ref` | Governance/provenance of vocabulary changes |
| O4 | Do any additional requirement kinds belong in the pilot (e.g. schedule windows, location mode)? | Only `weekly_hours` and `mandatory_qualification` | Fairness/accommodation review before adding |
| O5 | How should outcomes cite opportunity-subject evidence? | `EvidenceRecord` supports opportunity subjects, but outcomes cite requirements, which carry their own source refs | Recommendation/explanation PRs may need direct opportunity evidence citations |

## Test evidence

**Run environment:** fresh `git clone` of branch `contracts/v0.2-eligibility-evidence` at commit `b99158f2bf64eec961b473e52e0856865dd452ef`; new virtualenvs; Python 3.13.17 (Linux).

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
Ran 185 tests in 0.527s

OK (skipped=9)
```

The 9 skips are the JSON Schema conformance tests (4 from PR #4, 5 new), skipped with a visible reason when the dev dependency is absent.

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
Ran 185 tests in 0.707s

OK
```

- **Per module:**

  | Module | Tests |
  |---|---|
  | `test_identity` | 16 |
  | `test_records` | 37 |
  | `test_source_versions` | 18 |
  | `test_schemas` | 8 |
  | `test_json_schema_conformance` | 9 |
  | `test_claims` (new) | 34 |
  | `test_eligibility` (new) | 40 |
  | `test_evidence` (new) | 23 |

- All 185 tests reported `ok`; none failed, errored or skipped. Many tests iterate subTests.
- PR #4 contributed 81 tests; this PR adds 104.
- Only Python 3.13.17 was tested. `jsonschema` is the only pinned dev dependency.

**Supplementary local checks (not committed tooling):**

- **pyflakes**, run from a scratch virtualenv only: clean on `rap_contracts/` and `tests/`.
- **Mutation checks.** On scratch copies, each of the 15 safety boundaries below was disabled individually, and every one caused at least one test failure (failing-test counts in brackets):
  - qualification fail without a declared "lacks" claim [1];
  - inferred/contested claims accepted for pass/fail [2];
  - cross-org admission check removed [5];
  - live authority check removed [11];
  - content-hash check removed [2];
  - unknown chunks omitted from the external response [3];
  - conflict detection disabled [2];
  - inferred promotion allowed [1];
  - unknown given precedence over fail [4];
  - an integrity code allowed as an unknown reason [4];
  - candidate-statement provenance check removed [1];
  - decision rule removed from the committed schema file only [4];
  - text loaded before the authority check [9];
  - participation-conflict check removed [1];
  - policy source pin not compared [1].
- **Defects found and fixed during development:**
  - `RetrievalChunk.text_pointer` accepted a URL, contradicting its contract; it now excludes `:`.
  - A test-side substring scan was replaced by an exact-shape assertion.

<details>
<summary>Full verbose test output (dev requirements, commit b99158f)</summary>

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
test_decision_must_follow_outcomes (test_eligibility.DecisionConsistencyTests) ... ok
test_fail_dominates_unknown (test_eligibility.DecisionConsistencyTests) ... ok
test_one_outcome_per_rule (test_eligibility.DecisionConsistencyTests) ... ok
test_unknown_reason_codes_cannot_express_integrity_failures (test_eligibility.DecisionConsistencyTests) ... ok
test_active_rule_has_no_unknown_outcome_pending_o1 (test_eligibility.FixtureCaseTests) ... ok
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
test_pr4_fixture_and_capabilities_still_valid (test_schemas.Pr4CompatibilityTests) ... ok
test_pr4_schema_bodies_unchanged (test_schemas.Pr4CompatibilityTests) ... ok
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
Ran 185 tests in 0.707s

OK
```

(Fully qualified test IDs shortened to `module.Class` for width.)

</details>

## Out of scope (deferred)

- D-004.03 human review authority, D-004.04 escalation, D-004.08 idempotency/audit, D-004.09 reason codes for review, D-004.12 evaluation fixtures.
- The deterministic eligibility engine itself.
- Drupal, production RAG, agents, Temporal, LangGraph, LangFuse, hosted infrastructure, CI expansion, paid inference.

## Freeze status

**Not frozen.** A freeze requires the remaining D-004 areas, the open decisions above, and an explicit owner decision.
