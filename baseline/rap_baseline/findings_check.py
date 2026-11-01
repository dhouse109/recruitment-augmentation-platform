"""L1: independent verification of structured findings (PR-S2, P13).

``verify_findings(fa, result, projected, prov)`` re-derives everything from raw
records in the ADMITTED projection (the object the source gate admitted and
phase-2 validation accepted) and compares. It never trusts a classification,
role or header value carried by the findings artifact.

Step 1 -- trusted header. The input fingerprint, output digest and result id are
recomputed with ``identity`` (the definition of those identities; it is not a
classification), from the admitted projection, the result and the engine-held
``EngineIdentity`` the fingerprint covers. The engine-held P11 provenance must
agree with the recomputed values, and only then is the artifact header compared
with them. The gated reference set is taken from that provenance.

(Implementation note, deferred technical debt TD-1: the engine identity is passed in rather than rebuilt from the
provenance's version fields, because PR-S1 provenance records the rule-table and
citation versions from ``rules`` constants while the fingerprint covers
``engine.ENGINE``; PR-S1's own test of engine identity changes only the latter.)

Step 2 -- exact SD-4 precedence and SD-5 citations (I7). Each subject's status is
recomputed, the exact ``(result, reason_code)`` and the exact cited claim,
participation and requirement sets follow from the statuses, and they must EQUAL
the ``EligibilityResult``. A supportable but precedence-incorrect result fails.

Steps 3-5 -- scope (I9), provenance closure (I10: the artifact's source references
equal the gated set) and accounting (I1-I6, I8: subject partition, requirement,
contribution and evidence coverage, roles, standing, relations, gaps).

Independence is code-level: this module imports no ``rap_baseline.rules``,
``engine``, ``inputs`` or ``selection_check`` (import-scanned), and makes no
authority call. It is written separately from the producer, by the same author;
its discriminating power is shown by failure-first mutations, not assumed.
"""

from __future__ import annotations

import dataclasses
from typing import Any, Iterable

from rap_contracts.claims import ClaimState, ClaimType, ProgramParticipation, ProgramParticipationStatus
from rap_contracts.eligibility import PolicyRuleKind, RuleResult, derive_decision
from rap_contracts.evidence import EvidenceBasis

from . import identity
from .findings import (
    Contribution,
    EvidenceAttribution,
    FindingsArtifact,
    FindingsContent,
    RequirementAttribution,
    RuleFindings,
    SubjectFinding,
)

#: Pinned versions this verifier implements. Any other value is rejected.
ACCEPTED_FINDINGS_PRODUCER = "rap-baseline.findings/0.1.0"
ACCEPTED_FINDINGS_POLICY = "findings/1"
_CONTENT_DIGEST_VERSION = "rap-baseline.findings-content/1"
_FINDINGS_ID_VERSION = "rap-baseline.findings-id/1"

_VERIFIED = EvidenceBasis.INDEPENDENT_VERIFICATION
_PASSING = {"active", "confirmed", "meets", "satisfied_verified", "satisfied_declared", "none_required"}
_GAP = {"not_declared": "no_source_backed_value", "not_evidenced": "no_source_backed_value",
        "only_inferred": "only_inferred_signal", "contested": "conflicting_sources",
        "hours_not_published": "opportunity_requirement_unpublished", "not_recorded": "no_participation_record"}


class FindingsMismatch(Exception):
    """Findings, result and provenance disagree with the admitted projection. ``subcode`` names the invariant class."""

    def __init__(self, subcode: str, detail: str) -> None:
        super().__init__(f"{subcode}: {detail}")
        self.subcode = subcode


def _fail(subcode: str, detail: str):
    raise FindingsMismatch(subcode, detail)


# --- step 1: trusted header -----------------------------------------------------


def _plain(obj: Any) -> Any:
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: _plain(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, (list, tuple)):
        return [_plain(x) for x in obj]
    return obj


