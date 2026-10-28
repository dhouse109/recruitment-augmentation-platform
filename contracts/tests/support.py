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


# ---------------------------------------------------------------------------
# Eligibility / evidence fixture (extends the foundations fixture)
# ---------------------------------------------------------------------------

EXT_FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "eligibility-evidence-v0.2.0-dev.json"


def ext_raw() -> dict[str, Any]:
    with EXT_FIXTURE_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


def ext_capabilities() -> dict[SourceSystem, SourceSystemCapabilities]:
    caps = [SourceSystemCapabilities.model_validate(c) for c in ext_raw()["capabilities"]]
    return {c.source_system: c for c in caps}


def ext_records() -> ContractRecordSet:
    """Foundations records plus the additional candidates/profiles/applications."""
    base, extra = records(), ext_raw()["additional_records"]
    return ContractRecordSet(
        candidates=base.candidates + tuple(Candidate.model_validate(r) for r in extra["candidates"]),
        profiles=base.profiles + tuple(CandidateProfile.model_validate(r) for r in extra["profiles"]),
        programs=base.programs,
        opportunities=base.opportunities,
        applications=base.applications + tuple(Application.model_validate(r) for r in extra["applications"]),
    )


def ext_context(doc: dict[str, Any] | None = None):
    """EligibilityContext built from the extended fixture (or a mutated copy of it)."""
    from rap_contracts.claims import CandidateClaim, ClaimVocabulary, ProgramParticipation
    from rap_contracts.eligibility import EligibilityContext, OpportunityRequirement, PolicySet
    from rap_contracts.evidence import EvidenceRecord, index_evidence

    doc = doc if doc is not None else ext_raw()
    return EligibilityContext(
        records=ext_records(),
        policies=tuple(PolicySet.model_validate(r) for r in doc["policies"]),
        requirements=tuple(OpportunityRequirement.model_validate(r) for r in doc["requirements"]),
        claims=tuple(CandidateClaim.model_validate(r) for r in doc["claims"]),
        participations=tuple(ProgramParticipation.model_validate(r) for r in doc["participations"]),
        evidence=index_evidence(EvidenceRecord.model_validate(r) for r in doc["evidence"]),
        vocabularies=tuple(ClaimVocabulary.model_validate(r) for r in doc["vocabularies"]),
    )


def ext_results(doc: dict[str, Any] | None = None):
    from rap_contracts.eligibility import EligibilityResult

    doc = doc if doc is not None else ext_raw()
    return tuple(EligibilityResult.model_validate(r) for r in doc["eligibility_results"])


def ext_chunk_index():
    from rap_contracts.evidence import RetrievalChunk

    return {c["id"]: RetrievalChunk.model_validate(c) for c in ext_raw()["chunks"]}


class FixtureChunkStore:
    """MOCK controlled derived store. Records every load so tests can prove no early reads."""

    def __init__(self, contents: dict[str, str] | None = None) -> None:
        self.contents = dict(contents if contents is not None else ext_raw()["chunk_store"])
        self.loads: list[str] = []

    def load(self, text_pointer: str) -> str:
        self.loads.append(text_pointer)
        return self.contents[text_pointer]


def scenario_authority(principal: str = COORDINATOR) -> FixtureSourceAuthority:
    """MOCK authority: every fixture source version current+allowed for ``principal``,
    except the fixture's declared overrides (superseded / withdrawn)."""
    doc = ext_raw()
    authority = FixtureSourceAuthority()
    refs: set[SourceReference] = set()
    ctx = ext_context()
    for rec in ctx.records.profiles + ctx.records.applications + ctx.records.opportunities + ctx.records.programs:
        refs.add(rec.source_ref)
    refs |= {e.source_ref for e in ctx.evidence.values()}
    refs |= {r.source_ref for r in ctx.requirements} | {p.source_ref for p in ctx.policies}
    refs |= {c.source_ref for c in ext_chunk_index().values()}
    for ref in refs:
        authority.set(principal, ref, VersionStatus.CURRENT, AccessStatus.ALLOWED)
    for override in doc["mock_authority_overrides"]:
        authority.set(principal, SourceReference.model_validate(override["source_ref"]),
                      VersionStatus(override["version_status"]), AccessStatus(override["access_status"]))
    return authority


# ---------------------------------------------------------------------------
# Review fixture (extends the eligibility/evidence fixture)
# ---------------------------------------------------------------------------

REVIEW_FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "review-v0.2.0-dev.json"
REVIEW_PRINCIPAL_AUTHENTICATED_AT = datetime(2026, 10, 28, 13, 55, tzinfo=timezone.utc)


def review_raw() -> dict[str, Any]:
    with REVIEW_FIXTURE_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


def recommendation_context(doc: dict[str, Any] | None = None):
    from rap_contracts.recommendation import RecommendationContext, index_eligibility_results

    return RecommendationContext(eligibility=ext_context(doc), eligibility_results=index_eligibility_results(ext_results(doc)),
                                 capabilities=ext_capabilities())


def review_models(doc: dict[str, Any] | None = None):
    from rap_contracts.recommendation import Recommendation, VerificationResult
    from rap_contracts.review import ReviewReasonVocabulary

    doc = doc if doc is not None else review_raw()
    return (
        [Recommendation.model_validate(r) for r in doc["recommendations"]],
        [VerificationResult.model_validate(v) for v in doc["verifications"]],
        [ReviewReasonVocabulary.model_validate(v) for v in doc["reason_vocabularies"]],
    )


def review_service(doc: dict[str, Any] | None = None, authority: "FixtureSourceAuthority | None" = None,
                   context=None):
    """Fresh in-memory TEST DOUBLE seeded from the review fixture, with verifications applied."""
    from review_double import InMemoryReviewService, MockAuthenticator, MockAuthorizer
    from rap_contracts.review import AuthenticatedPrincipal, ReviewerGrant

    doc = doc if doc is not None else review_raw()
    principals, grants = {}, {}
    for p in doc["mock_principals"]:
        principals[p["credential"]] = AuthenticatedPrincipal(
            principal_id=p["principal"], kind=p["kind"], authenticated_by="mock-authenticator/0",
            authenticated_at=REVIEW_PRINCIPAL_AUTHENTICATED_AT)
        grants[p["principal"]] = tuple(ReviewerGrant.model_validate(g) for g in p["grants"])
    recs, verifications, vocabularies = review_models(doc)
    return InMemoryReviewService(
        authenticator=MockAuthenticator(principals), authorizer=MockAuthorizer(grants),
        authority=authority if authority is not None else scenario_authority(),
        context=context if context is not None else recommendation_context(),
        recommendations=recs, verifications=verifications, reason_vocabularies=vocabularies)


def review_command(recommendation_id="recommendation_a_data", action="approve_for_follow_up",
                   code="meets_published_criteria", comment=None, key="key-demo-0000000001",
                   verification_id=None, vocabulary=("review_reasons_demo", 1)):
    from rap_contracts.review import HumanReviewCommand

    payload = {"idempotency_key": key, "recommendation_id": recommendation_id,
               "verification_id": verification_id or recommendation_id.replace("recommendation_", "verification_") + "_1",
               "action": action, "reason": {"vocabulary_id": vocabulary[0], "vocabulary_version": vocabulary[1], "code": code}}
    if comment is not None:
        payload["comment"] = comment
    return HumanReviewCommand.model_validate(payload)
