"""Opportunity-specific eligibility and versioned policy contracts (D-004.05, D-004.06).

This module defines the result and policy contracts and a *support verifier*:
``check_eligibility_result`` confirms that a labeled outcome is consistent with
the inputs it cites and with absence conditions in a complete record set. It
does not select inputs or compute outcomes; it is NOT an eligibility engine.

Source-integrity and authorization failures are not eligibility outcomes: they
must fail closed before eligibility processing (``evidence.require_sources_admissible``),
and no ``unknown`` reason code exists for them.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Annotated, Iterable, Literal, Mapping, Union

from pydantic import AwareDatetime, ConfigDict, Field, model_validator

from .claims import (
    CandidateClaim,
    ClaimState,
    ClaimType,
    ClaimVocabulary,
    Code,
    ParticipationId,
    ProgramParticipation,
    ProgramParticipationStatus,
    VocabularyPin,
)
from .evidence import EvidenceBasis, EvidenceRecord, FieldPath
from .invariants import ContractRecordSet, ContractViolation
from .models import (
    CandidateId,
    ComponentId,
    ContractModel,
    OpportunityId,
    OpportunityStatus,
    OrganizationId,
    ProgramId,
    SourceReference,
    SourceSystem,
    SourceSystemCapabilities,
    _ID_BODY,
)
from .source_checks import DEFAULT_SNAPSHOT_METHODS, SnapshotMethodRegistry, check_version_kind

PolicySetId = Annotated[str, Field(pattern=rf"^policy_{_ID_BODY}$", max_length=64)]
RequirementId = Annotated[str, Field(pattern=rf"^requirement_{_ID_BODY}$", max_length=64)]
EligibilityId = Annotated[str, Field(pattern=rf"^eligibility_{_ID_BODY}$", max_length=64)]
ClaimIdRef = Annotated[str, Field(pattern=rf"^claim_{_ID_BODY}$", max_length=64)]
RuleId = Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9]*(-[A-Z0-9]+)*-[0-9]{3}$", max_length=64)]
Version = Annotated[int, Field(ge=1)]

# ---------------------------------------------------------------------------
# Published opportunity requirements (owner decision C)
# ---------------------------------------------------------------------------


class WeeklyHoursRequirement(ContractModel):
    kind: Literal["weekly_hours"]
    hours_per_week: Annotated[int, Field(ge=0, le=168)]


class MandatoryQualificationRequirement(ContractModel):
    kind: Literal["mandatory_qualification"]
    vocabulary: VocabularyPin
    skill_code: Code


RequirementSpec = Annotated[
    Union[WeeklyHoursRequirement, MandatoryQualificationRequirement], Field(discriminator="kind")
]


class OpportunityRequirement(ContractModel):
    """A published requirement, versioned by the exact authoritative source it came from.

    ``source_ref`` must be the opportunity's own source at the same version as
    the Opportunity record, or the exact source of a policy set that covers the
    opportunity. The Opportunity contract itself is unchanged.
    """

    id: RequirementId
    organization_id: OrganizationId
    opportunity_id: OpportunityId
    requirement: RequirementSpec
    source_ref: SourceReference
    field_path: FieldPath

    @model_validator(mode="after")
    def _scope(self) -> "OpportunityRequirement":
        if self.source_ref.organization_id != self.organization_id:
            raise ValueError("source_ref.organization_id must equal organization_id")
        return self


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------


class PolicyRuleKind(str, Enum):
    OPPORTUNITY_STATUS_ACTIVE = "opportunity_status_active"
    PROGRAM_PARTICIPATION_CONFIRMED = "program_participation_confirmed"
    AVAILABILITY_MEETS_REQUIRED_HOURS = "availability_meets_required_hours"
    MANDATORY_QUALIFICATION_EVIDENCED = "mandatory_qualification_evidenced"


class PolicyRule(ContractModel):
    rule_id: RuleId
    rule_version: Version
    kind: PolicyRuleKind
    program_id: ProgramId | None = None

    @model_validator(mode="after")
    def _params(self) -> "PolicyRule":
        needs_program = self.kind is PolicyRuleKind.PROGRAM_PARTICIPATION_CONFIRMED
        if needs_program != (self.program_id is not None):
            raise ValueError("program_id is required for, and only for, program participation rules")
        return self


class PolicySet(ContractModel):
    """Immutable versioned rule set. (id, version) identifies exactly one content + source version."""

    id: PolicySetId
    organization_id: OrganizationId
    version: Version
    source_ref: SourceReference
    program_id: ProgramId | None = None
    rules: Annotated[tuple[PolicyRule, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def _consistency(self) -> "PolicySet":
        if self.source_ref.organization_id != self.organization_id:
            raise ValueError("source_ref.organization_id must equal organization_id")
        ids = [r.rule_id for r in self.rules]
        if len(set(ids)) != len(ids):
            raise ValueError("rule_id values must be unique within a policy set")
        for rule in self.rules:
            if rule.program_id is not None and self.program_id is not None and rule.program_id != self.program_id:
                raise ValueError("a participation rule must name the policy's program")
        return self


class PolicyPin(ContractModel):
    policy_set_id: PolicySetId
    version: Version
    source_ref: SourceReference


# ---------------------------------------------------------------------------
# Outcomes and results
# ---------------------------------------------------------------------------


class RuleResult(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    UNKNOWN = "unknown"


#: Allowed reason codes per (rule kind, result). There are deliberately no
#: unknown codes for source-integrity or authorization failures, and no
#: unknown code for the active-status rule (open decision O1).
REASON_CODES: Mapping[PolicyRuleKind, Mapping[RuleResult, frozenset[str]]] = {
    PolicyRuleKind.OPPORTUNITY_STATUS_ACTIVE: {
        RuleResult.PASS: frozenset({"opportunity_active"}),
        RuleResult.FAIL: frozenset({"opportunity_paused", "opportunity_closed"}),
        RuleResult.UNKNOWN: frozenset(),
    },
    PolicyRuleKind.PROGRAM_PARTICIPATION_CONFIRMED: {
        RuleResult.PASS: frozenset({"participation_confirmed"}),
        RuleResult.FAIL: frozenset({"participation_not_participating"}),
        RuleResult.UNKNOWN: frozenset({"participation_not_recorded"}),
    },
    PolicyRuleKind.AVAILABILITY_MEETS_REQUIRED_HOURS: {
        RuleResult.PASS: frozenset({"availability_meets_required_hours"}),
        RuleResult.FAIL: frozenset({"availability_below_required_hours"}),
        RuleResult.UNKNOWN: frozenset(
            {"availability_not_declared", "availability_contested", "required_hours_not_published"}
        ),
    },
    PolicyRuleKind.MANDATORY_QUALIFICATION_EVIDENCED: {
        RuleResult.PASS: frozenset(
            {"qualification_declared", "qualification_independently_verified", "no_mandatory_qualification"}
        ),
        RuleResult.FAIL: frozenset(
            {"qualification_contradicted_by_declaration", "qualification_contradicted_by_verification"}
        ),
        RuleResult.UNKNOWN: frozenset(
            {"qualification_not_evidenced", "qualification_only_inferred", "qualification_contested"}
        ),
    },
}


def _reason_code_schema() -> dict:
    return {"allOf": [
        {"if": {"properties": {"rule_kind": {"const": kind.value}, "result": {"const": res.value}},
                "required": ["rule_kind", "result"]},
         "then": {"properties": {"reason_code": {"enum": sorted(codes)} if codes else {"not": {}}}}}
        for kind, by_result in REASON_CODES.items() for res, codes in by_result.items()
    ]}


class RuleOutcome(ContractModel):
    model_config = ConfigDict(extra="forbid", frozen=True, json_schema_extra=_reason_code_schema())

    rule_id: RuleId
    rule_version: Version
    rule_kind: PolicyRuleKind
    result: RuleResult
    reason_code: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")]
    claim_ids: tuple[ClaimIdRef, ...] = ()
    participation_ids: tuple[ParticipationId, ...] = ()
    requirement_ids: tuple[RequirementId, ...] = ()

    @model_validator(mode="after")
    def _reason(self) -> "RuleOutcome":
        if self.reason_code not in REASON_CODES[self.rule_kind][self.result]:
            raise ValueError(f"reason_code {self.reason_code!r} is not valid for {self.rule_kind.value}/{self.result.value}")
        for name in ("claim_ids", "participation_ids", "requirement_ids"):
            ids = getattr(self, name)
            if len(set(ids)) != len(ids):
                raise ValueError(f"{name} must be unique")
        return self


class EligibilityDecision(str, Enum):
    """Opportunity- and policy-version-scoped assessment. Never a candidate-level outcome."""

    ELIGIBLE = "eligible"
    INELIGIBLE = "ineligible"
    NEEDS_INFORMATION = "needs_information"


def derive_decision(outcomes: Iterable[RuleOutcome]) -> EligibilityDecision:
    results = {o.result for o in outcomes}
    if RuleResult.FAIL in results:
        return EligibilityDecision.INELIGIBLE
    if RuleResult.UNKNOWN in results:
        return EligibilityDecision.NEEDS_INFORMATION
    return EligibilityDecision.ELIGIBLE


class EligibilityResult(ContractModel):
    """Assessment of ONE candidate for ONE opportunity version under ONE pinned policy version.

    There is intentionally no candidate-level status, rejection, rank or score.
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        json_schema_extra={
            "allOf": [{
                "if": {"properties": {"rule_outcomes": {"contains": {"properties": {"result": {"const": "fail"}}}}}},
                "then": {"properties": {"decision": {"const": "ineligible"}}},
                "else": {
                    "if": {"properties": {"rule_outcomes": {"contains": {"properties": {"result": {"const": "unknown"}}}}}},
                    "then": {"properties": {"decision": {"const": "needs_information"}}},
                    "else": {"properties": {"decision": {"const": "eligible"}}},
                },
            }]
        },
    )

    id: EligibilityId
    organization_id: OrganizationId
    candidate_id: CandidateId
    opportunity_id: OpportunityId
    opportunity_ref: SourceReference
    policy: PolicyPin
    rule_outcomes: Annotated[tuple[RuleOutcome, ...], Field(min_length=1)]
    decision: EligibilityDecision
    evaluated_at: AwareDatetime
    evaluated_by: ComponentId

    @model_validator(mode="after")
    def _consistency(self) -> "EligibilityResult":
        for ref, name in ((self.opportunity_ref, "opportunity_ref"), (self.policy.source_ref, "policy.source_ref")):
            if ref.organization_id != self.organization_id:
                raise ValueError(f"{name}.organization_id must equal organization_id")
        ids = [o.rule_id for o in self.rule_outcomes]
        if len(set(ids)) != len(ids):
            raise ValueError("one outcome per rule")
        expected = derive_decision(self.rule_outcomes)
        if self.decision is not expected:
            raise ValueError(f"decision must be {expected.value} given the rule outcomes")
        return self


