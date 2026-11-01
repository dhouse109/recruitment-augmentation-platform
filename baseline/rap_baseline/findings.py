"""Runtime-local structured findings (PR-S2): types, canonical form, digests and ids. NOT a contract.

Findings are produced by ``rules.build_findings`` from the same frozen ``DecisionInputs``
the rules evaluated, then verified independently by ``findings_check.verify_findings``
(L1) before an explanation is built. They account for every selected input of the
admitted projection, including inputs the ``EligibilityResult`` does not cite (G12a-c).

Three levels:

* ``SubjectFinding`` -- one per rule subject (a requirement, or the rule's single subject);
* ``Contribution`` -- one per selected claim or participation relevant to that subject;
* ``EvidenceAttribution`` -- one per evidence record of the input, with basis, exact
  source reference, field path and, for contested claims, the alternative index.

Identity is split (plan rev. 2.2 section 4.5):

* findings CONTENT is a pure function of the decision inputs and the findings policy;
  ``content_digest`` excludes every id, timestamp, principal and authority answer;
* the findings ARTIFACT binds content to one assessment: result id, input fingerprint,
  output digest, the single UTC ``as_of`` and the pinned producer/policy versions.

This module reads no claim value, state, status or hours (AST-enforced); it only
holds, serializes and hashes what ``rules.build_findings`` produced.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from rap_contracts.models import SourceReference

from .identity import canonical, canonical_sha256

FINDINGS_PRODUCER = "rap-baseline.findings/0.1.0"
CONTENT_DIGEST_VERSION = "rap-baseline.findings-content/1"
FINDINGS_ID_VERSION = "rap-baseline.findings-id/1"
FINDINGS_ID_HEX_CHARS = 40

# Closed vocabularies (the verifier and the explanation templates enumerate these).
SUBJECT_STATUSES: dict[str, tuple[str, ...]] = {
    "opportunity_status": ("active", "paused", "closed"),
    "program_participation": ("confirmed", "not_participating", "not_recorded"),
    "weekly_hours": ("meets", "below", "contested", "not_declared", "hours_not_published"),
    "qualification": ("satisfied_verified", "satisfied_declared", "contradicted_verified", "contradicted_declared",
                      "contested", "only_inferred", "not_evidenced"),
    "no_mandatory_qualification": ("none_required",),
}
SUBJECT_ROLES = ("decisive", "uncited_nonpass", "uncited_satisfied")
CONTRIBUTION_ROLES = ("cited", "uncited_material", "uncited_satisfying", "context")
RULE_STANDINGS = ("decision_input", "non_decision_input")
RELATIONS = ("support", "alternative_support", "inference_input", "authority_record")
BASES = ("candidate_statement", "independent_verification", "authority_record")
INFORMATION_GAPS = ("no_source_backed_value", "only_inferred_signal", "conflicting_sources",
                    "opportunity_requirement_unpublished", "no_participation_record")


@dataclass(frozen=True)
class EvidenceAttribution:
    evidence_id: str
    basis: str
    relation: str
    source_ref: SourceReference
    field_path: str
    alternative_index: int | None = None
    reading: str | None = None          # alternative reading for a contested skill claim ("has" / "lacks")
    reading_hours: int | None = None    # alternative reading for a contested availability claim


@dataclass(frozen=True)
class Contribution:
    input_kind: str                     # "claim" | "participation"
    input_id: str
    role: str
    claim_state: str | None             # None for participation records
    rule_standing: str
    reading: str | None                 # declared/inferred skill presence, or participation record status
    reading_hours: int | None           # declared/inferred availability hours
    inferred_by: str | None
    evidence: tuple[EvidenceAttribution, ...]


@dataclass(frozen=True)
class RequirementAttribution:
    requirement_id: str
    source_ref: SourceReference
    field_path: str


@dataclass(frozen=True)
class SubjectFinding:
    kind: str
    program_id: str | None
    skill_code: str | None
    requirement: RequirementAttribution | None
    subject_status: str
    subject_role: str
    information_gap: str | None
    declared_hours: int | None
    required_hours: int | None
    contributions: tuple[Contribution, ...]


@dataclass(frozen=True)
class RuleFindings:
    rule_id: str
    rule_version: int
    rule_kind: str
    result: str
    reason_code: str
    subjects: tuple[SubjectFinding, ...]


@dataclass(frozen=True)
class FindingsContent:
    organization_id: str
    candidate_id: str
    opportunity_id: str
    opportunity_ref: SourceReference
    policy_id: str
    policy_version: int
    policy_ref: SourceReference
    decision: str
    rules: tuple[RuleFindings, ...]


@dataclass(frozen=True)
class FindingsArtifact:
    findings_id: str
    result_id: str
    input_fingerprint: str
    output_digest: str
    as_of: datetime
    produced_by: str
    findings_policy: str
    content_digest: str
    content: FindingsContent


def to_plain(obj: Any) -> Any:
    """Dataclasses to dicts, tuples to lists; contract models are left for ``identity.canonical``."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: to_plain(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, (list, tuple)):
        return [to_plain(item) for item in obj]
    return obj


def content_canonical(content: FindingsContent) -> Any:
    return canonical(to_plain(content))


def content_digest(content: FindingsContent, findings_policy: str) -> str:
    return canonical_sha256({"v": CONTENT_DIGEST_VERSION, "findings_policy": findings_policy,
                             "content": to_plain(content)})


def findings_id(result_id: str, digest: str) -> str:
    h = canonical_sha256({"v": FINDINGS_ID_VERSION, "result_id": result_id, "content_digest": digest})
    return "findings_" + h.removeprefix("sha256:")[:FINDINGS_ID_HEX_CHARS]


def make_artifact(content: FindingsContent, result, provenance, findings_policy: str) -> FindingsArtifact:
    """Bind content to one assessment. Header values are copied, and L1 re-derives them independently."""
    digest = content_digest(content, findings_policy)
    return FindingsArtifact(
        findings_id=findings_id(result.id, digest),
        result_id=result.id,
        input_fingerprint=provenance.input_fingerprint,
        output_digest=provenance.output_digest,
        as_of=result.evaluated_at,
        produced_by=FINDINGS_PRODUCER,
        findings_policy=findings_policy,
        content_digest=digest,
        content=content,
    )


def artifact_canonical(artifact: FindingsArtifact) -> Any:
    return canonical(to_plain(artifact))
