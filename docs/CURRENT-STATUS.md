# Current Status — Recruitment Augmentation Platform

**Phase:** Planning / proposed contract review
**Implementation authorization:** **NONE**
**Repository branch target:** `main` (via reviewed PRs only)
**Pilot:** Fictional nonprofit internship placement using entirely synthetic records

## Accepted design commitments

- **D-001:** General-purpose recruitment architecture, nonprofit internship pilot.
- **D-002:** Drupal as the pilot's authoritative business record system; revision- and permission-aware RAG supports AI inside and outside Drupal.
- **D-003:** Versioned synthetic evaluation and gated prompt/model/retrieval changes.
- **Candidate lifecycle (confirmed):** Drupal user registration → reusable candidate profile → distinct applications against programs or opportunities → eligibility and matching → verified suggestions → human review for follow-up.

See `docs/decisions/README.md` for actual ADRs.

## In review, NOT accepted

- Domain and contract descriptions under `docs/models/` are **v0.1 proposals**.
- Twelve contract-review recommendations await explicit approval.
- The physical Drupal entity/module choices, authorization transport, retrieval index/database, stack details, orchestration topology, evaluation runner, and thresholds are open.
- The model examples described in the companion draft contract package are **not imported as executable code in this documentation PR**. Schemas, fixtures, and test sources will require a separate follow-on integration/freeze PR after contract review.

## Next steps

1. Review and approve/revise the twelve decisions in `docs/models/contract-review-recommendations.md`.
2. Build Contract v0.2 (typed contracts, schema generation, synthetic fixtures, negative tests) and plan deterministic Slice 0.
3. Decide the implementation method, Claude execution environment, and stage gates; prepare agent instructions.
4. Authorize one bounded implementation slice only after contract and execution-gate approval.

## Evidence policy

No production software or model evaluations have been completed in this repository. Draft schema tests cited in prior planning materials are **local design spike results**, not CI or integrated acceptance tests. No real recruitment outcomes, external client records, or proprietary configuration should be committed.

## Change control

Every PR states: accepted decisions relied upon, changes proposed, verification performed, deferred items, and whether implementation is authorized. Merging a PR that imports a **proposed** model does not constitute a separate decision to approve that model.