# ---------------------------------------------------------------------------
# Cross-record checks and outcome support verification
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EligibilityContext:
    """A complete record set for checking eligibility results."""

    records: ContractRecordSet
    policies: tuple[PolicySet, ...] = ()
    requirements: tuple[OpportunityRequirement, ...] = ()
    claims: tuple[CandidateClaim, ...] = ()
    participations: tuple[ProgramParticipation, ...] = ()
    evidence: Mapping[str, EvidenceRecord] = field(default_factory=dict)
    vocabularies: tuple[ClaimVocabulary, ...] = ()


def check_policy_sets(
    policies: Iterable[PolicySet],
    records: ContractRecordSet,
    capabilities: Mapping[SourceSystem, SourceSystemCapabilities],
    methods: SnapshotMethodRegistry = DEFAULT_SNAPSHOT_METHODS,
) -> None:
    programs = {p.id: p for p in records.programs}
    by_pin: dict[tuple[str, int], PolicySet] = {}
    by_source: dict[SourceReference, tuple[str, int]] = {}
    for pol in policies:
        check_version_kind(pol.source_ref, capabilities, methods)
        for prog_id in {pol.program_id, *(r.program_id for r in pol.rules)} - {None}:
            prog = programs.get(prog_id)
            if prog is None:
                raise ContractViolation("unknown_reference", f"policy {pol.id} references unknown program {prog_id}")
            if prog.organization_id != pol.organization_id:
                raise ContractViolation("cross_org_reference", f"policy {pol.id} references another organization's program")
        pin = (pol.id, pol.version)
        prior = by_pin.get(pin)
        if prior is not None and prior != pol:
            raise ContractViolation("policy_version_conflict", f"{pol.id} v{pol.version} has two different definitions")
        by_pin[pin] = pol
        other = by_source.get(pol.source_ref)
        if other is not None and other != pin:
            raise ContractViolation("policy_version_conflict", f"one source version backs {other} and {pin}")
        by_source[pol.source_ref] = pin


