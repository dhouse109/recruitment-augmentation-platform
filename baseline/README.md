# `baseline/` — Slice 0 deterministic eligibility engine (PR-S1)

**Status:** owner-authorized PR-S1 scope only (2026-10-31). Synthetic data only. **Not** an evaluation runner, explanation generator, recommendation engine or Drupal integration. Contract v0.2 is unchanged and not frozen.

`rap_baseline.assess(request, context, authority, capabilities)` computes one `rap_contracts.eligibility.EligibilityResult` for **one candidate × one opportunity × one explicitly pinned policy version**. It uses already-loaded records and makes no model call or network request. It writes nothing. The outcome is one of:

| Outcome | Meaning |
|---|---|
| `Assessed(result, provenance)` | A result the **unmodified** contract validators accepted (post-check), plus runtime provenance: input fingerprint, output digest, principal and source checks |
| `Refused(stage, code, …)` | A designed fail-closed stop: reference, organization, structure, source integrity/authorization, or contradictory records. **Internal only.** Never an `unknown` rule outcome |
| `Errored(stage, code, …)` | A request or engine defect (invalid request, rule/construction/post-check/provenance failure, or any unexpected exception). Never converted into a refusal or an outcome |

| Module | Responsibility |
|---|---|
| `request.py` | `EligibilityRequest`, outcome types, stages |
| `inputs.py` | P1–P4: targets, metadata-only projection, organization guard, structural validators (no authority call, no value reads) |
| `engine.py` | P0–P11 orchestration: source gate, phase-2 wrapper validation, rules, result, post-check, provenance; never raises (unexpected exceptions → `Errored`) |
| `rules.py` | The only module that reads claim values, states, statuses and hours; approved SD-4/SD-5 rules |
| `identity.py` | `DecisionInputs`, input fingerprint, output digest, result id, UTC canonicalization |
| `provenance.py` | Recording authority wrapper and `AssessmentProvenance` (runtime-local, not a contract) |

## Commands

```bash
# from the repository root, Python 3.13
python -m venv .venv && . .venv/bin/activate
pip install -r contracts/requirements-dev.txt        # pydantic 2.13.5 (+ jsonschema for the contract suite)
cd baseline
PYTHONPATH=../contracts python -m unittest discover -s tests -v
```

`tests/` is not a package. `tests/builders.py` holds the test-only synthetic world and a synthetic source authority. The engine adds no dependency beyond `contracts/requirements.txt`.

## What passing tests do and do not mean

They show that the engine's ordering, fail-closed plumbing, rules, identity and determinism behave as specified on **test-local synthetic records**, and that every assessed result passes the unmodified contract validators. They do **not** show any of the following:
- real Drupal authorization, revision currentness or context completeness (the authority is synthetic; T4);
- any evaluation run, case observation or metric value (PR-S3 is not authorized);
- accuracy. Tests use only test-local synthetic records and synthetic hand-written labels; no contract fixture file (golden or nominal held-out) is read.

See `docs/baseline/slice-0-eligibility-engine.md`.
