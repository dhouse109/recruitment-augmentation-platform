"""Phase 1, admission (A1-A8): all-or-nothing, before any engine call (plan section 4.1).

Any failure raises ``AdmissionAbort``. The caller exits with code 3 and writes
nothing: no ``EvaluationRun``, ``CaseObservation``, sidecar or coverage file, and
the output directory is not created.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from rap_contracts.evaluation import NOT_APPLICABLE, CodeRevision, EvaluationCase, OptionalPin
from rap_contracts.models import CONTRACT_VERSION

from . import EXPECTED_CONTRACT_VERSION, AdmissionAbort
from .applicability import check_applicability
from .definitions import DefinitionsCheck, verify_definitions
from .fixtures import FIXTURE_DIR, FixtureSet, GoldenData, check_integrity, load_fixtures
from .scope import (
    AdmittedScope,
    LabelKey,
    OwnershipGraph,
    build_ownership,
    build_scope,
    project_label_key,
    raw_pool,
)


@dataclass(frozen=True)
class RunConfig:
    as_of: datetime
    out: Path
    code_revision: CodeRevision
    purpose: str = "regression"
    replicates: int = 1
    retrieval_index: OptionalPin = NOT_APPLICABLE
    prompt: OptionalPin = NOT_APPLICABLE
    model: OptionalPin = NOT_APPLICABLE
    judge: OptionalPin = NOT_APPLICABLE


@dataclass(frozen=True)
class Admitted:
    as_of: datetime  # UTC
    golden: GoldenData
    definitions: DefinitionsCheck
    graph: OwnershipGraph
    selected: tuple[EvaluationCase, ...]
    scopes: Mapping[str, AdmittedScope]
    keys: Mapping[tuple[str, str], LabelKey]
    principals: Mapping[str, str]
    opened: tuple[str, ...]
    contract_version: str
    code_revision: CodeRevision | None = None


def check_environment(config: RunConfig) -> datetime:
    """A1: clean recorded commit, contract version, purpose, no model pins, one replicate, aware as_of, new output path."""
    rev = config.code_revision
    if rev.status != "recorded" or rev.dirty is not False:
        raise AdmissionAbort("A1", "code_revision_not_clean", "a recorded, clean commit is required")
    if CONTRACT_VERSION != EXPECTED_CONTRACT_VERSION:
        raise AdmissionAbort("A1", "contract_version_mismatch", f"installed {CONTRACT_VERSION}")
    if config.purpose != "regression":
        raise AdmissionAbort("A1", "purpose_not_regression", str(config.purpose))
    if any(p.status != "not_applicable" for p in (config.retrieval_index, config.prompt, config.model, config.judge)):
        raise AdmissionAbort("A1", "model_pin_present", "no retrieval index, prompt, model or judge pin is admitted")
    if config.replicates != 1:
        raise AdmissionAbort("A1", "replicates_not_one", str(config.replicates))
    as_of = config.as_of
    if not isinstance(as_of, datetime) or as_of.tzinfo is None or as_of.utcoffset() is None:
        raise AdmissionAbort("A1", "as_of_not_aware", "as_of must be timezone-aware")
    if Path(config.out).exists():
        raise AdmissionAbort("A1", "output_exists", str(config.out))
    return as_of.astimezone(timezone.utc)


def resolve_keys(selected: tuple[EvaluationCase, ...], pool: Mapping[str, Any], case_records: Mapping[str, Any],
                 graph: OwnershipGraph, scopes: Mapping[str, AdmittedScope]) -> tuple[dict, dict]:
    """A7: every selected engine step's label exists once, is in scope and has a key the scope can assess."""
    keys: dict[tuple[str, str], LabelKey] = {}
    principals: dict[str, str] = {}
    for case in selected:
        declared = case.initial_state.authority.principals
        if len(declared) != 1:
            raise AdmissionAbort("A7", "principal_count", f"{case.id}: {len(declared)}")
        principals[case.id] = declared[0]
        scope = scopes[case.id]
        ctx = scope.eligibility
        for step in case.steps:
            if step.operation != "eligibility_support":
                continue
            hits = [r for r in list(pool["eligibility_results"]) + list(case_records.get("eligibility_results", []))
                    if r["id"] == step.eligibility_result_id]
            if len(hits) != 1:
                raise AdmissionAbort("A7", "label_id_missing" if not hits else "label_id_duplicate",
                                     f"{case.id}/{step.step_id}")
            if graph.owner("eligibility_results", hits[0]) not in scope.candidates:
                raise AdmissionAbort("A7", "label_out_of_scope", f"{case.id}/{step.step_id}")
            key = project_label_key(hits[0])
            cands = {c.id: c for c in ctx.records.candidates}
            opps = {o.id: o for o in ctx.records.opportunities}
            cand, opp = cands.get(key.candidate_id), opps.get(key.opportunity_id)
            if cand is None or key.candidate_id not in scope.candidates:
                raise AdmissionAbort("A7", "key_candidate_not_in_scope", f"{case.id}/{step.step_id}")
            if opp is None:
                raise AdmissionAbort("A7", "key_opportunity_unknown", f"{case.id}/{step.step_id}")
            if not (key.organization_id == cand.organization_id == opp.organization_id):
                raise AdmissionAbort("A7", "key_organization_mismatch", f"{case.id}/{step.step_id}")
            policy = [p for p in ctx.policies if (p.id, p.version) == (key.policy.policy_set_id, key.policy.version)]
            if len(policy) != 1 or policy[0].source_ref != key.policy.source_ref:
                raise AdmissionAbort("A7", "key_policy_pin_mismatch", f"{case.id}/{step.step_id}")
            keys[(case.id, step.step_id)] = key
    return keys, principals


def admit_fixtures(fs: FixtureSet, as_of: datetime) -> Admitted:
    """A3-A8 over already-loaded fixtures. Shared by ``run`` and ``verify-repeat``."""
    golden = check_integrity(fs)                                   # A3
    definitions = verify_definitions(fs.definitions, golden.manifest)  # A4
    pool = raw_pool(fs.layers)
    case_records = fs.golden["case_records"]
    graph = build_ownership(pool, case_records, golden.cases)        # A5
    selected = check_applicability(golden.cases)                    # A8 (classification needed before scoping)
    scopes = {case.id: build_scope(case, pool, case_records, graph) for case in selected}  # A6
    keys, principals = resolve_keys(selected, pool, case_records, graph, scopes)            # A7
    return Admitted(as_of=as_of, golden=golden, definitions=definitions, graph=graph, selected=selected,
                    scopes=scopes, keys=keys, principals=principals, opened=fs.opened,
                    contract_version=CONTRACT_VERSION)


def admit(config: RunConfig, fixture_dir: Path = FIXTURE_DIR) -> Admitted:
    as_of = check_environment(config)                               # A1
    fs = load_fixtures(fixture_dir)                                  # A2
    admitted = admit_fixtures(fs, as_of)
    return Admitted(**{**admitted.__dict__, "code_revision": config.code_revision})
