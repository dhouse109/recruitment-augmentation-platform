# ADR-0004 — Contract Review Gate: Twelve Domain Decisions

**Decision ID:** D-004  
**Status:** Accepted (requirements and architecture decisions; contract implementation is still pending)  
**Decision date:** 2026-10-19  
**Decision owner:** Project owner  
**Approval basis:** The owner explicitly authorized using the coach's recommended answer as the approved answer for each outstanding contract-review decision.  
**Supersedes:** The **pending approval status**, not the historical contents, of `docs/models/contract-review-recommendations.md`.  
**Related decisions:** D-001, D-002, D-003 and the confirmed candidate lifecycle  
**Next gate:** Contract v0.2 revision and verification

## Context

The first contract review identified twelve choices in identity, Drupal entity modeling, human oversight, policy/eligibility, source versioning, write semantics, claim governance, retrieval access, and evaluation. A prior PR imported them as proposals, without accepting them. The project owner has now expressly delegated selection of the previously recommended answer for **each** outstanding item and authorized proceeding.

These are accepted **requirements-level design constraints**. They are not evidence that the v0.1 Pydantic examples or JSON Schemas already satisfy them, or that Drupal behavior is running.

## Confirmed lifecycle (existing approval)

A person registers with Drupal, develops a reusable candidate profile, and submits one or more **distinct applications** against programs or opportunities. Account, Candidate, CandidateProfile and Application are different domain concepts.

## Accepted dispositions — all 12 items

### D-004.01 — Identity, subject, and organization scope

A Drupal account authenticates a person; it is **not** their portable `candidate_id`. Within an organization, one user account maps to at most one stable Candidate record; the same account may have distinct, organization-scoped Candidate identities in different organizations. Portable IDs must be opaque and must not contain or derive from personal information. Cross-organization disclosure or identity consolidation is not permitted by default.

**Test obligation:** Reject conflicting account-to-Candidate identity mappings within an organization and all cross-org reads/matches unless separately authorized by a future design.

### D-004.02 — Profile / application / opportunity separation

Use distinct, versionable **logical** `CandidateProfile`, `Application`, and `Opportunity` records. Each application has independent status and submission history; changing a reusable profile cannot silently rewrite a past submitted application. Prefer revisionable Drupal content entities during implementation study, but the **physical** schema, bundles, and Drupal modules remain open.

**Test obligation:** Demonstrate one candidate with two independent applications and a profile revision that does not mutate submitted application snapshots.

### D-004.03 — Human review authority

For the first pilot, an authenticated nonprofit **program coordinator** reviews suggestions. `approve_for_follow_up` authorizes investigation/outreach only; it is not a placement, hiring, offer, admission, or rejection decision. Only an authorized human can record a review disposition. Model output alone cannot assert approval.

**Test obligation:** Reject unauthenticated, unauthorized, wrong-scope, or machine-origin approval requests. The contract's `actor_type="human"` alone is insufficient authorization.

### D-004.04 — Failed verification and escalation

A failed, stale, or unresolved verification cannot enter the normal verified recommendation approval path. It enters a distinct human escalation path with `request_information` or `dismiss_suggestion`. Normal `approve_for_follow_up` requires verified evidence, live authorization, current source revisions, and a valid current policy.

**Test obligation:** Reject normal approval of any recommendation whose verification is failed, stale, escalated or unresolved; allow only authorized escalation actions.

### D-004.05 — `ineligible` is opportunity- and policy-scoped

`ineligible` is a **deterministic assessment of one opportunity under one pinned policy/version**, not a global judgment of an applicant. It cannot automatically trigger rejection, exclusion from other opportunities, or a final recruitment outcome. UI explanations must expose the exact rule and evidence/unknown status.

**Test obligation:** Verify that an ineligible result for opportunity A does not alter eligibility for opportunity B or create a candidate-level rejection event.

### D-004.06 — Four fictional policy categories, with unknown states

Adopt as **synthetic pilot fixtures** only: active opportunity status, confirmed pilot participation, candidate-declared availability versus published hours, and explicitly published required qualifications. Policy rules must be deterministic, versioned, explained, and evaluated from authorized evidence. Unknown, missing, contested, or ambiguous data means `needs_information` when a requirement cannot be decided, **not assumed disqualification or guessed qualifications**. An explicit, reliable contradictory fact may support an opportunity-specific `ineligible` result. Real-world rules require legal, fairness, accessibility and accommodation review before deployment.

**Test obligation:** Exercise fail/pass/unknown for every rule, especially missing skill or availability evidence and accommodation-sensitive cases.

### D-004.07 — Source version semantics

`SourceReference` must represent a source's version **honestly**: native Drupal revision when available, otherwise a validated logical snapshot token (including Drupal User when appropriate). A snapshot token must never be labeled as a native revision. Revision/snapshot and authorization freshness are separate checks. Source revisions and permission changes must be revalidated against live Drupal authority before use in model context and before consequential reviewer action.

**Test obligation:** Validate both version kinds and reject stale, withdrawn, deleted, or newly inaccessible sources even when their derived index entry persists.

### D-004.08 — Review idempotency and append-only audit

The authoritative **Drupal review-write service** enforces authenticated reviewer attribution, an atomic transaction, a unique idempotency key, and durable audit/event recording. Retrying the same key with the same semantic payload returns the prior outcome without duplicate side effects; reusing that key with conflicting payload must fail. Corrections are new events; prior events are retained according to a future retention policy. Pydantic and AI workflow validation alone cannot enforce persistence guarantees.

