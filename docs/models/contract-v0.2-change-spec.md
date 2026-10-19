# Contract v0.2 — Change Specification and Review Handoff

**Status:** PROPOSED implementation brief (not code authorization or contract freeze)  
**Date:** 2026-10-19  
**Source of authority:** [D-004](../decisions/ADR-0004-contract-review-dispositions.md) with D-001 through D-003  
**Input:** Proposed v0.1 domain contracts, mapping, schemas and synthetic evaluation cases  
**Target deliverable:** Reviewable v0.2 Pydantic v2 reference contracts + JSON Schemas + tests + fixture manifest + compatibility/migration notes  
**Dependency:** Accepted domain decisions are available; physical Drupal modules remain undecided

## Rules for contract implementers

- Do not quietly introduce runtime, model, module or persistence choices merely to make schema examples run.
- Model contracts are **portable**. Drupal source IDs and entity types belong in adapter/source-reference metadata, not domain identity keys.
- Treat authenticating Drupal users, querying current access, enforcing atomic writes and maintaining append-only storage as **service/integration responsibilities**, not guarantees of Pydantic objects.
- Use synthetic identities only; forbid production/client records in fixture data, tests, prompts, telemetry and screenshots.
- Expected outcomes are labels until an implementation actually runs. Do not invent pass counts or AI performance improvements.
- A mandatory field must have a documented reason; unknown/stale/contested inputs must be represented without coercing them into false facts.

## Type-level changes and target evidence

| Decision | Contract / boundary work | Test required |
|---|---|---|
| D-004.01 | Independent `Candidate.id`, `identity_source_ref`, `organization_id`; mapping identity invariant, one scoped Candidate per account. | Same account creates distinct Candidate identities across two orgs; duplicate identity within one org rejected; cross-org match rejected. |
| D-004.02 | Distinct `CandidateProfile`, `Application`, `Opportunity` with versioned refs and application snapshots. | One profile revision, two applications, no mutation of submitted application evidence. |
| D-004.03 | `ReviewDecision` follow-up only; authenticated principal and correct role checked at service boundary. | Reject actor spoofing, machine-submitted and wrong-scope approvals. |
| D-004.04 | Define `Recommendation` states and distinct `EscalationAction` or equivalent command; strict transition matrix. | Failed / stale verification cannot become `approve_for_follow_up`; request information or dismissal allowed under authorization. |
| D-004.05 | `EligibilityResult` keyed to opportunity, rule and immutable policy version; status enum includes `needs_information`. | Opportunity-specific negative result never creates global rejection. |
| D-004.06 | `PolicyRule` and `RuleOutcome` with deterministic known/unknown/fail semantics and reason/evidence references. | Each of four pilot rules has pass, fail, and unknown/ambiguous cases. |
| D-004.07 | Refactor `SourceReference` version into an explicit native-revision vs logical-snapshot representation. | Both forms validate; wrong-kind claims, stale sources and revoked permissions fail at adapter check. |
| D-004.08 | Add typed `HumanReviewCommand` and `AuditEvent` result with idempotency identity and source run references; clearly mark transaction enforcement as Drupal service duty. | Same key/same payload returns original; conflicting reuse fails; concurrent uniqueness demonstrated only in later Drupal integration tests. |
| D-004.09 | `ReviewDecision.reason_code` required; optional `comment`, with conditional explanation validator. | Unknown codes rejected; approval needs no free text; designated dismiss/exception cases require explanation. |
| D-004.10 | Allowlisted claim field/value contracts, `declared/inferred/unknown/contested` states, source lineage; restricted fields excluded. | Unknown+fabricated value fails; inferred cannot auto-confirm; sensitive/unapproved keys rejected. |
| D-004.11 | `RetrievalChunk` links to `SourceReference`, org and access/freshness metadata; authorization remains live-boundary check. | Stale/withdrawn/cross-org/unauthorized chunks never enter model context, even if index still contains them. |
| D-004.12 | `EvaluationCase`, pinned `EvaluationRun`, `CaseObservation`, reviewer rubric and split metadata. | Reproduce golden cases; held-out cannot be included in prompt-tuning loop; reports distinguish expected labels from measured observations. |

## State transition specifications to write before code freeze

1. Application: `draft` → `submitted` / `withdrawn` / `closed`; preserve immutable submission evidence. Define permitted reopen behavior explicitly rather than assuming it.
2. Recommendation: `pending_verification` → `ready_for_review` after independent verification, or `needs_information` / `escalated` / `obsolete` after failures or changes.
3. Review action: normal follow-up approval only from `ready_for_review` with current, authorized source evidence; escalation actions from `needs_information` or `escalated`.
4. MatchRun: specify stop/fail/timeout/cancel semantics and persist typed reason codes without inventing a Temporal topology yet.

## Execution acceptance evidence for a future v0.2 PR

- **File manifest:** source models, validation helpers, generated Schemas, pilot fixtures and separate tests with a clear README.
- **Reproducibility:** documented local command to install minimal dependencies and run unit tests from a clean checkout; pinned versions where useful.
- **Results:** paste or attach actual test-command output (pass/fail counts), not estimates from prose.
- **Negative coverage:** organization scopes, source freshness, forbidden review transitions, unsupported evidence, unknown-state behavior, claim allowlist, idempotency semantic examples.
- **Traceability:** a matrix from D-004.01–D-004.12 to source code, tests and expected outcomes.
- **Data policy:** fixtures wholly fictional; no PII, application data, API keys or client materials.
- **Caveats:** model-level/mock tests cannot establish actual Drupal ACL, atomic write or RAG index invalidation; separate integration gates are required.
- **Portability:** same domain contracts accept one fictional job opportunity in addition to nonprofit internships.

## What must remain out of scope

- Launching Drupal, AI services, or agent workflows.
- Real applicant processing, hiring/placement automation or fairness claims from synthetic data.
- Selecting a particular vector store, cloud, provider, Django/FastAPI service, or multi-agent implementation without an ADR.
- Inventing measured LLM scores, cost savings or accuracy benefits.
- Marking the contract **frozen** based only on model/unit-test success.

## Recommended next PR sequence

1. **This PR:** accept D-004 and define the v0.2 contract change obligations. No executable application code.
2. **Next PR:** implement/reference v0.2 portable typed contracts, generate JSON Schemas, add synthetic cases and unit tests; include evidence and review before considering freeze.
3. **Separate planning PR:** agree on deterministic Slice 0, Drupal integration plan, Claude execution instructions and spending boundaries.
4. **Implementation PRs:** only after stage gates are explicitly approved by the project owner.

The first **implementation** milestone remains deterministic eligibility and human-review semantics on fully synthetic fixtures, not a live AI placement system.
