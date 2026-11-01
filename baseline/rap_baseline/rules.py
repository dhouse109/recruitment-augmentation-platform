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

from rap_contracts.claims import CandidateClaim, ClaimState, ClaimType, ProgramParticipation, ProgramParticipationStatus
from rap_contracts.eligibility import (
    MandatoryQualificationRequirement,
    OpportunityRequirement,
    PolicyRule,
    PolicyRuleKind,
    RuleOutcome,
    RuleResult,
    WeeklyHoursRequirement,
    derive_decision,
)
from rap_contracts.evidence import EvidenceBasis
from rap_contracts.models import OpportunityStatus

from .findings import (
    Contribution,
    EvidenceAttribution,
    FindingsContent,
    RequirementAttribution,
    RuleFindings,
    SubjectFinding,
)
from .identity import DecisionInputs, normalize_ref

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


# --- PR-S2: structured findings (one pass over the same DecisionInputs) --------
#
# ``build_findings`` runs AFTER ``evaluate`` (P12) over the identical frozen
# ``DecisionInputs`` and the produced outcomes. It does not dispatch through
# ``EVALUATORS`` and does not call ``claims.values_conflict``, so every existing
# fault-injection point keeps its behavior. Its output is never trusted: the
# independent verifier (``findings_check``, L1) recomputes everything from the
# admitted projection.

FINDINGS_POLICY_VERSION = "findings/1"

_PASS_STATUSES = frozenset({"active", "confirmed", "meets", "satisfied_verified", "satisfied_declared", "none_required"})
_GAPS = {
    "not_declared": "no_source_backed_value",
    "not_evidenced": "no_source_backed_value",
    "only_inferred": "only_inferred_signal",
    "contested": "conflicting_sources",
    "hours_not_published": "opportunity_requirement_unpublished",
    "not_recorded": "no_participation_record",
}


def _requirement_attribution(req: OpportunityRequirement) -> RequirementAttribution:
    return RequirementAttribution(requirement_id=req.id, source_ref=normalize_ref(req.source_ref), field_path=req.field_path)


def _attribution(d: DecisionInputs, evidence_id: str, relation: str, index=None, alt_value=None) -> EvidenceAttribution:
    ev = d.evidence[evidence_id]
    reading = reading_hours = None
    if alt_value is not None:
        if alt_value.kind == "skill":
            reading = alt_value.presence
        elif alt_value.kind == "availability":
            reading_hours = alt_value.hours_per_week
    return EvidenceAttribution(evidence_id=evidence_id, basis=ev.basis.value, relation=relation,
                               source_ref=normalize_ref(ev.source_ref), field_path=ev.field_path,
                               alternative_index=index, reading=reading, reading_hours=reading_hours)


def _sorted_attributions(items) -> tuple[EvidenceAttribution, ...]:
    return tuple(sorted(items, key=lambda a: (-1 if a.alternative_index is None else a.alternative_index, a.evidence_id)))


def _claim_contribution(c: CandidateClaim, role: str, d: DecisionInputs) -> Contribution:
    reading = reading_hours = None
    if c.state is ClaimState.CONTESTED:
        attributions = [_attribution(d, e, "alternative_support", i, alt.value)
                        for i, alt in enumerate(c.alternatives) for e in alt.evidence_ids]
    elif c.state is ClaimState.INFERRED:
        attributions = [_attribution(d, e, "inference_input") for e in c.evidence_ids]
    else:
        attributions = [_attribution(d, e, "support") for e in c.all_evidence_ids()]
    if c.state in (ClaimState.DECLARED, ClaimState.INFERRED):
        if c.claim_type is ClaimType.SKILL:
            reading = c.value.presence
        elif c.claim_type is ClaimType.AVAILABILITY:
            reading_hours = c.value.hours_per_week
    return Contribution(input_kind="claim", input_id=c.id, role=role, claim_state=c.state.value,
                        rule_standing="decision_input" if c.state is ClaimState.DECLARED else "non_decision_input",
                        reading=reading, reading_hours=reading_hours, inferred_by=c.inferred_by,
                        evidence=_sorted_attributions(attributions))


