"""F4/B3 PR-1 -- verify-only owner-review decision record (owner decisions H-1 to H-4, 2026-11-06).

The record ``evaluation-owner-review-decisions-v1-v0.2.0-dev.json`` is a machine-readable transcription of the
project owner's self-attested F4/B3 decisions (RAP-F4-B3-OWNER-REVIEW-2026-11-06, merged PR #22). This module
verifies it and nothing more:

* ``verify_record`` either returns ``None`` or raises ``RecordRejected`` with a specific code. It never returns,
  derives or maps a label status. Mapping a recorded decision to any case status is NOT authorized (PR-2
  decisions R-1 and R-2 are not approved).
* Every check is all-or-nothing: one failure rejects the whole record. There is no partial success, fallback or
  repair.
* The record's integrity pin is the SHA-256 of its raw bytes, held here (``RECORD_FILE_SHA256``), never inside the
  record. Changing both is visible in a diff; this is repository-level tamper evidence, not trusted attestation.

Held-out boundary: ``read_allowed`` opens only four files (this record, golden v2, golden v1 and the PR #22
Markdown record) and refuses any other name before ``open``. This module does not import ``eval_harness`` and
never loads the base fixture layers or the nominal held-out case fixture.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import unittest
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from rap_contracts.evaluation import (
    EvaluationCase,
    EvaluationDatasetManifest,
    case_sha256,
    check_manifest_cases,
    pin_manifest,
)
from rap_contracts.invariants import ContractViolation

REPO = Path(__file__).resolve().parents[2]
FIXTURE_DIR = REPO / "contracts" / "fixtures"

RECORD_FILE = "evaluation-owner-review-decisions-v1-v0.2.0-dev.json"
GOLDEN_V2_FILE = "evaluation-golden-v2-v0.2.0-dev.json"
GOLDEN_V1_FILE = "evaluation-golden-v0.2.0-dev.json"
SOURCE_PATH = "docs/evaluation/F4-B3-OBJECTIVE-GOLDEN-OWNER-REVIEW-2026-11-06.md"

#: Raw-byte SHA-256 of RECORD_FILE (H-2). Stored outside the record; the record never contains its own digest.
RECORD_FILE_SHA256 = "sha256:e74096ef8bbb45290eb3b44aeee78965a366260c9673930e826e60acf3516d36"

ALLOWED = {
    RECORD_FILE: FIXTURE_DIR / RECORD_FILE,
    GOLDEN_V2_FILE: FIXTURE_DIR / GOLDEN_V2_FILE,
    GOLDEN_V1_FILE: FIXTURE_DIR / GOLDEN_V1_FILE,
    SOURCE_PATH: REPO / SOURCE_PATH,
}

TOP_KEYS = {"record_set", "id", "version", "contract_version", "data_policy", "interpretation", "notes", "dataset",
            "source_record", "provenance", "decided_on", "coverage", "summary", "decisions"}
LITERALS = {
    "record_set": "owner_review_decisions",
    "id": "evalreviewdecisions_golden",
    "contract_version": "0.2.0-dev.foundations.6",
    "data_policy": "synthetic_only",
    "interpretation": "recorded_decisions_only",
    "decided_on": "2026-11-06",
}
DATASET_KEYS = {"id", "version", "split", "root"}
SOURCE_KEYS = {"document_id", "path", "merged_in", "file_sha256"}
SOURCE_LITERALS = {"document_id": "RAP-F4-B3-OWNER-REVIEW-2026-11-06", "path": SOURCE_PATH,
                   "merged_in": "4314deac7bc09e4b7914403a8bfd95c962d798fa"}
PROVENANCE_KEYS = {"basis", "trusted_attestation"}
COVERAGE_KEYS = {"kind", "entry_count"}
SUMMARY_KEYS = {"accepted", "corrections_requested", "deferred"}
ENTRY_KEYS = {"case_id", "case_version", "case_sha256", "batch", "decision"}
DECISION = "accepted_as_pinned"
#: No status-transition or resolver semantics may appear anywhere in the record (H-1).
FORBIDDEN_TOKENS = ("review_status", "owner_reviewed", "to_status", "effective", "adjudicat", "resolv", "proposed")
SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")


class RecordRejected(Exception):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


def read_allowed(name: str) -> bytes:
    """Open one allowlisted file. Any other name is refused before ``open``."""
    if name not in ALLOWED:
        raise RecordRejected("path_not_allowed", name)
    return ALLOWED[name].read_bytes()


def sha256_bytes(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    keys = [k for k, _ in pairs]
    if len(keys) != len(set(keys)):
        raise RecordRejected("record_duplicate_key", ",".join(sorted({k for k in keys if keys.count(k) > 1})))
    return dict(pairs)


def _reject_constant(name: str) -> None:
    raise RecordRejected("record_malformed", f"non-finite constant {name}")


def parse_strict(raw: bytes) -> Any:
    try:
        text = raw.decode("utf-8")
        return json.loads(text, object_pairs_hook=_no_duplicates, parse_constant=_reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RecordRejected("record_malformed", type(exc).__name__) from None


def _int(value: Any) -> bool:
    return type(value) is int  # excludes bool


def _closed(obj: Any, keys: set[str], where: str) -> None:
    if not isinstance(obj, dict):
        raise RecordRejected("record_schema", f"{where} is not an object")
    if set(obj) != keys:
        extra, missing = sorted(set(obj) - keys), sorted(keys - set(obj))
        raise RecordRejected("record_unknown_field" if extra else "record_schema",
                             f"{where}: extra={extra} missing={missing}")


def _section(text: str, start: str, end: str) -> str:
    i, j = text.find(start), text.find(end)
    if i < 0 or j < 0 or j <= i:
        raise RecordRejected("source_unparseable", f"section {start!r}")
    return text[i:j]


def parse_source(raw: bytes) -> dict[str, Any]:
    """Strictly parse the PR #22 record's header root, section 2 (batches) and section 3 (bindings)."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise RecordRejected("source_unparseable", "utf-8") from None
    roots = re.findall(r"^\*\*Golden manifest root:\*\* `(sha256:[0-9a-f]{64})`$", text, re.M)
    if len(roots) != 1:
        raise RecordRejected("source_unparseable", "manifest root header")
    batches: dict[str, int] = {}
    batch_counts: dict[int, int] = {}
    for line in _section(text, "## 2. Batch reconciliation", "## 3. ").splitlines():
        if not line.startswith("| ") or line.startswith(("| Batch", "|---", "| **Total**")):
            continue
        m = re.fullmatch(r"\| (\d) \| ((?:g\d{3}[a-z]?)(?:, g\d{3}[a-z]?)*) \| (\d+) \|", line)
        if not m:
            raise RecordRejected("source_unparseable", f"batch row {line!r}")
        ids = m.group(2).split(", ")
        if int(m.group(3)) != len(ids) or int(m.group(1)) in batch_counts:
            raise RecordRejected("source_unparseable", f"batch row {line!r}")
        batch_counts[int(m.group(1))] = len(ids)
        for cid in ids:
            if f"evalcase_{cid}" in batches:
                raise RecordRejected("source_unparseable", f"{cid} in two batches")
            batches[f"evalcase_{cid}"] = int(m.group(1))
    bindings: dict[str, tuple[int, str]] = {}
    for line in _section(text, "## 3. Immutable case/version/hash bindings", "## 4. ").splitlines():
        if not line.startswith("| `"):
            continue
        m = re.fullmatch(r"\| `(evalcase_g\d{3}[a-z]?)` \| (\d+) \| `(sha256:[0-9a-f]{64})` \|", line)
        if not m or m.group(1) in bindings:
            raise RecordRejected("source_unparseable", f"binding row {line!r}")
        bindings[m.group(1)] = (int(m.group(2)), m.group(3))
    if len(bindings) != 26 or set(bindings) != set(batches):
        raise RecordRejected("source_unparseable", "sections 2 and 3 do not cover the same 26 cases")
    return {"root": roots[0], "batches": batches, "batch_counts": batch_counts, "bindings": bindings}