def _trusted_header(fa: FindingsArtifact, result, projected, prov, engine_identity):
    if not isinstance(engine_identity, identity.EngineIdentity) or engine_identity.evaluated_by != result.evaluated_by:
        _fail("header_mismatch", "engine identity does not match the result's evaluated_by")
    d = identity.build_decision_inputs(projected, result.organization_id, result.candidate_id, result.opportunity_id,
                                       engine_identity)
    if_star = identity.input_fingerprint(d)
    od_star = identity.output_digest(result)
    rid_star = identity.result_id(if_star, result.evaluated_at)
    if prov.input_fingerprint != if_star:
        _fail("header_mismatch", "provenance input fingerprint differs from the recomputed fingerprint")
    if prov.output_digest != od_star:
        _fail("header_mismatch", "provenance output digest differs from the recomputed digest")
    if not (prov.result_id == result.id == rid_star):
        _fail("header_mismatch", "result id differs from the id recomputed from the fingerprint and as_of")
    if prov.as_of != result.evaluated_at or prov.evaluated_by != result.evaluated_by:
        _fail("header_mismatch", "provenance as_of or evaluated_by differs from the result")
    # only now is the artifact header compared, against the trusted values
    if (fa.result_id, fa.input_fingerprint, fa.output_digest) != (rid_star, if_star, od_star):
        _fail("header_mismatch", "findings header does not match the trusted result id, fingerprint and digest")
    if fa.as_of != result.evaluated_at:
        _fail("header_mismatch", "findings as_of differs from the result's evaluated_at")
    if fa.produced_by != ACCEPTED_FINDINGS_PRODUCER or fa.findings_policy != ACCEPTED_FINDINGS_POLICY:
        _fail("header_mismatch", "unpinned findings producer or policy version")
    digest = identity.canonical_sha256({"v": _CONTENT_DIGEST_VERSION, "findings_policy": ACCEPTED_FINDINGS_POLICY,
                                        "content": _plain(fa.content)})
    if fa.content_digest != digest:
        _fail("header_mismatch", "content digest does not match the content")
    fid = "findings_" + identity.canonical_sha256({"v": _FINDINGS_ID_VERSION, "result_id": rid_star,
                                                   "content_digest": digest}).removeprefix("sha256:")[:40]
    if fa.findings_id != fid:
        _fail("header_mismatch", "findings id does not match the trusted result id and content digest")
    return d, tuple(prov.gated_refs)


# --- step 2: statuses and the exact SD-4 / SD-5 outcome ----------------------------


def _backed(claim, evidence) -> bool:
    return any(evidence[e].basis is _VERIFIED for e in claim.evidence_ids)


def _sorted_ids(items: Iterable) -> tuple[str, ...]:
    return tuple(sorted({x.id for x in items}))


class _Subject:
    """L1's own working record for one rule subject."""

    def __init__(self, kind, status, rel, det, *, req=None, program_id=None, code=None, declared_hours=None,
                 required_hours=None):
        self.kind, self.status, self.rel, self.det = kind, status, list(rel), list(det)
        self.req, self.program_id, self.code = req, program_id, code
        self.declared_hours, self.required_hours = declared_hours, required_hours


def _subjects_active(rule, d) -> list[_Subject]:
    return [_Subject("opportunity_status", d.opportunity.status.value, (), ())]


def _subjects_participation(rule, d) -> list[_Subject]:
    rel = [p for p in d.participations if p.candidate_id == d.candidate_id and p.program_id == rule.program_id]
    seen = {p.status for p in rel}
    if not rel:
        return [_Subject("program_participation", "not_recorded", (), (), program_id=rule.program_id)]
    if seen == {ProgramParticipationStatus.CONFIRMED}:
        status = "confirmed"
    elif seen == {ProgramParticipationStatus.NOT_PARTICIPATING}:
        status = "not_participating"
    else:
        _fail("precedence_mismatch", "conflicting participation records were admitted")
    return [_Subject("program_participation", status, rel, rel, program_id=rule.program_id)]


