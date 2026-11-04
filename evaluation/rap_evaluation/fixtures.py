"""Allowed-path fixture loading (A2) and integrity pins (A3).

Only five files may be opened: the three pinned base layers, the golden v2 case
file and the definitions file that pins it (draft metric definitions v1 and draft
safety-gate policy v3; F3, RAP-F3-PLAN-2026-11-04 rev. 1.1). Golden v1 and the
definitions v1/v2 files are preserved unchanged in the repository but are not
read by this runner version. The nominal held-out case file's path is never
constructed here or anywhere in this package.

Parsing the shared base layers is contact with held-out-owned synthetic records
(candidates D and E): the eligibility layer is shared. The guards in ``scope.py``
establish only that no such record is constructed as a contract model, supplied
to the engine or validator, or emitted in an artifact (plan rev. 2.1, section 4.2).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from rap_contracts.evaluation import (
    Custody,
    EvaluationCase,
    EvaluationDatasetManifest,
    HeldOutIntegrity,
    ManifestPin,
    Split,
    check_manifest_cases,
    pin_manifest,
)
from rap_contracts.invariants import ContractViolation
from rap_contracts.source_checks import canonical_json_sha256

from . import AdmissionAbort

REPO = Path(__file__).resolve().parents[2]
FIXTURE_DIR = REPO / "contracts" / "fixtures"

LAYER_FILES = ("foundations-v0.2.0-dev.json", "eligibility-evidence-v0.2.0-dev.json", "review-v0.2.0-dev.json")
GOLDEN_FILE = "evaluation-golden-v2-v0.2.0-dev.json"  # evalset_golden v2 (F3); golden v1 is never loaded
#: Draft metrics v1 + draft safety-gate policy v3 (pins golden v2). Definitions v1/v2 and rubric v2 are never loaded.
DEFINITIONS_FILE = "evaluation-definitions-golden-v2-v0.2.0-dev.json"
ALLOWED_FILES = frozenset(LAYER_FILES + (GOLDEN_FILE, DEFINITIONS_FILE))


@dataclass(frozen=True)
class FixtureSet:
    layers: dict[str, Any]
    golden: dict[str, Any]
    definitions: dict[str, Any]
    opened: tuple[str, ...]


def read_allowed(fixture_dir: Path, name: str) -> Any:
    """Open one allowed fixture file by name. Anything else is an admission abort before ``open``."""
    if name not in ALLOWED_FILES:
        raise AdmissionAbort("A2", "path_not_allowed", name)
    path = Path(fixture_dir) / name
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        raise AdmissionAbort("A2", "fixture_missing", name) from None
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise AdmissionAbort("A2", "json_parse_error", f"{name}: {type(exc).__name__}") from None


def load_fixtures(fixture_dir: Path = FIXTURE_DIR) -> FixtureSet:
    opened: list[str] = []
    layers = {}
    for name in LAYER_FILES:
        layers[name] = read_allowed(fixture_dir, name)
        opened.append(name)
    golden = read_allowed(fixture_dir, GOLDEN_FILE)
    opened.append(GOLDEN_FILE)
    definitions = read_allowed(fixture_dir, DEFINITIONS_FILE)
    opened.append(DEFINITIONS_FILE)
    return FixtureSet(layers=layers, golden=golden, definitions=definitions, opened=tuple(opened))


@dataclass(frozen=True)
class GoldenData:
    manifest: EvaluationDatasetManifest
    cases: tuple[EvaluationCase, ...]
    pin: ManifestPin
    layer_digests: tuple[tuple[str, str], ...]
    document_sha256: str


def check_integrity(fs: FixtureSet) -> GoldenData:
    """A3: the golden manifest is repository-visible golden, and every pin matches the loaded content."""
    golden = fs.golden
    try:
        manifest = EvaluationDatasetManifest.model_validate(golden["manifest"])
    except (KeyError, TypeError, ValidationError) as exc:
        raise AdmissionAbort("A3", "manifest_invalid", type(exc).__name__) from None
    if (manifest.split is not Split.GOLDEN or manifest.custody is not Custody.REPOSITORY_VISIBLE
            or manifest.held_out_integrity is not HeldOutIntegrity.NOT_APPLICABLE):
        raise AdmissionAbort("A3", "manifest_not_golden", f"{manifest.id}: {manifest.split.value}")
    if manifest.data_policy != "synthetic_only":
        raise AdmissionAbort("A3", "data_policy", "only synthetic data is admitted")
    names = tuple(p.name for p in manifest.fixture_layers)
    if names != LAYER_FILES:
        raise AdmissionAbort("A3", "layer_set_mismatch", ",".join(names))
    digests = []
    for pin in manifest.fixture_layers:
        actual = canonical_json_sha256(fs.layers[pin.name])
        if actual != pin.sha256:
            raise AdmissionAbort("A3", "layer_digest_mismatch", pin.name)
        digests.append((pin.name, actual))
    if "case_records" not in golden or canonical_json_sha256(golden["case_records"]) != manifest.case_records_sha256:
        raise AdmissionAbort("A3", "case_records_digest_mismatch", manifest.id)
    try:
        cases = tuple(EvaluationCase.model_validate(c) for c in golden["cases"])
    except (KeyError, TypeError, ValidationError) as exc:
        raise AdmissionAbort("A3", "case_invalid", type(exc).__name__) from None
    try:
        check_manifest_cases(manifest, cases)
    except ContractViolation as exc:
        raise AdmissionAbort("A3", exc.code, str(exc)) from None
    return GoldenData(manifest=manifest, cases=cases, pin=pin_manifest(manifest), layer_digests=tuple(digests),
                      document_sha256=canonical_json_sha256(golden))
