"""Phase 1 (P1-P4): metadata-only target resolution, projection, organization guard, structural checks.

Nothing in this module may read a claim value, contested alternative value,
claim state, participation status, opportunity status or required-hours value
(enforced by an AST test). Those are read only after the source gate, in
phase 2. Every function here runs before any authority call.

Structural metadata used here (candidate, profile and application versions,
programs, opportunities targeted by the candidate's applications, claim
vocabularies) is not gated: it must arrive from a pre-authorized adapter
(``load_authorized_case``). Decision-relevant sources are gated in P5.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Iterable, Mapping

from rap_contracts.claims import ClaimType
from rap_contracts.eligibility import (
    EligibilityContext,
    MandatoryQualificationRequirement,
    PolicyRuleKind,
    PolicySet,
    WeeklyHoursRequirement,
    check_policy_sets,
    check_requirements,
)
from rap_contracts.evidence import EvidenceSubject, EvidenceSubjectKind, check_evidence_records, resolve_evidence_ids
from rap_contracts.invariants import ContractRecordSet, ContractViolation, check_record_set
from rap_contracts.models import Candidate, Opportunity, SourceReference, SourceSystem, SourceSystemCapabilities
from rap_contracts.source_checks import check_record_set_versions

from .identity import ref_sort_key
from .request import EligibilityRequest


@dataclass(frozen=True)
class Targets:
    candidate: Candidate
    opportunity: Opportunity
    policy: PolicySet


def _single(items: Iterable, record_id: str, what: str):
    hits = [x for x in items if x.id == record_id]
    if not hits:
        raise ContractViolation("unknown_reference", f"{what} {record_id} not found")
    if len(hits) > 1:
        raise ContractViolation("duplicate_id", f"{what} {record_id} appears more than once")
    return hits[0]


def _same_org(org: str, request_org: str, what: str) -> None:
    if org != request_org:
        raise ContractViolation("cross_org_reference", f"{what} is outside the requested organization")


def resolve_targets(request: EligibilityRequest, ctx: EligibilityContext) -> Targets:
    """P1: references, organization guard and policy scope. Reads ids, organizations and program ids only."""
    org = request.organization_id
    candidate = _single(ctx.records.candidates, request.candidate_id, "candidate")
    _same_org(candidate.organization_id, org, "candidate")
    opportunity = _single(ctx.records.opportunities, request.opportunity_id, "opportunity")
    _same_org(opportunity.organization_id, org, "opportunity")
    _same_org(opportunity.source_ref.organization_id, org, "opportunity source")
    _same_org(request.policy.source_ref.organization_id, org, "requested policy pin")
    pin = request.policy
    matches = {p for p in ctx.policies if p.id == pin.policy_set_id and p.version == pin.version}
    if len(matches) > 1:
        raise ContractViolation("policy_version_conflict", f"{pin.policy_set_id} v{pin.version} has two definitions")
    policy = next(iter(matches), None)
    if policy is None or policy.source_ref != pin.source_ref:
        raise ContractViolation("policy_version_mismatch", "the requested policy pin does not match a supplied policy")
    _same_org(policy.organization_id, org, "policy")
    _same_org(policy.source_ref.organization_id, org, "policy source")
    if policy.program_id is not None and opportunity.program_id != policy.program_id:
        raise ContractViolation("policy_scope_mismatch", f"{policy.id} does not cover {opportunity.id}")
    for rule in policy.rules:
        if rule.program_id is not None and rule.program_id != opportunity.program_id:
            raise ContractViolation("participation_program_mismatch",
                                    f"{rule.rule_id} requires {rule.program_id}; {opportunity.id} is not in it")
    return Targets(candidate=candidate, opportunity=opportunity, policy=policy)


def project(ctx: EligibilityContext, t: Targets) -> EligibilityContext:
    """P2: the rule-relevant inputs plus the structural records the existing validators need.

    Selection uses only: policy rule kinds and program ids; requirement kind,
    skill code and opportunity id; claim candidate id, claim type, subject code
    and evidence ids; participation candidate id, program id and evidence ids.
    """
    records = ctx.records
    cand, opp, policy = t.candidate, t.opportunity, t.policy
    kinds = {rule.kind for rule in policy.rules}
    wants_hours = PolicyRuleKind.AVAILABILITY_MEETS_REQUIRED_HOURS in kinds
    wants_quals = PolicyRuleKind.MANDATORY_QUALIFICATION_EVIDENCED in kinds
    requirements = tuple(
        r for r in ctx.requirements if r.opportunity_id == opp.id and (
            (isinstance(r.requirement, WeeklyHoursRequirement) and wants_hours)
            or (isinstance(r.requirement, MandatoryQualificationRequirement) and wants_quals)))
    codes = {r.requirement.skill_code for r in requirements if isinstance(r.requirement, MandatoryQualificationRequirement)}
    claims = tuple(
        c for c in ctx.claims if c.candidate_id == cand.id and (
            (c.claim_type is ClaimType.AVAILABILITY and wants_hours)
            or (c.claim_type is ClaimType.SKILL and c.subject_code in codes)))
    rule_programs = {rule.program_id for rule in policy.rules if rule.program_id is not None}
    participations = tuple(p for p in ctx.participations if p.candidate_id == cand.id and p.program_id in rule_programs)

    evidence_ids = sorted({e for c in claims for e in c.all_evidence_ids()} | {e for p in participations for e in p.evidence_ids})
    missing = [e for e in evidence_ids if e not in ctx.evidence]
    if missing:
        raise ContractViolation("invalid_citation", f"evidence {missing[0]} does not exist")
    evidence: Mapping = MappingProxyType({e: ctx.evidence[e] for e in evidence_ids})

    applications = tuple(a for a in records.applications if a.candidate_id == cand.id)
    profiles = tuple(p for p in records.profiles if p.candidate_id == cand.id)
    opportunity_ids = {opp.id} | {a.target.opportunity_id for a in applications if a.target.opportunity_id}
    opportunities = tuple(o for o in records.opportunities if o.id in opportunity_ids)
    program_ids = ({opp.program_id, policy.program_id} | rule_programs
                   | {a.target.program_id for a in applications} | {o.program_id for o in opportunities}) - {None}
    vocab_pins = ({(c.vocabulary.id, c.vocabulary.version) for c in claims}
                  | {(r.requirement.vocabulary.id, r.requirement.vocabulary.version)
                     for r in requirements if isinstance(r.requirement, MandatoryQualificationRequirement)})
    return EligibilityContext(
        records=ContractRecordSet(
            candidates=(cand,), profiles=profiles, applications=applications, opportunities=opportunities,
            programs=tuple(p for p in records.programs if p.id in program_ids)),
        policies=(policy,),
        requirements=requirements,
        claims=claims,
        participations=participations,
        evidence=evidence,
        vocabularies=tuple(v for v in ctx.vocabularies if (v.id, v.version) in vocab_pins),
    )


def gate_refs(p: EligibilityContext, t: Targets) -> tuple[SourceReference, ...]:
    """Every decision-relevant authoritative source of the projection, deduplicated and sorted."""
    refs = {t.opportunity.source_ref, t.policy.source_ref}
    refs |= {r.source_ref for r in p.requirements}
    refs |= {e.source_ref for e in p.evidence.values()}
    return tuple(sorted(refs, key=ref_sort_key))


def organization_guard(p: EligibilityContext, t: Targets, org: str) -> None:
    """P3: every projected record and every source to be gated is in the requested organization."""
    r = p.records
    for rec in (*r.candidates, *r.profiles, *r.applications, *r.opportunities, *r.programs,
                *p.policies, *p.requirements, *p.claims, *p.participations, *p.evidence.values(), *p.vocabularies):
        _same_org(rec.organization_id, org, f"{type(rec).__name__} {getattr(rec, 'id', '')}")
    for app in r.applications:
        if app.submission is not None:
            _same_org(app.submission.profile_ref.organization_id, org, f"application {app.id} submission")
    for ref in gate_refs(p, t):
        _same_org(ref.organization_id, org, "a gated source")
    subject = EvidenceSubject(kind=EvidenceSubjectKind.CANDIDATE, id=t.candidate.id)
    for claim in p.claims:
        resolve_evidence_ids(claim.all_evidence_ids(), p.evidence, org, subject)
    for part in p.participations:
        resolve_evidence_ids(part.evidence_ids, p.evidence, org, subject)


def structural_checks(p: EligibilityContext, capabilities: Mapping[SourceSystem, SourceSystemCapabilities]) -> None:
    """P4: existing validators that take neither claims nor participations."""
    check_record_set(p.records)
    check_record_set_versions(p.records, capabilities)
    check_evidence_records(p.evidence, p.records, capabilities)
    check_policy_sets(p.policies, p.records, capabilities)
    check_requirements(p, capabilities)
