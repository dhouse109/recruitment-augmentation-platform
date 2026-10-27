"""D-004.07 -- source version semantics (representation) and separate freshness/access checks."""

import copy
import re
import unittest
from types import MappingProxyType

from pydantic import ValidationError

import support
from rap_contracts.invariants import ContractViolation
from rap_contracts.models import (
    AccessStatus,
    LogicalSnapshot,
    NativeRevision,
    SourceReference,
    SourceSystemCapabilities,
    VersionStatus,
)
from rap_contracts.source_checks import (
    DEFAULT_SNAPSHOT_METHODS,
    SHA256_CANONICAL_JSON_V1,
    canonical_json_sha256,
    check_record_set_versions,
    check_version_kind,
    checked,
    require_current_and_allowed,
    require_historical_resolvable,
)


def _native_ref():
    return copy.deepcopy(support.raw()["opportunities"][0]["source_ref"])


def _snapshot_ref():
    return copy.deepcopy(support.raw()["example_source_references"][0])


class VersionKindRepresentationTests(unittest.TestCase):
    def test_both_version_kinds_validate(self):
        native = SourceReference.model_validate(_native_ref())
        snap = SourceReference.model_validate(_snapshot_ref())
        self.assertIsInstance(native.version, NativeRevision)
        self.assertIsInstance(snap.version, LogicalSnapshot)
        caps = support.capabilities()
        check_version_kind(native, caps)
        check_version_kind(snap, caps)  # Drupal-User-style identity record versioned by logical snapshot

    def test_all_fixture_refs_match_declared_capabilities(self):
        check_record_set_versions(support.records(), support.capabilities())

    def test_malformed_versions_rejected(self):
        native, snap = _native_ref(), _snapshot_ref()
        sv = snap["version"]
        cases = {
            "missing kind": {**native, "version": {"revision_id": "41"}},
            "unknown kind": {**native, "version": {"kind": "hash", "revision_id": "41"}},
            "empty revision id": {**native, "version": {"kind": "native_revision", "revision_id": ""}},
            "revision id with space": {**native, "version": {"kind": "native_revision", "revision_id": "4 1"}},
            "integer revision id": {**native, "version": {"kind": "native_revision", "revision_id": 41}},
            "snapshot token labeled native": {**native, "version": {"kind": "native_revision", "revision_id": sv["token"]}},
            "native with snapshot fields": {**native, "version": {"kind": "native_revision", "revision_id": "41", "token": sv["token"]}},
            "snapshot without captured_at": {**snap, "version": {k: v for k, v in sv.items() if k != "captured_at"}},
            "snapshot naive captured_at": {**snap, "version": {**sv, "captured_at": "2026-10-20T13:00:00"}},
            "snapshot without provenance": {**snap, "version": {k: v for k, v in sv.items() if k != "captured_by"}},
            "snapshot token without scheme": {**snap, "version": {**sv, "token": sv["token"].split(":", 1)[1]}},
            "snapshot bad method syntax": {**snap, "version": {**sv, "method": "SHA256"}},
            "missing organization": {k: v for k, v in native.items() if k != "organization_id"},
            "unknown source system": {**native, "entity": {**native["entity"], "source_system": "spreadsheet"}},
        }
        for label, payload in cases.items():
            with self.subTest(label), self.assertRaises(ValidationError):
                SourceReference.model_validate(payload)


class CapabilityCheckTests(unittest.TestCase):
    def setUp(self):
        self.caps = support.capabilities()

    def _expect(self, payload, code, **kw):
        with self.assertRaises(ContractViolation) as ctx:
            check_version_kind(SourceReference.model_validate(payload), self.caps, **kw)
        self.assertEqual(ctx.exception.code, code)

    def test_native_revision_claimed_for_snapshot_only_type_rejected(self):
        ref = _snapshot_ref()
        ref["version"] = {"kind": "native_revision", "revision_id": "1"}
        self._expect(ref, "native_revision_claim_unsupported")

    def test_snapshot_substituted_for_available_native_revision_rejected(self):
        ref = _native_ref()
        ref["version"] = _snapshot_ref()["version"]
        self._expect(ref, "snapshot_for_revisionable_type")

    def test_undeclared_entity_type_fails_closed(self):
        ref = _native_ref()
        ref["entity"]["entity_type"] = "attachment"
        self._expect(ref, "undeclared_entity_type")

    def test_undeclared_source_system_fails_closed(self):
        ref = _native_ref()
        ref["entity"]["source_system"] = "drupal"  # fixture adapter declares only 'fixture'
        self._expect(ref, "unknown_source_system")

    def test_unregistered_snapshot_method_rejected(self):
        ref = _snapshot_ref()
        ref["version"]["method"] = "blake3-canonical-json/v1"
        self._expect(ref, "unsupported_snapshot_method")

    def test_malformed_sha256_token_rejected(self):
        for token in ("sha256:" + "A" * 64, "sha256:" + "a" * 63, "md5:" + "a" * 32):
            with self.subTest(token=token):
                ref = _snapshot_ref()
                ref["version"]["token"] = token
                self._expect(ref, "malformed_snapshot_token")

    def test_additional_method_can_be_registered_without_contract_change(self):
        method = "blake3-canonical-json/v1"
        registry = MappingProxyType({**DEFAULT_SNAPSHOT_METHODS, method: re.compile(r"blake3:[0-9a-f]{64}")})
        caps_doc = support.raw()["capabilities"][0]
        caps_doc["snapshot_methods"].append(method)
        caps = {c.source_system: c for c in [SourceSystemCapabilities.model_validate(caps_doc)]}
        ref = _snapshot_ref()
        ref["version"].update(method=method, token="blake3:" + "0" * 64)
        check_version_kind(SourceReference.model_validate(ref), caps, registry)

    def test_capabilities_cannot_declare_both_kinds_for_one_type(self):
        doc = support.raw()["capabilities"][0]
        doc["logical_snapshot_entity_types"].append("opportunity")
        with self.assertRaises(ValidationError):
            SourceSystemCapabilities.model_validate(doc)


