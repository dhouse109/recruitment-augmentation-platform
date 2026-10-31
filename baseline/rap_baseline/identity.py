"""Deterministic identity: decision inputs, input fingerprint, output digest and result id.

* ``DecisionInputs`` is the ONLY object the rules receive, and the same object
  is fingerprinted: what is fingerprinted is what is evaluated.
* Every timezone-aware datetime anywhere in a fingerprinted structure
  (including nested ``LogicalSnapshot.captured_at``) is normalized to UTC
  before hashing, so equivalent timezone representations of one instant hash
  identically. Naive datetimes are rejected.
* The result id identifies a deterministic assessment (input fingerprint +
  UTC assessment time). It is not necessarily a globally unique execution
  event; the requesting principal and the individual source checks are
  recorded separately in provenance.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

from pydantic import BaseModel

from rap_contracts.claims import CandidateClaim, ClaimVocabulary, ProgramParticipation
from rap_contracts.eligibility import EligibilityContext, EligibilityResult, OpportunityRequirement, PolicySet
from rap_contracts.evidence import EvidenceRecord
from rap_contracts.models import LogicalSnapshot, Opportunity, SourceReference
from rap_contracts.source_checks import canonical_json_sha256

INPUT_FINGERPRINT_VERSION = "rap-baseline.input/1"
OUTPUT_DIGEST_VERSION = "rap-baseline.output/1"
RESULT_ID_VERSION = "rap-baseline.eligibility-id/1"
RESULT_ID_HEX_CHARS = 40  # "eligibility_" + 40 hex = 52 characters (EligibilityId max 64)


class IdentityError(ValueError):
    """A value cannot be canonicalized (naive datetime, float, unknown type)."""


def to_utc(moment: datetime) -> datetime:
    if not isinstance(moment, datetime) or moment.tzinfo is None or moment.utcoffset() is None:
        raise IdentityError("a timezone-aware datetime is required")
    return moment.astimezone(timezone.utc)


def utc_text(moment: datetime) -> str:
    return to_utc(moment).isoformat().replace("+00:00", "Z")


def _sort_key(item: Any) -> str:
    return json.dumps(item, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical(value: Any) -> Any:
    """JSON-ready canonical form: UTC datetimes, enum values, sorted sets. Rejects floats and unknown types."""
    if isinstance(value, BaseModel):
        return canonical(value.model_dump(mode="python"))
    if isinstance(value, datetime):
        return utc_text(value)
    if isinstance(value, Enum):
        return canonical(value.value)
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, Mapping):
        out = {}
        for key, item in value.items():
            key = key.value if isinstance(key, Enum) else key
            if not isinstance(key, str):
                raise IdentityError(f"non-string mapping key {key!r}")
            out[key] = canonical(item)
        return out
    if isinstance(value, (list, tuple)):
        return [canonical(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((canonical(item) for item in value), key=_sort_key)
    raise IdentityError(f"cannot canonicalize {type(value).__name__}")


def canonical_sha256(value: Any) -> str:
    return canonical_json_sha256(canonical(value))


def normalize_ref(ref: SourceReference) -> SourceReference:
    """Same reference (equal under ``==``) with a UTC ``captured_at`` for logical snapshots."""
    version = ref.version
    if isinstance(version, LogicalSnapshot):
        return ref.model_copy(update={"version": version.model_copy(update={"captured_at": to_utc(version.captured_at)})})
    return ref


def ref_sort_key(ref: SourceReference) -> str:
    return _sort_key(canonical(ref))


@dataclass(frozen=True)
class EngineIdentity:
    evaluated_by: str
    rule_table_version: str
    citation_policy_version: str


@dataclass(frozen=True)
class DecisionInputs:
    """Everything the rules may read, after source admission and phase-2 validation."""

    organization_id: str
    candidate_id: str
    opportunity: Opportunity
    policy: PolicySet
    requirements: tuple[OpportunityRequirement, ...]
    claims: tuple[CandidateClaim, ...]
    participations: tuple[ProgramParticipation, ...]
    evidence: Mapping[str, EvidenceRecord]
    vocabularies: tuple[ClaimVocabulary, ...]
    engine: EngineIdentity


def build_decision_inputs(projected: EligibilityContext, organization_id: str, candidate_id: str,
                          opportunity_id: str, engine: EngineIdentity) -> DecisionInputs:
    by_id = lambda items: tuple(sorted(items, key=lambda r: r.id))  # noqa: E731
    return DecisionInputs(
        organization_id=organization_id,
        candidate_id=candidate_id,
        opportunity=next(o for o in projected.records.opportunities if o.id == opportunity_id),
        policy=projected.policies[0],
        requirements=by_id(r for r in projected.requirements if r.opportunity_id == opportunity_id),
        claims=by_id(projected.claims),
        participations=by_id(projected.participations),
        evidence=MappingProxyType({k: projected.evidence[k] for k in sorted(projected.evidence)}),
        vocabularies=tuple(sorted(projected.vocabularies, key=lambda v: (v.id, v.version))),
        engine=engine,
    )


def input_fingerprint(d: DecisionInputs) -> str:
    return canonical_sha256({
        "v": INPUT_FINGERPRINT_VERSION,
        "engine": {"evaluated_by": d.engine.evaluated_by, "rule_table": d.engine.rule_table_version,
                   "citation_policy": d.engine.citation_policy_version},
        "request": {"organization_id": d.organization_id, "candidate_id": d.candidate_id,
                    "opportunity_id": d.opportunity.id,
                    "policy": {"policy_set_id": d.policy.id, "version": d.policy.version,
                               "source_ref": d.policy.source_ref}},
        "opportunity": d.opportunity,
        "policy": d.policy,
        "requirements": list(d.requirements),
        "claims": list(d.claims),
        "participations": list(d.participations),
        "evidence": [d.evidence[k] for k in sorted(d.evidence)],
        "vocabularies": list(d.vocabularies),
    })


def output_digest(result: EligibilityResult) -> str:
    return canonical_sha256({"v": OUTPUT_DIGEST_VERSION,
                             "result": result.model_dump(mode="python", exclude={"id", "evaluated_at"})})


def result_id(fingerprint: str, as_of: datetime) -> str:
    digest = canonical_json_sha256({"v": RESULT_ID_VERSION, "input_fingerprint": fingerprint,
                                    "evaluated_at": utc_text(as_of)})
    return "eligibility_" + digest.removeprefix("sha256:")[:RESULT_ID_HEX_CHARS]
