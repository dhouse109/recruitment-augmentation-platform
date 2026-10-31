"""Deterministic rule evaluators: approved SD-4 precedence and SD-5 citation policy.

The only module that reads claim values, claim states, contested alternatives,
participation statuses, opportunity status and required hours. It receives a
``DecisionInputs`` only, after the source gate and phase-2 validation.

SD-5 citation policy: (a) pass/fail cite every authoritative input of the
decisive state plus the requirement(s) compared; (b) unknown cites every
non-declared claim of the undetermined key(s) plus, for qualifications, the
undetermined requirements; (c) never cite a satisfied key's records in a
non-pass outcome, never cite a non-declared claim in pass/fail; (d) sorted ids.

Known limitation G12 (SD-18, approved for PR-S1 only): when one mandatory
qualification is contradicted by verification and another only by
self-declaration, the outcome is ``qualification_contradicted_by_verification``
citing only the verification-backed contradiction. The declaration-backed
contradiction is omitted from the citations. A result is therefore NOT an
exhaustive account of every failed qualification and is not sufficient for
reviewer-facing explanations.
"""

from __future__ import annotations

from enum import Enum
from typing import Callable, Iterable

from rap_contracts.claims import CandidateClaim, ClaimState, ClaimType, ProgramParticipationStatus
from rap_contracts.eligibility import (
    MandatoryQualificationRequirement,
    OpportunityRequirement,
    PolicyRule,
    PolicyRuleKind,
    RuleOutcome,
    RuleResult,
    WeeklyHoursRequirement,
)
from rap_contracts.evidence import EvidenceBasis
from rap_contracts.models import OpportunityStatus

from .identity import DecisionInputs

RULE_TABLE_VERSION = "sd4-precedence/1"
CITATION_POLICY_VERSION = "sd5-citations/1"


class RuleEvaluationError(RuntimeError):
    """An input state the phase-2 validators should have refused reached the rules (engine defect)."""


def _outcome(rule: PolicyRule, result: RuleResult, reason: str, claims: Iterable[CandidateClaim] = (),
             participations: Iterable = (), requirements: Iterable[OpportunityRequirement] = ()) -> RuleOutcome:
    return RuleOutcome(
        rule_id=rule.rule_id, rule_version=rule.rule_version, rule_kind=rule.kind, result=result, reason_code=reason,
        claim_ids=tuple(sorted({c.id for c in claims})),
        participation_ids=tuple(sorted({p.id for p in participations})),
        requirement_ids=tuple(sorted({r.id for r in requirements})),
    )


# --- opportunity_status_active (O1: pass/fail only) -------------------------

_STATUS = {
    OpportunityStatus.ACTIVE: (RuleResult.PASS, "opportunity_active"),
    OpportunityStatus.PAUSED: (RuleResult.FAIL, "opportunity_paused"),
    OpportunityStatus.CLOSED: (RuleResult.FAIL, "opportunity_closed"),
}


def _active(rule: PolicyRule, d: DecisionInputs) -> RuleOutcome:
    result, reason = _STATUS[d.opportunity.status]
    return _outcome(rule, result, reason)


# --- program_participation_confirmed ----------------------------------------


def _participation(rule: PolicyRule, d: DecisionInputs) -> RuleOutcome:
    records = [p for p in d.participations if p.program_id == rule.program_id and p.candidate_id == d.candidate_id]
    if not records:
        return _outcome(rule, RuleResult.UNKNOWN, "participation_not_recorded")
    statuses = {p.status for p in records}
    if statuses == {ProgramParticipationStatus.CONFIRMED}:
        return _outcome(rule, RuleResult.PASS, "participation_confirmed", participations=records)
    if statuses == {ProgramParticipationStatus.NOT_PARTICIPATING}:
        return _outcome(rule, RuleResult.FAIL, "participation_not_participating", participations=records)
    raise RuleEvaluationError("conflicting participation records reached the rules")


# --- availability_meets_required_hours ---------------------------------------


def _availability(rule: PolicyRule, d: DecisionInputs) -> RuleOutcome:
    hours_reqs = [r for r in d.requirements if isinstance(r.requirement, WeeklyHoursRequirement)]
    claims = [c for c in d.claims if c.claim_type is ClaimType.AVAILABILITY and c.candidate_id == d.candidate_id]
    declared = [c for c in claims if c.state is ClaimState.DECLARED]
    non_declared = [c for c in claims if c.state is not ClaimState.DECLARED]
    if not hours_reqs:                                                     # row 1
        return _outcome(rule, RuleResult.UNKNOWN, "required_hours_not_published")
    if len(hours_reqs) > 1:
        raise RuleEvaluationError("more than one weekly_hours requirement reached the rules")
    if any(c.state is ClaimState.CONTESTED for c in claims):              # row 2
        return _outcome(rule, RuleResult.UNKNOWN, "availability_contested", claims=non_declared)
    if not declared:                                                       # row 3
        return _outcome(rule, RuleResult.UNKNOWN, "availability_not_declared", claims=non_declared)
    hours = {c.value.hours_per_week for c in declared}                     # row 4
    if len(hours) != 1:
        raise RuleEvaluationError("conflicting declared availability reached the rules")
    required = hours_reqs[0].requirement.hours_per_week
    if hours.pop() >= required:
        return _outcome(rule, RuleResult.PASS, "availability_meets_required_hours", claims=declared, requirements=hours_reqs)
    return _outcome(rule, RuleResult.FAIL, "availability_below_required_hours", claims=declared, requirements=hours_reqs)


