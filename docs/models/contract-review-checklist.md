# Contract Review Gate — Accepted Decisions and Remaining Implementation Checks

**Decision status:** APPROVED by project-owner delegation (D-004, 2026-10-19)  
**Contract status:** **v0.1 remains proposed; v0.2 NOT YET BUILT or frozen**  
**Accepted decision basis:** D-001, D-002, D-003, [D-004](../decisions/ADR-0004-contract-review-dispositions.md)  
**Confirmed lifecycle:** Drupal account → reusable candidate profile → distinct program/opportunity applications

## Decisions accepted

Each selected answer and its rationale, exceptions, and test obligations are recorded in ADR-0004. A checked item means the **decision** is approved, not that its software has been implemented.

- [x] **D-004.01 — Identity:** Drupal account versus organization-scoped Candidate; one per organization, with opaque portable IDs.
- [x] **D-004.02 — Entity separation:** Distinct revisionable logical CandidateProfile, Application, and Opportunity; physical Drupal type remains open.
- [x] **D-004.03 — Human reviewer:** Nonprofit coordinator; approve for **follow-up only**.
- [x] **D-004.04 — Escalation:** Failed/stale verification cannot enter normal approval; request information or dismiss suggestion.
- [x] **D-004.05 — Eligibility:** Opportunity- and policy-specific, not candidate rejection.
- [x] **D-004.06 — Pilot policies:** Four configurable fictional categories; missing/conflicting data becomes needs_information rather than an inferred rejection.
- [x] **D-004.07 — Source version:** Native Drupal revisions or validated logical snapshots; permission and freshness rechecked separately.
- [x] **D-004.08 — Writes:** Authenticated Drupal service enforces transactionality, idempotency, and append-only audit events.
- [x] **D-004.09 — Review reasons:** Structured reason_code; optional comment with conditional explanation.
- [x] **D-004.10 — Claims:** Allowlisted, source-backed fields and explicit epistemic states; inferred claims are not authoritative.
- [x] **D-004.11 — RAG:** Scoped and live-authorized retrieval with revision/currentness and withdrawal handling.
- [x] **D-004.12 — Evaluation:** Complete synthetic fixtures, adjudicated labels, held-out cases, reproducible measurements.

**Additional accepted rule:** Deterministic eligibility and explanation baseline before model-dependent matching or multi-agent claims.

## Unfinished implementation gates for Contract v0.2

- [ ] Update typed Pydantic reference contracts, enums, and cross-object validators to match all twelve decisions.
- [ ] Generate JSON Schema outputs and ensure their semantics align with the Python validation boundaries.
- [ ] Implement synthetic fixture cases for all positive, negative, unknown, stale, cross-organization, escalation and idempotency scenarios.
- [ ] Run automated tests and retain actual commands and observed results in GitHub/CI evidence.
- [ ] Distinguish mock-backed contract tests from future Drupal live authorization, source-freshness and transactional review tests.
- [ ] Reconcile candidate lifecycle and review escalation against explicit state-transition tables.
- [ ] Complete a reproducible deterministic eligibility-policy baseline design and execution plan.
- [ ] Produce an evaluation fixture rubric without inventing quality, safety, cost or latency results.
- [ ] Keep unselected implementation technologies in an OPEN register and obtain separate decisions where necessary.
- [ ] Present a Contract v0.2 freeze proposal only after contracts, fixtures, and required tests are reviewed.

## Exit criteria

**Decision gate:** Complete with D-004 adoption.  
**Contract implementation / freeze gate:** Not yet complete.  
**Claude implementation authorization:** Not granted by this ADR or checklist alone.

**Next deliverables:** Contract v0.2 revision, deterministic policy evaluation specification, reproducible synthetic case set, and the first executable Slice 0 plan.