def _subjects_availability(rule, d) -> list[_Subject]:
    reqs = [r for r in d.requirements if r.requirement.kind == "weekly_hours"]
    rel = [c for c in d.claims if c.candidate_id == d.candidate_id and c.claim_type is ClaimType.AVAILABILITY]
    if len(reqs) > 1:
        _fail("accounting_mismatch", "more than one weekly_hours requirement was admitted")
    if not reqs:
        return [_Subject("weekly_hours", "hours_not_published", rel, ())]
    req = reqs[0]
    required = req.requirement.hours_per_week
    states = {c.state for c in rel}
    declared = [c for c in rel if c.state is ClaimState.DECLARED]
    others = [c for c in rel if c.state is not ClaimState.DECLARED]
    if ClaimState.CONTESTED in states:
        return [_Subject("weekly_hours", "contested", rel, others, req=req, required_hours=required)]
    if not declared:
        return [_Subject("weekly_hours", "not_declared", rel, others, req=req, required_hours=required)]
    hours = sorted({c.value.hours_per_week for c in declared})
    if len(hours) != 1:
        _fail("precedence_mismatch", "conflicting declared availability was admitted")
    status = "meets" if hours[0] >= required else "below"
    return [_Subject("weekly_hours", status, rel, declared, req=req, declared_hours=hours[0], required_hours=required)]


def _qualification_status(rel, evidence) -> tuple[str, list]:
    declared = [c for c in rel if c.state is ClaimState.DECLARED]
    if declared:
        readings = {c.value.presence for c in declared}
        if len(readings) != 1:
            _fail("precedence_mismatch", "conflicting declared skill claims were admitted")
        backed = any(_backed(c, evidence) for c in declared)
        if readings == {"has"}:
            return ("satisfied_verified" if backed else "satisfied_declared"), declared
        return ("contradicted_verified" if backed else "contradicted_declared"), declared
    states = {c.state for c in rel}
    others = list(rel)
    if ClaimState.CONTESTED in states:
        return "contested", others
    if rel and states == {ClaimState.INFERRED}:
        return "only_inferred", others
    return "not_evidenced", others


def _subjects_qualification(rule, d) -> list[_Subject]:
    reqs = sorted((r for r in d.requirements if r.requirement.kind == "mandatory_qualification"), key=lambda r: r.id)
    if not reqs:
        return [_Subject("no_mandatory_qualification", "none_required", (), ())]
    out = []
    for req in reqs:
        code = req.requirement.skill_code
        rel = [c for c in d.claims if c.candidate_id == d.candidate_id and c.claim_type is ClaimType.SKILL
               and c.subject_code == code]
        status, det = _qualification_status(rel, d.evidence)
        out.append(_Subject("qualification", status, rel, det, req=req, code=code))
    return out


_SUBJECTS = {
    PolicyRuleKind.OPPORTUNITY_STATUS_ACTIVE: _subjects_active,
    PolicyRuleKind.PROGRAM_PARTICIPATION_CONFIRMED: _subjects_participation,
    PolicyRuleKind.AVAILABILITY_MEETS_REQUIRED_HOURS: _subjects_availability,
    PolicyRuleKind.MANDATORY_QUALIFICATION_EVIDENCED: _subjects_qualification,
}

_STATUS_OUTCOME = {  # single-subject kinds: status -> (result, reason, cite determinative inputs, cite requirement)
    "active": (RuleResult.PASS, "opportunity_active", False, False),
    "paused": (RuleResult.FAIL, "opportunity_paused", False, False),
    "closed": (RuleResult.FAIL, "opportunity_closed", False, False),
    "confirmed": (RuleResult.PASS, "participation_confirmed", True, False),
    "not_participating": (RuleResult.FAIL, "participation_not_participating", True, False),
    "not_recorded": (RuleResult.UNKNOWN, "participation_not_recorded", False, False),
    "hours_not_published": (RuleResult.UNKNOWN, "required_hours_not_published", False, False),
    "contested": (RuleResult.UNKNOWN, "availability_contested", True, False),
    "not_declared": (RuleResult.UNKNOWN, "availability_not_declared", True, False),
    "meets": (RuleResult.PASS, "availability_meets_required_hours", True, True),
    "below": (RuleResult.FAIL, "availability_below_required_hours", True, True),
    "none_required": (RuleResult.PASS, "no_mandatory_qualification", False, False),
}


