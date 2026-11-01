"""TEST-ONLY helpers for the PR-S3b runner tests.

Tests inject a ``CodeRevision`` (plan R-3): only the CLI reads git. Tamper
helpers work on deep copies in memory or on temporary copies of the five
ALLOWED fixture files; the nominal held-out case file is never copied, opened
or named. ``tampered`` bypasses the A3 integrity check explicitly (returning the
real pins) so that A5-A8 and execution-phase checks can be reached with
synthetic in-memory copies; A3 itself is tested without any bypass.
"""

from __future__ import annotations

import copy
import shutil
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from unittest import mock

from rap_contracts.evaluation import CodeRevision, EvaluationCase

from rap_evaluation import admission
from rap_evaluation.admission import RunConfig, admit_fixtures
from rap_evaluation.fixtures import ALLOWED_FILES, FIXTURE_DIR, FixtureSet, GoldenData, check_integrity, load_fixtures
from rap_evaluation.identity import new_execution_id
from rap_evaluation.run import produce

AS_OF = datetime(2026, 11, 1, tzinfo=timezone.utc)
CLEAN = CodeRevision(status="recorded", commit="a" * 40, dirty=False)
LAYER_EVIDENCE = "eligibility-evidence-v0.2.0-dev.json"

_CACHE: dict = {}


def config(out: Path, **kw) -> RunConfig:
    return RunConfig(as_of=kw.pop("as_of", AS_OF), out=Path(out), code_revision=kw.pop("code_revision", CLEAN), **kw)


def real_fixtures() -> FixtureSet:
    if "fs" not in _CACHE:
        _CACHE["fs"] = load_fixtures()
    return _CACHE["fs"]


def admitted(as_of: datetime = AS_OF):
    key = ("admitted", as_of)
    if key not in _CACHE:
        _CACHE[key] = admit_fixtures(real_fixtures(), as_of)
    return _CACHE[key]


def products(assess_fn: Callable | None = None, adm=None, out: Path | None = None):
    adm = adm if adm is not None else admitted()
    return produce(config(out or Path("/nonexistent/unused")), adm, new_execution_id(), assess_fn)


def copy_allowed(dst: Path) -> Path:
    """Copy only the five allowed fixture files (never the held-out case file)."""
    dst.mkdir(parents=True, exist_ok=True)
    for name in sorted(ALLOWED_FILES):
        shutil.copyfile(FIXTURE_DIR / name, dst / name)
    return dst


@contextmanager
def tampered(layers: Callable | None = None, golden: Callable | None = None, definitions: Callable | None = None):
    """Admission over mutated in-memory copies, with A3 integrity explicitly bypassed (real pins returned)."""
    real = real_fixtures()
    fs = FixtureSet(layers=copy.deepcopy(real.layers), golden=copy.deepcopy(real.golden),
                    definitions=copy.deepcopy(real.definitions), opened=real.opened)
    if layers:
        layers(fs.layers)
    if golden:
        golden(fs.golden)
    if definitions:
        definitions(fs.definitions)
    pins = check_integrity(real)
    bypass = GoldenData(manifest=pins.manifest, cases=tuple(EvaluationCase.model_validate(c) for c in fs.golden["cases"]),
                        pin=pins.pin, layer_digests=pins.layer_digests, document_sha256=pins.document_sha256)
    with mock.patch.object(admission, "load_fixtures", return_value=fs), \
            mock.patch.object(admission, "check_integrity", return_value=bypass):
        yield fs


def case_doc(doc: dict, case_id: str) -> dict:
    return next(c for c in doc["cases"] if c["id"] == case_id)


def layer_record(layers: dict, kind: str, record_id: str) -> dict:
    return next(r for r in layers[LAYER_EVIDENCE][kind] if r["id"] == record_id)


class TempDirTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="rap-eval-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def assertNothingPublished(self, out: Path) -> None:
        self.assertFalse(out.exists(), f"{out} must not exist")
        parent = out.parent
        if parent.exists():
            leftovers = [p.name for p in parent.iterdir() if p.name.startswith(f".{out.name}.tmp-")]
            self.assertEqual(leftovers, [], "temporary publication directory left behind")


class LazyClassFixture(TempDirTest):
    """A class-level fixture (``_fixture``) built on first use instead of in ``setUpClass``.

    If building it fails, the same exception is raised in every test that runs, so each test is
    reported as an error and the suite's test count stays stable (the mutation harness treats an
    altered count as a harness error, never as a detection).
    """

    @classmethod
    def _fixture(cls) -> None:  # pragma: no cover - overridden
        pass

    def setUp(self) -> None:
        super().setUp()
        cls = type(self)
        state = cls.__dict__.get("_fixture_state")
        if state is None:
            try:
                cls._fixture()
                state = (True, None)
            except Exception as exc:
                state = (False, exc)
            cls._fixture_state = state
        if not state[0]:
            raise state[1]
