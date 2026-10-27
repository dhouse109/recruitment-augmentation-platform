"""Test support: fixture loading and a MOCK source authority.

``FixtureSourceAuthority`` is an in-memory stand-in for live Drupal authority.
It lets tests exercise fail-closed *plumbing*. It provides no evidence about
real Drupal ACLs, revision retention, transactional behavior, or freshness.
"""

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rap_contracts.invariants import ContractRecordSet
from rap_contracts.models import (
    AccessStatus,
    Application,
    Candidate,
    CandidateProfile,
    Opportunity,
    Program,
    SourceCheckResult,
    SourceReference,
    SourceSystem,
    SourceSystemCapabilities,
    VersionStatus,
)

FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "foundations-v0.2.0-dev.json"
CHECKED_AT = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)
MOCK_AUTHORITY_ID = "fixture-authority-mock/0.2.0-dev.foundations"
COORDINATOR = "principal_demo_coordinator"  # opaque mock caller id; not authentication


def raw() -> dict[str, Any]:
    """A fresh deep copy of the fixture document, safe to mutate in negative tests."""
    with FIXTURE_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


def raw_record(section: str, record_id: str, index: int = 0) -> dict[str, Any]:
    matches = [r for r in raw()[section] if r["id"] == record_id]
    return copy.deepcopy(matches[index])


def capabilities() -> dict[SourceSystem, SourceSystemCapabilities]:
    caps = [SourceSystemCapabilities.model_validate(c) for c in raw()["capabilities"]]
    return {c.source_system: c for c in caps}


def records() -> ContractRecordSet:
    doc = raw()
    return ContractRecordSet(
        candidates=tuple(Candidate.model_validate(r) for r in doc["candidates"]),
        profiles=tuple(CandidateProfile.model_validate(r) for r in doc["profiles"]),
        programs=tuple(Program.model_validate(r) for r in doc["programs"]),
        opportunities=tuple(Opportunity.model_validate(r) for r in doc["opportunities"]),
        applications=tuple(Application.model_validate(r) for r in doc["applications"]),
    )


def by_id(items, record_id):
    return next(r for r in items if r.id == record_id)


class FixtureSourceAuthority:
    """MOCK authority. Unknown (principal, ref) pairs fail closed as unavailable+denied."""

    def __init__(self) -> None:
        self._state: dict[tuple[str, SourceReference], tuple[VersionStatus, AccessStatus]] = {}
        self.substitute: dict[SourceReference, SourceReference] = {}
        self.raise_error = False
        self.calls: list[SourceReference] = []

    def set(self, principal_id: str, ref: SourceReference, version: VersionStatus, access: AccessStatus) -> None:
        self._state[(principal_id, ref)] = (version, access)

    def check(self, principal_id: str, ref: SourceReference) -> SourceCheckResult:
        self.calls.append(ref)
        if self.raise_error:
            raise RuntimeError("mock authority unreachable")
        answered = self.substitute.get(ref, ref)
        version, access = self._state.get(
            (principal_id, answered), (VersionStatus.UNAVAILABLE, AccessStatus.DENIED)
        )
        return SourceCheckResult(
            source=answered,
            checked_at=CHECKED_AT,
            checked_by=MOCK_AUTHORITY_ID,
            version_status=version,
            access_status=access,
        )