def _expected_outcome(kind: PolicyRuleKind, subjects: list[_Subject], d):
    """(result, reason, claim ids, participation ids, requirement ids) under SD-4 rows and SD-5 citations."""
    if kind is not PolicyRuleKind.MANDATORY_QUALIFICATION_EVIDENCED or subjects[0].kind == "no_mandatory_qualification":
        s = subjects[0]
        res, reason, cite_inputs, cite_req = _STATUS_OUTCOME[s.status]
        inputs = s.det if cite_inputs else []
        claims = [x for x in inputs if kind is not PolicyRuleKind.PROGRAM_PARTICIPATION_CONFIRMED]
        parts = [x for x in inputs if kind is PolicyRuleKind.PROGRAM_PARTICIPATION_CONFIRMED]
        reqs = [s.req] if cite_req else []
        return res, reason, _sorted_ids(claims), _sorted_ids(parts), _sorted_ids(reqs)

    contradicted = [s for s in subjects if s.status.startswith("contradicted_")]
    if contradicted:  # rows 1-2: verification first (SD-18; G12 limitation)
        lacking = [c for s in contradicted for c in s.det]
        verified = [c for c in lacking if _backed(c, d.evidence)]
        chosen = verified or lacking
        reason = ("qualification_contradicted_by_verification" if verified
                  else "qualification_contradicted_by_declaration")
        codes = {c.subject_code for c in chosen}
        return (RuleResult.FAIL, reason, _sorted_ids(chosen), (),
                _sorted_ids(s.req for s in subjects if s.code in codes))
    open_ = [s for s in subjects if s.status not in ("satisfied_verified", "satisfied_declared")]
    if open_:  # rows 3-5: contested > only_inferred > not_evidenced
        seen = {s.status for s in open_}
        reason = next(f"qualification_{name}" for name in ("contested", "only_inferred", "not_evidenced") if name in seen)
        return (RuleResult.UNKNOWN, reason, _sorted_ids(c for s in open_ for c in s.det), (),
                _sorted_ids(s.req for s in open_))
    reason = ("qualification_independently_verified" if all(s.status == "satisfied_verified" for s in subjects)
              else "qualification_declared")  # rows 6-7
    return (RuleResult.PASS, reason, _sorted_ids(c for s in subjects for c in s.det), (),
            _sorted_ids(s.req for s in subjects))


# --- expected findings content (L1's own construction) ---------------------------


def _attr(d, evidence_id, relation, index=None, alt=None) -> EvidenceAttribution:
    ev = d.evidence.get(evidence_id)
    if ev is None:
        _fail("accounting_mismatch", f"evidence {evidence_id} is not in the admitted projection")
    reading = hours = None
    if alt is not None and alt.kind == "skill":
        reading = alt.presence
    elif alt is not None and alt.kind == "availability":
        hours = alt.hours_per_week
    return EvidenceAttribution(evidence_id=evidence_id, basis=ev.basis.value, relation=relation,
                               source_ref=identity.normalize_ref(ev.source_ref), field_path=ev.field_path,
                               alternative_index=index, reading=reading, reading_hours=hours)


def _contribution(item, role, d) -> Contribution:
    if isinstance(item, ProgramParticipation):
        attrs = [_attr(d, e, "authority_record") for e in item.evidence_ids]
        return Contribution(input_kind="participation", input_id=item.id, role=role, claim_state=None,
                            rule_standing="decision_input", reading=item.status.value, reading_hours=None,
                            inferred_by=None, evidence=_order(attrs))
    st = item.state
    if st is ClaimState.CONTESTED:
        attrs = [_attr(d, e, "alternative_support", i, alt.value) for i, alt in enumerate(item.alternatives)
                 for e in alt.evidence_ids]
    elif st is ClaimState.INFERRED:
        attrs = [_attr(d, e, "inference_input") for e in item.evidence_ids]
    else:
        attrs = [_attr(d, e, "support") for e in item.evidence_ids]
    reading = hours = None
    if st in (ClaimState.DECLARED, ClaimState.INFERRED):
        if item.claim_type is ClaimType.SKILL:
            reading = item.value.presence
        elif item.claim_type is ClaimType.AVAILABILITY:
            hours = item.value.hours_per_week
    return Contribution(input_kind="claim", input_id=item.id, role=role, claim_state=st.value,
                        rule_standing="decision_input" if st is ClaimState.DECLARED else "non_decision_input",
                        reading=reading, reading_hours=hours, inferred_by=item.inferred_by, evidence=_order(attrs))


