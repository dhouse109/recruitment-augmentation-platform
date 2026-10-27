# Contract v0.2 Foundations — Traceability, Evidence and Limits

**Document ID:** RAP-CONTRACT-002-F  
**Contract version:** `0.2.0-dev.foundations` — **partial development version; proposed; NOT frozen**  
**PR:** #4 (Contract Foundations)  
**Base:** `main` @ `dfebdf06a1b43b4999cf420f5337b4b5da91e85a` (merge of PR #3)  
**Scope:** D-004.01, D-004.02, and the *representation* requirements of D-004.07 only  
**Code:** [`contracts/`](../../contracts/README.md)

This PR implements **portable reference contracts** with Pydantic v2. Pydantic is used for these reference contracts only; this is **not** a selection of the application runtime, persistence layer, Drupal modules or orchestration design. All other D-004 areas (.03–.06, .08–.12) are deferred to later PRs.

## Owner decisions applied (2026-10-27)

| # | Decision | Encoded as |
|---|---|---|
| 1 | Profiles are organization-scoped; no automatic cross-org projection/sharing | `CandidateProfile.organization_id` + candidate/org equality checks; no account-level profile type exists |
| 2 | Profile = version envelope + metadata; claims deferred | `CandidateProfile` has `id`, `organization_id`, `candidate_id`, `source_ref` only |
| 3 | Submissions pin exact historical versions without copying claim values; fail closed when unavailable/withdrawn/unauthorized; no circular self-reference | `SubmissionSnapshot.profile_ref` (full ref) + `application_version` (bare version of the application's own source entity); `resolve_submission_evidence` asks only for pinned versions and rejects substitution |
| 4 | `withdrawn`/`closed` terminal; reopen/amend **unsupported in this version**, not permanently prohibited | `ALLOWED_APPLICATION_TRANSITIONS`; one submission per application |
| 5 | ≥1 program/opportunity target, consistent org; duplicate policy open | `ApplicationTarget` validator + `check_record_set` |
| 6 | Explicit version kind + adapter capabilities; SHA-256 initial but not the only method; provenance and responsibilities stated | `NativeRevision` / `LogicalSnapshot` discriminated union; `SourceSystemCapabilities`; open `SnapshotMethodRegistry` |
| 7 | Identity reference not changeable via ordinary updates; opaque portable IDs | `check_candidate_update`; frozen models; typed-prefix ID pattern |
| 8 | Partial dev version, pinned Pydantic, stable schema IDs, not frozen | `CONTRACT_VERSION`, `pydantic==2.13.5`, versioned `$id`, `x-contract-status` |

## Evidence levels used below

- **Schema** — enforced by the Pydantic model and (where expressible) the generated JSON Schema.
- **Invariant** — enforced by a pure Python function over in-memory records (`invariants.py`, `source_checks.py`). States the rule an authoritative store must enforce; does not enforce it in storage.
- **Mock** — exercised against `FixtureSourceAuthority`, an in-memory test double. Demonstrates fail-closed *plumbing* only.
- **Not established** — requires Drupal integration or a later PR.

## Traceability matrix

### D-004.01 — Identity, subject and organization scope

| Requirement | Code | Tests | Evidence level |
|---|---|---|---|
| Account is identity, not `candidate_id` | `Candidate.identity_source: SourceEntityKey`; `check_identity_source` | `test_identity_source_must_be_declared_identity_type`, `test_personal_data_shaped_and_mistyped_ids_rejected` (`user_9001`) | Schema + Invariant |
| ≤1 Candidate per account per organization | `check_identity_mappings` (`identity_conflict`) | `test_second_candidate_for_same_account_in_same_org_rejected` | Invariant — **DB uniqueness not established** |
| Same account → distinct org-scoped Candidates | fixture `candidate_demo_a` / `candidate_demo_c` | `test_same_account_gets_distinct_candidates_in_two_orgs`; `candidate_id_reused` test | Invariant |
| Opaque, PII-free portable IDs | typed-prefix lowercase pattern (blocks `@`, `.`, spaces, upper case) | `test_personal_data_shaped_and_mistyped_ids_rejected`, `test_unknown_fields_rejected` | Schema (partial) — **opacity is an ID-issuer obligation; a pattern cannot prove it** |
| Identity reference immutable via ordinary update | `check_candidate_update`; `frozen=True` | `test_identity_source_change_rejected`, `test_organization_change_rejected`, `test_attribute_assignment_blocked` | Invariant + Schema |
| No cross-org consolidation / disclosure | org-equality checks on every cross-record reference | `CrossOrganizationReferenceTests` (3 cross-record negatives, 1 model-level negative, 1 positive) | Invariant — **cross-org *match* rejection deferred to matching contracts; live cross-org read denial not established** |

### D-004.02 — Profile / application / opportunity separation

| Requirement | Code | Tests | Evidence level |
|---|---|---|---|
| Distinct logical records | `CandidateProfile`, `Application`, `Opportunity` (+ minimal `Program`) | all fixtures validate; `test_fixture_record_set_is_consistent` | Schema + Invariant |
| One candidate, two independent applications | fixture `application_demo_a_data` / `application_demo_a_web` | `test_one_candidate_two_independent_applications`, `test_withdrawing_one_application_leaves_the_other_untouched` | Invariant |
| Profile revision does not mutate submitted snapshot | `SubmissionSnapshot` pins `profile_ref`; `check_application_update` (`submission_rewrite`) | `test_profile_revision_does_not_mutate_submitted_snapshot`, `test_rewriting_pinned_profile_to_newer_revision_rejected`, `test_removing_submission_rejected` | Invariant — **Drupal revision retention not established** |
| Pinned evidence resolves without substituting newer versions | `resolve_submission_evidence`, `checked` (`source_substitution`) | `PinnedEvidenceResolutionTests` (10 tests) | Mock |
| Independent status and submission history | `ApplicationStatus`; transition table; status↔submission coupling (model + JSON Schema `allOf`) | `test_full_transition_matrix` (16 pairs), `test_status_submission_coupling`, `test_reopen_via_update_rejected`, `test_submission_added_only_by_draft_to_submitted` | Schema + Invariant |
| Program/opportunity target, consistent org | `ApplicationTarget` (`anyOf` in schema); `check_record_set` | `TargetTests` (4 tests) | Schema + Invariant |
| Portability (non-internship) | `Opportunity.opportunity_type` open label | `test_job_opportunity_uses_same_contracts` (`org_demo_002`, `job`) | Schema |

### D-004.07 — Source version semantics (representation)

| Requirement | Code | Tests | Evidence level |
|---|---|---|---|
| Native revision vs logical snapshot, honestly labeled | `SourceVersion` discriminated union; `:` excluded from native revision IDs | `test_both_version_kinds_validate`, `test_malformed_versions_rejected` (14 cases incl. snapshot token labeled native) | Schema |
| Native revision when available, otherwise snapshot (incl. User) | `check_version_kind` against `SourceSystemCapabilities` | `CapabilityCheckTests` (8 tests), `test_all_fixture_refs_match_declared_capabilities` | Invariant — **capabilities are adapter declarations, not verified Drupal facts** |
| Snapshot method not hard-coded | `SnapshotMethodRegistry`; `DEFAULT_SNAPSHOT_METHODS` holds `sha256-canonical-json/v1` | `test_additional_method_can_be_registered_without_contract_change`, `test_unregistered_snapshot_method_rejected` | Invariant |
| Token provenance | `LogicalSnapshot.captured_at`, `captured_by`, `method`; `canonical_json_sha256` reference definition | `test_fixture_tokens_reproduce_from_declared_payloads`, `test_canonicalization_ignores_key_order` | Schema + Invariant — **token-to-record correspondence is verifiable only by the authority** |
| Version and access are separate checks | `SourceCheckResult.version_status` / `access_status`; `require_current_and_allowed`, `require_historical_resolvable` | `FreshnessAndAccessSeparationTests` (5 tests) | Mock |
| Reject stale, withdrawn, deleted, newly inaccessible | same gates | `test_version_and_access_are_independent`, `test_newly_inaccessible_source_rejected` | Mock — **live Drupal revalidation not established; "even when the derived index entry persists" deferred to D-004.11** |

## Snapshot token responsibilities

| Party | Responsibility |
|---|---|
| Adapter (producer) | Chooses version kind from declared capabilities; computes the token with a registered method over the authoritative record; records `captured_at` and `captured_by`. Which record fields enter the payload is **OPEN** per entity type. |
| Consumer | May check shape and method-specific token format (`check_version_kind`). Format validity says **nothing** about freshness or authorization. |
| Authority (live Drupal) | Sole source of truth on whether the exact version is current, superseded-but-retained, withdrawn, deleted or unavailable, and whether the principal may read it. |

`sha256-canonical-json/v1`: UTF-8 JSON, sorted keys, separators `,` and `:`, no NaN/Infinity; token `sha256:` + lowercase hex. Additional methods are added by registering a method ID and token pattern; the portable contract does not change.

## Guarantees NOT established by this PR

Local schema, invariant and mock tests **cannot** establish:

1. **Uniqueness under persistence/concurrency** — one Candidate per (organization, account) requires a database constraint in the authoritative store.
2. **Live authorization** — `principal_id` in the mock is an opaque string, not authentication. No Drupal ACL, role or delegation behavior is tested.
3. **Source freshness** — the mock reports whatever state a test configures. No live revision lookup occurs.
4. **Revision retention** — pinned profile/application versions must remain retrievable in Drupal for as long as submissions need them. **Retention is a future Drupal integration requirement**; until it is designed, resolution of a purged version fails closed (`source_unavailable`).
5. **Snapshot correctness** — that a logical snapshot token corresponds to the record content can only be checked by the authority.
6. **Immutability in storage** — frozen Pydantic objects and update checks do not stop a database row from being rewritten.
7. **Transactionality, idempotency, append-only audit** — D-004.08, out of scope.
8. **Derived-index invalidation** — D-004.11, out of scope.
9. **Non-Python consumers** — JSON Schemas carry structure (including status↔submission and target `anyOf` rules) but not cross-record invariants, version-kind capability checks or source-check policy. JSON Schema validation of fixtures was not run (no additional dependency added).

## Unresolved semantics (documented, not encoded)

| # | Question | Current position |
|---|---|---|
| U1 | Does a Candidate have its own authoritative Drupal record, or is it an adapter mapping only? | Not modeled: `Candidate` has no `source_ref`. Adding one is additive. |
| U2 | Account merge / identity correction process | Requires a separately designed, audited process; ordinary updates reject it. |
| U3 | Reopen, post-submission amendment, resubmission | Unsupported in this version; requires explicit contract review. |
| U4 | Duplicate applications to the same target | OPEN; Drupal/business policy. |
| U5 | Audit-only access to withdrawn applications and their pinned evidence | Not designed. Evidence resolution fails closed (`application_withdrawn`). |
| U6 | Physical capture of `application_version` without self-reference (submit-transition revision vs separate submission entity) | Adapter concern; contract holds a bare version of the application's own entity. |
| U7 | Snapshot payload scope per entity type; snapshot staleness/TTL | OPEN; no expiry semantics encoded. |
| U8 | Ordering/comparison of native revision IDs | Not assumed; IDs are opaque strings. |
| U9 | Profile lifecycle (withdrawn/deleted profile) beyond version status | Not modeled; only reported via `SourceCheckResult`. |
| U10 | Additional `SourceSystem` values for other ATS adapters | Enum extension is additive; requires review. |
| U11 | `Organization` and full `Program`/`Opportunity` attributes | Minimal envelopes only; attributes belong to D-004.06/.10 work. |

## Test evidence

**Run environment:** fresh `git clone` of branch `contracts/v0.2-foundations` at commit `0512de3955c0f790dc1171cc51337278cf253cd7`; new virtualenv; Python 3.13.17 (Linux); dependencies installed only from `contracts/requirements.txt`.

```text
$ python -m pip freeze
annotated-types==0.8.0
pydantic==2.13.5
pydantic_core==2.46.5
typing-inspection==0.4.4
typing_extensions==4.16.0

$ python -m rap_contracts.schema_export --check
schema drift: NONE

$ python -m unittest discover -s tests -v
...
Ran 71 tests in 0.152s

OK
```

Per module: `test_identity` 16, `test_records` 31, `test_source_versions` 18, `test_schemas` 6. Several tests iterate subTests (e.g. 16 transition pairs, 14 malformed-version cases, 7 invalid IDs). Python versions other than 3.13.17 were not tested.

**Supplementary local mutation check (not committed tooling):** seven invariants were individually disabled on a scratch copy — identity conflict, submission rewrite, `:` exclusion in native revisions, substitution detection, superseded-as-current, reopen-from-closed, snapshot-for-revisionable-type. Each mutation caused at least one test failure.

<details>
<summary>Full verbose test output</summary>

```text
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
Ran 71 tests in 0.152s

OK
```

(Fully qualified test IDs shortened to `module.Class` for width.)

</details>

## Out of scope (deferred)

D-004.03 human review authority, .04 escalation, .05/.06 eligibility and policy rules, .08 idempotency/audit, .09 reason codes, .10 claim vocabulary, .11 RAG authorization/index invalidation, .12 evaluation fixtures. No Drupal runtime, AI agents, retrieval, paid inference, hosted infrastructure or CI.

## Freeze status

**Not frozen.** A Contract v0.2 freeze requires the remaining D-004 areas, reviewed fixtures and tests, and an explicit owner decision.
