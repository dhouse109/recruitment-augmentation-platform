# Portable Reference Contracts — v0.2 Foundations

**Version:** `0.2.0-dev.foundations` — partial development version, **proposed, NOT frozen**  
**Covers:** D-004.01 identity, D-004.02 profile/application separation, D-004.07 source-version representation  
**Traceability, evidence and limits:** [`docs/models/contract-v0.2-foundations.md`](../docs/models/contract-v0.2-foundations.md)

Pydantic v2 is used for these reference contracts only. It is not a selection of the application runtime. All data is synthetic.

## Layout

| Path | Contents |
|---|---|
| `rap_contracts/models.py` | Contract models and single-record validators |
| `rap_contracts/invariants.py` | Cross-record rules: identity mapping, org scope, lifecycle, submission preservation |
| `rap_contracts/source_checks.py` | Version-kind checks, snapshot-method registry, fail-closed source-check policy, `SourceAuthority` protocol |
| `rap_contracts/schema_export.py` | Deterministic JSON Schema generation and drift check |
| `schemas/` | Generated JSON Schemas (do not edit by hand) |
| `fixtures/` | Synthetic fixture set |
| `tests/` | `unittest` suites; `tests/support.py` holds the **mock** source authority |

## Reproduce

From a clean checkout, in the `contracts/` directory:

```bash
python -m venv .venv && . .venv/bin/activate
python -m pip install -r requirements.txt
python -m rap_contracts.schema_export --check   # expect: schema drift: NONE
python -m unittest discover -s tests -v
```

Regenerate schemas after an intentional model change with `python -m rap_contracts.schema_export`, and commit the result with the change. Output is reproducible only with the pinned Pydantic version.

## What passing tests do and do not mean

Passing tests show that the contracts, invariants and fail-closed plumbing behave as specified on synthetic data. They do **not** show live Drupal authorization, source freshness, revision retention, database uniqueness, transactionality or append-only audit. Tests that use `FixtureSourceAuthority` are mock-level only.
