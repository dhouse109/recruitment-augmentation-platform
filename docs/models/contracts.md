# Portable Contract Reference — Candidate / Recruitment Workflow

**Document ID:** RAP-CONTRACT-001  
**Version:** 0.1.0 / Proposed  
**Decision basis:** D-001, D-002, D-003  
**Contract examples:** `contracts/rap_contracts/models.py`; `contracts/examples/`  
**Schema output:** `contracts/schemas/*.schema.json`

> **Note (PR #4):** The v0.1 example code and schemas referenced on this page were never committed to `main`. The `contracts/` directory now holds the partial **v0.2 foundations** contracts (`0.2.0-dev.foundations`); see [`contract-v0.2-foundations.md`](contract-v0.2-foundations.md). The demo commands below describe the v0.1 draft and do not apply to the current `contracts/` package. This page remains the v0.1 design reference.

## Purpose

These are **framework-independent domain agreements**, represented here by runnable **Pydantic v2 examples** and generated JSON Schemas. Pydantic is useful because the original intended stack includes it; this **does not choose** the runtime, Drupal modules, orchestration design, database, or spec framework. A future toolchain may consume the JSON Schemas instead.

Version proposed contracts independently of the product foundation. `0.1.0` is a **design draft**, not a stable v1 API or production spec.

## Contract catalog

| Context | Types | Minimum semantics |
|---|---|---|
| Authority | `SourceReference`, `Organization`, `Program`, `Candidate`, `CandidateProfile`, `Application`, `Opportunity`, `PolicySet` | Scoped identifiers, source versions, separation of account/profile/application |
| Evidence | `CandidateClaim`, `EvidenceRecord`, `RetrievalChunk` | Declared/inferred/unknown/contested state, evidence IDs, derived chunks, access scope |
| Execution | `MatchRun`, `RuleOutcome`, `EligibilityResult`, `Recommendation`, `VerificationResult` | Pinned policy version, deterministically derived rule result, verification state, no final placement |
| Human governance | `ReviewDecision`, `AuditEvent` | Human-only follow-up decision, versioned references, idempotency identity |
| Quality | `EvaluationCase`, `CaseObservation`, `EvaluationRun` | Golden/held-out split, pinned versions, observed safety signals, no invented scores |

### Shape validation vs semantic validation

- Pydantic ensures fields and enums are structurally valid, and checks local invariants (e.g. unknown claim has no invented value).
- `boundaries.py` illustrates cross-record checks (e.g. organization equality, eligible opportunity, evidence IDs, human reviewer).
- Neither layer authenticates a human or decides if Drupal permissions permit using a document. The Drupal-backed service must do **live** access/currentness checks and audit writes transactionally.
- The test mocks returning `True` for a callback validate the plumbing, **not** real Drupal security.

## Proposed contract validation gates

| Gate | What must be checked before advancing | Where enforced |
|---|---|---|
| Input | Strict schema, allowed organization, current sources | Pydantic + live source adapter |
| Eligibility | Source-backed known/unknown states, hard rules, policy version | Deterministic policy engine (future implementation) |
| Suggested match | `EligibilityResult.decision == eligible`, evidence pointers resolve | Application boundary |
| Verification | Citations, constrained scope, source currentness, unsupported claims | Deterministic checks + optional model verifier |
| Review display/action | Authenticated reviewer, correct scope, verified/current recommendation | Drupal API + UI and authoritative write transaction |
| Change promotion | Measured benchmark cases, no unblocked safety failures | Eval runner and review process (future implementation) |

**Safety warning:** `ReviewDecision.actor_type="human"` is only a literal type restriction; it is not identity proof. The server must derive reviewer identity from authenticated Drupal context, not arbitrary JSON. Likewise a valid Pydantic `RetrievalChunk` is not proof that its text may be placed into a prompt.

## Source and status rules

1. Source identifiers must be opaque, not derived from PII.
2. Never accept a claim with `state=unknown` and a fabricated value.
3. `inferred` means a *proposal*, not a business fact. Explicit review/correction would be required to change authoritative profile records.
4. If one rule outcome is `fail`, the opportunity is `ineligible`; if none fail but any are `unknown`, it is `needs_information`; otherwise `eligible`.
5. No numeric match score exists in this draft. Do not imply a calibrated suitability score.
6. A recommendation does not confer authority to reject, offer, hire, place, or admit someone.
7. Draft example `CandidateProfile.claims` and `Opportunity.attributes` are intentionally small; their permitted field vocabulary still requires policy/data governance review before implementation.

## Versioning and migrations

- Model names and field meanings are provisional; changing a meaning requires a documented migration/ADR discussion.
- Schema changes should carry contract revision and explicit fixture updates.
- Source revisions and policy versions must be pinned to each `MatchRun` and evaluated again on consequential review.
- JSON Schema structural interoperability does not guarantee the same cross-object and authorization behavior in non-Python implementations.

## Traceability for acceptance

- Portable job fixture: `PILOT-T008`.
- User/profile/application distinction: `PILOT-T011`.
- Unauthorized/cross-organization: `PILOT-T004`, `PILOT-T013`.
- Missing/conflicting candidate facts: `PILOT-T002`, `PILOT-T010`.
- Evidence resolution and source freshness: `PILOT-T005`, `PILOT-T012`, `PILOT-T014`.
- Coordinator-only dispositions and idempotency: `PILOT-T006`, `PILOT-T007` (**transactional uniqueness not implemented by this contract-only package**).
- Safety/eval test design: `PILOT-T016`, `PILOT-T017` (**runner and promotion decision engine not yet implemented**).

## Contract demo commands

```bash
python -m pip install 'pydantic>=2.9,<3'
PYTHONPATH=contracts python -m unittest discover -s contracts/tests -v
```

These are tests of model semantics and local examples. They do **not** prove the full 18 pilot acceptance tests or a running Drupal integration.