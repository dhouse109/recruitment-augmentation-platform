"""Execution, configuration, specification and normalized output identities, and ``verify-repeat`` (plan section 6).

* Execution identity: ``evalrun_`` + 32 random hex characters, unique per run (not deterministic, by design).
* Configuration identity: ``ConfigurationPin.fingerprint``, recomputed by the contract.
* Specification identity: a canonical digest over everything that defines what was run.
* Normalized output identity: a canonical digest over the case observations (``run_id`` normalized),
  the coverage report and, per sidecar entry, everything except wall-clock times.
"""

from __future__ import annotations

import secrets
from typing import Any, Mapping

from rap_contracts.source_checks import canonical_json_sha256

from . import EXECUTED_BY, MOCK_AUTHORITY_ID
from .applicability import SELECTION_VERSION, class_table_digest

SPEC_VERSION = "rap-evaluation.spec/1"
OUTPUT_VERSION = "rap-evaluation.output/1"
NORMALIZED_RUN_ID = "evalrun_normalized"

PASS, NOT_INDEPENDENT, NOT_COMPARABLE, DETERMINISM_FAILURE = "PASS", "NOT_INDEPENDENT", "NOT_COMPARABLE", "DETERMINISM_FAILURE"


def new_execution_id() -> str:
    return "evalrun_" + secrets.token_hex(16)


def specification(*, admitted, as_of_text: str, configuration_fingerprint: str) -> dict:
    g = admitted.golden
    return {
        "v": SPEC_VERSION,
        "manifest": g.pin.model_dump(mode="json"),
        "manifest_contract_version": g.manifest.contract_version,
        "layers": [{"name": n, "sha256": d} for n, d in g.layer_digests],
        "case_records_sha256": g.manifest.case_records_sha256,
        "golden_document_sha256": g.document_sha256,
        "definitions": admitted.definitions.canonical(),
        "class_table_sha256": class_table_digest(),
        "selection_version": SELECTION_VERSION,
        "as_of": as_of_text,
        "principal_policy": "case_declared_single_principal",
        "source_authority": {"kind": "fixture_mock", "checked_by": MOCK_AUTHORITY_ID},
        "runner": EXECUTED_BY,
        "contract_version": admitted.contract_version,
        "configuration_fingerprint": configuration_fingerprint,
    }


def spec_digest(spec: Mapping[str, Any]) -> str:
    return canonical_json_sha256(spec)


def normalized_output(observations: list[dict], coverage: dict, sidecar: dict) -> dict:
    obs = []
    for o in observations:
        o = dict(o)
        o["run_id"] = NORMALIZED_RUN_ID
        obs.append(o)
    entries = []
    for e in sidecar["entries"]:
        e = {k: v for k, v in e.items() if k != "wall_clock"}
        entries.append(e)
    return {"v": OUTPUT_VERSION, "observations": obs, "coverage": coverage,
            "sidecar": {k: v for k, v in sidecar.items() if k != "entries"} | {"entries": entries}}


def output_digest(observations: list[dict], coverage: dict, sidecar: dict) -> str:
    return canonical_json_sha256(normalized_output(observations, coverage, sidecar))


def verdict(*, run_id_a: str, run_id_b: str, config_a: str, config_b: str, spec_a: str, spec_b: str,
            output_a: str, output_b: str) -> str:
    if run_id_a == run_id_b:
        return NOT_INDEPENDENT
    if config_a != config_b or spec_a != spec_b:
        return NOT_COMPARABLE
    if output_a != output_b:
        return DETERMINISM_FAILURE
    return PASS


def verify_repeat(dir_a, dir_b, fixture_dir=None) -> dict:
    """Re-verify both runs (contracts, coverage, X1-X9, identities) and classify their relation.

    Each directory is re-admitted at its own ``as_of`` from the current fixtures
    (A2-A8, read-only) and validated exactly as at publication. Digests are
    recomputed from the files; the declared identity record is not trusted.
    A validation or binding failure raises ``BindingFailure`` (exit 4).
    """
    from datetime import datetime

    from rap_contracts.evaluation import EvaluationRun

    from . import BindingFailure
    from .admission import admit_fixtures
    from .artifacts import COVERAGE_FILE, IDENTITY_FILE, OBSERVATIONS_FILE, RUN_FILE, SIDECAR_FILE, load_dir, validate_published
    from .fixtures import FIXTURE_DIR, load_fixtures

    fs = load_fixtures(fixture_dir or FIXTURE_DIR)
    summary = {}
    for label, directory in (("a", dir_a), ("b", dir_b)):
        docs, texts = load_dir(directory)
        spec = docs[IDENTITY_FILE].get("specification") or {}
        try:
            as_of = datetime.fromisoformat(spec["as_of"].replace("Z", "+00:00"))
        except (KeyError, AttributeError, ValueError):
            raise BindingFailure("P5", f"{label}: specification has no valid as_of") from None
        admitted = admit_fixtures(fs, as_of)
        validate_published(docs, texts, admitted)
        run = EvaluationRun.model_validate(docs[RUN_FILE])
        summary[label] = {
            "execution_id": run.id,
            "configuration_fingerprint": run.configuration.fingerprint,
            "specification_digest": spec_digest(spec),
            "output_digest": output_digest(docs[OBSERVATIONS_FILE], docs[COVERAGE_FILE], docs[SIDECAR_FILE]),
        }
    a, b = summary["a"], summary["b"]
    result = verdict(run_id_a=a["execution_id"], run_id_b=b["execution_id"],
                     config_a=a["configuration_fingerprint"], config_b=b["configuration_fingerprint"],
                     spec_a=a["specification_digest"], spec_b=b["specification_digest"],
                     output_a=a["output_digest"], output_b=b["output_digest"])
    return {"verdict": result, "a": a, "b": b}