def _participation_contribution(p, role: str, d: DecisionInputs) -> Contribution:
    return Contribution(input_kind="participation", input_id=p.id, role=role, claim_state=None,
                        rule_standing="decision_input", reading=p.status.value, reading_hours=None, inferred_by=None,
                        evidence=_sorted_attributions(_attribution(d, e, "authority_record") for e in p.evidence_ids))


def _subject(kind: str, status: str, role: str, inputs: Iterable, det_ids: set, cited: set, d: DecisionInputs, *,
             requirement=None, program_id=None, skill_code=None, declared_hours=None, required_hours=None) -> SubjectFinding:
    passing = status in _PASS_STATUSES
    contributions = []
    for item in sorted(inputs, key=lambda x: x.id):
        if item.id in cited:
            c_role = "cited"
        elif item.id in det_ids:
            c_role = "uncited_satisfying" if passing else "uncited_material"
        else:
            c_role = "context"
        contributions.append(_participation_contribution(item, c_role, d) if isinstance(item, ProgramParticipation)
                             else _claim_contribution(item, c_role, d))
    return SubjectFinding(kind=kind, program_id=program_id, skill_code=skill_code,
                          requirement=None if requirement is None else _requirement_attribution(requirement),
                          subject_status=status, subject_role=role, information_gap=_GAPS.get(status),
                          declared_hours=declared_hours, required_hours=required_hours,
                          contributions=tuple(contributions))


def _f_active(rule: PolicyRule, d: DecisionInputs, o: RuleOutcome, cited: set) -> tuple[SubjectFinding, ...]:
    return (_subject("opportunity_status", d.opportunity.status.value, "decisive", (), set(), cited, d),)


def _f_participation(rule: PolicyRule, d: DecisionInputs, o: RuleOutcome, cited: set) -> tuple[SubjectFinding, ...]:
    rel = [p for p in d.participations if p.program_id == rule.program_id and p.candidate_id == d.candidate_id]
    statuses = {p.status for p in rel}
    if not rel:
        status = "not_recorded"
    elif statuses == {ProgramParticipationStatus.CONFIRMED}:
        status = "confirmed"
    elif statuses == {ProgramParticipationStatus.NOT_PARTICIPATING}:
        status = "not_participating"
    else:
        raise RuleEvaluationError("conflicting participation records reached the findings")
    return (_subject("program_participation", status, "decisive", rel, {p.id for p in rel}, cited, d,
                     program_id=rule.program_id),)


def _f_availability(rule: PolicyRule, d: DecisionInputs, o: RuleOutcome, cited: set) -> tuple[SubjectFinding, ...]:
    hours_reqs = [r for r in d.requirements if isinstance(r.requirement, WeeklyHoursRequirement)]
    rel = [c for c in d.claims if c.claim_type is ClaimType.AVAILABILITY and c.candidate_id == d.candidate_id]
    declared = [c for c in rel if c.state is ClaimState.DECLARED]
    non_declared = [c for c in rel if c.state is not ClaimState.DECLARED]
    if len(hours_reqs) > 1:
        raise RuleEvaluationError("more than one weekly_hours requirement reached the findings")
    req = hours_reqs[0] if hours_reqs else None
    required = None if req is None else req.requirement.hours_per_week
    declared_hours = None
    if req is None:
        status, det = "hours_not_published", []
    elif any(c.state is ClaimState.CONTESTED for c in rel):
        status, det = "contested", non_declared
    elif not declared:
        status, det = "not_declared", non_declared
    else:
        values = {c.value.hours_per_week for c in declared}
        if len(values) != 1:
            raise RuleEvaluationError("conflicting declared availability reached the findings")
        declared_hours = values.pop()
        status, det = ("meets" if declared_hours >= required else "below"), declared
    return (_subject("weekly_hours", status, "decisive", rel, {c.id for c in det}, cited, d, requirement=req,
                     declared_hours=declared_hours, required_hours=required),)


