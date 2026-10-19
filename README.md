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
Planning and discovery. No recruitment application or integrated agent workflow has been implemented in this repository. Product decisions D-001 through D-004 are accepted. Contract v0.1 is still a draft, and revised v0.2 contracts, Drupal implementation details, orchestration, and measured evaluation thresholds remain under review.

Start with [Current Status](docs/CURRENT-STATUS.md) and the [Decision Index](docs/decisions/README.md).

## Working agreement
Changes arrive through pull requests; the repository owner reviews and merges. No real candidate records, employer materials, private prompts, client configuration or credentials should be committed. All pilot data must be synthetic or explicitly licensed.

Claude implementation is **not authorized** until the contract review and execution plan are approved.
