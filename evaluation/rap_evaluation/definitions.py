"""A4: read-only verification of the draft metric definitions v1 and safety-gate policy v3 (plan section 4.3).

F3 (RAP-F3-PLAN-2026-11-04 rev. 1.1, decision F3-D2 option P1): policy v3 is
policy v1 with its golden manifest pin moved to ``evalset_golden`` v2. The
metric definitions stay at draft v1 (decision E7 unchanged); draft metrics v2
remain non-default and are never loaded.

Only ``metric_definitions`` and ``safety_gate_policy`` are used. Nothing is
computed, approved or defaulted: no metric value, gate evaluation, comparison or
promotion API is called. ``check_policy_manifest`` is a consistency check that
the policy pins exactly this golden manifest. The policy's held-out manifest pin
is recorded (identity and root only) and never resolved.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from rap_contracts.evaluation import DefinitionsPin, EvaluationDatasetManifest, content_sha256
from rap_contracts.invariants import ContractViolation
from rap_contracts.promotion import MetricDefinitionSet, SafetyGatePolicy, check_policy_manifest
from rap_contracts.source_checks import canonical_json_sha256

from . import AdmissionAbort

METRICS_PIN = DefinitionsPin(id="evaldefs_metrics", version=1)
POLICY_PIN = DefinitionsPin(id="evaldefs_safety_gate", version=3)


@dataclass(frozen=True)
class DefinitionsCheck:
    metrics: DefinitionsPin
    policy: DefinitionsPin
    file_sha256: str
    metrics_sha256: str
    policy_sha256: str
    statuses: tuple[str, str]
    held_out_manifest_pin: dict  # recorded only; never resolved

    def canonical(self) -> dict:
        return {
            "metrics": self.metrics.model_dump(mode="json"),
            "safety_policy": self.policy.model_dump(mode="json"),
            "file_sha256": self.file_sha256,
            "metrics_sha256": self.metrics_sha256,
            "policy_sha256": self.policy_sha256,
            "statuses": list(self.statuses),
            "held_out_manifest_pin_unresolved": self.held_out_manifest_pin,
        }


def verify_definitions(doc: Any, golden_manifest: EvaluationDatasetManifest) -> DefinitionsCheck:
    try:
        metrics = MetricDefinitionSet.model_validate(doc["metric_definitions"])
        policy = SafetyGatePolicy.model_validate(doc["safety_gate_policy"])
    except (KeyError, TypeError, ValidationError) as exc:
        raise AdmissionAbort("A4", "definitions_invalid", type(exc).__name__) from None
    if metrics.pin != METRICS_PIN:
        raise AdmissionAbort("A4", "metrics_pin_mismatch", f"{metrics.id} v{metrics.version}")
    if policy.pin != POLICY_PIN:
        raise AdmissionAbort("A4", "policy_pin_mismatch", f"{policy.id} v{policy.version}")
    if metrics.status != "draft" or policy.status != "draft":
        raise AdmissionAbort("A4", "definitions_not_draft", "the runner never treats definitions as approved")
    if policy.definitions != metrics.pin:
        raise AdmissionAbort("A4", "policy_definitions_pin_mismatch", f"{policy.definitions.id} v{policy.definitions.version}")
    try:
        check_policy_manifest(policy, golden_manifest)
    except ContractViolation as exc:
        raise AdmissionAbort("A4", exc.code, str(exc)) from None
    return DefinitionsCheck(
        metrics=metrics.pin, policy=policy.pin, file_sha256=canonical_json_sha256(doc),
        metrics_sha256=content_sha256(metrics), policy_sha256=content_sha256(policy),
        statuses=(metrics.status, policy.status),
        held_out_manifest_pin=policy.held_out_manifest.model_dump(mode="json"))