**Test obligation:** Execute retry, concurrent duplicate and conflicting-reuse cases against the actual write service when implemented.

### D-004.09 — Reason codes and conditional narrative

All `ReviewDecision` records require a structured, versioned `reason_code` from an allowed vocabulary. Human `comment` is optional for routine approval and conditionally required for exceptions, dismissals or cases where the code alone is insufficient to support review. Store neither unsupported accusations nor unrelated candidate-sensitive information in comments.

**Test obligation:** Accept routine documented approval without free text, reject unknown reason codes, and enforce narrative rules when required.

### D-004.10 — Bounded candidate-claim vocabulary

Start with a controlled, schema-validated vocabulary for source-supported skills, experience, interests, declared availability and work preferences; program participation is verified from an authoritative program/application source. Preserve `declared`, `inferred`, `unknown`, `contested` semantics. Inferred values are **non-authoritative proposals** and cannot silently become declared, confirmed, or verified facts. Unknown values cannot be populated by guessing. Do not feed medical/accommodation details, protected characteristics, unrelated demographic data, or unreviewed proxies into matching prompts or ranking.

**Test obligation:** Reject unsupported claim fields, unknown-with-fabricated-value, unapproved inferred-to-fact transitions, and restricted fields in evaluation/retrieval requests.

### D-004.11 — RAG authorization and source currentness

A vector/retrieval index is a **derived, disposable projection** of Drupal content. Organization-scope checks, live access control, withdrawal/deletion handling, and source version currentness must be applied **before any retrieved content enters model context and again before reviewer action**. Deny unsafe access immediately even when an index deletion/rebuild is pending. Retrieved documents and prompts are untrusted data, not instructions.

**Test obligation:** Test guessed chunk IDs, cross-organization references, revoked permissions, stale revisions, withdrawn records and prompt-injection text.

### D-004.12 — Evaluation fixtures, adjudication, and held-out separation

Convert the existing proposed evaluation labels into complete, versioned synthetic case fixtures, machine-readable expected outcomes, and a documented human review rubric. Adjudicate subjective expectations with a reviewer before reporting benchmark performance. Maintain a truly separate held-out set that has not been exposed to prompt selection. Pin code, policies, prompts, models, and source snapshots for comparisons; report per-case failures and cost/latency when measured. Never present example labels or earlier design-spike tests as an integrated benchmark.

**Test obligation:** Produce reproducible no-model baseline, explicit safety-gate results, per-case evaluation records, and a documented promotion decision once implementations exist.

## Additional approved engineering rule — deterministic baseline first

Before any paid model-dependent inference, deliver and test a **deterministic eligibility + explanation baseline** using synthetic fixtures. Compare model and agent approaches against the exact same permitted cases to establish incremental utility and cost. A gain in aggregate utility may **never** excuse cross-organization data exposure, policy-rule violations, stale/revoked evidence, or critical unsupported claims.

This is a sequencing decision, not approval of a specific runtime or model.

## Consequences for Contract v0.2

The next contract revision **must**:
1. Update source version structure for `native_revision` vs `logical_snapshot`.
2. Separate verified recommendation approval from verification-failure escalation and encode legal state transitions.
3. Add structured review `reason_code`, optional `comment`, and conditional validation.
4. Constrain candidate-claim vocabulary and keep AI-derived suggestions non-authoritative.
5. Preserve organization scope, application/profile revision semantics, versioned policy results and unknown-state behavior.
6. Include synthetically reproducible negative fixtures for authorization, stale sources, forbidden transitions, idempotency, and policy unknowns.
7. Identify guarantees needing Drupal integration tests and not misrepresent local contract-unit tests as proof of live authorization or transactionality.
8. Keep RAG and eval requirements traceable to accepted D-002 and D-003.

## What remains OPEN

- Exact Drupal module/entity approach and provisioned Drupal version.
- Whether to use a specific Python package topology, vector store, model vendor or model routing.
- Temporal/LangGraph/LangChain/LangFuse deployment boundaries and any development-framework selection; they remain intended demonstration technologies, not yet locked implementation choices.
- Review UI design, API transport and token delegation scheme.
- Data retention/privacy compliance design for any **future real-candidate deployment**; first pilot is synthetic only.
- Quantitative quality thresholds beyond zero-tolerance safety invariants (require empirical baselines).
- **Contract v0.2 implementation**, validation run, and formal freeze/implementation authorization.

## Decision status and approval semantics

This ADR accepts the **recommended answers to all twelve questions** under explicit project-owner delegation in conversation on 2026-10-19. It does **not** automatically freeze the current v0.1 type definitions. The project owner continues to review and merge PRs; no code may be claimed complete until evidence is present.

## References

- `docs/models/contract-review-recommendations.md`
- `docs/models/contract-review-checklist.md`
- `docs/models/domain.md`
- `docs/models/drupal-domain-mapping.md`
- `docs/models/contracts.md`
- `docs/decisions/ADR-0001-general-platform-nonprofit-pilot.md`
- `docs/decisions/ADR-0002-drupal-authoritative-reference-and-rag-boundaries.md`
- `docs/decisions/ADR-0003-versioned-agent-evaluation-and-prompt-promotion.md`