def load_golden(doc: Any) -> tuple[EvaluationDatasetManifest, list[EvaluationCase]]:
    try:
        manifest = EvaluationDatasetManifest.model_validate(doc["manifest"])
        cases = [EvaluationCase.model_validate(c) for c in doc["cases"]]
        check_manifest_cases(manifest, cases)
    except (KeyError, TypeError, ValidationError, ContractViolation) as exc:
        raise RecordRejected("golden_invalid", type(exc).__name__) from None
    return manifest, cases


def verify_record(raw: bytes, *, expected_sha256: str, golden_doc: Any, source_raw: bytes) -> None:
    """Verify the decision record against an independently held digest, the supplied golden dataset and the
    PR #22 source record. Returns ``None`` or raises ``RecordRejected``. It never yields a label status."""
    if sha256_bytes(raw) != expected_sha256:
        raise RecordRejected("record_digest_mismatch")
    rec = parse_strict(raw)
    lowered = raw.decode("utf-8").lower()
    hits = [t for t in FORBIDDEN_TOKENS if t in lowered]
    if hits:
        raise RecordRejected("record_status_semantics", ",".join(hits))
    _closed(rec, TOP_KEYS, "record")
    for key, value in LITERALS.items():
        if rec[key] != value:
            raise RecordRejected("record_vocabulary", key)
    if not _int(rec["version"]) or rec["version"] != 1:
        raise RecordRejected("record_vocabulary", "version")
    if not isinstance(rec["notes"], list) or not rec["notes"] or not all(isinstance(n, str) for n in rec["notes"]):
        raise RecordRejected("record_schema", "notes")
    _closed(rec["provenance"], PROVENANCE_KEYS, "provenance")
    if rec["provenance"]["basis"] != "self_attested_owner_statement":
        raise RecordRejected("record_vocabulary", "provenance.basis")
    if rec["provenance"]["trusted_attestation"] is not False:
        raise RecordRejected("record_attestation_unsupported")

    _closed(rec["source_record"], SOURCE_KEYS, "source_record")
    for key, value in SOURCE_LITERALS.items():
        if rec["source_record"][key] != value:
            raise RecordRejected("source_identity_mismatch", key)
    if not SHA256.fullmatch(str(rec["source_record"]["file_sha256"])):
        raise RecordRejected("record_schema", "source_record.file_sha256")
    if sha256_bytes(source_raw) != rec["source_record"]["file_sha256"]:
        raise RecordRejected("source_digest_mismatch")
    source = parse_source(source_raw)

    manifest, cases = load_golden(golden_doc)
    pin = pin_manifest(manifest).model_dump(mode="json")
    _closed(rec["dataset"], DATASET_KEYS, "dataset")
    if rec["dataset"] != pin:
        raise RecordRejected("dataset_mismatch", f"{manifest.id} v{manifest.version}")
    if source["root"] != rec["dataset"]["root"]:
        raise RecordRejected("source_root_mismatch")

    _closed(rec["coverage"], COVERAGE_KEYS, "coverage")
    _closed(rec["summary"], SUMMARY_KEYS, "summary")
    decisions = rec["decisions"]
    if rec["coverage"]["kind"] != "complete_manifest":
        raise RecordRejected("coverage_unsupported", str(rec["coverage"]["kind"]))
    if not isinstance(decisions, list) or not _int(rec["coverage"]["entry_count"]) \
            or rec["coverage"]["entry_count"] != len(decisions):
        raise RecordRejected("coverage_count_mismatch", "entry_count differs from the number of entries")

    pins = {p.case_id: p for p in manifest.case_pins}
    recomputed = {c.id: case_sha256(c) for c in cases}
    seen: set[str] = set()
    for entry in decisions:
        _closed(entry, ENTRY_KEYS, "decision entry")
        cid = entry["case_id"]
        if entry["decision"] != DECISION:
            raise RecordRejected("decision_unsupported", str(entry["decision"]))
        if cid in seen:
            raise RecordRejected("duplicate_entry", str(cid))
        seen.add(cid)
        if cid not in pins:
            raise RecordRejected("unknown_case", str(cid))
        if not _int(entry["case_version"]) or entry["case_version"] != pins[cid].version \
                or entry["case_sha256"] != pins[cid].sha256 or entry["case_sha256"] != recomputed[cid]:
            raise RecordRejected("entry_binding_mismatch", str(cid))
        if (entry["case_version"], entry["case_sha256"]) != source["bindings"].get(cid):
            raise RecordRejected("source_table_mismatch", f"{cid} binding")
        if not _int(entry["batch"]) or entry["batch"] != source["batches"].get(cid):
            raise RecordRejected("source_table_mismatch", f"{cid} batch")
    if seen != set(pins):
        raise RecordRejected("missing_entry", ",".join(sorted(set(pins) - seen)))
    if rec["coverage"]["entry_count"] != len(pins) or set(source["bindings"]) != set(pins):
        raise RecordRejected("coverage_count_mismatch", "entries do not cover the manifest")
    if (rec["summary"]["accepted"], rec["summary"]["corrections_requested"], rec["summary"]["deferred"]) \
            != (len(decisions), 0, 0) or not all(_int(v) for v in rec["summary"].values()):
        raise RecordRejected("summary_mismatch")
    return None


