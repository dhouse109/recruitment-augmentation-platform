# Portable Reference Contracts — Contract v0.2 (partial)

**Version:** `0.2.0-dev.foundations.4` — partial development version, **proposed, NOT frozen**  
**Covers:** D-004.01 identity, .02 profile/application separation, .07 source-version representation (PR #4); D-004.05 eligibility results, .06 versioned policy rules, .10 candidate claims, .11 evidence and retrieval admission (PR #5); D-004.03 review authority, .04 verification and escalation, .08 idempotency and audit, .09 review reasons (PR #6); D-004.12 evaluation cases, dataset manifests, runs, observations, adjudication, safety gates and promotion decisions (PR #7)  
**Traceability, evidence and limits:** [`contract-v0.2-foundations.md`](../docs/models/contract-v0.2-foundations.md), [`contract-v0.2-eligibility-evidence.md`](../docs/models/contract-v0.2-eligibility-evidence.md), [`contract-v0.2-review.md`](../docs/models/contract-v0.2-review.md), [`contract-v0.2-evaluation.md`](../docs/models/contract-v0.2-evaluation.md); contract-wide [`contract-v0.2-freeze-readiness.md`](../docs/models/contract-v0.2-freeze-readiness.md) (assessment only)

Pydantic v2 is used for these reference contracts only. It is not a selection of the application runtime. All data is synthetic.

## Layout

| Path | Contents |
|---|---|
| `rap_contracts/models.py` | Contract models and single-record validators |
| `rap_contracts/invariants.py` | Cross-record rules: identity mapping, org scope, lifecycle, submission preservation |
| `rap_contracts/source_checks.py` | Version-kind checks, snapshot-method registry, fail-closed source-check policy, `SourceAuthority` protocol |
| `rap_contracts/evidence.py` | `EvidenceRecord`, derived `RetrievalChunk`, retrieval request/response, fail-closed admission, pre-eligibility source gate |
| `rap_contracts/claims.py` | Claim vocabulary, `CandidateClaim` states, conflict detection, `ProgramParticipation` |
| `rap_contracts/eligibility.py` | `PolicySet`, `OpportunityRequirement`, `RuleOutcome`, `EligibilityResult`, outcome-support verifier (**not an engine**) |
| `rap_contracts/recommendation.py` | `Recommendation` (application context), `VerificationResult`, transition table, verification acceptance |
| `rap_contracts/review.py` | Review commands, trusted principal/grant shapes, reason vocabulary, `ReviewDecision`, `AuditEvent`, `ReviewOutcome`, pure evaluation, write-service protocol |
| `rap_contracts/evaluation.py` | `EvaluationCase` (typed operation steps), dataset manifests and custody declarations, `EvaluationRun`, `CaseObservation`, evidence tiers, structural attribution (PR #7) |
| `rap_contracts/adjudication.py` | Reviewer rubric, caller-declared review items, per-output `AdjudicationRecord` with exactly two designated primaries and derived results, conflict registers, structural-only reportability (never genuine without a trusted service) and diagnostic usefulness coverage (PR #7; F4 PR-B) |
| `rap_contracts/promotion.py` | Metric definitions, safety-gate policy, pure gate evaluation, `HeldOutGateAttestation`, strict `PromotionDecision`, future trusted-service protocol (PR #7) |
| `rap_contracts/schema_export.py` | Deterministic JSON Schema generation and drift check |
| `schemas/` | Generated JSON Schemas (do not edit by hand) |
| `fixtures/` | Synthetic fixture sets: `foundations-…` (PR #4), `eligibility-evidence-…` (PR #5) and `review-…` (PR #6), each extending the previous; `evaluation-golden-…`, `evaluation-nominal-held-out-…` (exposed demonstration, not blinded) and `evaluation-definitions-…` (draft metrics, gate policy, rubric) (PR #7); `evaluation-definitions-v2-…` (**proposed draft** definitions v2: metrics v2 and gate policy v2 with the unchanged v1 rubric; not approved and **not the harness default**, which stays v1) (F4 PR-A); `evaluation-rubric-v2-…` (**proposed draft** reviewer rubric v2: exactly two primaries, expectation-grounded N/A) (F4 PR-B) |
| `tests/` | `unittest` suites; `tests/support.py` holds the **mock** source authority and chunk store; `tests/review_double.py` is an in-memory **test double** of the review-write service; `tests/eval_harness.py` is the **test-only** evaluation conformance harness (tier T2) |
| `requirements.txt` / `requirements-dev.txt` | Runtime pin / dev-only additions for tests |

## Reproduce

From a clean checkout, in the `contracts/` directory:

```bash
python -m venv .venv && . .venv/bin/activate
python -m pip install -r requirements-dev.txt   # runtime pin + dev-only jsonschema
python -m rap_contracts.schema_export --check   # expect: schema drift: NONE
python -m unittest discover -s tests -v
python -m unittest discover -s tests -p 'test_evaluation*.py' -v   # focused; tests/ is not a package
```

`requirements.txt` holds the runtime pin only (`pydantic`). `requirements-dev.txt` adds `jsonschema` for the independent conformance tests in `tests/test_json_schema_conformance.py`; with runtime requirements alone those tests are reported as skipped.

`invariants.check_record_set` validates a record set as **complete** by default: every submission's exact pinned profile version must be present. Pass `pinned_versions="may_be_absent"` for a partial projection; the pinned version must then be established by `source_checks.resolve_submission_evidence`, which fails closed.

Regenerate schemas after an intentional model change with `python -m rap_contracts.schema_export`, and commit the result with the change. Output is reproducible only with the pinned Pydantic version.

## What passing tests do and do not mean

Passing tests show that the contracts, invariants and fail-closed plumbing behave as specified on synthetic data. They do **not** show live Drupal authorization, source freshness, revision retention, database uniqueness, transactionality or append-only audit. Tests that use `FixtureSourceAuthority` or `FixtureChunkStore` are mock-level only. Fixture eligibility results are hand-written expected labels; passing tests do not demonstrate an eligibility engine, an index, or that a model ignores injected instructions. The review test double proves nothing about authentication, transactions, concurrent idempotency or durable audit storage. Evaluation-case conformance (PR #7) is mock-level (tier T2): it shows hand-written labels and declared fault records agree with the reference validators. It is not a deterministic baseline, not a model evaluation and not integrated safety evidence; no evaluation run, metric value or report is committed. The draft definitions v2 (F4 PR-A) are definition text checked against the unchanged models and schemas: no metric they describe is produced, measured or reportable, and the zero-tolerance blocking tests are synthetic gate-logic tests, not integrated safety evidence. Held-out leakage tests are contract-level text checks, not custody or confidentiality proof. The adjudication tests (F4 PR-B) exercise synthetic reviewer, role, conflict and attestation values: these are structural claims, not authentication, role grants or proof of independence, and no record can be genuinely reportable in this contract version.