def _order(attrs) -> tuple[EvidenceAttribution, ...]:
    return tuple(sorted(attrs, key=lambda a: (a.alternative_index if a.alternative_index is not None else -1,
                                              a.evidence_id)))


def _expected_subject(s: _Subject, outcome, d) -> SubjectFinding:
    cited = set(outcome[2]) | set(outcome[3])
    passing = s.status in _PASSING
    det_ids = {x.id for x in s.det}
    if s.kind == "qualification" and s.req.id not in outcome[4]:
        role = "uncited_satisfied" if passing else "uncited_nonpass"
    else:
        role = "decisive"
    contributions = []
    for item in sorted(s.rel, key=lambda x: x.id):
        if item.id in cited:
            c_role = "cited"
        elif item.id in det_ids:
            c_role = "uncited_satisfying" if passing else "uncited_material"
        else:
            c_role = "context"
        contributions.append(_contribution(item, c_role, d))
    req = None if s.req is None else RequirementAttribution(
        requirement_id=s.req.id, source_ref=identity.normalize_ref(s.req.source_ref), field_path=s.req.field_path)
    return SubjectFinding(kind=s.kind, program_id=s.program_id, skill_code=s.code, requirement=req,
                          subject_status=s.status, subject_role=role, information_gap=_GAP.get(s.status),
                          declared_hours=s.declared_hours, required_hours=s.required_hours,
                          contributions=tuple(contributions))


# --- verification -------------------------------------------------------------------


def _refs(content: FindingsContent) -> set:
    refs = {content.opportunity_ref, content.policy_ref}
    for r in content.rules:
        for s in r.subjects:
            if s.requirement is not None:
                refs.add(s.requirement.source_ref)
            for c in s.contributions:
                refs |= {a.source_ref for a in c.evidence}
    return refs


def _scope(fa: FindingsArtifact, result, d) -> None:
    c = fa.content
    org = result.organization_id
    header = (c.organization_id, c.candidate_id, c.opportunity_id, c.opportunity_ref, c.policy_id, c.policy_version,
              c.policy_ref)
    expected = (org, result.candidate_id, result.opportunity_id, result.opportunity_ref, result.policy.policy_set_id,
                result.policy.version, result.policy.source_ref)
    if header != expected:
        _fail("scope_violation", "findings header does not name the assessed organization, candidate, opportunity and policy")
    claims = {x.id: x for x in d.claims}
    parts = {x.id: x for x in d.participations}
    reqs = {x.id: x for x in d.requirements}
    for rec in (*d.claims, *d.participations, *d.requirements, *d.evidence.values()):
        if rec.organization_id != org:
            _fail("scope_violation", f"{rec.id} is outside the assessed organization")
    for r in c.rules:
        for s in r.subjects:
            if s.requirement is not None:
                req = reqs.get(s.requirement.requirement_id)
                if req is None or req.opportunity_id != result.opportunity_id:
                    _fail("scope_violation", f"requirement {s.requirement.requirement_id} is not an admitted requirement")
            for con in s.contributions:
                rec = claims.get(con.input_id) if con.input_kind == "claim" else parts.get(con.input_id)
                if rec is None or rec.candidate_id != result.candidate_id:
                    _fail("scope_violation", f"input {con.input_id} is not an admitted input of the assessed candidate")
                for a in con.evidence:
                    ev = d.evidence.get(a.evidence_id)
                    if ev is None or ev.organization_id != org:
                        _fail("scope_violation", f"evidence {a.evidence_id} is not admitted evidence")


