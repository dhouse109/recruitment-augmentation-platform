"""TEST-ONLY synthetic world for the PR-S1 engine tests.

All records are new, test-local and fictional (``*_s1_*`` identifiers). No
nominal held-out (D/E/F) record or expected label is used. The authority here
is a synthetic stand-in: answers are declarations, not Drupal authorization.

``World`` holds plain dicts so tests can mutate a scenario before ``build()``
validates it through the unmodified contract models.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from rap_contracts.claims import CandidateClaim, ClaimVocabulary, ProgramParticipation
from rap_contracts.eligibility import EligibilityContext, OpportunityRequirement, PolicyPin, PolicySet
from rap_contracts.evidence import EvidenceRecord, index_evidence
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

from rap_baseline import EligibilityRequest, assess

ORG = "org_s1_alpha"
ORG2 = "org_s1_beta"
PRINCIPAL = "principal_s1_coordinator"
OTHER_PRINCIPAL = "principal_s1_second_coordinator"
AS_OF = datetime(2026, 11, 2, 15, 0, tzinfo=timezone.utc)
CHECKED_AT = datetime(2026, 11, 2, 14, 59, tzinfo=timezone.utc)
EASTERN = timezone(timedelta(hours=-5))
SNAPSHOT_METHOD = "sha256-canonical-json/v1"

ANA, BEN, CY = "candidate_s1_ana", "candidate_s1_ben", "candidate_s1_cy"
DATA, WEB, OPS, OTHER, BETA_JOB = ("opportunity_s1_data", "opportunity_s1_web", "opportunity_s1_ops",
                                   "opportunity_s1_other", "opportunity_s1_beta_job")
PILOT, BETA_POLICY = ("policy_s1_pilot", 1), ("policy_s1_beta", 1)
PATHWAYS, OTHER_PROGRAM, BETA_PROGRAM = "program_s1_pathways", "program_s1_other", "program_s1_beta"
HAS, LACKS = {"kind": "skill", "presence": "has"}, {"kind": "skill", "presence": "lacks"}


def hours(n: int) -> dict:
    return {"kind": "availability", "hours_per_week": n}


def ref(entity_type: str, entity_id: str, revision: str, org: str = ORG) -> dict:
    return {"organization_id": org, "entity": {"source_system": "fixture", "entity_type": entity_type, "entity_id": entity_id},
            "version": {"kind": "native_revision", "revision_id": revision}}


def snapshot(entity_type: str, entity_id: str, digit: str, org: str = ORG,
             captured_at: datetime = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)) -> dict:
    return {"organization_id": org, "entity": {"source_system": "fixture", "entity_type": entity_type, "entity_id": entity_id},
            "version": {"kind": "logical_snapshot", "method": SNAPSHOT_METHOD, "token": "sha256:" + digit * 64,
                        "captured_at": captured_at.isoformat(), "captured_by": "s1-test-adapter/1"}}


def capabilities_doc(policy_snapshot: bool = False) -> dict:
    native = ["application", "candidate_profile", "opportunity", "policy_set", "program_enrollment", "skill_assessment"]
    snap = ["program", "user"]
    if policy_snapshot:
        native.remove("policy_set")
        snap.append("policy_set")
    return {"source_system": "fixture", "declared_by": "s1-test-adapter/1", "identity_entity_types": ["user"],
            "native_revision_entity_types": native, "logical_snapshot_entity_types": snap,
            "snapshot_methods": [SNAPSHOT_METHOD], "participation_authority_entity_types": ["program_enrollment"],
            "verification_entity_types": ["skill_assessment"]}


PROFILE_REF = {ANA: ("5101", "21"), BEN: ("5102", "22"), CY: ("5103", "23")}
APP_REF = {ANA: ("7101", "71"), BEN: ("7102", "72"), CY: ("7103", "73")}


class World:
    """A consistent synthetic scenario. Mutate the lists, then ``build()``."""

    def __init__(self) -> None:
        self.caps = capabilities_doc()
        self.candidates = [
            {"id": ANA, "organization_id": ORG, "identity_source": {"source_system": "fixture", "entity_type": "user", "entity_id": "u101"}},
            {"id": BEN, "organization_id": ORG, "identity_source": {"source_system": "fixture", "entity_type": "user", "entity_id": "u102"}},
            {"id": CY, "organization_id": ORG2, "identity_source": {"source_system": "fixture", "entity_type": "user", "entity_id": "u103"}},
        ]
        self.programs = [
            {"id": PATHWAYS, "organization_id": ORG, "source_ref": snapshot("program", "3101", "1")},
            {"id": OTHER_PROGRAM, "organization_id": ORG, "source_ref": snapshot("program", "3102", "2")},
            {"id": BETA_PROGRAM, "organization_id": ORG2, "source_ref": snapshot("program", "3103", "3", org=ORG2)},
        ]
        self.opportunities = [
            self._opp(DATA, "active", PATHWAYS, "4101", "11"),
            self._opp(WEB, "active", PATHWAYS, "4102", "12"),
            self._opp(OPS, "paused", PATHWAYS, "4103", "13"),
            self._opp(OTHER, "active", OTHER_PROGRAM, "4104", "14"),
            {"id": BETA_JOB, "organization_id": ORG2, "opportunity_type": "job", "status": "active",
             "source_ref": ref("opportunity", "4201", "15", org=ORG2)},
        ]
        self.profiles = [self._profile(c, o) for c, o in ((ANA, ORG), (BEN, ORG), (CY, ORG2))]
        self.applications = [self._application(ANA, ORG, DATA, PATHWAYS), self._application(BEN, ORG, DATA, PATHWAYS),
                             self._application(CY, ORG2, BETA_JOB, None)]
        self.policies = [
            {"id": PILOT[0], "organization_id": ORG, "version": 1, "source_ref": ref("policy_set", "8101", "81"),
             "program_id": PATHWAYS, "rules": [
                 {"rule_id": "S1-ACTIVE-001", "rule_version": 1, "kind": "opportunity_status_active"},
                 {"rule_id": "S1-PROGRAM-002", "rule_version": 1, "kind": "program_participation_confirmed", "program_id": PATHWAYS},
                 {"rule_id": "S1-AVAIL-003", "rule_version": 1, "kind": "availability_meets_required_hours"},
                 {"rule_id": "S1-SKILL-004", "rule_version": 1, "kind": "mandatory_qualification_evidenced"}]},
            {"id": BETA_POLICY[0], "organization_id": ORG2, "version": 1, "source_ref": ref("policy_set", "8201", "82", org=ORG2),
             "rules": [{"rule_id": "S1B-ACTIVE-001", "rule_version": 1, "kind": "opportunity_status_active"},
                       {"rule_id": "S1B-AVAIL-002", "rule_version": 1, "kind": "availability_meets_required_hours"}]},
        ]
        self.vocabularies = [
            {"id": "vocabulary_s1", "organization_id": ORG, "version": 1,
             "skills": ["data_analysis", "python", "spreadsheets", "web_content"],
             "experience_areas": ["data_projects"], "interest_areas": ["data"], "work_preferences": ["remote"]},
            {"id": "vocabulary_s1_beta", "organization_id": ORG2, "version": 1, "skills": ["spreadsheets"],
             "experience_areas": ["retail"], "interest_areas": ["operations"], "work_preferences": ["onsite"]},
        ]
        self.requirements = []
        self.add_hours_requirement(DATA, 12)
        self.add_skill_requirement(DATA, "python")
        self.add_hours_requirement(WEB, 10)
        self.add_hours_requirement(OPS, 8)
        self.add_hours_requirement(OTHER, 8)
        self.requirements.append({"id": "requirement_s1_beta_job_hours", "organization_id": ORG2, "opportunity_id": BETA_JOB,
                                  "requirement": {"kind": "weekly_hours", "hours_per_week": 30},
                                  "source_ref": ref("opportunity", "4201", "15", org=ORG2), "field_path": "schedule.weekly_hours"})
        self.evidence: list[dict] = []
        self.claims: list[dict] = []
        self.participations: list[dict] = []
        # Ana: declared 20 h; python declared twice (profile + application); confirmed participation;
        # an unrelated work preference on its own entity (never selected).
        self.add_statement(ANA, "evidence_s1_ana_hours", "availability.weekly_hours")
        self.add_claim("claim_s1_ana_hours", ANA, None, "declared", hours(20), ["evidence_s1_ana_hours"])
        self.add_statement(ANA, "evidence_s1_ana_python_profile", "skills.python")
        self.add_statement(ANA, "evidence_s1_ana_python_app", "answers.python", source="application")
        self.add_claim("claim_s1_ana_python_profile", ANA, "python", "declared", HAS, ["evidence_s1_ana_python_profile"])
        self.add_claim("claim_s1_ana_python_app", ANA, "python", "declared", HAS, ["evidence_s1_ana_python_app"])
        self.add_participation("participation_s1_ana", ANA, PATHWAYS, "confirmed", "6101", "31")
        self.add_evidence("evidence_s1_ana_remote", ANA, "candidate_statement", ref("candidate_profile", "5101", "20"),
                          "preferences.remote")
        self.add_claim("claim_s1_ana_remote", ANA, "remote", "declared", {"kind": "work_preference", "stance": "prefers"},
                       ["evidence_s1_ana_remote"], claim_type="work_preference")
        # Ben: availability unknown; python contested (profile 'has' vs application 'lacks'); confirmed participation.
        self.add_claim("claim_s1_ben_hours", BEN, None, "unknown")
        self.add_statement(BEN, "evidence_s1_ben_python_profile", "skills.python")
        self.add_statement(BEN, "evidence_s1_ben_python_app", "answers.python", source="application")
        self.add_claim("claim_s1_ben_python", BEN, "python", "contested", alternatives=[
            {"value": HAS, "evidence_ids": ["evidence_s1_ben_python_profile"]},
            {"value": LACKS, "evidence_ids": ["evidence_s1_ben_python_app"]}])
        self.add_participation("participation_s1_ben", BEN, PATHWAYS, "confirmed", "6102", "32")
        # Cy (other organization): declared 35 h.
        self.add_statement(CY, "evidence_s1_cy_hours", "availability.weekly_hours", org=ORG2)
        self.add_claim("claim_s1_cy_hours", CY, None, "declared", hours(35), ["evidence_s1_cy_hours"], org=ORG2,
                       vocabulary="vocabulary_s1_beta")

    # --- record helpers ---------------------------------------------------
    @staticmethod
    def _opp(opp_id, status, program, entity, revision):
        return {"id": opp_id, "organization_id": ORG, "opportunity_type": "internship", "status": status,
                "program_id": program, "source_ref": ref("opportunity", entity, revision)}

    @staticmethod
    def _profile(cand, org):
        entity, rev = PROFILE_REF[cand]
        return {"id": "profile_" + cand.removeprefix("candidate_"), "organization_id": org, "candidate_id": cand,
                "source_ref": ref("candidate_profile", entity, rev, org=org)}

    @staticmethod
    def _application(cand, org, opp, program):
        entity, rev = APP_REF[cand]
        p_entity, p_rev = PROFILE_REF[cand]
        target = {"opportunity_id": opp}
        if program:
            target["program_id"] = program
        return {"id": "application_" + cand.removeprefix("candidate_"), "organization_id": org, "candidate_id": cand,
                "target": target, "status": "submitted", "source_ref": ref("application", entity, rev, org=org),
                "submission": {"submitted_at": "2026-10-30T14:00:00Z", "profile_id": "profile_" + cand.removeprefix("candidate_"),
                               "profile_ref": ref("candidate_profile", p_entity, p_rev, org=org),
                               "application_version": {"kind": "native_revision", "revision_id": rev}}}

    def opportunity(self, opp_id: str) -> dict:
        return next(o for o in self.opportunities if o["id"] == opp_id)

    def policy(self, pin=PILOT) -> dict:
        return next(p for p in self.policies if (p["id"], p["version"]) == pin)

    def add_hours_requirement(self, opp_id: str, n: int, req_id: str | None = None) -> str:
        opp = self.opportunity(opp_id)
        rid = req_id or f"requirement_s1_{opp_id.removeprefix('opportunity_s1_')}_hours"
        self.requirements.append({"id": rid, "organization_id": opp["organization_id"], "opportunity_id": opp_id,
                                  "requirement": {"kind": "weekly_hours", "hours_per_week": n},
                                  "source_ref": copy.deepcopy(opp["source_ref"]), "field_path": "schedule.weekly_hours"})
        return rid

    def add_skill_requirement(self, opp_id: str, code: str) -> str:
        opp = self.opportunity(opp_id)
        rid = f"requirement_s1_{opp_id.removeprefix('opportunity_s1_')}_{code}"
        self.requirements.append({"id": rid, "organization_id": opp["organization_id"], "opportunity_id": opp_id,
                                  "requirement": {"kind": "mandatory_qualification",
                                                  "vocabulary": {"id": "vocabulary_s1", "version": 1}, "skill_code": code},
                                  "source_ref": copy.deepcopy(opp["source_ref"]), "field_path": "qualifications.mandatory"})
        return rid

    def remove_requirement(self, req_id: str) -> None:
        self.requirements = [r for r in self.requirements if r["id"] != req_id]

    def add_evidence(self, eid, cand, basis, source_ref, path, org=ORG) -> str:
        self.evidence.append({"id": eid, "organization_id": org, "subject": {"kind": "candidate", "id": cand},
                              "basis": basis, "source_ref": source_ref, "field_path": path})
        return eid

    def add_statement(self, cand, eid, path, source="profile", org=ORG) -> str:
        entity, rev = (PROFILE_REF if source == "profile" else APP_REF)[cand]
        etype = "candidate_profile" if source == "profile" else "application"
        return self.add_evidence(eid, cand, "candidate_statement", ref(etype, entity, rev, org=org), path, org=org)

    def add_verification(self, cand, eid, entity_id, path, org=ORG) -> str:
        return self.add_evidence(eid, cand, "independent_verification", ref("skill_assessment", entity_id, "1", org=org),
                                 path, org=org)

    def add_claim(self, cid, cand, code, state, value=None, evidence_ids=(), alternatives=None, inferred_by=None,
                  org=ORG, vocabulary="vocabulary_s1", claim_type=None) -> str:
        claim_type = claim_type or ("availability" if code is None else "skill")
        c: dict[str, Any] = {"id": cid, "organization_id": org, "candidate_id": cand,
                             "vocabulary": {"id": vocabulary, "version": 1}, "claim_type": claim_type, "state": state}
        if code is not None:
            c["subject_code"] = code
        if value is not None:
            c["value"] = value
        if evidence_ids:
            c["evidence_ids"] = list(evidence_ids)
        if alternatives:
            c["alternatives"] = alternatives
        if state == "inferred":
            c["inferred_by"] = inferred_by or "s1-synthetic-inference/1"
        self.claims.append(c)
        return cid

    def remove_claim(self, cid: str) -> None:
        self.claims = [c for c in self.claims if c["id"] != cid]

    def claim(self, cid: str) -> dict:
        return next(c for c in self.claims if c["id"] == cid)

    def evidence_record(self, eid: str) -> dict:
        return next(e for e in self.evidence if e["id"] == eid)

    def add_participation(self, pid, cand, program, status, entity, revision, org=ORG) -> str:
        eid = f"evidence_s1_{pid.removeprefix('participation_s1_')}_enrollment"
        self.add_evidence(eid, cand, "authority_record", ref("program_enrollment", entity, revision, org=org), "status", org=org)
        self.participations.append({"id": pid, "organization_id": org, "candidate_id": cand, "program_id": program,
                                    "status": status, "evidence_ids": [eid]})
        return pid

    # --- build --------------------------------------------------------------
    def build(self) -> tuple[EligibilityContext, dict]:
        caps = SourceSystemCapabilities.model_validate(self.caps)
        records = ContractRecordSet(
            candidates=tuple(Candidate.model_validate(r) for r in self.candidates),
            profiles=tuple(CandidateProfile.model_validate(r) for r in self.profiles),
            programs=tuple(Program.model_validate(r) for r in self.programs),
            opportunities=tuple(Opportunity.model_validate(r) for r in self.opportunities),
            applications=tuple(Application.model_validate(r) for r in self.applications),
        )
        ctx = EligibilityContext(
            records=records,
            policies=tuple(PolicySet.model_validate(r) for r in self.policies),
            requirements=tuple(OpportunityRequirement.model_validate(r) for r in self.requirements),
            claims=tuple(CandidateClaim.model_validate(r) for r in self.claims),
            participations=tuple(ProgramParticipation.model_validate(r) for r in self.participations),
            evidence=index_evidence(EvidenceRecord.model_validate(r) for r in self.evidence),
            vocabularies=tuple(ClaimVocabulary.model_validate(r) for r in self.vocabularies),
        )
        return ctx, {SourceSystem.FIXTURE: caps}

    def request(self, cand=ANA, opp=DATA, pin=PILOT, principal=PRINCIPAL, as_of=AS_OF, org=None) -> EligibilityRequest:
        policy = PolicySet.model_validate(self.policy(pin))
        return EligibilityRequest(organization_id=org or policy.organization_id, candidate_id=cand, opportunity_id=opp,
                                  policy=PolicyPin(policy_set_id=policy.id, version=policy.version, source_ref=policy.source_ref),
                                  principal_id=principal, as_of=as_of)


@dataclass
class StubAuthority:
    """Synthetic source authority. Default: current + allowed for the listed principals; overrides per ref."""

    principals: tuple[str, ...] = (PRINCIPAL, OTHER_PRINCIPAL)
    overrides: dict = field(default_factory=dict)  # SourceReference -> (VersionStatus, AccessStatus)
    substitute: dict = field(default_factory=dict)  # SourceReference -> SourceReference
    raise_for: set = field(default_factory=set)
    log: list | None = None
    calls: list = field(default_factory=list)

    def check(self, principal_id: str, ref_: SourceReference) -> SourceCheckResult:
        self.calls.append(ref_)
        if self.log is not None:
            self.log.append(("check", ref_))
        if ref_ in self.raise_for:
            raise RuntimeError("synthetic authority unreachable")
        answered = self.substitute.get(ref_, ref_)
        if principal_id not in self.principals:
            version, access = VersionStatus.UNAVAILABLE, AccessStatus.DENIED
        else:
            version, access = self.overrides.get(ref_, (VersionStatus.CURRENT, AccessStatus.ALLOWED))
        return SourceCheckResult(source=answered, checked_at=CHECKED_AT, checked_by="s1-test-authority/1",
                                 version_status=version, access_status=access)

    def deny(self, ref_: SourceReference | dict) -> None:
        self.overrides[as_ref(ref_)] = (VersionStatus.CURRENT, AccessStatus.DENIED)

    def set(self, ref_: SourceReference | dict, version: VersionStatus, access: AccessStatus = AccessStatus.ALLOWED) -> None:
        self.overrides[as_ref(ref_)] = (version, access)


def as_ref(value: SourceReference | dict) -> SourceReference:
    return value if isinstance(value, SourceReference) else SourceReference.model_validate(value)


def run(world: World, cand=ANA, opp=DATA, pin=PILOT, authority: StubAuthority | None = None, **kw):
    ctx, caps = world.build()
    authority = authority if authority is not None else StubAuthority()
    return assess(world.request(cand, opp, pin, **kw), ctx, authority, caps), authority


def outcome_map(result) -> dict:
    """rule_id -> (result, reason, claim_ids, participation_ids, requirement_ids)."""
    return {o.rule_id: (o.result.value, o.reason_code, o.claim_ids, o.participation_ids, o.requirement_ids)
            for o in result.rule_outcomes}
