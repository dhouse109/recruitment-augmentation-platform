# Architecture Decision Index

**Authority:** Accepted decisions are recorded in ADRs. A proposed type or fixture is not automatically an implemented contract.

| ID | Status | Record |
|---|---|---|
| D-001 | **Accepted** | [ADR-0001 — General-purpose platform, nonprofit internship pilot](ADR-0001-general-platform-nonprofit-pilot.md) |
| D-002 | **Accepted** | [ADR-0002 — Drupal authoritative records and RAG boundaries](ADR-0002-drupal-authoritative-reference-and-rag-boundaries.md) |
| D-003 | **Accepted** | [ADR-0003 — Versioned evaluation and prompt promotion](ADR-0003-versioned-agent-evaluation-and-prompt-promotion.md) |
| D-004 | **Accepted** | [ADR-0004 — Twelve domain and contract review decisions](ADR-0004-contract-review-dispositions.md) |

## Confirmed candidate lifecycle

Drupal registration → reusable candidate profile → **separate applications** to programs or opportunities → evidence-backed eligibility/matching → verification → human follow-up review.

**Confirmed by project owner:** 2026-10-15.

## Contract review decisions

All twelve questions in [the contract-review checklist](../models/contract-review-checklist.md) are **answered and approved at the design-policy level**, using the proposed answers as expressly authorized by the owner on 2026-10-19.

The selected answers and their rationale are recorded in **D-004**. This approval supersedes the former *pending* status of the [recommendations](../models/contract-review-recommendations.md).

## Still not frozen or implemented

- Portable contract **v0.1 examples are still proposals**, because D-004 explicitly requires changes before Contract v0.2.
- Contract v0.2 schemas, code, test cases, and Drupal write services have **not** been demonstrated or frozen.
- Physical Drupal entities/modules, authentication/delegation, vector index, model selection, infrastructure, development framework and execution plan remain open.
- No implementation work is authorized merely by merging this documentation PR.

See [Current Status](../CURRENT-STATUS.md) for the next permitted planning tasks.