def check_requirements(
    ctx: EligibilityContext,
    capabilities: Mapping[SourceSystem, SourceSystemCapabilities],
    methods: SnapshotMethodRegistry = DEFAULT_SNAPSHOT_METHODS,
) -> None:
    opportunities = {o.id: o for o in ctx.records.opportunities}
    vocab_index = {(v.id, v.version): v for v in ctx.vocabularies}
    seen_ids, hours_for, quals_for = set(), defaultdict(int), defaultdict(set)
    for req in ctx.requirements:
        if req.id in seen_ids:
            raise ContractViolation("duplicate_id", f"duplicate requirement id {req.id}")
        seen_ids.add(req.id)
        opp = opportunities.get(req.opportunity_id)
        if opp is None:
            raise ContractViolation("unknown_reference", f"requirement {req.id} references unknown opportunity")
        if opp.organization_id != req.organization_id:
            raise ContractViolation("cross_org_reference", f"requirement {req.id} crosses organizations")
        check_version_kind(req.source_ref, capabilities, methods)
        from_opportunity = req.source_ref == opp.source_ref
        from_policy = any(
            req.source_ref == pol.source_ref and pol.organization_id == req.organization_id
            and (pol.program_id is None or pol.program_id == opp.program_id)
            for pol in ctx.policies
        )
        if not (from_opportunity or from_policy):
            raise ContractViolation(
                "requirement_source_mismatch",
                f"requirement {req.id} must come from the opportunity's exact source version or a covering policy",
            )
        spec = req.requirement
        if isinstance(spec, WeeklyHoursRequirement):
            hours_for[req.opportunity_id] += 1
            if hours_for[req.opportunity_id] > 1:
                raise ContractViolation("requirement_conflict", f"{req.opportunity_id} has more than one weekly_hours requirement")
        else:
            vocab = vocab_index.get((spec.vocabulary.id, spec.vocabulary.version))
            if vocab is None or vocab.organization_id != req.organization_id:
                raise ContractViolation("unknown_vocabulary", f"requirement {req.id} pins an unknown or foreign vocabulary")
            if spec.skill_code not in vocab.skills:
                raise ContractViolation("unsupported_claim_code", f"requirement {req.id}: {spec.skill_code} not in vocabulary")
            if spec.skill_code in quals_for[req.opportunity_id]:
                raise ContractViolation("duplicate_requirement", f"{req.opportunity_id} lists {spec.skill_code} twice")
            quals_for[req.opportunity_id].add(spec.skill_code)


