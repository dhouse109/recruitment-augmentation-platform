# Portable Reference Contracts — Contract v0.2 (partial)

**Version:** `0.2.0-dev.foundations.2` — partial development version, **proposed, NOT frozen**  
**Covers:** D-004.01 identity, .02 profile/application separation, .07 source-version representation (PR #4); D-004.05 eligibility results, .06 versioned policy rules, .10 candidate claims, .11 evidence and retrieval admission (PR #5)  
**Traceability, evidence and limits:** [`contract-v0.2-foundations.md`](../docs/models/contract-v0.2-foundations.md), [`contract-v0.2-eligibility-evidence.md`](../docs/models/contract-v0.2-eligibility-evidence.md)

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
| `rap_contracts/schema_export.py` | Deterministic JSON Schema generation and drift check |
| `schemas/` | Generated JSON Schemas (do not edit by hand) |
| `fixtures/` | Synthetic fixture sets: `foundations-…` (PR #4) and `eligibility-evidence-…` (extends it) |
| `tests/` | `unittest` suites; `tests/support.py` holds the **mock** source authority and chunk store |
| `requirements.txt` / `requirements-dev.txt` | Runtime pin / dev-only additions for tests |

## Reproduce

From a clean checkout, in the `contracts/` directory:

```bash
python -m venv .venv && . .venv/bin/activate
python -m pip install -r requirements-dev.txt   # runtime pin + dev-only jsonschema
python -m rap_contracts.schema_export --check   # expect: schema drift: NONE
python -m unittest discover -s tests -v
```

`requirements.txt` holds the runtime pin only (`pydantic`). `requirements-dev.txt` adds `jsonschema` for the independent conformance tests in `tests/test_json_schema_conformance.py`; with runtime requirements alone those tests are reported as skipped.

`invariants.check_record_set` validates a record set as **complete** by default: every submission's exact pinned profile version must be present. Pass `pinned_versions="may_be_absent"` for a partial projection; the pinned version must then be established by `source_checks.resolve_submission_evidence`, which fails closed.

Regenerate schemas after an intentional model change with `python -m rap_contracts.schema_export`, and commit the result with the change. Output is reproducible only with the pinned Pydantic version.

## What passing tests do and do not mean

Passing tests show that the contracts, invariants and fail-closed plumbing behave as specified on synthetic data. They do **not** show live Drupal authorization, source freshness, revision retention, database uniqueness, transactionality or append-only audit. Tests that use `FixtureSourceAuthority` or `FixtureChunkStore` are mock-level only. Fixture eligibility results are hand-written expected labels; passing tests do not demonstrate an eligibility engine, an index, or that a model ignores injected instructions.
