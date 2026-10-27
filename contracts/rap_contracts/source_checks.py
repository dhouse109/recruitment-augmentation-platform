"""Source version-kind validation and fail-closed source-check policy (D-004.07).

Responsibilities, stated plainly:

* The ADAPTER (producer) chooses the version kind from its declared
  capabilities, computes logical snapshot tokens with a registered method over
  the authoritative record, and records ``captured_at``/``captured_by``.
* A CONSUMER may validate shape and method-specific token format
  (``check_version_kind``). Format validity says nothing about freshness or
  authorization.
* Only the live AUTHORITY can report whether a referenced version is current,
  superseded-but-retained, withdrawn, deleted or unavailable, and whether a
  principal may read it (``SourceAuthority.check``). In this PR the only
  implementation of that protocol is a test mock.
"""

from __future__ import annotations

import hashlib
import json
import re
from types import MappingProxyType
from typing import Any, Mapping, Protocol

from .invariants import ContractRecordSet, ContractViolation, all_source_refs, application_submission_ref
from .models import (
    AccessStatus,
    Application,
    ApplicationStatus,
    LogicalSnapshot,
    NativeRevision,
    SourceCheckResult,
    SourceReference,
    SourceSystem,
    SourceSystemCapabilities,
    VersionStatus,
)

# ---------------------------------------------------------------------------
# Snapshot methods: an open registry, not a hard-coded single method
# ---------------------------------------------------------------------------

SHA256_CANONICAL_JSON_V1 = "sha256-canonical-json/v1"

SnapshotMethodRegistry = Mapping[str, "re.Pattern[str]"]

#: Initial registered method. Additional methods are added by registering a
#: method id and its token pattern; the portable contract does not change.
DEFAULT_SNAPSHOT_METHODS: SnapshotMethodRegistry = MappingProxyType(
    {SHA256_CANONICAL_JSON_V1: re.compile(r"sha256:[0-9a-f]{64}")}
)


def canonical_json_sha256(payload: Any) -> str:
    """Reference definition of ``sha256-canonical-json/v1``.

    UTF-8 JSON with sorted keys, no insignificant whitespace, no NaN/Infinity;
    token is ``sha256:`` + lowercase hex digest. Which fields of an
    authoritative record are included is an adapter-level decision (OPEN).
    """
    data = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return "sha256:" + hashlib.sha256(data.encode("utf-8")).hexdigest()


def check_version_kind(
    ref: SourceReference,
    capabilities: Mapping[SourceSystem, SourceSystemCapabilities],
    methods: SnapshotMethodRegistry = DEFAULT_SNAPSHOT_METHODS,
) -> None:
    """Native revision when the source declares one; otherwise a registered logical snapshot."""
    caps = capabilities.get(ref.entity.source_system)
    if caps is None:
        raise ContractViolation("unknown_source_system", f"no capabilities declared for {ref.entity.source_system.value}")
    etype = ref.entity.entity_type
    version = ref.version
    if etype in caps.native_revision_entity_types:
        if not isinstance(version, NativeRevision):
            raise ContractViolation(
                "snapshot_for_revisionable_type",
                f"{etype} declares native revisions; a logical snapshot cannot stand in for one",
            )
        return
    if etype in caps.logical_snapshot_entity_types:
        if not isinstance(version, LogicalSnapshot):
            raise ContractViolation(
                "native_revision_claim_unsupported",
                f"{etype} has no native revisions; the version must be labeled logical_snapshot",
            )
        if version.method not in caps.snapshot_methods or version.method not in methods:
            raise ContractViolation("unsupported_snapshot_method", f"snapshot method {version.method} is not registered")
        if not methods[version.method].fullmatch(version.token):
            raise ContractViolation("malformed_snapshot_token", f"token does not match {version.method}")
        return
    raise ContractViolation("undeclared_entity_type", f"{etype} has no declared version capability")


def check_record_set_versions(
    records: ContractRecordSet,
    capabilities: Mapping[SourceSystem, SourceSystemCapabilities],
    methods: SnapshotMethodRegistry = DEFAULT_SNAPSHOT_METHODS,
) -> None:
    for ref in all_source_refs(records):
        check_version_kind(ref, capabilities, methods)


# ---------------------------------------------------------------------------
# Live authority boundary (protocol only; mock in tests)
# ---------------------------------------------------------------------------


class SourceAuthority(Protocol):
    """Live check of one exact source version for one principal.

    ``principal_id`` is an opaque caller identifier for the check. Passing it
    is not authentication; a real implementation must derive the principal
    from authenticated Drupal context.
    """

    def check(self, principal_id: str, ref: SourceReference) -> SourceCheckResult: ...


_VERSION_FAILURE_CODES = {
    VersionStatus.WITHDRAWN: "source_withdrawn",
    VersionStatus.DELETED: "source_deleted",
    VersionStatus.UNAVAILABLE: "source_unavailable",
}


def checked(authority: SourceAuthority, principal_id: str, ref: SourceReference) -> SourceCheckResult:
    """Run one check; fail closed on errors, malformed results, or substitution."""
    try:
        result = authority.check(principal_id, ref)
    except Exception as exc:  # any authority failure denies use
        raise ContractViolation("source_check_error", f"authority check failed: {exc}") from exc
    if not isinstance(result, SourceCheckResult):
        raise ContractViolation("source_check_error", "authority returned a non-contract result")
    if result.source != ref:
        raise ContractViolation(
            "source_substitution", "authority answered for a different source/version than requested"
        )
    return result


def require_current_and_allowed(result: SourceCheckResult) -> None:
    """Gate for model context and consequential reviewer action."""
    if result.access_status is not AccessStatus.ALLOWED:
        raise ContractViolation("source_access_denied", "principal may not read this source")
    if result.version_status is VersionStatus.SUPERSEDED:
        raise ContractViolation("source_not_current", "a newer version exists")
    if result.version_status is not VersionStatus.CURRENT:
        raise ContractViolation(_VERSION_FAILURE_CODES[result.version_status], result.version_status.value)


def require_historical_resolvable(result: SourceCheckResult) -> None:
    """Gate for resolving pinned historical evidence: the exact version must still resolve and be readable."""
    if result.access_status is not AccessStatus.ALLOWED:
        raise ContractViolation("source_access_denied", "principal may not read this source")
    if result.version_status not in (VersionStatus.CURRENT, VersionStatus.SUPERSEDED):
        raise ContractViolation(_VERSION_FAILURE_CODES[result.version_status], result.version_status.value)


def resolve_submission_evidence(
    application: Application, authority: SourceAuthority, principal_id: str
) -> tuple[SourceCheckResult, SourceCheckResult]:
    """Resolve the exact pinned profile and application versions of a submission.

    Never substitutes a newer profile: the authority is asked about the pinned
    version only, and any answer for another version is rejected. Unavailable,
    withdrawn, deleted or unauthorized versions fail closed. A withdrawn
    application is not usable as active evidence (audit-only access is a
    separate, not-yet-designed authorization path).
    """
    if application.submission is None:
        raise ContractViolation("no_submission", f"{application.id} has no submission snapshot")
    if application.status is ApplicationStatus.WITHDRAWN:
        raise ContractViolation("application_withdrawn", f"{application.id} is withdrawn")
    profile_result = checked(authority, principal_id, application.submission.profile_ref)
    require_historical_resolvable(profile_result)
    app_result = checked(authority, principal_id, application_submission_ref(application))
    require_historical_resolvable(app_result)
    return profile_result, app_result