def _unsupported(outcome: RuleOutcome, why: str) -> ContractViolation:
    return ContractViolation("unsupported_outcome", f"{outcome.rule_id} {outcome.result.value}/{outcome.reason_code}: {why}")


def check_eligibility_result(result: EligibilityResult, ctx: EligibilityContext) -> None:
    candidates = {c.id: c for c in ctx.records.candidates}
    opportunities = {o.id: o for o in ctx.records.opportunities}
    cand, opp = candidates.get(result.candidate_id), opportunities.get(result.opportunity_id)
    if cand is None or opp is None:
        raise ContractViolation("unknown_reference", f"{result.id} references unknown candidate/opportunity")
    if not (cand.organization_id == opp.organization_id == result.organization_id):
        raise ContractViolation("cross_org_reference", f"{result.id} crosses organizations")
    if result.opportunity_ref != opp.source_ref:
        raise ContractViolation("opportunity_version_mismatch", f"{result.id} does not pin the opportunity's version")

    policy = next(
        (p for p in ctx.policies if p.id == result.policy.policy_set_id and p.version == result.policy.version), None
    )
    if policy is None or policy.source_ref != result.policy.source_ref:
        raise ContractViolation("policy_version_mismatch", f"{result.id} pins a policy version that does not match")
    if policy.organization_id != result.organization_id:
        raise ContractViolation("cross_org_reference", f"{result.id} uses another organization's policy")
    if policy.program_id is not None and opp.program_id != policy.program_id:
        raise ContractViolation("policy_scope_mismatch", f"{policy.id} does not cover {opp.id}")
    rules = {(r.rule_id, r.rule_version, r.kind): r for r in policy.rules}
    outcome_keys = {(o.rule_id, o.rule_version, o.rule_kind) for o in result.rule_outcomes}
    if outcome_keys != set(rules):
        raise ContractViolation("rule_set_mismatch", f"{result.id} outcomes do not match {policy.id} v{policy.version} rules")

    claims = {c.id: c for c in ctx.claims}
    parts = {p.id: p for p in ctx.participations}
    reqs = {r.id: r for r in ctx.requirements}
    opp_reqs = [r for r in ctx.requirements if r.opportunity_id == opp.id]
    cand_claims = [c for c in ctx.claims if c.candidate_id == cand.id]

    for outcome in result.rule_outcomes:
        cited_claims, cited_parts, cited_reqs = [], [], []
        for cid in outcome.claim_ids:
            c = claims.get(cid)
            if c is None or c.candidate_id != cand.id or c.organization_id != result.organization_id:
                raise ContractViolation("invalid_citation", f"{outcome.rule_id} cites claim {cid} not about {cand.id}")
            cited_claims.append(c)
        for pid in outcome.participation_ids:
            p = parts.get(pid)
            if p is None or p.candidate_id != cand.id or p.organization_id != result.organization_id:
                raise ContractViolation("invalid_citation", f"{outcome.rule_id} cites participation {pid} not about {cand.id}")
            cited_parts.append(p)
        for rid in outcome.requirement_ids:
            r = reqs.get(rid)
            if r is None or r.opportunity_id != opp.id:
                raise ContractViolation("invalid_citation", f"{outcome.rule_id} cites requirement {rid} not about {opp.id}")
            cited_reqs.append(r)
        if outcome.result is not RuleResult.UNKNOWN and any(c.state is not ClaimState.DECLARED for c in cited_claims):
            raise ContractViolation(
                "non_authoritative_input",
                f"{outcome.rule_id}: pass/fail may cite only declared claims (inferred/unknown/contested are not facts)",
            )
        _verify_support(outcome, rules[(outcome.rule_id, outcome.rule_version, outcome.rule_kind)], opp,
                        cand.id, cited_claims, cited_parts, cited_reqs, opp_reqs, cand_claims, ctx)