# --- mandatory_qualification_evidenced ---------------------------------------


class Qual(str, Enum):
    HAS = "has"
    LACKS = "lacks"
    CONTESTED = "contested"
    INFERRED_ONLY = "inferred_only"
    NONE = "none"


def _verified(claim: CandidateClaim, d: DecisionInputs) -> bool:
    return any(d.evidence[e].basis is EvidenceBasis.INDEPENDENT_VERIFICATION for e in claim.all_evidence_ids())


def _classify(claims: list[CandidateClaim]) -> Qual:
    declared = [c for c in claims if c.state is ClaimState.DECLARED]
    if declared:
        presences = {c.value.presence for c in declared}
        if len(presences) != 1:
            raise RuleEvaluationError("conflicting declared skill claims reached the rules")
        return Qual.HAS if presences == {"has"} else Qual.LACKS
    if any(c.state is ClaimState.CONTESTED for c in claims):
        return Qual.CONTESTED
    if claims and all(c.state is ClaimState.INFERRED for c in claims):
        return Qual.INFERRED_ONLY
    return Qual.NONE


def _qualification(rule: PolicyRule, d: DecisionInputs) -> RuleOutcome:
    qual_reqs = sorted((r for r in d.requirements if isinstance(r.requirement, MandatoryQualificationRequirement)),
                       key=lambda r: r.id)
    if not qual_reqs:                                                      # row 0
        return _outcome(rule, RuleResult.PASS, "no_mandatory_qualification")
    skill_claims = [c for c in d.claims if c.claim_type is ClaimType.SKILL and c.candidate_id == d.candidate_id]
    by_code = {r.requirement.skill_code: [c for c in skill_claims if c.subject_code == r.requirement.skill_code]
               for r in qual_reqs}
    state = {code: _classify(claims) for code, claims in by_code.items()}
    reqs_for = lambda codes: [r for r in qual_reqs if r.requirement.skill_code in codes]  # noqa: E731

    lacks_codes = [code for code, s in state.items() if s is Qual.LACKS]
    if lacks_codes:                                                        # rows 1-2
        lacks_claims = [c for code in lacks_codes for c in by_code[code] if c.state is ClaimState.DECLARED]
        verified = [c for c in lacks_claims if _verified(c, d)]
        if verified:
            cited, reason = verified, "qualification_contradicted_by_verification"
        else:
            cited, reason = lacks_claims, "qualification_contradicted_by_declaration"
        return _outcome(rule, RuleResult.FAIL, reason, claims=cited,
                        requirements=reqs_for({c.subject_code for c in cited}))

    undetermined = [code for code, s in state.items() if s is not Qual.HAS]
    if undetermined:                                                       # rows 3-5
        states = {state[code] for code in undetermined}
        if Qual.CONTESTED in states:
            reason = "qualification_contested"
        elif Qual.INFERRED_ONLY in states:
            reason = "qualification_only_inferred"
        else:
            reason = "qualification_not_evidenced"
        cited = [c for code in undetermined for c in by_code[code] if c.state is not ClaimState.DECLARED]
        return _outcome(rule, RuleResult.UNKNOWN, reason, claims=cited, requirements=reqs_for(set(undetermined)))

    declared = [c for code in by_code for c in by_code[code] if c.state is ClaimState.DECLARED]  # rows 6-7
    every_code_verified = all(any(_verified(c, d) for c in by_code[code] if c.state is ClaimState.DECLARED)
                              for code in by_code)
    reason = "qualification_independently_verified" if every_code_verified else "qualification_declared"
    return _outcome(rule, RuleResult.PASS, reason, claims=declared, requirements=qual_reqs)


EVALUATORS: dict[PolicyRuleKind, Callable[[PolicyRule, DecisionInputs], RuleOutcome]] = {
    PolicyRuleKind.OPPORTUNITY_STATUS_ACTIVE: _active,
    PolicyRuleKind.PROGRAM_PARTICIPATION_CONFIRMED: _participation,
    PolicyRuleKind.AVAILABILITY_MEETS_REQUIRED_HOURS: _availability,
    PolicyRuleKind.MANDATORY_QUALIFICATION_EVIDENCED: _qualification,
}


def evaluate(d: DecisionInputs) -> tuple[RuleOutcome, ...]:
    """One outcome per policy rule, in policy order. Unsupported kinds cannot exist (closed enum)."""
    return tuple(EVALUATORS[rule.kind](rule, d) for rule in d.policy.rules)
