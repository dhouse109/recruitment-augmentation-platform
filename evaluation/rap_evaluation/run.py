"""Run orchestration: admission, execution, the ``partial`` ``EvaluationRun`` and the 26 case observations.

``status`` is always ``partial`` (decision E4): only 4 of the 26 pinned cases are
executed by an implemented component, so ``completed_at`` is absent and the run
is, correctly, ineligible for comparisons and promotion. The wall-clock end time
is recorded in the sidecar only.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from rap_baseline.identity import utc_text
from rap_contracts.evaluation import (
    Component,
    ConfigurationPin,
    EvaluationRun,
    Measurement,
    MeasurementStatus,
    RunKind,
    RunPurpose,
    StrategyPin,
    fingerprint_configuration,
)

from . import EXECUTED_BY, RunnerFailure
from .admission import Admitted, RunConfig, admit
from .artifacts import Products, build_coverage, publish
from .execute import NO_INFERENCE_COST, check_in_run_consistency, execute_case, not_run
from .fixtures import FIXTURE_DIR
from .identity import new_execution_id, specification

STRATEGY = StrategyPin(id="rap_baseline_eligibility", version=1, components=frozenset({Component.ELIGIBILITY}))
CONFIGURATION_ID = "rap_baseline_eligibility_slice0"
NOT_MEASURED_RUN_LATENCY = Measurement(status=MeasurementStatus.NOT_MEASURED, unit="milliseconds")


def build_run(run_id: str, started_at: datetime, config: RunConfig, admitted: Admitted) -> EvaluationRun:
    fingerprint = fingerprint_configuration(
        run_kind=RunKind.DETERMINISTIC_BASELINE, strategy=STRATEGY, code_revision=config.code_revision,
        contract_version=admitted.contract_version, retrieval_index=config.retrieval_index, prompt=config.prompt,
        model=config.model, judge=config.judge)
    return EvaluationRun(
        id=run_id, run_kind=RunKind.DETERMINISTIC_BASELINE, purpose=RunPurpose.REGRESSION,
        manifests=(admitted.golden.pin,), definitions=admitted.definitions.metrics,
        safety_policy=admitted.definitions.policy, contract_version=admitted.contract_version,
        code_revision=config.code_revision, strategy=STRATEGY,
        configuration=ConfigurationPin(id=CONFIGURATION_ID, fingerprint_version=1, fingerprint=fingerprint),
        source_authority="fixture_mock", retrieval_index=config.retrieval_index, prompt=config.prompt,
        model=config.model, judge=config.judge, replicates=config.replicates, started_at=started_at,
        completed_at=None, status="partial", errors=(), latency=NOT_MEASURED_RUN_LATENCY, cost=NO_INFERENCE_COST,
        executed_by=EXECUTED_BY)


def produce(config: RunConfig, admitted: Admitted, run_id: str, assess_fn: Callable | None = None) -> Products:
    """Phase 2 (execution) over an admitted input. Engine refusals and errors become observations."""
    try:
        started_at = datetime.now(timezone.utc)
        selected = {c.id for c in admitted.selected}
        observations, entries = [], []
        for case in admitted.golden.cases:
            if case.id in selected:
                ex = execute_case(case, admitted.scopes[case.id], admitted.keys, admitted.principals[case.id],
                                  admitted.as_of, run_id, assess_fn)
                observations.append(ex.observation)
                entries.extend(ex.entries)
            else:
                observations.append(not_run(case, run_id))
        check_in_run_consistency(entries)
        run = build_run(run_id, started_at, config, admitted)
        coverage = build_coverage(observations, [e.to_json() for e in entries])
        spec = specification(admitted=admitted, as_of_text=utc_text(admitted.as_of),
                             configuration_fingerprint=run.configuration.fingerprint)
        return Products(run=run, observations=observations, entries=entries, coverage=coverage, spec=spec,
                        admitted=admitted)
    except RunnerFailure:
        raise
    except Exception as exc:
        raise RunnerFailure("unexpected_runner_exception", type(exc).__name__) from exc


def run_evaluation(config: RunConfig, fixture_dir: Path = FIXTURE_DIR, assess_fn: Callable | None = None,
                   run_id: str | None = None) -> Path:
    """Admit (exit 3 on failure, nothing written), execute, then publish atomically (exit 4 on failure)."""
    run_id = run_id or new_execution_id()
    admitted = admit(config, fixture_dir)
    products = produce(config, admitted, run_id, assess_fn)
    return publish(products, config.out)