def _structure(content: FindingsContent) -> list:
    return [(r.rule_id, r.rule_version, r.rule_kind,
             [(s.kind, s.requirement.requirement_id if s.requirement else None, s.program_id,
               [(c.input_kind, c.input_id, [(a.evidence_id, a.alternative_index) for a in c.evidence])
                for c in s.contributions]) for s in r.subjects])
            for r in content.rules]


def verify_findings(fa: FindingsArtifact, result, projected, prov, engine_identity) -> None:
    """Raise ``FindingsMismatch`` unless the findings are exactly those of the admitted projection.

    ``prov`` is the engine-held P11 provenance and ``engine_identity`` the engine-held
    ``EngineIdentity`` that the input fingerprint covers. Neither is taken from ``fa``.
    """
    d, gated = _trusted_header(fa, result, projected, prov, engine_identity)

    if len(d.policy.rules) != len(result.rule_outcomes):
        _fail("precedence_mismatch", "result outcomes do not align with the policy rules")
    expected_rules = []
    for rule, o in zip(d.policy.rules, result.rule_outcomes):
        subjects = _SUBJECTS[rule.kind](rule, d)
        expected_rules.append((rule, subjects, _expected_outcome(rule.kind, subjects, d), o))
    for rule, _subjects, (res, reason, cl, pa, rq), o in expected_rules:
        if (o.rule_id, o.rule_version, o.rule_kind) != (rule.rule_id, rule.rule_version, rule.kind):
            _fail("precedence_mismatch", f"{o.rule_id} is out of policy order")
        if (o.result, o.reason_code) != (res, reason):
            _fail("precedence_mismatch", f"{rule.rule_id}: result has {o.result.value}/{o.reason_code}; "
                                         f"SD-4 gives {res.value}/{reason}")
        if (tuple(o.claim_ids), tuple(o.participation_ids), tuple(o.requirement_ids)) != (cl, pa, rq):
            _fail("citation_mismatch", f"{rule.rule_id}: citations differ from the exact SD-5 citation sets")
    if result.decision is not derive_decision(result.rule_outcomes):
        _fail("precedence_mismatch", "decision does not follow from the outcomes")

    _scope(fa, result, d)

    if _refs(fa.content) != set(gated):
        _fail("provenance_mismatch", "findings source references differ from the gated source set")

    expected = FindingsContent(
        organization_id=result.organization_id, candidate_id=result.candidate_id,
        opportunity_id=result.opportunity_id, opportunity_ref=identity.normalize_ref(d.opportunity.source_ref),
        policy_id=d.policy.id, policy_version=d.policy.version, policy_ref=identity.normalize_ref(d.policy.source_ref),
        decision=result.decision.value,
        rules=tuple(RuleFindings(rule_id=rule.rule_id, rule_version=rule.rule_version, rule_kind=rule.kind.value,
                                 result=outcome[0].value, reason_code=outcome[1],
                                 subjects=tuple(_expected_subject(s, outcome, d) for s in subjects))
                    for rule, subjects, outcome, _o in expected_rules))

    # I4/I5 global coverage: every selected input and every admitted evidence record is accounted for
    seen_inputs = {c.input_id for r in expected.rules for s in r.subjects for c in s.contributions}
    if seen_inputs != {x.id for x in d.claims} | {x.id for x in d.participations}:
        _fail("accounting_mismatch", "an admitted input belongs to no rule subject")
    seen_evidence = {a.evidence_id for r in expected.rules for s in r.subjects for c in s.contributions for a in c.evidence}
    if seen_evidence != set(d.evidence):
        _fail("accounting_mismatch", "an admitted evidence record is attributed to no input")

    if _structure(fa.content) != _structure(expected):
        _fail("accounting_mismatch", "subjects, contributions or evidence attributions differ from the admitted projection")
    if fa.content != expected:
        _fail("role_mismatch", "a status, role, standing, relation, gap, reading or attribution differs")
