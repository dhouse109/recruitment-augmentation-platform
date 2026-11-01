"""L2: metadata-only projection-selection verification (PR-S2, P2b).

``verify_selection(supplied, targets, projected)`` runs immediately after the P2
projection and BEFORE the organization guard, structural checks and the source
gate. It makes no authority call and reads no claim value, state, presence,
hours, status or alternative value (AST-enforced): only the metadata fields
listed in ``metadata_view``.

It re-derives the selection with its own code (it does not call
``inputs.project``) and requires every projected collection to contain exactly
the expected records -- nothing missing, nothing extra -- as the SAME objects
(``is``) that were supplied, in supplied order. A substituted copy under the same
id therefore fails without any value being read.

Organization scoping is deliberately NOT checked here: like ``project()``, the
selection is organization-agnostic, and the P3 organization guard still refuses
cross-organization records. On a correct projection this check never fails, so
PR-S1 refusal precedence is unchanged.

Completeness levels: this establishes L2 (projection == selection rules applied to
the supplied context). It cannot establish L3 (the supplied context contains every
relevant Drupal record); that remains an adapter assertion (T4).
"""

from __future__ import annotations

from typing import Any, NamedTuple

from rap_contracts.claims import ClaimType
from rap_contracts.eligibility import PolicyRuleKind


class SelectionMismatch(Exception):
    """The projection is not exactly the metadata selection of the supplied context (an engine defect)."""


class RequirementMeta(NamedTuple):
    id: str
    opportunity_id: str
    kind: str
    skill_code: str | None
    vocabulary_pin: tuple | None
    ref: Any


class ClaimMeta(NamedTuple):
    id: str
    candidate_id: str
    claim_type: Any
    subject_code: str | None
    vocabulary_pin: tuple
    evidence_ids: tuple
    ref: Any


class ParticipationMeta(NamedTuple):
    id: str
    candidate_id: str
    program_id: str
    evidence_ids: tuple
    ref: Any


class ApplicationMeta(NamedTuple):
    id: str
    candidate_id: str
    target_opportunity_id: str | None
    target_program_id: str | None
    ref: Any


class ProfileMeta(NamedTuple):
    id: str
    candidate_id: str
    ref: Any


class OpportunityMeta(NamedTuple):
    id: str
    program_id: str | None
    ref: Any


class IdMeta(NamedTuple):
    id: str
    ref: Any


class PolicyMeta(NamedTuple):
    id: str
    version: int
    program_id: str | None
    rule_kinds: tuple
    rule_programs: tuple
    ref: Any


class VocabularyMeta(NamedTuple):
    pin: tuple
    ref: Any


#: The complete L2 inventory: the metadata fields ``inputs.project()`` reads to decide membership.
INVENTORY = {
    "requirements": RequirementMeta._fields,
    "claims": ClaimMeta._fields,
    "participations": ParticipationMeta._fields,
    "applications": ApplicationMeta._fields,
    "profiles": ProfileMeta._fields,
    "opportunities": OpportunityMeta._fields,
    "programs": IdMeta._fields,
    "candidates": IdMeta._fields,
    "policies": PolicyMeta._fields,
    "vocabularies": VocabularyMeta._fields,
    "evidence": ("key", "ref"),
}


def _requirement_meta(r) -> RequirementMeta:
    spec = r.requirement
    qual = spec.kind == "mandatory_qualification"
    return RequirementMeta(r.id, r.opportunity_id, spec.kind, spec.skill_code if qual else None,
                           (spec.vocabulary.id, spec.vocabulary.version) if qual else None, r)


def _policy_meta(p) -> PolicyMeta:
    return PolicyMeta(p.id, p.version, p.program_id, tuple(rule.kind for rule in p.rules),
                      tuple(rule.program_id for rule in p.rules if rule.program_id is not None), p)


def metadata_view(ctx) -> dict[str, tuple]:
    """Metadata-only view of an ``EligibilityContext`` (each entry keeps an opaque ``ref`` for identity checks)."""
    r = ctx.records
    return {
        "requirements": tuple(_requirement_meta(x) for x in ctx.requirements),
        "claims": tuple(ClaimMeta(x.id, x.candidate_id, x.claim_type, x.subject_code,
                                  (x.vocabulary.id, x.vocabulary.version), tuple(x.all_evidence_ids()), x)
                        for x in ctx.claims),
        "participations": tuple(ParticipationMeta(x.id, x.candidate_id, x.program_id, tuple(x.evidence_ids), x)
                                for x in ctx.participations),
        "applications": tuple(ApplicationMeta(x.id, x.candidate_id, x.target.opportunity_id, x.target.program_id, x)
                              for x in r.applications),
        "profiles": tuple(ProfileMeta(x.id, x.candidate_id, x) for x in r.profiles),
        "opportunities": tuple(OpportunityMeta(x.id, x.program_id, x) for x in r.opportunities),
        "programs": tuple(IdMeta(x.id, x) for x in r.programs),
        "candidates": tuple(IdMeta(x.id, x) for x in r.candidates),
        "policies": tuple(_policy_meta(x) for x in ctx.policies),
        "vocabularies": tuple(VocabularyMeta((x.id, x.version), x) for x in ctx.vocabularies),
        "evidence": tuple((key, ctx.evidence[key]) for key in sorted(ctx.evidence)),
    }


