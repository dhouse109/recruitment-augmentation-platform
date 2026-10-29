# Current Status — Recruitment Augmentation Platform

**Phase:** Contract v0.2 reference contracts cover D-004.01–.12 (proposed, **not frozen**) → owner decisions and Slice 0 planning  
**Implementation authorization:** Contract and documentation work only, under explicitly scoped owner-authorized PRs (merged: PRs #4–#7, Contract v0.2 reference contracts; PR #8, F2 forward redaction). **No application implementation** is authorized; Contract v0.2 and the execution plan are not frozen.  
**Current reference-contract version:** `0.2.0-dev.foundations.4`  
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
**Contract v0.2: reference contracts at `0.2.0-dev.foundations.4` cover all twelve D-004 decisions (D-004.01–.12); proposed, not accepted or frozen.**

**Coverage is not implementation.** Reference-contract coverage means portable Pydantic contracts, generated JSON Schemas, synthetic fixtures and local tests, with schema-level (T1) and mock-level (T2) evidence only. Runtime implementation, trusted services (Drupal review-write and authentication, evaluation-record, held-out custody), evaluation execution and measured results remain outstanding.

- **v0.2 foundations (`0.2.0-dev.foundations`, PR #4, merged):** reference contracts, generated JSON Schemas, synthetic fixtures and local positive/negative tests for D-004.01, D-004.02 and the representation requirements of D-004.07. See `docs/models/contract-v0.2-foundations.md` for traceability, test evidence and the guarantees that local and mock tests cannot establish.
- **v0.2 eligibility and evidence foundations (`0.2.0-dev.foundations.2`, PR #5, merged):** reference contracts, schemas, synthetic fixtures and tests for D-004.05 (eligibility results), D-004.06 (versioned policy rules; fixture expected labels, **no engine**), D-004.10 (controlled claims) and D-004.11 (evidence, derived chunks, mock-level fail-closed retrieval admission). See `docs/models/contract-v0.2-eligibility-evidence.md`, including the approved active-status exception (O1) and open decisions O2–O5.
- **v0.2 recommendation verification and human review foundations (`0.2.0-dev.foundations.3`, PR #6, merged):** reference contracts, schemas, synthetic fixtures and tests for D-004.03 (server-derived reviewer authority), D-004.04 (recommendations bound to a submitted application, substantive verification, escalation, exhaustive transitions), D-004.08 (semantic idempotency, linked audit corrections; **in-memory test double only**) and D-004.09 (versioned reason codes, conditional comments). See `docs/models/contract-v0.2-review.md`, including future Drupal write-service requirements and the owner-approved decisions N1–N6.
- **v0.2 evaluation, adjudication and held-out separation (`0.2.0-dev.foundations.4`, PR #7, merged after review repairs R1–R7):** reference contracts, schemas, synthetic golden and **nominal (exposed, not blinded)** held-out case fixtures, draft metric/safety-gate/rubric definitions and a **test-only** conformance harness for D-004.12. Evidence is mock-level (T2) only; no evaluation run, measurement, adjudication or promotion decision exists. See `docs/models/contract-v0.2-evaluation.md` and the contract-wide assessment `docs/models/contract-v0.2-freeze-readiness.md` (assessment only; no freeze).
- **Not yet implemented:** the deterministic eligibility and recommendation engines (Slice 0 baseline); human adjudication; trusted held-out custody; the Drupal review-write service and any evaluation-record service; any evaluation run or measured result.
- **Evaluation directory layout:** PROJECT-FOUNDATION and RAP-EVAL-001 propose different `evals/` layouts. **Neither is selected or implemented, and no `evals/` directory exists.** Committed evaluation artifacts live under `contracts/` (contracts, fixtures and a test-only conformance harness).

The v0.1 contracts and domain mapping in documentation are proposals and design references; the seed evaluation labels in RAP-EVAL-001 are superseded by the case fixtures in `contracts/` (PR #7). New source, fixtures, and runnable test code require a separate PR and verification. Earlier local modeling checks do not prove integrated source authorization, review transactionality, or model quality.

## Approved implementation constraints to enforce in v0.2

- Account / Candidate / Profile / Application separation; one stable Candidate per organization per account.
- Opportunity-specific eligibility with explicit unknowns.
- Escalation for failed verification; no follow-up approval for unverified recommendations.
- Native revision or validated logical source snapshot; live permission/currentness checks.
- Human-authorized Drupal review writes with structured reason codes, idempotency and append-only events.
- Source-backed allowlisted claims; no AI-inferred factual promotions or sensitive proxy matching.
- Versioned synthetic evaluation and a deterministic eligibility/explanation baseline ahead of paid model inference.

## Work now authorized as planning/contract revision

*Completed:* the Contract v0.2 reference-contract proposal for D-004.01–.12, with generated schemas, synthetic cases, negative tests and observed test output (PRs #4–#7, merged). It remains a proposal and is not frozen.

1. Propose the deterministic eligibility engine and Slice 0 execution plan; choose and document any supporting technology decisions separately.
2. Define implementation stage gates and Claude instructions (`AGENTS.md`, `CLAUDE.md`) for later review.
3. Request explicit authorization before full application implementation or claiming a contract freeze.

## Open follow-ups and owner decisions (each needs separate authorization)

- **F2 historical exposure:** forward redaction of restricted source material is merged (PR #8), so the current tree is clean. Earlier copies remain in Git history and GitHub PR refs; history rewriting is not authorized and the repository remains private.
- **F3:** give evaluation cases g002 and g008 separate scenarios. Required before the owner reviews those two labels (F4 B3); needs separate versioned case, manifest and draft-policy revisions.
- **F4:** Stage A owner decisions B1–B5 and N1–N3 and PR-A specification decisions D1–D5 were approved on 2026-10-29 (`docs/evaluation/F4-definitions-decision-record.md`). PR-A proposes draft definitions v2 (`contracts/fixtures/evaluation-definitions-v2-v0.2.0-dev.json`): definition text and tests only, with no model, schema or contract-version change. **No definition is approved**; v1 and v2 remain `status: draft`, and v1 is still the harness default. Proposed follow-ups — PR-B (adjudication contracts), PR-C to PR-E (replicate, comparison, verifier-observation and coverage contracts) and PR-F (research-selection record) — and Slice 0 are **not authorized**.
- **O3, O4 and the remainder of O5:** open contract decisions.
- **Freeze:** Contract v0.2 freeze readiness is assessed in `docs/models/contract-v0.2-freeze-readiness.md` (assessment only; not ready).

## Remaining OPEN implementation selections

- Drupal core version, physical entity types, module strategy, secure service delegation.
- Database/index backend, model providers, LangGraph/LangChain/Temporal/LangFuse topology, deployment.
- Quantitative non-safety evaluation thresholds; reviewer and adjudicator staffing and trusted attestation for subjective adjudication (the procedure is decided in F4 B2).
- Framework choice for spec-driven versus custom R&D execution.
- Retention/compliance measures needed before real-applicant deployment.

## Evidence and change control

No production pilot, Drupal integration, agent pipeline, or measured model benchmark exists in this repository yet. All data must be synthetic or expressly licensed. PRs must identify decisions, test evidence, risks, and withheld claims. **Merging a planning PR does not by itself authorize executable implementation or real-applicant processing.**