def _f_qualification(rule: PolicyRule, d: DecisionInputs, o: RuleOutcome, cited: set) -> tuple[SubjectFinding, ...]:
    qual_reqs = sorted((r for r in d.requirements if isinstance(r.requirement, MandatoryQualificationRequirement)),
                       key=lambda r: r.id)
    if not qual_reqs:
        return (_subject("no_mandatory_qualification", "none_required", "decisive", (), set(), cited, d),)
    skill_claims = [c for c in d.claims if c.claim_type is ClaimType.SKILL and c.candidate_id == d.candidate_id]
    out = []
    for req in qual_reqs:
        code = req.requirement.skill_code
        rel = [c for c in skill_claims if c.subject_code == code]
        declared = [c for c in rel if c.state is ClaimState.DECLARED]
        state = _classify(rel)
        backed = any(_verified(c, d) for c in declared)
        status = {
            Qual.HAS: "satisfied_verified" if backed else "satisfied_declared",
            Qual.LACKS: "contradicted_verified" if backed else "contradicted_declared",
            Qual.CONTESTED: "contested",
            Qual.INFERRED_ONLY: "only_inferred",
            Qual.NONE: "not_evidenced",
        }[state]
        det = declared if state in (Qual.HAS, Qual.LACKS) else [c for c in rel if c.state is not ClaimState.DECLARED]
        if req.id in o.requirement_ids:
            role = "decisive"
        else:
            role = "uncited_satisfied" if status in _PASS_STATUSES else "uncited_nonpass"
        out.append(_subject("qualification", status, role, rel, {c.id for c in det}, cited, d, requirement=req,
                            skill_code=code))
    return tuple(out)


FINDERS: dict[PolicyRuleKind, Callable[[PolicyRule, DecisionInputs, RuleOutcome, set], tuple[SubjectFinding, ...]]] = {
    PolicyRuleKind.OPPORTUNITY_STATUS_ACTIVE: _f_active,
    PolicyRuleKind.PROGRAM_PARTICIPATION_CONFIRMED: _f_participation,
    PolicyRuleKind.AVAILABILITY_MEETS_REQUIRED_HOURS: _f_availability,
    PolicyRuleKind.MANDATORY_QUALIFICATION_EVIDENCED: _f_qualification,
}


def build_findings(d: DecisionInputs, outcomes: tuple[RuleOutcome, ...]) -> FindingsContent:
    """Findings content for the produced outcomes: a pure function of ``d`` and the outcomes' citations."""
    if len(outcomes) != len(d.policy.rules):
        raise RuleEvaluationError("outcomes do not align with the policy rules")
    rule_findings = []
    for rule, o in zip(d.policy.rules, outcomes):
        if (o.rule_id, o.rule_version, o.rule_kind) != (rule.rule_id, rule.rule_version, rule.kind):
            raise RuleEvaluationError("outcomes do not align with the policy rules")
        cited = set(o.claim_ids) | set(o.participation_ids)
        rule_findings.append(RuleFindings(rule_id=rule.rule_id, rule_version=rule.rule_version, rule_kind=rule.kind.value,
                                          result=o.result.value, reason_code=o.reason_code,
                                          subjects=FINDERS[rule.kind](rule, d, o, cited)))
    return FindingsContent(
        organization_id=d.organization_id, candidate_id=d.candidate_id, opportunity_id=d.opportunity.id,
        opportunity_ref=normalize_ref(d.opportunity.source_ref), policy_id=d.policy.id, policy_version=d.policy.version,
        policy_ref=normalize_ref(d.policy.source_ref), decision=derive_decision(outcomes).value,
        rules=tuple(rule_findings))
