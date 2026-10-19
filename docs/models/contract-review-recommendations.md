# Contract Review — Recommended Dispositions (Not Yet Approved)

**Artifact status:** PROPOSED / decision support only
**Review owner:** Project owner
**Decision context:** D-001 through D-003 and the confirmed candidate lifecycle
**Source:** Prior twelve-decision contract review recommendations, consolidated here for GitHub review
**Important:** A PR merge **does not** itself imply approval of this decision list. Explicit sign-off is required before contract freeze.

## Confirmed independently

**Candidate lifecycle:** A person registers in Drupal, develops a reusable profile, and submits one or more distinct applications against programs or opportunities. The account, candidate identity, profile, and application are separate concepts.

## Twelve open contract decisions

| # | Area | Recommended disposition | Acceptance concern |
|---|---|---|---|
| 1 | Identity | A Drupal account links to one organization-scoped Candidate per organization, with potential separate Candidates across organizations. IDs are opaque and independent of Drupal UID. | No implicit cross-organization data sharing. |
| 2 | Drupal entities | Distinct, revisionable CandidateProfile, Application, and Opportunity *logical* entities. Prefer content entities provisionally; choose physical module/bundle layout later. | Submitted applications preserve their own history; profile updates do not rewrite them. |
| 3 | Human authority | Pilot reviewer: program coordinator. `approve_for_follow_up` authorizes outreach/consideration only. | No model-originated hiring, final placement, denial, or admission. |
| 4 | Failed verification | Route failed verification to a separate escalation with `request_information` or `dismiss_suggestion` actions, not normal approval. | Normal review approval must require verified, fresh evidence. |
| 5 | Eligibility | `ineligible` means not eligible **for one opportunity under one specified policy revision**; never an overall applicant rejection. | Render rule-specific explanations; negative results cannot silently become disposition. |
| 6 | Pilot policies | Retain active status, program participation, declared availability, and published qualification categories as **fictional configurable rules**. Missing or ambiguous evidence leads to `needs_information`; do not infer lack of skill from absent evidence. | Real policies require accessibility, accommodation, fairness, and legal review. |
| 7 | Source versioning | `SourceReference` supports Drupal native entity revision **or** validated logical snapshot token for unrevisioned sources such as User. | Authorization and freshness are rechecked against Drupal; permission changes invalidate access. |
| 8 | Review writes | Drupal authoritative write service enforces transactions, idempotency keys, and append-only event history. Same key/same payload returns original; same key/conflicting payload fails. | Pydantic field validation is not storage enforcement. |
| 9 | Reasons | Require structured `reason_code`; optional `comment`, with fuller explanation conditionally required for exceptions or dismissals. | Review UI should not force unnecessary free text on routine approvals. |
| 10 | Claims | Use a small allowlist: source-backed skills, experience, interests, declared availability, work preferences, confirmed program participation. Explicit `declared/inferred/unknown/contested` state. | No unreviewed demographic/proxy/medical data in AI matching; inferred claims are never promoted silently to authoritative facts. |
| 11 | RAG | Retrieval requires organization scope, Drupal access checks, source revisions, withdrawal handling, and immediate fail-closed behavior on access/freshness failures. | Revalidate before model context and before reviewer action; a vector index is never authoritative. |
| 12 | Evaluation | Convert initial 12 labels into reproducible case fixtures and reviewer-adjudicated rubrics; maintain a genuinely separate held-out set. | No claimed benchmark results without an actual run and measured observations. |

## Recommended additional baseline rule (proposal)

Before calling any LLM, execute a deterministic eligibility and explanation baseline. Measure whether an AI model adds recommendation utility against this baseline while keeping hard-policy violations, unauthorized retrieval, and stale evidence as blocking regressions.

## Proposed review gate

- [ ] Project owner approves or revises #1–#12 explicitly.
- [ ] Open disagreements are recorded with their impact on contracts.
- [ ] Cross-record organization scoping, freshness, and human authorization have negative tests.
- [ ] Source versions, review transitions, idempotency semantics, and structured reasons are reflected in Contract v0.2.
- [ ] Synthetic cases and evaluation rubric are versioned, with no invented metrics.
- [ ] Physical Drupal implementation and AI tool choices remain undecided unless separately approved.
- [ ] Then and only then authorize the Contract v0.2 freeze PR and Slice 0 planning.

## Decision log

| Date | Event | Status |
|---|---|---|
| 2026-10-15 | Owner confirmed the account → profile → multiple applications lifecycle. | **Accepted lifecycle only** |
| 2026-10-19 | These twelve recommended dispositions were transferred into GitHub for review. | **Pending owner approval** |