def _has_basis(claim: CandidateClaim, basis: EvidenceBasis, evidence: Mapping[str, EvidenceRecord]) -> bool:
    return any(evidence[e].basis is basis for e in claim.all_evidence_ids() if e in evidence)


def _verify_support(outcome, rule, opp, candidate_id, cited_claims, cited_parts, cited_reqs, opp_reqs, cand_claims, ctx):
    kind, res, code = outcome.rule_kind, outcome.result, outcome.reason_code

    if kind is PolicyRuleKind.OPPORTUNITY_STATUS_ACTIVE:
        if cited_claims or cited_parts or cited_reqs:
            raise _unsupported(outcome, "the active-status rule reads only the pinned opportunity")
        expected = {OpportunityStatus.ACTIVE: "opportunity_active", OpportunityStatus.PAUSED: "opportunity_paused",
                    OpportunityStatus.CLOSED: "opportunity_closed"}[opp.status]
        if code != expected:
            raise _unsupported(outcome, f"pinned opportunity status is {opp.status.value}")
        return

    if kind is PolicyRuleKind.PROGRAM_PARTICIPATION_CONFIRMED:
        if cited_claims or cited_reqs:
            raise _unsupported(outcome, "participation is an authoritative record, not a claim")
        relevant = [p for p in ctx.participations if p.candidate_id == candidate_id and p.program_id == rule.program_id]
        if res is RuleResult.UNKNOWN:
            if cited_parts or relevant:
                raise _unsupported(outcome, "a participation record exists")
            return
        want = ProgramParticipationStatus.CONFIRMED if res is RuleResult.PASS else ProgramParticipationStatus.NOT_PARTICIPATING
        if not cited_parts or any(p.program_id != rule.program_id or p.status is not want for p in cited_parts):
            raise _unsupported(outcome, f"requires cited {want.value} records for {rule.program_id}")
        return

    if kind is PolicyRuleKind.AVAILABILITY_MEETS_REQUIRED_HOURS:
        hours_reqs = [r for r in opp_reqs if isinstance(r.requirement, WeeklyHoursRequirement)]
        declared = [c for c in cand_claims if c.claim_type is ClaimType.AVAILABILITY and c.state is ClaimState.DECLARED]
        if any(c.claim_type is not ClaimType.AVAILABILITY for c in cited_claims) or any(
            not isinstance(r.requirement, WeeklyHoursRequirement) for r in cited_reqs
        ) or cited_parts:
            raise _unsupported(outcome, "cites inputs unrelated to availability")
        if res is RuleResult.UNKNOWN:
            if code == "required_hours_not_published":
                if hours_reqs or cited_reqs:
                    raise _unsupported(outcome, "a weekly_hours requirement is published")
            elif code == "availability_not_declared":
                if declared or any(c.state is ClaimState.CONTESTED for c in cited_claims):
                    raise _unsupported(outcome, "a declared or contested availability exists")
            elif code == "availability_contested":
                if declared or not any(c.state is ClaimState.CONTESTED for c in cited_claims):
                    raise _unsupported(outcome, "requires a cited contested availability claim and no declared value")
            return
        if len(cited_reqs) != 1 or cited_reqs != hours_reqs or not cited_claims:
            raise _unsupported(outcome, "pass/fail cites the published weekly_hours requirement and declared availability")
        hours = {c.value.hours_per_week for c in cited_claims}
        if len(hours) != 1:
            raise _unsupported(outcome, "cited availability claims disagree")
        meets = hours.pop() >= cited_reqs[0].requirement.hours_per_week
        if meets != (res is RuleResult.PASS):
            raise _unsupported(outcome, "declared hours do not support this result")
        return

    # MANDATORY_QUALIFICATION_EVIDENCED
    qual_reqs = [r for r in opp_reqs if isinstance(r.requirement, MandatoryQualificationRequirement)]
    if cited_parts or any(c.claim_type is not ClaimType.SKILL for c in cited_claims) or any(
        r not in qual_reqs for r in cited_reqs
    ):
        raise _unsupported(outcome, "cites inputs unrelated to mandatory qualifications")
    codes = {r.requirement.skill_code for r in cited_reqs}
    if any(c.subject_code not in codes for c in cited_claims):
        raise _unsupported(outcome, "cites a skill claim for a code the cited requirements do not name")

    if code == "no_mandatory_qualification":
        if qual_reqs or cited_reqs or cited_claims:
            raise _unsupported(outcome, "the opportunity publishes mandatory qualifications")
        return
    if not cited_reqs:
        raise _unsupported(outcome, "must cite the mandatory qualification requirement(s) it evaluates")

    if res is RuleResult.PASS:
        if set(cited_reqs) != set(qual_reqs):
            raise _unsupported(outcome, "pass must cover every mandatory qualification")
        for req in qual_reqs:
            support = [c for c in cited_claims if c.subject_code == req.requirement.skill_code and c.value.presence == "has"]
            if not support:
                raise _unsupported(outcome, f"no declared 'has' claim for {req.requirement.skill_code}")
            if code == "qualification_independently_verified" and not any(
                _has_basis(c, EvidenceBasis.INDEPENDENT_VERIFICATION, ctx.evidence) for c in support
            ):
                raise _unsupported(outcome, f"{req.requirement.skill_code} is declared, not independently verified")
        if any(c.value.presence != "has" for c in cited_claims):
            raise _unsupported(outcome, "pass cannot cite contradicting claims")
        return

    if res is RuleResult.FAIL:
        # Only explicit, source-backed contradiction supports failure. Absence never does.
        if not cited_claims or any(c.value.presence != "lacks" for c in cited_claims):
            raise _unsupported(outcome, "fail requires cited declared 'lacks' claims (absence is not contradiction)")
        basis = (EvidenceBasis.INDEPENDENT_VERIFICATION if code == "qualification_contradicted_by_verification"
                 else EvidenceBasis.CANDIDATE_STATEMENT)
        if not all(_has_basis(c, basis, ctx.evidence) for c in cited_claims):
            raise _unsupported(outcome, f"contradicting claims are not backed by {basis.value} evidence")
        return

    # UNKNOWN
    def states_for(skill_code: str) -> set:
        return {c.state for c in cand_claims if c.claim_type is ClaimType.SKILL and c.subject_code == skill_code}

    if code == "qualification_contested":
        if not any(c.state is ClaimState.CONTESTED for c in cited_claims):
            raise _unsupported(outcome, "requires a cited contested skill claim")
    elif code == "qualification_only_inferred":
        inferred_codes = {c.subject_code for c in cited_claims if c.state is ClaimState.INFERRED}
        if not any(states_for(sc) == {ClaimState.INFERRED} for sc in inferred_codes):
            raise _unsupported(outcome, "requires a cited inferred claim for a code with no source-backed claim")
    else:  # qualification_not_evidenced
        if not any(not (states_for(sc) & {ClaimState.DECLARED, ClaimState.CONTESTED}) for sc in codes):
            raise _unsupported(outcome, "every cited qualification has a source-backed claim")
        if any(c.state in (ClaimState.DECLARED, ClaimState.CONTESTED) for c in cited_claims):
            raise _unsupported(outcome, "cites source-backed claims while asserting no evidence")


