"""Runtime-local provenance (not a contract): who asked, what was checked, what identities resulted.

``RecordingAuthority`` wraps the caller's ``SourceAuthority`` so the unmodified
``require_sources_admissible`` can be used while each answer is captured.
Recording proves only what the supplied authority answered. With the synthetic
fixture authority used in tests this is mock-level evidence: it does not
establish Drupal authorization, revision currentness or context completeness.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from rap_contracts.models import SourceCheckResult, SourceReference

from .identity import canonical, normalize_ref, utc_text


@dataclass(frozen=True)
class CheckRecord:
    ref: SourceReference
    answer: SourceCheckResult | None
    raised: str | None = None


@dataclass
class RecordingAuthority:
    inner: object
    records: list[CheckRecord] = field(default_factory=list)

    def check(self, principal_id: str, ref: SourceReference) -> SourceCheckResult:
        try:
            answer = self.inner.check(principal_id, ref)
        except Exception as exc:
            self.records.append(CheckRecord(ref=ref, answer=None, raised=type(exc).__name__))
            raise
        self.records.append(CheckRecord(ref=ref, answer=answer if isinstance(answer, SourceCheckResult) else None,
                                        raised=None if isinstance(answer, SourceCheckResult) else "non_contract_result"))
        return answer


@dataclass(frozen=True)
class AssessmentProvenance:
    result_id: str
    input_fingerprint: str
    output_digest: str
    principal_id: str
    as_of: datetime
    evaluated_by: str
    rule_table_version: str
    citation_policy_version: str
    gated_refs: tuple[SourceReference, ...]
    checks: tuple[SourceCheckResult, ...]

    def canonical(self) -> dict:
        return {
            "result_id": self.result_id,
            "input_fingerprint": self.input_fingerprint,
            "output_digest": self.output_digest,
            "principal_id": self.principal_id,
            "as_of": utc_text(self.as_of),
            "evaluated_by": self.evaluated_by,
            "rule_table_version": self.rule_table_version,
            "citation_policy_version": self.citation_policy_version,
            "gated_refs": [canonical(normalize_ref(r)) for r in self.gated_refs],
            "checks": [canonical(c) for c in self.checks],
        }
