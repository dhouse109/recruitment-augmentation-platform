"""P14: deterministic explanation over verified findings (PR-S2). Runtime-local; NOT a contract.

The explanation is built from the L1-verified ``FindingsArtifact`` only -- never from
``EligibilityResult`` citations alone (owner decision D2 supersedes SD-6) -- using a
fixed, versioned template table (D5). No prose is generated and no source string is
ever used as a template: ids, field paths and source locators are inserted as escaped,
quoted data.

Identity (plan rev. 2.2 section 4.5):

* explanation CONTENT (statements, typed params, limitations and ``rendered_body``) is a
  pure function of the findings content and the template version. The scope sentence
  holds the reserved slot ``SLOT`` exactly once, so the content digest is independent
  of time;
* the explanation ARTIFACT carries ``rendered_text`` -- the body with the slot replaced by
  the UTC ``as_of`` -- plus a time-dependent ``rendered_text_digest`` and the ids.

Slice 0 explanations are internal artifacts: not authorized for reviewer presentation,
confer no authorization, currentness or decision, and render skill codes only (O3).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .findings import (
    BASES,
    CONTRIBUTION_ROLES,
    INFORMATION_GAPS,
    RELATIONS,
    RULE_STANDINGS,
    SUBJECT_ROLES,
    SUBJECT_STATUSES,
    FindingsArtifact,
    to_plain,
)
from .identity import canonical, canonical_sha256, utc_text

EXPLANATION_PRODUCER = "rap-baseline.explanation/0.1.0"
TEMPLATES_VERSION = "explain-templates/1"
CONTENT_DIGEST_VERSION = "rap-baseline.explanation-content/1"
EXPLANATION_ID_VERSION = "rap-baseline.explanation-id/1"
SLOT = "⟦as_of⟧"  # the reserved time slot; appears exactly once in every rendered_body

#: Accepted pins, checked at P14 against the module constants actually used.
_PINNED = ("rap-baseline.explanation/0.1.0", "explain-templates/1", "findings/1", "rap-baseline.findings/0.1.0")


class ExplanationMismatch(Exception):
    """The explanation could not be built or failed its own consistency check."""


@dataclass(frozen=True)
class Statement:
    key: str
    ref: str
    params: tuple[tuple[str, Any], ...]


@dataclass(frozen=True)
class ExplanationContent:
    statements: tuple[Statement, ...]
    limitations: tuple[str, ...]
    rendered_body: str


@dataclass(frozen=True)
class ExplanationArtifact:
    explanation_id: str
    findings_id: str
    as_of: datetime
    produced_by: str
    templates: str
    explanation_content_digest: str
    content: ExplanationContent
    rendered_text: str
    rendered_text_digest: str


# --- template table (explain-templates/1) --------------------------------------------

_Q = "Mandatory qualification {skill_code} (requirement {requirement_id})"
_ALSO = "Also material, not cited by the eligibility result: "
_UNCITED = "Not cited by the eligibility result: "
_SCOPE = "This assessment covers this opportunity under this policy version only."

TEMPLATES: dict[str, str] = {
    "decision/eligible": "Assessment: eligible for opportunity {opportunity_id} under policy {policy_id} version "
                         "{policy_version}, as of " + SLOT + ". " + _SCOPE,
    "decision/ineligible": "Assessment: not eligible for opportunity {opportunity_id} under policy {policy_id} version "
                           "{policy_version}, as of " + SLOT + ". " + _SCOPE
                           + " It says nothing about any other opportunity.",
    "decision/needs_information": "Assessment: more information is needed for opportunity {opportunity_id} under policy "
                                  "{policy_id} version {policy_version}, as of " + SLOT + ". " + _SCOPE,
    "rule/pass": "Rule {rule_id} version {rule_version}: pass ({reason_code}).",
    "rule/fail": "Rule {rule_id} version {rule_version}: fail ({reason_code}).",
    "rule/unknown": "Rule {rule_id} version {rule_version}: undetermined ({reason_code}).",
    # subjects: (kind, status, role)
    "subject/opportunity_status/active/decisive": "The opportunity record {opportunity_ref} shows the opportunity as active.",
    "subject/opportunity_status/paused/decisive": "The opportunity record {opportunity_ref} shows the opportunity as paused.",
    "subject/opportunity_status/closed/decisive": "The opportunity record {opportunity_ref} shows the opportunity as closed.",
    "subject/program_participation/confirmed/decisive": "Program records show participation in {program_id} as confirmed.",
    "subject/program_participation/not_participating/decisive":
        "Program records show no participation in {program_id}.",
    "subject/program_participation/not_recorded/decisive":
        "No program participation record for {program_id} is present in the supplied records.",
    "subject/weekly_hours/meets/decisive":
        "Declared availability of {declared_hours} hours per week meets the published requirement of "
        "{required_hours} hours per week (requirement {requirement_id}).",
    "subject/weekly_hours/below/decisive":
        "Declared availability of {declared_hours} hours per week is below the published requirement of "
        "{required_hours} hours per week (requirement {requirement_id}).",
    "subject/weekly_hours/contested/decisive":
        "Availability sources conflict, so no availability value is determined "
        "(requirement {requirement_id}: {required_hours} hours per week).",
    "subject/weekly_hours/not_declared/decisive":
        "No source-backed availability value is present (requirement {requirement_id}: {required_hours} hours per week).",
    "subject/weekly_hours/hours_not_published/decisive":
        "The opportunity publishes no weekly-hours requirement, so availability is not compared.",
    "subject/qualification/satisfied_verified/decisive":
        _Q + " is present in declared claims, at least one of which its source records as independently verified.",
    "subject/qualification/satisfied_declared/decisive":
        _Q + " is present in declared claims; none is recorded as independently verified.",
    "subject/qualification/contradicted_verified/decisive":
        _Q + " is contradicted by a declared claim that its source records as independent verification.",
    "subject/qualification/contradicted_declared/decisive":
        _Q + " is contradicted by the candidate's own statement.",
    "subject/qualification/contested/decisive": _Q + ": sources conflict, so no value is determined.",
    "subject/qualification/only_inferred/decisive": _Q + ": only an inferred signal exists, and it is not a fact.",
    "subject/qualification/not_evidenced/decisive": _Q + ": no source-backed value is present.",
    "subject/qualification/contradicted_declared/uncited_nonpass":
        _ALSO + _Q + " is contradicted by the candidate's own statement.",
    "subject/qualification/contested/uncited_nonpass": _ALSO + _Q + ": sources conflict, so no value is determined.",
    "subject/qualification/only_inferred/uncited_nonpass":
        _ALSO + _Q + ": only an inferred signal exists, and it is not a fact.",
    "subject/qualification/not_evidenced/uncited_nonpass": _ALSO + _Q + ": no source-backed value is present.",
    "subject/qualification/satisfied_verified/uncited_satisfied":
        _UNCITED + _Q + " is present in declared claims, at least one of which its source records as independently verified.",
    "subject/qualification/satisfied_declared/uncited_satisfied":
        _UNCITED + _Q + " is present in declared claims; none is recorded as independently verified.",
    "subject/no_mandatory_qualification/none_required/decisive": "The opportunity publishes no mandatory qualification.",
    # contributions: (role, rule standing)
    "contribution/cited/decision_input": "Cited decision input {input_id} ({detail}).",
    "contribution/cited/non_decision_input": "Cited non-decision input {input_id} ({detail}); it is not treated as a fact.",
    "contribution/uncited_material/decision_input":
        "Material decision input not cited by the eligibility result: {input_id} ({detail}).",
    "contribution/uncited_material/non_decision_input":
        "Material non-decision input not cited by the eligibility result: {input_id} ({detail}); it is not treated as a fact.",
    "contribution/uncited_satisfying/decision_input":
        "Supporting decision input not cited by the eligibility result: {input_id} ({detail}).",
    "contribution/context/decision_input": "Context only, not determinative here: {input_id} ({detail}).",
    "contribution/context/non_decision_input":
        "Context only: non-decision input {input_id} ({detail}); it is not treated as a fact.",
    # evidence attributions: (relation, basis)
    "attribution/support/candidate_statement":
        "Evidence {evidence_id}: self-declared (candidate statement); source {source}, field {field_path}.",
    "attribution/support/independent_verification":
        "Evidence {evidence_id}: recorded by its source as independently verified; source {source}, field {field_path}.",
    "attribution/alternative_support/candidate_statement":
        "Evidence {evidence_id} supports alternative {alternative_index} ({alternative}): self-declared "
        "(candidate statement); source {source}, field {field_path}.",
    "attribution/alternative_support/independent_verification":
        "Evidence {evidence_id} supports alternative {alternative_index} ({alternative}): recorded by its source "
        "as independently verified; source {source}, field {field_path}.",
    "attribution/inference_input/candidate_statement":
        "Evidence {evidence_id} was an input to an inference; it is not described as stating the inferred value. "
        "Self-declared (candidate statement); source {source}, field {field_path}.",
    "attribution/inference_input/independent_verification":
        "Evidence {evidence_id} was an input to an inference; it is not described as stating the inferred value. "
        "Recorded by its source as independently verified; source {source}, field {field_path}.",
    "attribution/authority_record/authority_record":
        "Evidence {evidence_id}: program record; source {source}, field {field_path}.",
    # information gaps (what is missing; never who is at fault)
    "gap/no_source_backed_value":
        "Information gap: no source-backed value is present. This does not establish that it is absent.",
    "gap/only_inferred_signal": "Information gap: only an inferred signal is present.",
    "gap/conflicting_sources":
        "Information gap: sources conflict. No alternative is preferred and no party is identified as responsible.",
    "gap/opportunity_requirement_unpublished": "Information gap: the opportunity has not published this requirement.",
    "gap/no_participation_record": "Information gap: no program participation record is present.",
    # limitations
    "section/limitations": "Limitations:",
    "limitation/opportunity_and_policy_scoped": "Scope: this assessment applies to this opportunity under this policy "
                                                "version only.",
    "limitation/context_completeness_asserted_by_adapter":
        "Completeness: the supplied records are asserted complete by the loading adapter; that is not established here.",
    "limitation/synthetic_source_authority":
        "Source checks: source admission was decided by a synthetic test authority, not by Drupal.",
    "limitation/not_authorized_for_presentation":
        "Use: this explanation is an internal artifact and is not authorized for reviewer presentation.",
    "limitation/recheck_sources_before_action":
        "Action: sources must be re-checked for currentness and access before any reviewer action.",
    "limitation/non_decision_inputs_present":
        "Some listed inputs are inferred, contested or unknown; they are not treated as facts.",
}

_NON_QUAL_KINDS = ("opportunity_status", "program_participation", "weekly_hours", "no_mandatory_qualification")

#: Every combination of the closed key vocabularies that cannot occur. The coverage test
#: requires TEMPLATES and UNREACHABLE to partition each full product exactly.
UNREACHABLE: frozenset[str] = frozenset(
    # only qualification subjects can be uncited (other rules have exactly one, always cited, subject)
    [f"subject/{k}/{s}/{r}" for k in _NON_QUAL_KINDS for s in SUBJECT_STATUSES[k]
     for r in ("uncited_nonpass", "uncited_satisfied")]
    # SD-4 cites every verification-backed contradiction, so one is never uncited
    + ["subject/qualification/contradicted_verified/uncited_nonpass"]
    # an uncited non-pass subject cannot be satisfied, and an uncited satisfied subject cannot be non-pass
    + ["subject/qualification/satisfied_verified/uncited_nonpass", "subject/qualification/satisfied_declared/uncited_nonpass"]
    + [f"subject/qualification/{s}/uncited_satisfied" for s in
       ("contradicted_verified", "contradicted_declared", "contested", "only_inferred", "not_evidenced")]
    # a satisfied subject is determined by declared (decision-input) claims only
    + ["contribution/uncited_satisfying/non_decision_input"]
    # candidate claims are backed only by statement or verification evidence; participations only by authority records
    + [f"attribution/{rel}/authority_record" for rel in ("support", "alternative_support", "inference_input")]
    + ["attribution/authority_record/candidate_statement", "attribution/authority_record/independent_verification"]
)

KEY_SPACE = {
    "subject": [f"subject/{k}/{s}/{r}" for k, statuses in SUBJECT_STATUSES.items() for s in statuses for r in SUBJECT_ROLES],
    "contribution": [f"contribution/{r}/{st}" for r in CONTRIBUTION_ROLES for st in RULE_STANDINGS],
    "attribution": [f"attribution/{rel}/{b}" for rel in RELATIONS for b in BASES],
    "gap": [f"gap/{g}" for g in INFORMATION_GAPS],
}

MANDATORY_LIMITATIONS = ("opportunity_and_policy_scoped", "context_completeness_asserted_by_adapter",
                         "synthetic_source_authority", "not_authorized_for_presentation",
                         "recheck_sources_before_action")

# --- rendering ------------------------------------------------------------------------

_STATE_PHRASE = {"declared": "declared claim", "inferred": "inferred claim", "contested": "contested claim",
                 "unknown": "unknown-state claim", None: "program record"}
_READING_PHRASE = {"has": "has", "lacks": "lacks", "confirmed": "confirmed", "not_participating": "not participating"}
_INT_PARAMS = {"rule_version", "policy_version", "declared_hours", "required_hours", "alternative_index"}


def _data(value: Any) -> str:
    """Source-derived strings are inserted as quoted, escaped data: never as template text, never as a slot."""
    return (json.dumps(str(value), ensure_ascii=True)
            .replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026"))


def _source(ref) -> str:
    plain = canonical(ref)  # JSON-ready form: enum members become their codes
    entity, version = plain["entity"], plain["version"]
    token = f"rev:{version['revision_id']}" if version["kind"] == "native_revision" else f"snapshot:{version['token']}"
    return f"{entity['source_system']}/{entity['entity_type']}/{entity['entity_id']}@{token}"


def _detail(p: dict) -> str:
    parts = [_STATE_PHRASE[p.get("claim_state")]]
    if p.get("reading") is not None:
        parts.append("reading: " + _READING_PHRASE[p["reading"]])
    if p.get("reading_hours") is not None:
        parts.append(f"reading: {int(p['reading_hours'])} hours per week")
    if p.get("inferred_by") is not None:
        parts.append("inferred by " + _data(p["inferred_by"]))
    return ", ".join(parts)


def _alternative(p: dict) -> str:
    if p.get("reading") is not None:
        return "reading: " + _READING_PHRASE[p["reading"]]
    if p.get("reading_hours") is not None:
        return f"reading: {int(p['reading_hours'])} hours per week"
    return "no reading"


def _render(statement: Statement) -> str:
    template = TEMPLATES.get(statement.key)
    if template is None or statement.key in UNREACHABLE:
        raise ExplanationMismatch(f"no template for {statement.key}")
    p = dict(statement.params)
    fields = {}
    for name, val in p.items():
        if name in _INT_PARAMS:
            fields[name] = str(int(val))
        elif name not in ("claim_state", "reading", "reading_hours", "inferred_by"):
            fields[name] = _data(val)
    if statement.key.startswith("contribution/"):
        fields["detail"] = _detail(p)
    if statement.key.startswith("attribution/alternative_support/"):
        fields["alternative"] = _alternative(p)
    return template.format(**fields)


def _params(**kw) -> tuple[tuple[str, Any], ...]:
    return tuple(sorted((k, v) for k, v in kw.items() if v is not None))


def _statements(fa: FindingsArtifact) -> list[tuple[int, Statement]]:
    c = fa.content
    out: list[tuple[int, Statement]] = [(0, Statement(f"decision/{c.decision}", "decision", _params(
        opportunity_id=c.opportunity_id, policy_id=c.policy_id, policy_version=c.policy_version)))]
    for r in c.rules:
        rref = f"rule:{r.rule_id}"
        out.append((0, Statement(f"rule/{r.result}", rref, _params(rule_id=r.rule_id, rule_version=r.rule_version,
                                                                   reason_code=r.reason_code))))
        for s in r.subjects:
            sref = f"{rref}/subject:{s.kind}:{s.requirement.requirement_id if s.requirement else s.program_id or '-'}"
            out.append((1, Statement(f"subject/{s.kind}/{s.subject_status}/{s.subject_role}", sref, _params(
                opportunity_ref=_source(c.opportunity_ref) if s.kind == "opportunity_status" else None,
                program_id=s.program_id, skill_code=s.skill_code,
                requirement_id=s.requirement.requirement_id if s.requirement else None,
                declared_hours=s.declared_hours, required_hours=s.required_hours))))
            if s.information_gap is not None:
                out.append((2, Statement(f"gap/{s.information_gap}", sref + "/gap", ())))
            for con in s.contributions:
                cref = f"{sref}/input:{con.input_id}"
                out.append((2, Statement(f"contribution/{con.role}/{con.rule_standing}", cref, _params(
                    input_id=con.input_id, claim_state=con.claim_state, reading=con.reading,
                    reading_hours=con.reading_hours, inferred_by=con.inferred_by))))
                for a in con.evidence:
                    aref = f"{cref}/evidence:{a.evidence_id}" + (
                        f"#alt{a.alternative_index}" if a.alternative_index is not None else "")
                    out.append((3, Statement(f"attribution/{a.relation}/{a.basis}", aref, _params(
                        evidence_id=a.evidence_id, source=_source(a.source_ref), field_path=a.field_path,
                        alternative_index=a.alternative_index, reading=a.reading, reading_hours=a.reading_hours))))
    return out


def _limitations(fa: FindingsArtifact) -> tuple[str, ...]:
    non_decision = any(con.rule_standing == "non_decision_input"
                       for r in fa.content.rules for s in r.subjects for con in s.contributions)
    return MANDATORY_LIMITATIONS + (("non_decision_inputs_present",) if non_decision else ())


def content_digest(content: ExplanationContent, templates: str) -> str:
    return canonical_sha256({"v": CONTENT_DIGEST_VERSION, "templates": templates, "content": to_plain(content)})


def explanation_id(fid: str, digest: str, templates: str) -> str:
    h = canonical_sha256({"v": EXPLANATION_ID_VERSION, "findings_id": fid, "explanation_content_digest": digest,
                          "templates": templates})
    return "explanation_" + h.removeprefix("sha256:")[:40]


def _text_digest(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


_DEPTH = {"decision": 0, "rule": 0, "subject": 1, "gap": 2, "contribution": 2, "attribution": 3}


def _expected_index(fa: FindingsArtifact) -> list[tuple[str, str, tuple]]:
    """(key, reference, identifying params) for every finding element, in canonical order (review repair R2).

    One entry per rule, subject, applicable information gap, contribution and evidence
    attribution of the verified findings, plus the decision header.
    """
    c = fa.content
    index = [(f"decision/{c.decision}", "decision", (("opportunity_id", c.opportunity_id), ("policy_id", c.policy_id)))]
    for r in c.rules:
        rref = f"rule:{r.rule_id}"
        index.append((f"rule/{r.result}", rref, (("reason_code", r.reason_code), ("rule_id", r.rule_id))))
        for s in r.subjects:
            req = s.requirement.requirement_id if s.requirement is not None else None
            sref = f"{rref}/subject:{s.kind}:{req or s.program_id or '-'}"
            index.append((f"subject/{s.kind}/{s.subject_status}/{s.subject_role}", sref,
                          (("program_id", s.program_id), ("requirement_id", req), ("skill_code", s.skill_code))))
            if s.information_gap is not None:
                index.append((f"gap/{s.information_gap}", f"{sref}/gap", ()))
            for con in s.contributions:
                cref = f"{sref}/input:{con.input_id}"
                index.append((f"contribution/{con.role}/{con.rule_standing}", cref, (("input_id", con.input_id),)))
                for a in con.evidence:
                    alt = "" if a.alternative_index is None else f"#alt{a.alternative_index}"
                    index.append((f"attribution/{a.relation}/{a.basis}", f"{cref}/evidence:{a.evidence_id}{alt}",
                                  (("alternative_index", a.alternative_index), ("evidence_id", a.evidence_id),
                                   ("field_path", a.field_path))))
    return index


def _completeness(ea: ExplanationArtifact, fa: FindingsArtifact) -> None:
    """Every finding element is represented exactly once, in order, with the right reference and identity,
    and every statement is rendered as one line of the body (review repair R2)."""
    expected = _expected_index(fa)
    statements = ea.content.statements
    if len(statements) != len(expected):
        raise ExplanationMismatch(f"explanation has {len(statements)} statements for {len(expected)} finding elements")
    for statement, (key, ref, ident) in zip(statements, expected):
        params = dict(statement.params)
        if (statement.key, statement.ref) != (key, ref) or any(params.get(k) != v for k, v in ident):
            raise ExplanationMismatch(f"statement {statement.ref} does not represent finding element {ref}")
    lines = ea.content.rendered_body.split("\n")
    if len(lines) != len(statements) + 1 + len(ea.content.limitations):
        raise ExplanationMismatch("rendered body lines do not correspond one-to-one with the statements")
    for line, statement in zip(lines, statements):
        depth = _DEPTH[statement.key.split("/", 1)[0]]
        if line != ("  " * depth) + ("- " if depth else "") + _render(statement):
            raise ExplanationMismatch(f"rendered line for {statement.ref} does not match its statement")
    if ea.content.limitations != _limitations(fa):
        raise ExplanationMismatch("limitations do not match the findings")


def _verify(ea: ExplanationArtifact, fa: FindingsArtifact) -> None:
    """P14 self-check: pins, completeness against the findings, the single time slot, the substitution, digests, ids."""
    if (ea.produced_by, ea.templates, fa.findings_policy, fa.produced_by) != _PINNED:
        raise ExplanationMismatch("unpinned explanation, template or findings version")
    _completeness(ea, fa)
    if ea.content.rendered_body.count(SLOT) != 1:
        raise ExplanationMismatch("rendered_body must hold the time slot exactly once")
    if SLOT in ea.rendered_text or ea.rendered_text != ea.content.rendered_body.replace(SLOT, utc_text(fa.as_of)):
        raise ExplanationMismatch("rendered_text is not the body with the slot filled from as_of")
    if ea.as_of != fa.as_of or ea.findings_id != fa.findings_id:
        raise ExplanationMismatch("explanation is not bound to these findings")
    digest = content_digest(ea.content, ea.templates)
    if ea.explanation_content_digest != digest or ea.explanation_id != explanation_id(fa.findings_id, digest, ea.templates):
        raise ExplanationMismatch("explanation digest or id mismatch")
    if ea.rendered_text_digest != _text_digest(ea.rendered_text):
        raise ExplanationMismatch("rendered text digest mismatch")


def build_explanation(fa: FindingsArtifact) -> ExplanationArtifact:
    indented = _statements(fa)
    statements = tuple(s for _, s in indented)
    limitations = _limitations(fa)
    lines = [("  " * depth) + ("- " if depth else "") + _render(s) for depth, s in indented]
    lines.append(TEMPLATES["section/limitations"])
    lines += ["  - " + TEMPLATES[f"limitation/{name}"] for name in limitations]
    body = "\n".join(lines)
    content = ExplanationContent(statements=statements, limitations=limitations, rendered_body=body)
    digest = content_digest(content, TEMPLATES_VERSION)
    text = body.replace(SLOT, utc_text(fa.as_of))
    ea = ExplanationArtifact(
        explanation_id=explanation_id(fa.findings_id, digest, TEMPLATES_VERSION), findings_id=fa.findings_id,
        as_of=fa.as_of, produced_by=EXPLANATION_PRODUCER, templates=TEMPLATES_VERSION,
        explanation_content_digest=digest, content=content, rendered_text=text, rendered_text_digest=_text_digest(text))
    _verify(ea, fa)
    return ea


def artifact_canonical(ea: ExplanationArtifact) -> Any:
    return canonical(to_plain(ea))


__all__ = ["EXPLANATION_PRODUCER", "SLOT", "TEMPLATES", "TEMPLATES_VERSION", "UNREACHABLE", "ExplanationArtifact",
           "ExplanationContent", "ExplanationMismatch", "Statement", "artifact_canonical", "build_explanation"]