def check_eligibility_results(results: Iterable[EligibilityResult], ctx: EligibilityContext) -> None:
    """Each result is checked independently; one result per (candidate, opportunity, policy version)."""
    seen_ids, seen_keys = set(), {}
    for res in results:
        if res.id in seen_ids:
            raise ContractViolation("duplicate_id", f"duplicate eligibility id {res.id}")
        seen_ids.add(res.id)
        key = (res.candidate_id, res.opportunity_id, res.policy.policy_set_id, res.policy.version)
        if key in seen_keys:
            raise ContractViolation(
                "conflicting_results" if seen_keys[key] != res.decision else "duplicate_result",
                f"more than one result for {key}",
            )
        seen_keys[key] = res.decision
        check_eligibility_result(res, ctx)


def eligibility_source_refs(result: EligibilityResult, ctx: EligibilityContext) -> list[SourceReference]:
    """Every source version a result depends on, for the fail-closed gate before processing."""
    claims = {c.id: c for c in ctx.claims}
    parts = {p.id: p for p in ctx.participations}
    reqs = {r.id: r for r in ctx.requirements}
    refs = [result.opportunity_ref, result.policy.source_ref]
    for outcome in result.rule_outcomes:
        refs += [reqs[r].source_ref for r in outcome.requirement_ids]
        evidence_ids = [e for c in outcome.claim_ids for e in claims[c].all_evidence_ids()]
        evidence_ids += [e for p in outcome.participation_ids for e in parts[p].evidence_ids]
        refs += [ctx.evidence[e].source_ref for e in evidence_ids]
    return refs