class SnapshotMethodTests(unittest.TestCase):
    def test_fixture_tokens_reproduce_from_declared_payloads(self):
        doc = support.raw()
        self.assertEqual(
            canonical_json_sha256(doc["snapshot_payloads"]["user-9001"]),
            doc["example_source_references"][0]["version"]["token"],
        )
        self.assertEqual(
            canonical_json_sha256(doc["snapshot_payloads"]["program-3001"]),
            doc["programs"][0]["source_ref"]["version"]["token"],
        )

    def test_canonicalization_ignores_key_order(self):
        self.assertEqual(canonical_json_sha256({"b": 1, "a": "é"}), canonical_json_sha256({"a": "é", "b": 1}))
        self.assertTrue(DEFAULT_SNAPSHOT_METHODS[SHA256_CANONICAL_JSON_V1].fullmatch(canonical_json_sha256({})))


class FreshnessAndAccessSeparationTests(unittest.TestCase):
    """Mock-authority tests: they exercise the fail-closed gate, not live Drupal checks."""

    def setUp(self):
        self.ref = SourceReference.model_validate(_snapshot_ref())
        self.authority = support.FixtureSourceAuthority()

    def _result(self, version, access, principal=support.COORDINATOR):
        self.authority.set(principal, self.ref, version, access)
        return checked(self.authority, principal, self.ref)

    def test_well_formed_token_does_not_imply_current_or_allowed(self):
        check_version_kind(self.ref, support.capabilities())  # shape + method format pass
        with self.assertRaises(ContractViolation) as ctx:
            require_current_and_allowed(checked(self.authority, support.COORDINATOR, self.ref))
        self.assertEqual(ctx.exception.code, "source_access_denied")  # unknown to authority -> fail closed

    def test_current_and_allowed_passes(self):
        require_current_and_allowed(self._result(VersionStatus.CURRENT, AccessStatus.ALLOWED))

    def test_version_and_access_are_independent(self):
        cases = {
            (VersionStatus.CURRENT, AccessStatus.DENIED): "source_access_denied",
            (VersionStatus.SUPERSEDED, AccessStatus.ALLOWED): "source_not_current",
            (VersionStatus.WITHDRAWN, AccessStatus.ALLOWED): "source_withdrawn",
            (VersionStatus.DELETED, AccessStatus.ALLOWED): "source_deleted",
            (VersionStatus.UNAVAILABLE, AccessStatus.ALLOWED): "source_unavailable",
        }
        for (version, access), code in cases.items():
            with self.subTest(version=version.value, access=access.value):
                with self.assertRaises(ContractViolation) as ctx:
                    require_current_and_allowed(self._result(version, access))
                self.assertEqual(ctx.exception.code, code)

    def test_newly_inaccessible_source_rejected(self):
        require_current_and_allowed(self._result(VersionStatus.CURRENT, AccessStatus.ALLOWED))
        with self.assertRaises(ContractViolation) as ctx:
            require_current_and_allowed(self._result(VersionStatus.CURRENT, AccessStatus.DENIED))
        self.assertEqual(ctx.exception.code, "source_access_denied")

    def test_historical_gate_accepts_superseded_but_not_missing_or_denied(self):
        require_historical_resolvable(self._result(VersionStatus.SUPERSEDED, AccessStatus.ALLOWED))
        for version, access in ((VersionStatus.UNAVAILABLE, AccessStatus.ALLOWED),
                                (VersionStatus.WITHDRAWN, AccessStatus.ALLOWED),
                                (VersionStatus.SUPERSEDED, AccessStatus.DENIED)):
            with self.subTest(version=version.value, access=access.value), self.assertRaises(ContractViolation):
                require_historical_resolvable(self._result(version, access))


if __name__ == "__main__":
    unittest.main()
