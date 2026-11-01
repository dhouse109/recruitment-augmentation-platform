# Recruitment Augmentation Platform

A specification-first, human-supervised recruitment augmentation research project.

## Approved product direction
- **D-001:** General-purpose recruitment architecture with nonprofit internship placement as the first synthetic pilot.
- **D-002:** Drupal is the authoritative reference system for pilot users, profiles, applications, opportunities, policy, and human decisions; permission-aware RAG exposes source-revision-backed evidence to external AI services.
- **D-003:** Versioned synthetic evaluation cases, regression measurement, and explicit promotion gates are mandatory for model, prompt, retrieval, and agent changes.
- **D-004:** All twelve domain-contract review decisions are accepted as requirements, including separated application records, guarded human review, source revision semantics, structured reasons, evidence governance, and deterministic baseline first.

## Candidate lifecycle
Drupal account registration → reusable candidate profile → distinct applications against programs or opportunities → eligibility and matching → verified recommendations → human review.

The system may recommend **follow-up**, but cannot independently hire, reject, admit, or finalize placement decisions.

## Status
Contract reference development and two merged Slice 0 components. No recruitment application or integrated agent workflow has been implemented in this repository. Product decisions D-001 through D-004 are accepted. Contract v0.1 remains a draft design reference, superseded in scope by v0.2.

- **Contract v0.2** reference contracts (`contracts/`, current version `0.2.0-dev.foundations.5`) cover all twelve D-004 decisions (D-004.01–.12) with generated schemas, synthetic fixtures and local tests. They are proposed and **not frozen**. Eligibility results, recommendations, verifications and evaluation-case expectations in the contract fixtures are hand-written labels.
- **Slice 0 PR-S1 (PR #12, merged 2026-10-31)** added the first implemented deterministic eligibility engine (`baseline/rap_baseline`). It computes one opportunity- and policy-scoped `EligibilityResult` from already-loaded synthetic records, with no model call, and every result is checked by the unmodified contracts. Its tests run on test-local synthetic records against a **synthetic source authority**. They do not establish Drupal authorization, revision currentness or context completeness, which remain future (T4) obligations. Known limitation G12 (mixed-basis qualification contradictions are only partially cited) is unresolved. See [Slice 0 PR-S1](docs/baseline/slice-0-eligibility-engine.md).
- **Slice 0 PR-S2 (PR #14, merged 2026-11-01)** added independently verified, runtime-local findings and deterministic, evidence-grounded explanations. G12a–c remain limitations of the eligibility *result* citations; findings account for omitted material. Explanations are internal and not authorized for reviewer presentation. See [Slice 0 PR-S2](docs/baseline/slice-0-explanations.md).
- **Not yet implemented:** a recommendation engine, verifier or offline evaluation runner (PR-S3); any Drupal review-write service or trusted evaluation service; any evaluation run, T3/T4 evidence or measured result. PR-S3 is not authorized. Drupal implementation details, orchestration and measured evaluation thresholds remain open.

Start with [Current Status](docs/CURRENT-STATUS.md) and the [Decision Index](docs/decisions/README.md).

## Working agreement
Changes arrive through pull requests; the repository owner reviews and merges. No real candidate records, employer materials, private prompts, client configuration or credentials should be committed. All pilot data must be synthetic or explicitly licensed.

AI-assisted contributors work only on owner-authorized, explicitly scoped PRs. **Contract implementation** (portable reference contracts, generated schemas, synthetic fixtures and local tests) proceeds only under such a scope, as with PRs #4–#7, #10 and #11. **Executable components** proceed only under an equally explicit scope; Slice 0 PR-S1 (eligibility, PR #12) and PR-S2 (internal findings and explanations, PR #14) were separately authorized and merged. **Full application development** — Drupal runtime, AI agents, retrieval, paid inference, hosted infrastructure or production integrations — is **not authorized** until the contract review and execution plan are approved.
