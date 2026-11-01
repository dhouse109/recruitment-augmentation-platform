"""Artifact writing, publication validation, cross-artifact binding verification and atomic publication.

Publication checks: contract re-validation (P1); the execution state machine
(SM1-SM3: a step is skipped iff an earlier prerequisite stopped the case, and the
prerequisite's status follows from its re-run validator result); the X1-X9
bindings; the recorded source-gate evidence (G1: gated references and fixture-mock
answers reconstructed from the admitted scope); coverage (P4); the held-out
identifier scan (S1); and the identity record (P5).

Everything is written to a temporary directory next to ``--out``, re-read from
disk, re-parsed through the contracts and checked: run and observation shape,
coverage, the X1-X9 bindings between observations, cases, the sidecar and the
admitted scopes, the identities, and an output scan for held-out-owned
identifiers. Only then is the directory renamed to ``--out`` in one step. Any
failure removes the temporary directory: nothing is published.

X1-X9 re-derive what they check. The input fingerprint is recomputed from the
ADMITTED scope and key with the engine's published projection and identity
functions, the result id and output digest are recomputed from that fingerprint
and the stored result bytes, and the validator is re-run on the stored result.
A declared sidecar fingerprint or id is never trusted. This is not a trusted
attestation: no trusted evaluation-record service exists.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from pydantic import ValidationError

from rap_baseline import EVALUATED_BY, EligibilityRequest
from rap_baseline.engine import ENGINE
from rap_baseline.identity import (
    build_decision_inputs,
    canonical,
    input_fingerprint,
    normalize_ref,
    output_digest,
    result_id,
    utc_text,
)
from rap_baseline.inputs import gate_refs, project, resolve_targets
from rap_contracts.eligibility import EligibilityResult
from rap_contracts.evaluation import CaseObservation, EvaluationRun, StepRole, StepStatus

from . import EXECUTED_BY, BindingFailure, RunnerFailure
from .authority import FixtureMockAuthority
from .applicability import CLASS_REASONS, CLASS_TABLE, F3_SHARED_SCENARIO, SELECTION, SELECTION_VERSION, class_table_digest
from .execute import ENGINE_BASIS, VALIDATOR_BASIS, WORKFLOW, validate_context, compare, result_json, rule_view, validate_result
from .identity import output_digest as normalized_output_digest
from .identity import spec_digest, specification

RUN_FILE, OBSERVATIONS_FILE, COVERAGE_FILE, SIDECAR_FILE, IDENTITY_FILE = (
    "run.json", "observations.json", "coverage.json", "sidecar.json", "identity.json")
FILES = (RUN_FILE, OBSERVATIONS_FILE, COVERAGE_FILE, SIDECAR_FILE, IDENTITY_FILE)

STATEMENTS = (
    "Engine steps (T3, deterministic_baseline_execution) record agreement or disagreement with PROPOSED, "
    "unadjudicated labels. Agreement is not reviewed correctness, accuracy or safety.",
    "g025 s1 is a reference-validator prerequisite (T2, reference_validator), not an engine step.",
    "The source authority is a fixture mock: no Drupal authorization, permission or currentness is established (not T4).",
    "Run status is partial: 4 of 26 pinned cases were executed. No metric, gate, comparison or promotion was computed.",
    "g002 and g008 share one scenario (F3): they are one distinct assessment.",
)


@dataclass
class Products:
    run: EvaluationRun
    observations: list[CaseObservation]
    entries: list  # execute.SidecarEntry
    coverage: dict
    spec: dict
    admitted: Any


# ---------------------------------------------------------------------------
# Coverage
# ---------------------------------------------------------------------------


def _assessment(entry: Mapping[str, Any]) -> str:
    k = {f: v for f, v in entry["label_key"].items() if f != "label_id"}
    return json.dumps([k, entry["request"]], sort_keys=True)


def build_coverage(observations: Iterable[CaseObservation], entries: list[Mapping[str, Any]]) -> dict:
    observations = list(observations)
    executed = [o for o in observations if o.execution_status == "executed"]
    steps = [s for o in executed for s in o.steps if s.status is not StepStatus.NOT_EVALUATED]
    return {
        "artifact": "rap-evaluation.coverage/1",
        "pinned_cases": len(observations),
        "executed_cases": len(executed),
        "executed": [{"case_id": o.case_id, "class": CLASS_TABLE[o.case_id]} for o in executed],
        "not_run_cases": len(observations) - len(executed),
        "not_run": [{"case_id": o.case_id, "class": CLASS_TABLE[o.case_id], "reason": CLASS_REASONS[CLASS_TABLE[o.case_id]]}
                    for o in observations if o.execution_status == "not_run"],
        "executed_steps": len(steps),
        "engine_steps": sum(1 for s in steps if s.basis is ENGINE_BASIS),
        "validator_steps": sum(1 for s in steps if s.basis is VALIDATOR_BASIS),
        "engine_invocations": len(entries),
        "distinct_assessments": len({_assessment(e) for e in entries}),
        "f3_shared_scenario": list(F3_SHARED_SCENARIO),
        "selection": list(SELECTION),
        "selection_version": SELECTION_VERSION,
        "class_table_sha256": class_table_digest(),
        "evidence_tiers": {"engine_steps": "T3 deterministic_baseline_execution",
                           "validator_steps": "T2 reference_validator", "integrated": "not T4"},
        "statements": list(STATEMENTS),
    }


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def sidecar_document(entries: list) -> dict:
    return {"artifact": "rap-evaluation.sidecar/1", "visibility": "internal_only",
            "workflow": WORKFLOW, "entries": [e.to_json() for e in entries]}


def serialize(p: Products) -> dict[str, Any]:
    observations = [o.model_dump(mode="json") for o in p.observations]
    sidecar = sidecar_document(p.entries)
    return {
        RUN_FILE: p.run.model_dump(mode="json"),
        OBSERVATIONS_FILE: observations,
        COVERAGE_FILE: p.coverage,
        SIDECAR_FILE: sidecar,
        IDENTITY_FILE: {
            "artifact": "rap-evaluation.identity/1",
            "execution_id": p.run.id,
            "configuration_fingerprint": p.run.configuration.fingerprint,
            "specification": p.spec,
            "specification_digest": spec_digest(p.spec),
            "output_digest": normalized_output_digest(observations, p.coverage, sidecar),
        },
    }


def dumps(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def load_dir(directory: Path) -> tuple[dict[str, Any], dict[str, str]]:
    docs, texts = {}, {}
    for name in FILES:
        path = Path(directory) / name
        try:
            texts[name] = path.read_text(encoding="utf-8")
            docs[name] = json.loads(texts[name])
        except (OSError, json.JSONDecodeError) as exc:
            raise BindingFailure("P0", f"{name}: {type(exc).__name__}") from None
    extra = sorted(set(os.listdir(directory)) - set(FILES))
    if extra:
        raise BindingFailure("P0", f"unexpected files: {extra}")
    return docs, texts


# ---------------------------------------------------------------------------
# Cross-artifact binding verification (X1-X9)
# ---------------------------------------------------------------------------


def _fail(check: str, detail: str) -> None:
    raise BindingFailure(check, detail)


def _projection(key, scope, principal: str, as_of):
    request = EligibilityRequest(organization_id=key.organization_id, candidate_id=key.candidate_id,
                                 opportunity_id=key.opportunity_id, policy=key.policy, principal_id=principal, as_of=as_of)
    targets = resolve_targets(request, scope.eligibility)
    return targets, project(scope.eligibility, targets)


def recompute_fingerprint(key, scope, principal: str, as_of) -> str:
    """The input fingerprint, recomputed from the ADMITTED scope and key (never read from the sidecar)."""
    _, projected = _projection(key, scope, principal, as_of)
    return input_fingerprint(build_decision_inputs(projected, key.organization_id, key.candidate_id,
                                                   key.opportunity_id, ENGINE))


def expected_gate_evidence(case, index: int, key, scope, principal: str, as_of) -> tuple[list, list]:
    """The source-gate audit fields an engine step must have recorded, reconstructed from the admitted scope.

    Gated references: the engine's own decision-relevant set for the admitted projection (``gate_refs``), in its
    order. Answers: the approved deterministic fixture-mock behaviour for this case's principal, with the case's
    overrides and the authority deltas of every step up to and including this one. A reproducible mock answer is
    NOT trusted external authority evidence; it only shows the recorded answers are the ones the mock gives.
    """
    targets, projected = _projection(key, scope, principal, as_of)
    refs = gate_refs(projected, targets)
    authority = FixtureMockAuthority([principal], scope.source_refs, as_of)
    authority.apply(case.initial_state.authority.overrides)
    for step in case.steps[:index + 1]:
        authority.apply(step.authority_delta)
    answers = [authority.check(principal, ref) for ref in refs]
    return [canonical(normalize_ref(r)) for r in refs], [canonical(a) for a in answers]


def verify_bindings(observations: list[CaseObservation], entries: list[Mapping[str, Any]], admitted) -> None:
    cases = {c.id: c for c in admitted.selected}
    as_of_text = utc_text(admitted.as_of)
    by_step: dict[tuple[str, str], Mapping[str, Any]] = {}
    for e in entries:
        k = (e.get("case_id"), e.get("step_id"))
        if k in by_step:
            _fail("X1", f"duplicate sidecar entry {k}")
        by_step[k] = e
    referenced: set[tuple[str, str]] = set()
    generated: dict[tuple, tuple] = {}
    for obs in observations:
        if obs.execution_status != "executed":
            continue
        case = cases.get(obs.case_id)
        if case is None:
            _fail("P2", f"{obs.case_id} executed but not selected")
        steps = {s.step_id: s for s in case.steps}
        if [s.step_id for s in obs.steps] != [s.step_id for s in case.steps]:
            _fail("P2", f"{obs.case_id}: observed steps differ from the case's steps")
        scope = admitted.scopes[case.id]
        principal = admitted.principals[case.id]
        halted = False
        for index, so in enumerate(obs.steps):
            step = steps[so.step_id]
            k = (case.id, step.step_id)
            if so.operation.value != step.operation or so.role is not step.role:
                _fail("P2", f"{k}: operation or role differs from the case")
            # Execution state machine (SM1-SM3): a step is skipped if and only if an earlier prerequisite or
            # control step did not match. An engine refusal or error is an evaluated (errored) step.
            if halted and so.status is not StepStatus.NOT_EVALUATED:
                _fail("SM2", f"{k}: evaluated after a prerequisite stopped the case")
            if not halted and so.status is StepStatus.NOT_EVALUATED:
                _fail("SM1", f"{k}: skipped although nothing earlier stopped the case")
            if step.operation != "eligibility_support":
                if so.basis is not VALIDATOR_BASIS or k in by_step:
                    _fail("P3", f"{k}: prerequisite must be a reference-validator step with no engine entry")
                if so.status is not StepStatus.NOT_EVALUATED:
                    again = validate_context(scope)
                    if (again.result, again.violation_code) != (so.observed.result, so.observed.violation_code):
                        _fail("P3", f"{k}: prerequisite observation not reproduced")
                    exp = step.expected
                    follows = (StepStatus.MATCHED if (again.result, again.violation_code) == (exp.result, exp.violation_code)
                               else StepStatus.MISMATCHED)
                    if so.status is not follows:
                        _fail("SM3", f"{k}: prerequisite status {so.status.value} does not follow from the validator "
                                     f"result and the expectation ({follows.value})")
            elif so.basis is not ENGINE_BASIS:
                _fail("P3", f"{k}: engine step basis is {so.basis.value}")
            if step.role in (StepRole.PREREQUISITE, StepRole.CONTROL) and so.status is not StepStatus.MATCHED:
                halted = True
            if step.operation != "eligibility_support" or so.status is StepStatus.NOT_EVALUATED:
                continue
            e = by_step.get(k)
            if e is None:
                _fail("X1", f"{k}: no sidecar entry")
            referenced.add(k)
            key = admitted.keys[k]
            if e.get("label_key") != key.canonical() or e.get("request") != {"principal_id": principal, "as_of": as_of_text}:
                _fail("X5", f"{k}: sidecar key or request differs from the admitted key")
            if so.status in (StepStatus.MATCHED, StepStatus.MISMATCHED):
                _check_assessed(k, step, so, e, key, scope, principal, admitted)
                _check_gate_evidence(k, case, index, e, key, scope, principal, admitted)
                generated.setdefault(key.assessment(), (e["result_json"], so.observed.eligibility_result_id))
                if generated[key.assessment()] != (e["result_json"], so.observed.eligibility_result_id):
                    _fail("X9", f"{k}: steps sharing a key carry different generated results")
            elif so.status is StepStatus.ERRORED:
                _check_errored(k, so, e)
                generated.setdefault(key.assessment(), (e.get("outcome"), json.dumps(e.get("refusal"), sort_keys=True)))
                if generated[key.assessment()] != (e.get("outcome"), json.dumps(e.get("refusal"), sort_keys=True)):
                    _fail("X9", f"{k}: steps sharing a key carry different engine outcomes")
            else:
                _fail("P3", f"{k}: unexpected status {so.status.value}")
    orphans = set(by_step) - referenced
    if orphans:
        _fail("X1", f"orphan sidecar entries {sorted(orphans)}")


def _check_assessed(k, step, so, e, key, scope, principal, admitted) -> None:
    # X2: the stored bytes parse, are canonical, and name the observed id
    if e.get("outcome") != "assessed" or not isinstance(e.get("result_json"), str):
        _fail("X2", f"{k}: evaluated engine step without generated result bytes")
    try:
        result = EligibilityResult.model_validate_json(e["result_json"])
    except ValidationError:
        _fail("X2", f"{k}: sidecar bytes are not an EligibilityResult")
    if result_json(result) != e["result_json"]:
        _fail("X2", f"{k}: sidecar bytes are not the canonical serialization")
    if so.observed.eligibility_result_id != result.id or e.get("result_id") != result.id:
        _fail("X2", f"{k}: observed id does not name the generated result")
    # X3: recompute fingerprint, id and digest; never trust the declared values
    try:
        fp = recompute_fingerprint(key, scope, principal, admitted.as_of)
    except Exception as exc:  # the admitted key no longer resolves: binding cannot be established
        _fail("X3", f"{k}: fingerprint not recomputable ({type(exc).__name__})")
    prov = e.get("provenance") or {}
    if e.get("input_fingerprint") != fp or prov.get("input_fingerprint") != fp:
        _fail("X3", f"{k}: declared input fingerprint differs from the recomputed one")
    if result.id != result_id(fp, admitted.as_of):
        _fail("X3", f"{k}: result id is not recomputable from the admitted inputs and as_of")
    digest = output_digest(result)
    if e.get("output_digest") != digest or prov.get("output_digest") != digest:
        _fail("X3", f"{k}: output digest differs from the stored result")
    if (prov.get("result_id"), prov.get("principal_id"), prov.get("as_of"), prov.get("evaluated_by")) != (
            result.id, principal, utc_text(admitted.as_of), EVALUATED_BY):
        _fail("X3", f"{k}: provenance does not describe this result")
    # X4: never a label id
    if result.id == step.eligibility_result_id or result.id in admitted.graph.label_ids:
        _fail("X4", f"{k}: generated id equals a fixture label id")
    # X5: the result's key is the admitted label key
    p = result.policy
    if (result.organization_id, result.candidate_id, result.opportunity_id, p.policy_set_id, p.version,
            p.source_ref) != key.assessment():
        _fail("X5", f"{k}: generated result key differs from the admitted label key")
    # X6: observed decision and outcomes are the result's, and the status is the comparison's
    if so.observed.decision != result.decision or tuple(so.observed.rule_outcomes) != rule_view(result):
        _fail("X6", f"{k}: observed decision or rule outcomes differ from the generated result")
    if (so.status is StepStatus.MATCHED) != compare(step, so.observed):
        _fail("X6", f"{k}: step status does not follow from the comparison with the label")
    # X7: the validator verdict is reproduced on the generated result
    if validate_result(result, scope) != (so.observed.result, so.observed.violation_code):
        _fail("X7", f"{k}: validator verdict on the generated result not reproduced")


def _check_gate_evidence(k, case, index, e, key, scope, principal, admitted) -> None:
    """G1: the recorded source-gate audit fields equal the reconstruction; nothing missing, substituted or extra."""
    prov = e.get("provenance") or {}
    try:
        refs, answers = expected_gate_evidence(case, index, key, scope, principal, admitted.as_of)
    except Exception as exc:
        _fail("G1", f"{k}: gate evidence not reconstructible ({type(exc).__name__})")
    if prov.get("gated_refs") != refs:
        _fail("G1", f"{k}: recorded gated references differ from the admitted projection's gate set")
    if prov.get("checks") != answers:
        _fail("G1", f"{k}: recorded source-check answers differ from the fixture-mock reconstruction")
    if any((a.get("version_status"), a.get("access_status")) != ("current", "allowed") for a in answers):
        _fail("G1", f"{k}: assessed although a gated source was not current and allowed")


def _check_errored(k, so, e) -> None:
    refusal = e.get("refusal") or {}
    if (e.get("outcome") not in ("refused", "errored") or e.get("result_json") is not None
            or e.get("result_id") is not None or e.get("provenance") is not None
            or not refusal.get("stage") or not refusal.get("code")):
        _fail("X8", f"{k}: errored step must carry an engine refusal or error and no result")
    if so.observed.error_type != f"engine_{e['outcome']}" or so.observed.eligibility_result_id is not None:
        _fail("X8", f"{k}: error type does not match the engine outcome")


# ---------------------------------------------------------------------------
# Publication validation
# ---------------------------------------------------------------------------


def scan_held_out(texts: Mapping[str, str], identifiers: Iterable[str]) -> None:
    for ident in sorted(identifiers):
        pattern = re.compile(r"(?<![A-Za-z0-9_])" + re.escape(ident) + r"(?![A-Za-z0-9_])")
        for name, text in texts.items():
            if pattern.search(text):
                _fail("S1", f"held-out-owned identifier in {name}")


def validate_published(docs: Mapping[str, Any], texts: Mapping[str, str], admitted) -> None:
    try:
        run = EvaluationRun.model_validate(docs[RUN_FILE])
        observations = [CaseObservation.model_validate(o) for o in docs[OBSERVATIONS_FILE]]
    except (ValidationError, TypeError) as exc:
        _fail("P1", f"contract re-validation failed: {type(exc).__name__}")
    g = admitted.golden
    if (run.status != "partial" or run.completed_at is not None or run.run_kind.value != "deterministic_baseline"
            or run.purpose.value != "regression" or run.manifests != (g.pin,) or run.source_authority != "fixture_mock"
            or run.definitions != admitted.definitions.metrics or run.safety_policy != admitted.definitions.policy
            or run.contract_version != admitted.contract_version or run.executed_by != EXECUTED_BY
            or run.latency.status.value != "not_measured" or run.replicates != 1):
        _fail("P1", "run fields differ from the admitted specification")
    if [o.case_id for o in observations] != [c.id for c in g.cases]:
        _fail("P1", "observations are not exactly the pinned cases in manifest order")
    pins = {p.case_id: p for p in g.manifest.case_pins}
    for o in observations:
        if o.run_id != run.id or o.case_sha256 != pins[o.case_id].sha256 or o.case_version != pins[o.case_id].version:
            _fail("P1", f"{o.case_id}: run id or case pin differs")
        if o.execution_status != ("executed" if o.case_id in SELECTION else "not_run"):
            _fail("P1", f"{o.case_id}: selected cases are executed and all others not_run")
        if o.latency.status.value != "not_measured" or o.cost.status.value != "not_applicable":
            _fail("P1", f"{o.case_id}: measurement fields must be not_measured / not_applicable")
    entries = docs[SIDECAR_FILE].get("entries")
    if not isinstance(entries, list) or not all(isinstance(e, dict) for e in entries):
        _fail("P1", "sidecar has no entries")
    verify_bindings(observations, entries, admitted)
    if docs[COVERAGE_FILE] != build_coverage(observations, entries):
        _fail("P4", "coverage does not follow from the observations and sidecar")
    scan_held_out(texts, admitted.graph.held_out_identifiers)
    ident = docs[IDENTITY_FILE]
    expected_spec = specification(admitted=admitted, as_of_text=utc_text(admitted.as_of),
                                  configuration_fingerprint=run.configuration.fingerprint)
    if (ident.get("execution_id") != run.id or ident.get("configuration_fingerprint") != run.configuration.fingerprint
            or ident.get("specification") != expected_spec or ident.get("specification_digest") != spec_digest(expected_spec)
            or ident.get("output_digest") != normalized_output_digest(docs[OBSERVATIONS_FILE], docs[COVERAGE_FILE],
                                                                      docs[SIDECAR_FILE])):
        _fail("P5", "identity record does not match the recomputed identities")


# ---------------------------------------------------------------------------
# Atomic publication
# ---------------------------------------------------------------------------


def publish(products: Products, out: Path) -> Path:
    out = Path(out)
    if out.exists():
        raise RunnerFailure("output_exists", str(out))
    created: list[Path] = []
    parent = out.parent
    while not parent.exists():
        created.append(parent)
        parent = parent.parent
    tmp = None
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = Path(tempfile.mkdtemp(prefix=f".{out.name}.tmp-", dir=out.parent))
        for name, obj in serialize(products).items():
            (tmp / name).write_text(dumps(obj), encoding="utf-8")
        docs, texts = load_dir(tmp)
        validate_published(docs, texts, products.admitted)
        os.rename(tmp, out)
        return out
    except BaseException as exc:
        if tmp is not None:
            shutil.rmtree(tmp, ignore_errors=True)
        for path in created:  # deepest first
            try:
                path.rmdir()
            except OSError:
                pass
        if isinstance(exc, RunnerFailure) or not isinstance(exc, Exception):
            raise
        raise RunnerFailure("publication_failed", type(exc).__name__) from exc
