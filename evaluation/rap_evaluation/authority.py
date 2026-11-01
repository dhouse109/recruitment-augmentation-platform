"""``FixtureMockAuthority``: a declared, synthetic source authority for admitted golden scopes.

Every in-scope source reference is ``current`` and ``allowed`` for the case's
declared principals; case overrides and step deltas are applied as declared;
everything else is ``unavailable`` and ``denied``. ``checked_at`` is the run's
pinned ``as_of`` (a declared synthetic time). Its answers are fixture
declarations: they are NOT evidence of Drupal authorization, permissions,
revision currentness or context completeness (that would be T4).
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable

from rap_contracts.evaluation import AuthorityOverride
from rap_contracts.models import AccessStatus, SourceCheckResult, SourceReference, VersionStatus

from . import MOCK_AUTHORITY_ID


class FixtureMockAuthority:
    def __init__(self, principals: Iterable[str], refs: Iterable[SourceReference], as_of: datetime) -> None:
        self._state: dict[tuple[str, SourceReference], tuple[VersionStatus, AccessStatus]] = {}
        self.as_of = as_of
        self.calls: list[tuple[str, SourceReference]] = []
        refs = tuple(refs)
        for principal in principals:
            for ref in refs:
                self._state[(principal, ref)] = (VersionStatus.CURRENT, AccessStatus.ALLOWED)

    def apply(self, overrides: Iterable[AuthorityOverride]) -> None:
        for o in overrides:
            self._state[(o.principal_id, o.source_ref)] = (o.version_status, o.access_status)

    def check(self, principal_id: str, ref: SourceReference) -> SourceCheckResult:
        self.calls.append((principal_id, ref))
        version, access = self._state.get((principal_id, ref), (VersionStatus.UNAVAILABLE, AccessStatus.DENIED))
        return SourceCheckResult(source=ref, checked_at=self.as_of, checked_by=MOCK_AUTHORITY_ID,
                                 version_status=version, access_status=access)
