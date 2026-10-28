# Current Status — Recruitment Augmentation Platform

**Phase:** Approved domain-policy decisions → Contract v0.2 revision planning  
**Implementation authorization:** Contract work only, under explicitly scoped owner-authorized PRs (PR #4: Contract v0.2 foundations; PR #5: eligibility and evidence foundations; PR #6: recommendation verification and human review foundations). **No application implementation** is authorized; contracts and execution plan are not frozen.  
**Repository branch target:** `main` through reviewed PRs  
**Pilot:** Fictional nonprofit internship placement; synthetic data only

## Accepted decisions

- **D-001:** General-purpose recruitment architecture with a nonprofit internship pilot.
- **D-002:** Drupal authoritative business records and controlled AI inside/outside Drupal via permission-aware RAG.
- **D-003:** Versioned synthetic evaluation, regression assessment, and gated changes.
- **D-004:** Twelve accepted contract-review decisions plus deterministic-baseline-first sequencing.
- **Confirmed lifecycle:** Drupal account → reusable candidate profile → one or more distinct program/opportunity applications → eligibility/matching → verification → authenticated human follow-up review.

See `docs/decisions/README.md` and the individual ADRs for authoritative detail.

## Contract status

**Design decisions: approved.**  
**Pydantic models / JSON Schemas v0.1: draft design reference only (never committed as code); superseded in scope by v0.2 work as it lands.**  
**Contract v0.2: partially implemented as a proposal; not accepted or frozen.**

- **v0.2 foundations (`0.2.0-dev.foundations`, PR #4):** reference contracts, generated JSON Schemas, synthetic fixtures and local positive/negative tests for D-004.01, D-004.02 and the representation requirements of D-004.07. See `docs/models/contract-v0.2-foundations.md` for traceability, test evidence and the guarantees that local and mock tests cannot establish.
- **v0.2 eligibility and evidence foundations (`0.2.0-dev.foundations.2`, PR #5):** reference contracts, schemas, synthetic fixtures and tests for D-004.05 (eligibility results), D-004.06 (versioned policy rules; fixture expected labels, **no engine**), D-004.10 (controlled claims) and D-004.11 (evidence, derived chunks, mock-level fail-closed retrieval admission). See `docs/models/contract-v0.2-eligibility-evidence.md`, including the approved active-status exception (O1) and open decisions O2–O5.
- **v0.2 recommendation verification and human review foundations (`0.2.0-dev.foundations.3`, PR #6):** reference contracts, schemas, synthetic fixtures and tests for D-004.03 (server-derived reviewer authority), D-004.04 (recommendations bound to a submitted application, substantive verification, escalation, exhaustive transitions), D-004.08 (semantic idempotency, linked audit corrections; **in-memory test double only**) and D-004.09 (versioned reason codes, conditional comments). See `docs/models/contract-v0.2-review.md`, including future Drupal write-service requirements and the owner-approved decisions N1–N6.
- **v0.2 evaluation, adjudication and held-out separation (`0.2.0-dev.foundations.4`, PR #7, under review):** reference contracts, schemas, synthetic golden and **nominal (exposed, not blinded)** held-out case fixtures, draft metric/safety-gate/rubric definitions and a **test-only** conformance harness for D-004.12. Evidence is mock-level (T2) only; no evaluation run, measurement, adjudication or promotion decision exists. See `docs/models/contract-v0.2-evaluation.md` and the contract-wide assessment `docs/models/contract-v0.2-freeze-readiness.md` (assessment only; no freeze).
- **Not yet implemented:** the deterministic eligibility and recommendation engines (Slice 0 baseline); human adjudication; trusted held-out custody; the Drupal review-write service and any evaluation-record service.

The v0.1 contracts, domain mapping, and synthetic evaluation labels currently in documentation are proposals and design references. New source, fixtures, and runnable test code require a separate PR and verification. Earlier local modeling checks do not prove integrated source authorization, review transactionality, or model quality.

## Approved implementation constraints to enforce in v0.2

- Account / Candidate / Profile / Application separation; one stable Candidate per organization per account.
- Opportunity-specific eligibility with explicit unknowns.
- Escalation for failed verification; no follow-up approval for unverified recommendations.
- Native revision or validated logical source snapshot; live permission/currentness checks.
- Human-authorized Drupal review writes with structured reason codes, idempotency and append-only events.
- Source-backed allowlisted claims; no AI-inferred factual promotions or sensitive proxy matching.
- Versioned synthetic evaluation and a deterministic eligibility/explanation baseline ahead of paid model inference.

## Work now authorized as planning/contract revision

1. Produce a **Contract v0.2** proposal implementing D-004, including generated schemas, synthetic cases, negative tests, and observed test output. *D-004.01/.02/.07 in PR #4 (merged); D-004.05/.06/.10/.11 in PR #5 (merged); D-004.03/.04/.08/.09 proposed in PR #6; D-004.12 follows in a separately scoped PR.*
2. Propose the deterministic eligibility engine and Slice 0 execution plan; choose and document any supporting technology decisions separately.
3. Define implementation stage gates and Claude instructions (`AGENTS.md`, `CLAUDE.md`) for later review.
4. Request explicit authorization before full application implementation or claiming a contract freeze.

## Remaining OPEN implementation selections

- Drupal core version, physical entity types, module strategy, secure service delegation.
- Database/index backend, model providers, LangGraph/LangChain/Temporal/LangFuse topology, deployment.
- Quantitative non-safety evaluation thresholds and how human subjective cases are adjudicated.
- Framework choice for spec-driven versus custom R&D execution.
- Retention/compliance measures needed before real-applicant deployment.

## Evidence and change control

No production pilot, Drupal integration, agent pipeline, or measured model benchmark exists in this repository yet. All data must be synthetic or expressly licensed. PRs must identify decisions, test evidence, risks, and withheld claims. **Merging a planning PR does not by itself authorize executable implementation or real-applicant processing.**