def _expected(view: dict, candidate, opportunity: OpportunityMeta, policy: PolicyMeta) -> dict[str, list]:
    wants_hours = PolicyRuleKind.AVAILABILITY_MEETS_REQUIRED_HOURS in policy.rule_kinds
    wants_quals = PolicyRuleKind.MANDATORY_QUALIFICATION_EVIDENCED in policy.rule_kinds
    reqs = [m for m in view["requirements"] if m.opportunity_id == opportunity.id and (
        (m.kind == "weekly_hours" and wants_hours) or (m.kind == "mandatory_qualification" and wants_quals))]
    codes = {m.skill_code for m in reqs if m.kind == "mandatory_qualification"}
    claims = [m for m in view["claims"] if m.candidate_id == candidate.id and (
        (m.claim_type is ClaimType.AVAILABILITY and wants_hours)
        or (m.claim_type is ClaimType.SKILL and m.subject_code in codes))]
    rule_programs = set(policy.rule_programs)
    parts = [m for m in view["participations"] if m.candidate_id == candidate.id and m.program_id in rule_programs]
    evidence_keys = sorted({e for m in claims for e in m.evidence_ids} | {e for m in parts for e in m.evidence_ids})
    apps = [m for m in view["applications"] if m.candidate_id == candidate.id]
    profiles = [m for m in view["profiles"] if m.candidate_id == candidate.id]
    opp_ids = {opportunity.id} | {m.target_opportunity_id for m in apps if m.target_opportunity_id}
    opps = [m for m in view["opportunities"] if m.id in opp_ids]
    program_ids = ({opportunity.program_id, policy.program_id} | rule_programs
                   | {m.target_program_id for m in apps} | {m.program_id for m in opps}) - {None}
    vocab_pins = {m.vocabulary_pin for m in claims} | {m.vocabulary_pin for m in reqs if m.kind == "mandatory_qualification"}
    supplied_evidence = dict(view["evidence"])
    return {
        "requirements": [m.ref for m in reqs],
        "claims": [m.ref for m in claims],
        "participations": [m.ref for m in parts],
        "applications": [m.ref for m in apps],
        "profiles": [m.ref for m in profiles],
        "opportunities": [m.ref for m in opps],
        "programs": [m.ref for m in view["programs"] if m.id in program_ids],
        "candidates": [candidate.ref],
        "policies": [policy.ref],
        "vocabularies": [m.ref for m in view["vocabularies"] if m.pin in vocab_pins],
        "evidence": [(key, supplied_evidence.get(key)) for key in evidence_keys],
    }


def _same(expected: list, actual: list) -> bool:
    return len(expected) == len(actual) and all(a is b for a, b in zip(expected, actual))


def verify_selection(supplied, targets, projected) -> None:
    """Raise ``SelectionMismatch`` unless ``projected`` is exactly the metadata selection of ``supplied``."""
    view = metadata_view(supplied)
    by_ref = lambda name: {id(m.ref): m for m in view[name]}  # noqa: E731
    candidate = by_ref("candidates").get(id(targets.candidate))
    opportunity = by_ref("opportunities").get(id(targets.opportunity))
    policy = by_ref("policies").get(id(targets.policy))
    if candidate is None or opportunity is None or policy is None:
        raise SelectionMismatch("a target is not a supplied record")
    expected = _expected(view, candidate, opportunity, policy)
    actual = metadata_view(projected)
    for name, wanted in expected.items():
        if name == "evidence":
            got = list(actual["evidence"])
            if [k for k, _ in got] != [k for k, _ in wanted] or not _same([v for _, v in wanted], [v for _, v in got]):
                raise SelectionMismatch("projected evidence differs from the selection")
            continue
        if not _same(wanted, [m.ref for m in actual[name]]):
            raise SelectionMismatch(f"projected {name} differ from the selection")