# ---------------------------------------------------------------------------
# Fixtures (read once, through the allowlist only)
# ---------------------------------------------------------------------------

RAW = read_allowed(RECORD_FILE)
SOURCE_RAW = read_allowed(SOURCE_PATH)
GOLDEN_V2 = json.loads(read_allowed(GOLDEN_V2_FILE))
GOLDEN_V1 = json.loads(read_allowed(GOLDEN_V1_FILE))


def dump(rec: Any) -> bytes:
    return (json.dumps(rec, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def verify(raw: bytes = RAW, *, expected: str | None = None, golden: Any = GOLDEN_V2,
           source: bytes = SOURCE_RAW) -> None:
    """Defaults to an attacker-consistent digest so that downstream invariants are exercised independently of
    the pin; the pin itself is tested separately."""
    return verify_record(raw, expected_sha256=sha256_bytes(raw) if expected is None else expected,
                         golden_doc=golden, source_raw=source)


class PositiveTests(unittest.TestCase):

    def test_record_verifies_against_the_independent_pin_and_returns_no_status(self):
        self.assertIsNone(verify_record(RAW, expected_sha256=RECORD_FILE_SHA256, golden_doc=GOLDEN_V2,
                                        source_raw=SOURCE_RAW))

    def test_raw_byte_digest_matches_the_pin(self):
        self.assertEqual("sha256:" + hashlib.sha256((FIXTURE_DIR / RECORD_FILE).read_bytes()).hexdigest(),
                         RECORD_FILE_SHA256)

    def test_record_does_not_contain_its_own_digest(self):
        self.assertNotIn(RECORD_FILE_SHA256.split(":")[1].encode(), RAW)

    def test_source_document_digest_and_identity(self):
        rec = parse_strict(RAW)
        self.assertEqual(rec["source_record"]["file_sha256"], sha256_bytes(SOURCE_RAW))
        self.assertEqual(rec["source_record"]["merged_in"], "4314deac7bc09e4b7914403a8bfd95c962d798fa")
        self.assertEqual(rec["source_record"]["path"], SOURCE_PATH)

    def test_dataset_pin_is_recomputed_golden_v2(self):
        manifest, cases = load_golden(GOLDEN_V2)
        check_manifest_cases(manifest, cases)
        rec = parse_strict(RAW)
        self.assertEqual(rec["dataset"], pin_manifest(manifest).model_dump(mode="json"))
        self.assertEqual((rec["dataset"]["id"], rec["dataset"]["version"], rec["dataset"]["split"]),
                         ("evalset_golden", 2, "golden"))
        self.assertEqual(rec["dataset"]["root"],
                         "sha256:3bd060439f58ce4d28e5272d5169135fc93526d5cec8a78de3a8dc4dfbd4d25e")
        self.assertEqual(parse_source(SOURCE_RAW)["root"], rec["dataset"]["root"])

    def test_26_entries_bind_manifest_pins_and_recomputed_hashes(self):
        manifest, cases = load_golden(GOLDEN_V2)
        rec = parse_strict(RAW)
        entries = {e["case_id"]: e for e in rec["decisions"]}
        self.assertEqual(len(rec["decisions"]), 26)
        self.assertEqual(len(entries), 26)
        self.assertEqual(set(entries), {p.case_id for p in manifest.case_pins})
        by_id = {c.id: c for c in cases}
        for p in manifest.case_pins:
            with self.subTest(case=p.case_id):
                e = entries[p.case_id]
                self.assertEqual((e["case_version"], e["case_sha256"]), (p.version, p.sha256))
                self.assertEqual(e["case_sha256"], case_sha256(by_id[p.case_id]))
                self.assertEqual(e["decision"], DECISION)

    def test_coverage_batches_and_summary(self):
        rec = parse_strict(RAW)
        self.assertEqual(rec["coverage"], {"kind": "complete_manifest", "entry_count": 26})
        self.assertEqual(rec["summary"], {"accepted": 26, "corrections_requested": 0, "deferred": 0})
        counts: dict[int, int] = {}
        for e in rec["decisions"]:
            counts[e["batch"]] = counts.get(e["batch"], 0) + 1
        self.assertEqual(counts, {1: 2, 2: 6, 3: 5, 4: 5, 5: 5, 6: 3})
        self.assertEqual(counts, parse_source(SOURCE_RAW)["batch_counts"])

    def test_entries_equal_the_pr22_tables(self):
        source = parse_source(SOURCE_RAW)
        for e in parse_strict(RAW)["decisions"]:
            with self.subTest(case=e["case_id"]):
                self.assertEqual((e["case_version"], e["case_sha256"]), source["bindings"][e["case_id"]])
                self.assertEqual(e["batch"], source["batches"][e["case_id"]])

    def test_vocabulary_and_provenance(self):
        rec = parse_strict(RAW)
        self.assertEqual({k: rec[k] for k in LITERALS}, LITERALS)
        self.assertEqual(rec["provenance"], {"basis": "self_attested_owner_statement", "trusted_attestation": False})
        self.assertEqual({e["decision"] for e in rec["decisions"]}, {DECISION})
        lowered = RAW.decode("utf-8").lower()
        for token in FORBIDDEN_TOKENS:
            self.assertNotIn(token, lowered)

    def test_golden_v1_is_excluded_despite_shared_case_hashes(self):
        v1_manifest, _ = load_golden(GOLDEN_V1)
        v2_manifest, _ = load_golden(GOLDEN_V2)
        v1_pins = {(p.case_id, p.version, p.sha256) for p in v1_manifest.case_pins}
        shared = v1_pins & {(p.case_id, p.version, p.sha256) for p in v2_manifest.case_pins}
        self.assertEqual(len(shared), 24)
        self.assertNotEqual(pin_manifest(v1_manifest).root, parse_strict(RAW)["dataset"]["root"])
        with self.assertRaises(RecordRejected) as ctx:
            verify_record(RAW, expected_sha256=RECORD_FILE_SHA256, golden_doc=GOLDEN_V1, source_raw=SOURCE_RAW)
        self.assertEqual(ctx.exception.code, "dataset_mismatch")

    def test_golden_v2_embedded_statuses_are_unchanged(self):
        _, cases = load_golden(GOLDEN_V2)
        self.assertEqual(len(cases), 26)
        for c in cases:
            with self.subTest(case=c.id):
                self.assertEqual((c.provenance.review_status.value, c.adjudication_status.value),
                                 ("proposed", "not_adjudicated"))

    def test_g010_keeps_its_not_observable_safety_disposition(self):
        case = next(c for c in GOLDEN_V2["cases"] if c["id"] == "evalcase_g010")
        found: list[tuple[str, str]] = []

        def walk(node: Any) -> None:
            if isinstance(node, dict):
                if node.get("category") == "prompt_injection_compliance":
                    found.append((node["category"], node.get("disposition")))
                for v in node.values():
                    walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)

        walk(case)
        self.assertEqual(found, [("prompt_injection_compliance", "not_observable")])

    def test_reader_refuses_unlisted_files_before_open(self):
        for name in ("evaluation-nominal-held-out-v0.2.0-dev.json", "foundations-v0.2.0-dev.json",
                     "eligibility-evidence-v0.2.0-dev.json", "review-v0.2.0-dev.json",
                     "evaluation-definitions-golden-v2-v0.2.0-dev.json", "../fixtures/" + RECORD_FILE):
            with self.subTest(name=name), self.assertRaises(RecordRejected) as ctx:
                read_allowed(name)
            self.assertEqual(ctx.exception.code, "path_not_allowed")


def _mutated(fn) -> bytes:
    rec = copy.deepcopy(parse_strict(RAW))
    fn(rec)
    return dump(rec)


def _entry(rec: dict, cid: str) -> dict:
    return next(e for e in rec["decisions"] if e["case_id"] == cid)


def _drop(rec: dict, cid: str, *, recount: bool) -> None:
    rec["decisions"] = [e for e in rec["decisions"] if e["case_id"] != cid]
    if recount:
        rec["coverage"]["entry_count"] = len(rec["decisions"])
        rec["summary"]["accepted"] = len(rec["decisions"])


def _duplicate(rec: dict) -> None:
    rec["decisions"][-1] = copy.deepcopy(rec["decisions"][0])


def _extra(rec: dict, cid: str) -> None:
    e = copy.deepcopy(rec["decisions"][0])
    e["case_id"] = cid
    rec["decisions"].append(e)
    rec["coverage"]["entry_count"] = len(rec["decisions"])
    rec["summary"]["accepted"] = len(rec["decisions"])


def _set(path: tuple, value: Any):
    def fn(rec: dict) -> None:
        node = rec
        for key in path[:-1]:
            if isinstance(node, list):
                node = next(e for e in node if e["case_id"] == key)
            else:
                node = node[key]
        node[path[-1]] = value
    return fn


def _tampered_golden() -> dict:
    doc = copy.deepcopy(GOLDEN_V2)
    case = next(c for c in doc["cases"] if c["id"] == "evalcase_g003")
    case["title"] = case["title"] + " (edited)"
    return doc


class NegativeTests(unittest.TestCase):
    """Every fault rejects the whole record with a specific code. Unless stated, the digest supplied is the
    mutated record's own, so each invariant is shown to hold independently of the digest pin."""

    def assertRejected(self, code: str, **kwargs) -> None:
        with self.assertRaises(RecordRejected) as ctx:
            verify(**kwargs)
        self.assertEqual(ctx.exception.code, code, str(ctx.exception))

    def test_wrong_record_digest(self):
        self.assertRejected("record_digest_mismatch", expected="sha256:" + "0" * 64)
        self.assertRejected("record_digest_mismatch", raw=RAW + b"\n", expected=RECORD_FILE_SHA256)
        edited = _mutated(_set(("notes",), ["edited"]))
        self.assertRejected("record_digest_mismatch", raw=edited, expected=RECORD_FILE_SHA256)

    def test_malformed_and_duplicate_keys(self):
        self.assertRejected("record_malformed", raw=b"{")
        self.assertRejected("record_malformed", raw=b"\xff\xfe")
        self.assertRejected("record_malformed", raw=b'{"version": NaN}')
        dup = RAW.replace(b'"version": 1,', b'"version": 1,\n  "version": 1,', 1)
        self.assertNotEqual(dup, RAW)
        self.assertRejected("record_duplicate_key", raw=dup)

    def test_unknown_or_missing_fields(self):
        cases = {
            "top-level extra": _set(("comment",), "x"),
            "dataset extra": _set(("dataset", "custody"), "repository_visible"),
            "entry extra": _set(("decisions", "evalcase_g001", "note"), "x"),
            "provenance extra": _set(("provenance", "reviewer"), "owner"),
        }
        for name, fn in cases.items():
            with self.subTest(name):
                self.assertRejected("record_unknown_field", raw=_mutated(fn))
        self.assertRejected("record_schema", raw=_mutated(lambda r: r.pop("summary")))
        self.assertRejected("record_schema", raw=_mutated(lambda r: _entry(r, "evalcase_g001").pop("batch")))

    def test_injected_status_or_resolver_fields(self):
        cases = {
            "entry review_status": _set(("decisions", "evalcase_g001", "review_status"), "x"),
            "entry to_status": _set(("decisions", "evalcase_g002", "to_status"), "x"),
            "top-level effective_status": _set(("effective_status",), "x"),
            "status value in notes": _set(("notes",), ["cases are owner_reviewed"]),
            "resolver field": _set(("resolver",), {"maps": "x"}),
            "adjudication word": _set(("notes",), ["adjudicated"]),
        }
        for name, fn in cases.items():
            with self.subTest(name):
                self.assertRejected("record_status_semantics", raw=_mutated(fn))

    def test_vocabulary(self):
        for key, value in (("interpretation", "status"), ("record_set", "x"), ("id", "x"), ("decided_on", "2026-11-07"),
                           ("data_policy", "real"), ("contract_version", "0.2.0-dev.foundations.7")):
            with self.subTest(key=key):
                self.assertRejected("record_vocabulary", raw=_mutated(_set((key,), value)))
        for value in (2, True, "1"):
            with self.subTest(version=value):
                self.assertRejected("record_vocabulary", raw=_mutated(_set(("version",), value)))
        self.assertRejected("record_vocabulary", raw=_mutated(_set(("provenance", "basis"), "trusted_service")))

    def test_trusted_attestation_true(self):
        for value in (True, 1, "false", None):
            with self.subTest(value=value):
                self.assertRejected("record_attestation_unsupported",
                                    raw=_mutated(_set(("provenance", "trusted_attestation"), value)))

    def test_source_document_faults(self):
        self.assertRejected("source_digest_mismatch",
                            raw=_mutated(_set(("source_record", "file_sha256"), "sha256:" + "1" * 64)))
        self.assertRejected("source_digest_mismatch", source=SOURCE_RAW + b"\n")
        self.assertRejected("source_identity_mismatch",
                            raw=_mutated(_set(("source_record", "merged_in"), "b751152b0984c082ca38495896a266015f6978ee")))
        self.assertRejected("source_identity_mismatch", raw=_mutated(_set(("source_record", "path"), "x.md")))

    def test_wrong_dataset_identity(self):
        for key, value in (("root", "sha256:" + "2" * 64), ("split", "held_out"), ("id", "evalset_nominal_held_out"),
                           ("version", 1)):
            with self.subTest(key=key):
                self.assertRejected("dataset_mismatch", raw=_mutated(_set(("dataset", key), value)))

    def test_golden_v1_supplied_where_v2_is_required(self):
        self.assertRejected("dataset_mismatch", golden=GOLDEN_V1)
        self.assertRejected("dataset_mismatch", raw=RAW, expected=RECORD_FILE_SHA256, golden=GOLDEN_V1)

    def test_modified_golden_content(self):
        self.assertRejected("golden_invalid", golden=_tampered_golden())
        self.assertRejected("golden_invalid", golden={"manifest": GOLDEN_V2["manifest"]})

    def test_missing_duplicate_and_extra_entries(self):
        self.assertRejected("coverage_count_mismatch",
                            raw=_mutated(lambda r: _drop(r, "evalcase_g017", recount=False)))
        self.assertRejected("missing_entry", raw=_mutated(lambda r: _drop(r, "evalcase_g017", recount=True)))
        self.assertRejected("duplicate_entry", raw=_mutated(_duplicate))
        self.assertRejected("unknown_case", raw=_mutated(lambda r: _extra(r, "evalcase_g026")))
        self.assertRejected("unknown_case", raw=_mutated(lambda r: _extra(r, "evalcase_h001")))

    def test_incorrect_coverage_count_or_kind(self):
        for count in (25, 27, 0):
            with self.subTest(count=count):
                self.assertRejected("coverage_count_mismatch",
                                    raw=_mutated(_set(("coverage", "entry_count"), count)))
        self.assertRejected("coverage_unsupported", raw=_mutated(_set(("coverage", "kind"), "partial")))

    def test_incorrect_summary(self):
        for key, value in (("accepted", 25), ("corrections_requested", 1), ("deferred", 1)):
            with self.subTest(key=key):
                self.assertRejected("summary_mismatch", raw=_mutated(_set(("summary", key), value)))

    def test_incorrect_case_version_or_hash(self):
        self.assertRejected("entry_binding_mismatch",
                            raw=_mutated(_set(("decisions", "evalcase_g002", "case_version"), 1)))
        self.assertRejected("entry_binding_mismatch",
                            raw=_mutated(_set(("decisions", "evalcase_g008", "case_sha256"), "sha256:" + "3" * 64)))
        v1_g002 = next(p for p in GOLDEN_V1["manifest"]["case_pins"] if p["case_id"] == "evalcase_g002")
        self.assertRejected("entry_binding_mismatch",
                            raw=_mutated(_set(("decisions", "evalcase_g002", "case_sha256"), v1_g002["sha256"])))

    def test_unknown_decision_vocabulary(self):
        for value in ("accepted", "rejected", "deferred", "corrected"):
            with self.subTest(value=value):
                self.assertRejected("decision_unsupported",
                                    raw=_mutated(_set(("decisions", "evalcase_g010", "decision"), value)))

    def test_disagreement_with_the_pr22_batch_mapping(self):
        self.assertRejected("source_table_mismatch",
                            raw=_mutated(_set(("decisions", "evalcase_g001", "batch"), 3)))
        self.assertRejected("source_table_mismatch",
                            raw=_mutated(_set(("decisions", "evalcase_g025", "batch"), 5)))

    def test_source_tables_that_disagree_or_do_not_parse(self):
        swapped = SOURCE_RAW.replace(b"| 1 | g002, g008 | 2 |", b"| 1 | g002, g009 | 2 |", 1)
        swapped = swapped.replace(b"| 3 | g007, g009, g010", b"| 3 | g007, g008, g010", 1)
        self.assertNotEqual(swapped, SOURCE_RAW)
        raw = _mutated(_set(("source_record", "file_sha256"), sha256_bytes(swapped)))
        self.assertRejected("source_table_mismatch", raw=raw, source=swapped)
        truncated = SOURCE_RAW.replace(b"| `evalcase_g025` |", b"| evalcase_g025 |", 1)
        raw = _mutated(_set(("source_record", "file_sha256"), sha256_bytes(truncated)))
        self.assertRejected("source_unparseable", raw=raw, source=truncated)
        other_root = SOURCE_RAW.replace(b"**Golden manifest root:** `sha256:3bd0", b"**Golden manifest root:** `sha256:3bd1", 1)
        raw = _mutated(_set(("source_record", "file_sha256"), sha256_bytes(other_root)))
        self.assertRejected("source_root_mismatch", raw=raw, source=other_root)


if __name__ == "__main__":
    unittest.main()
