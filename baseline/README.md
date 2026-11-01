# `baseline/` — Slice 0 deterministic eligibility engine (PR-S1) and explanations (PR-S2)

**Status:** owner-authorized PR-S1 (2026-10-31) and PR-S2 (2026-11-01) scope only. Synthetic data only. **Not** an evaluation runner, recommendation engine, reviewer presentation or Drupal integration. Contract v0.2 is unchanged and not frozen. PR-S2 explanations are runtime-local, internal artifacts and are **not authorized for reviewer presentation**.

`rap_baseline.assess(request, context, authority, capabilities)` computes one `rap_contracts.eligibility.EligibilityResult` for **one candidate × one opportunity × one explicitly pinned policy version**. It uses already-loaded records and makes no model call or network request. It writes nothing. The outcome is one of:

| Outcome | Meaning |
|---|---|
| `Assessed(result, provenance, findings, explanation)` | A result the **unmodified** contract validators accepted (post-check), plus runtime provenance (input fingerprint, output digest, principal and source checks) and, from PR-S2, independently verified structured findings and a deterministic explanation |
| `Refused(stage, code, …)` | A designed fail-closed stop: reference, organization, structure, source integrity/authorization, or contradictory records. **Internal only.** Never an `unknown` rule outcome |
| `Errored(stage, code, …)` | A request or engine defect: an invalid request; a rule, construction, post-check or provenance failure; from PR-S2, a projection-selection (`selection`), findings (`findings`) or explanation (`explanation`) verification failure; or any unexpected exception. Never converted into a refusal or an outcome. Carries no findings or explanation |

| Module | Responsibility |
|---|---|
| `request.py` | `EligibilityRequest`, outcome types, stages |
| `inputs.py` | P1–P4: targets, metadata-only projection, organization guard, structural validators (no authority call, no value reads) |
| `engine.py` | P0–P11 orchestration: source gate, phase-2 wrapper validation, rules, result, post-check, provenance; never raises (unexpected exceptions → `Errored`) |
| `rules.py` | Approved SD-4/SD-5 rules (`evaluate`, unchanged) and, from PR-S2, `build_findings` over the same `DecisionInputs` |
| `findings.py` | PR-S2: runtime-local findings types, canonical form, content digest, findings id (not a contract) |
| `findings_check.py` | PR-S2 L1: independent findings verification against the admitted projection (trusted header, exact SD-4/SD-5, scope, closure, accounting) |
| `selection_check.py` | PR-S2 L2: metadata-only projection-selection verification before the gate (`verify_selection`) |
| `explanation.py` | PR-S2: deterministic explanation from verified findings (fixed `explain-templates/1`, single time slot) |
| `identity.py` | `DecisionInputs`, input fingerprint, output digest, result id, UTC canonicalization |
| `provenance.py` | Recording authority wrapper and `AssessmentProvenance` (runtime-local, not a contract) |

## Commands

```bash
# from the repository root, Python 3.13
python -m venv .venv && . .venv/bin/activate
pip install -r contracts/requirements-dev.txt        # pydantic 2.13.5 (+ jsonschema for the contract suite)
cd baseline
PYTHONPATH=../contracts python -m unittest discover -s tests -v
# one module (tests/ is not a package): select it with -p
PYTHONPATH=../contracts python -m unittest discover -s tests -p 'test_g12_matrix.py' -v
cd ..
# PR-S2 A4: compare result/provenance bytes with another checkout (e.g. the PR-S1 base)
python -I baseline/tests/tools/dump_scenarios.py --code-root <other-checkout> > other.jsonl
python -I baseline/tests/tools/dump_scenarios.py --code-root . > head.jsonl && diff other.jsonl head.jsonl
# PR-S2 A3/A16: failure-first mutations on a scratch copy (about 3 minutes)
python -I baseline/tests/tools/mutations.py
```

`tests/` is not a package. `tests/builders.py` holds the test-only synthetic world and a synthetic source authority; `tests/g12_cases.py` holds the PR-S2 C01–C19 case matrix built on it. The engine adds no dependency beyond `contracts/requirements.txt`.

## What passing tests do and do not mean

They show that the engine's ordering, fail-closed plumbing, rules, identity and determinism behave as specified on **test-local synthetic records**, and that every assessed result passes the unmodified contract validators. They do **not** show any of the following:
- real Drupal authorization, revision currentness or context completeness (the authority is synthetic; T4);
- any evaluation run, case observation or metric value (PR-S3 is not authorized);
- accuracy. Tests use only test-local synthetic records and synthetic hand-written labels; no contract fixture file (golden or nominal held-out) is read;
- that explanations may be shown to reviewers (they may not), or that `EligibilityResult` citations are exhaustive (G12a–c remain open at the result level).

See `docs/baseline/slice-0-eligibility-engine.md` (PR-S1) and `docs/baseline/slice-0-explanations.md` (PR-S2).
