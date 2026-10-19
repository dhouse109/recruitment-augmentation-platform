# ADR-0002 — Drupal Authoritative Reference and Retrieval Boundaries

**Decision ID:** D-002 (formerly proposal P-002)  
**Status:** Accepted  
**Date:** 2026-10-12  
**Project:** Recruitment Augmentation Platform  
**Decision owner:** Project owner, explicitly approved in conversation  
**Supersedes:** The open source-of-truth and Drupal/RAG choices recorded in Foundation v0.2  
**Implementation status:** Not built; implementation details remain open

## Context

The original candidate-placement interview described Drupal-backed content and an external agent workflow. The new project will showcase AI **inside and outside Drupal** while keeping the general-purpose recruitment domain portable. We need one authoritative business system, controlled evidence retrieval, and independently verifiable authorization/freshness behavior.

**Evidence caution:** The interview describes a RAG pipeline but does not establish the original production retrieval implementation. This decision is for a new independent synthetic-data reference build, not a statement about client code.

## Decision

1. **Drupal is mandatory as the authoritative reference application for the first integrated nonprofit pilot.** It owns fictional user registration, candidate profile/application records, opportunity/program/policy records, and authorized human-review outcomes.
2. Keep **core platform contract IDs independent of Drupal IDs**. An adapter maps the authoritative Drupal entity ID + revision + organization context into portable candidate, opportunity, policy, evidence, and review contracts.
3. Candidate profile and application are distinct concepts. A Drupal `User` is an account/identity, a versioned candidate profile contains declared recruitment data, and an `Application` records participation in a specific program/opportunity. Exact Drupal entity/bundle/module representation is open.
4. **Structured eligibility facts are fetched through authoritative typed APIs**, not vector inference. Deterministic eligibility remains authoritative.
5. **RAG is a derived, permission-aware retrieval projection**, not the source of truth. Index permitted unstructured application answers, opportunity descriptions, and consented synthetic document text with organization/program scope, source entity/revision, evidence pointer, and index version.
6. Enforce authorization before any material enters model context, re-check current source revisions before promoting a recommendation, and invalidate/rebuild derived index entries after changes/withdrawal.
7. AI inside Drupal must be demonstrable through a coordinator-facing, evidence-aware summary/review surface. The mechanism (Drupal AI modules, custom Drupal UI, or Drupal UI calling an external service) is **open**.
8. AI outside Drupal uses a controlled Python-facing API/adapter for reasoning, verification, and reviewable suggestions; no agent has unrestricted Drupal business-record write authority.
9. Human program staff remain the authority for follow-up review. Autonomous placement, hiring, admissions, rejections, and offers are excluded.
10. The first **offline contract slice may use synthetic adapters**; this does not waive the mandatory Drupal/RAG integrated-pilot acceptance gate.

## Rationale

- Makes ownership and provenance explicit instead of letting an index become a competing truth store.
- Demonstrates both CMS-native AI experience and external agent engineering without hard-coding Drupal into reusable domain models.
- Separates deterministic policy/permissions from probabilistic reasoning.
- Allows simulated source edits, revocation, stale index tests, and documented consent/retention boundaries using synthetic data.

## Tradeoffs and constraints

- More integration work and stronger revision/authorization testing than a standalone Python demo.
- Derived index freshness and ACL semantics are now correctness-critical engineering concerns.
- Drupal as the reference application is not an assertion that other ATS/CMS adapters are implemented.
- Real applicant data is **prohibited** until a separate privacy, fairness, legal, security, and operational review.

## Explicitly open

- Drupal version, entity bundles/modules, Drupal AI strategy and interface UI.
- Retrieval backend: Drupal Search API path, externally hosted index, or hybrid.
- Embedding model, chunking approach, auth transport, infra, hosting, and caching.
- Whether LangChain assists retrieval/tool adapters; whether LangGraph/Temporal use is justified for the verified workflow (target stack remains a demonstration objective).

## Acceptance evidence

- [ ] Synthetic Drupal account, profile, and application resolve to portable candidate contracts with source IDs and revisions.
- [ ] Opportunities and policies originate from authoritative Drupal records.
- [ ] Cross-organization and unauthorized retrieval fail closed **before** context assembly.
- [ ] Every retrieved citation can be resolved to an allowed current source revision.
- [ ] Source update/withdrawal invalidates stale indexed content and prevents old recommendations being treated as current.
- [ ] Coordinator sees sourced vs inferred vs unknown claims within Drupal.
- [ ] Agent integration cannot execute a final recruiting decision without authorized human action.

## Related material

- `docs/decisions/ADR-0001-general-platform-nonprofit-pilot.md`
- `docs/decisions/ADR-0003-versioned-agent-evaluation-and-prompt-promotion.md`
- `docs/PROJECT_FOUNDATION.md` (v0.3.0)
- `docs/pilots/nonprofit-internship-placement.md`
- `docs/architecture/drupal-rag-evaluation-proposal-v0.1.md` (historical proposal; only ADRs/foundation govern accepted status)