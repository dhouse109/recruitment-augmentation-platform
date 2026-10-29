# ADR-0001 — General-Purpose Platform with Nonprofit Internship Pilot

**Decision ID:** D-001
**Status:** Accepted
**Decision date:** 2026-10-12
**Project:** Recruitment Augmentation Platform
**Implementation status:** Design only; no platform implementation implied

## Context

The project originated in a candidate-placement architecture from a prior private discussion. That scenario provides a defined first use case, but making the shared domain internship-specific would hinder other recruitment workflows.

> **Editorial erratum (2026-10-29, follow-up F2):** identifying historical context was removed from the first sentence of this section. D-001's decision, rationale, decision date and requirements are unchanged. The earlier wording remains in Git history.

The project owner selected a **general-purpose recruitment augmentation architecture with nonprofit internship placement as the first pilot**.

## Decision

1. Build a reusable core for authorized candidate-to-opportunity matching and review.
2. Model `Organization`, `Candidate`, `Opportunity`, `PolicySet`, `EvidenceRecord`, `EligibilityResult`, `MatchRun`, `Recommendation`, `VerificationResult`, `ReviewDecision`, and `AuditEvent` independently of any recruitment program.
3. Use opportunity categories and optional program references, rather than internship-only core entities.
4. Build the first end-to-end vertical slice for **one fictional nonprofit internship program**, with synthetic data and coordinator review.
5. Design organization scope into contracts and tests; do **not** imply production-ready multi-tenant SaaS is in scope.
6. Keep consequential hiring, placement, admissions, and candidate rejection decisions under human authority. The MVP only authorizes a suggestion for follow-up.
7. Delay technology choices, AI architecture complexity, and development methodology until contracts and acceptance criteria are reviewable.

## Rationale

- A narrow pilot exercises a real workflow with verifiable evidence.
- Generic contracts support jobs, fellowships, apprenticeships, and other permitted programs.
- Configurable policies separate organizational requirements from model outputs.
- A common evaluation harness permits comparison of deterministic and model-driven approaches.
- A synthetic, independently reproducible repository avoids exposing client or candidate data.

## Tradeoffs

**Benefits:** Reuse, portability tests, controlled policy variation, inspectable audit and evaluation boundaries, and credible public engineering evidence.

**Costs:** Organization/program abstraction work beyond a single internship prototype; potential over-generalization; employment-domain privacy, accessibility, accommodation, fairness, and legal obligations before real-world use.

## Non-decisions

This ADR does not select Drupal entity types, Python frameworks, LangGraph, Temporal, LangFuse, MCP, RAG infrastructure, cloud hosting, model vendor, or any spec-driven development methodology. Those must be evaluated separately.

It does not authorize any real-applicant processing, publication of proprietary data, autonomous disposition, or cross-organization sharing.

**Follow-on decision D-002** chooses Drupal as the authoritative *pilot reference implementation*, without invalidating the portable domain boundary specified here.

## Acceptance checks

- [ ] Core contracts have no mandatory internship-only types.
- [ ] Synthetic nonprofit scenario runs eligibility, verified recommendation, and human follow-up review.
- [ ] A fictional job opportunity validates against the same portable core contracts.
- [ ] Cross-organization access fails closed.
- [ ] Model output cannot write a final candidate hiring or placement decision.
- [ ] Policy and fixture versions are recorded with each run.

## References

- `docs/PROJECT-FOUNDATION.md`
- `docs/pilots/nonprofit-internship-placement.md`
- `docs/decisions/ADR-0002-drupal-authoritative-reference-and-rag-boundaries.md`
- `docs/decisions/ADR-0003-versioned-agent-evaluation-and-prompt-promotion.md`
