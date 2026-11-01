"""Ownership graph (A5), scoped construction with a cross-scope guard (A6) and label key projection (A7).

Ownership is derived from the record graph, never declared. Candidates that no
golden case scopes (the nominal held-out candidates D and E) are
"held-out-owned". Their raw records are parsed (the eligibility layer is
shared) and their owner and identifier fields are read so they can be
classified and later scanned for; they are never constructed as contract
models, never reach the engine or the validator, and never appear in an
artifact.

Labels (``eligibility_results``) are never constructed either. Only the key
fields of the label a step names are read (``project_label_key``); the label's
decision, rule outcomes, citations and timestamps are not read by the runner.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from pydantic import ValidationError

from rap_contracts.claims import CandidateClaim, ClaimVocabulary, ProgramParticipation
from rap_contracts.eligibility import EligibilityContext, OpportunityRequirement, PolicyPin, PolicySet
from rap_contracts.evaluation import EvaluationCase
from rap_contracts.evidence import EvidenceRecord, index_evidence
from rap_contracts.invariants import ContractRecordSet
from rap_contracts.models import (
    Application,
    Candidate,
    CandidateProfile,
    Opportunity,
    Program,
    SourceReference,
    SourceSystem,
    SourceSystemCapabilities,
)

from . import AdmissionAbort
from .fixtures import LAYER_FILES

#: Candidate-scoped record kinds (as in the contract fixtures). Everything else is shared base.
SCOPED_KINDS = ("candidates", "profiles", "applications", "evidence", "claims", "participations",
                "eligibility_results", "chunks", "recommendations", "verifications")
#: Scoped kinds the eligibility workflow constructs. Labels, chunks, recommendations and verifications are not built.
CONSTRUCTED_KINDS = ("candidates", "profiles", "applications", "evidence", "claims", "participations")

_MODELS = {"candidates": Candidate, "profiles": CandidateProfile, "applications": Application,
           "evidence": EvidenceRecord, "claims": CandidateClaim, "participations": ProgramParticipation}


def raw_pool(layers: Mapping[str, Any]) -> dict[str, Any]:
    """Every record of the three pinned base layers, by kind (raw dicts; nothing constructed)."""
    f, e, r = (layers[n] for n in LAYER_FILES)
    extra = e["additional_records"]
    return {
        "candidates": f["candidates"] + extra["candidates"],
        "profiles": f["profiles"] + extra["profiles"],
        "applications": f["applications"] + extra["applications"],
        "programs": f["programs"],
        "opportunities": f["opportunities"],
        "policies": e["policies"],
        "requirements": e["requirements"],
        "vocabularies": e["vocabularies"],
        "evidence": e["evidence"],
        "claims": e["claims"],
        "participations": e["participations"],
        "eligibility_results": e["eligibility_results"],
        "chunks": e["chunks"],
        "chunk_store": e["chunk_store"],
        "recommendations": r["recommendations"],
        "verifications": r["verifications"],
        "capabilities": e["capabilities"],
    }


def owner_of(kind: str, record: Mapping[str, Any], pool: Mapping[str, Any], extra: Mapping[str, Any]) -> str | None:
    """Owning candidate id, or None for shared base evidence. Unresolvable ownership is an A5 abort."""
    try:
        if kind == "candidates":
            return record["id"]
        if kind in ("profiles", "applications", "claims", "participations", "eligibility_results", "recommendations"):
            return record["candidate_id"]
        if kind == "evidence":
            return record["subject"]["id"] if record["subject"]["kind"] == "candidate" else None
        if kind == "verifications":
            recs = list(pool["recommendations"]) + list(extra.get("recommendations", []))
            rec = [r for r in recs if r["id"] == record["recommendation_id"]]
            rec_owners = {r["candidate_id"] for r in rec}
            if len(rec_owners) != 1:
                raise AdmissionAbort("A5", "owner_unresolvable", f"verification {record['id']}")
            return rec_owners.pop()
        if kind == "chunks":
            sources = (list(pool["profiles"]) + list(pool["applications"])
                       + list(extra.get("profiles", [])) + list(extra.get("applications", [])))
            src = [s for s in sources if s["source_ref"]["entity"] == record["source_ref"]["entity"]
                   and s["organization_id"] == record["organization_id"]]
            src_owners = {s["candidate_id"] for s in src}  # revisions of one source share an owner
            if len(src_owners) != 1:
                raise AdmissionAbort("A5", "owner_unresolvable", f"chunk {record['id']}")
            return src_owners.pop()
    except (KeyError, TypeError):
        raise AdmissionAbort("A5", "owner_unresolvable", f"{kind} record without owner fields") from None
    raise AdmissionAbort("A5", "unknown_kind", kind)


def _identifiers(kind: str, record: Mapping[str, Any]) -> set[str]:
    """Identifiers of a held-out-owned record that must never appear in an artifact."""
    out = {record["id"]}
    entity = record.get("source_ref", {}).get("entity", {}) if isinstance(record.get("source_ref"), dict) else {}
    if entity.get("entity_id"):
        out.add(entity["entity_id"])
    if kind == "chunks" and record.get("text_pointer"):
        out.add(record["text_pointer"])
    return out


@dataclass(frozen=True)
class OwnershipGraph:
    owners: Mapping[tuple[str, str], str | None]
    golden_candidates: frozenset[str]
    held_out_candidates: frozenset[str]
    held_out_identifiers: frozenset[str]
    label_ids: frozenset[str]

    def owner(self, kind: str, record: Mapping[str, Any]) -> str | None:
        try:
            return self.owners[(kind, record["id"])]
        except KeyError:
            raise AdmissionAbort("A6", "record_not_in_ownership_graph", f"{kind}") from None


def build_ownership(pool: Mapping[str, Any], case_records: Mapping[str, Any],
                    golden_cases: Iterable[EvaluationCase]) -> OwnershipGraph:
    """A5: derive the owner of every candidate-scoped raw record in the base layers and the golden case records."""
    owners: dict[tuple[str, str], str | None] = {}
    known = {c["id"] for c in pool["candidates"]} | {c["id"] for c in case_records.get("candidates", [])}
    for kind in SCOPED_KINDS:
        for rec in list(pool[kind]) + list(case_records.get(kind, [])):
            owner = owner_of(kind, rec, pool, case_records)
            if owner is None and kind != "evidence":
                raise AdmissionAbort("A5", "owner_unresolvable", f"{kind} record without an owning candidate")
            if owner is not None and owner not in known:
                raise AdmissionAbort("A5", "owner_unknown", f"{kind} owned by an unknown candidate")
            key = (kind, rec["id"])
            # Versioned records may repeat an id (e.g. two revisions of one profile); they must share one owner.
            if key in owners and owners[key] != owner:
                raise AdmissionAbort("A5", "conflicting_owner", f"{kind} id owned by more than one candidate")
            owners[key] = owner
    golden = frozenset(c for case in golden_cases for c in case.scope.candidates)
    if not golden <= known:
        raise AdmissionAbort("A5", "scope_candidate_unknown", ",".join(sorted(golden - known)))
    held_out = frozenset(known - golden)
    identifiers: set[str] = set(held_out)
    for kind in SCOPED_KINDS:
        for rec in list(pool[kind]) + list(case_records.get(kind, [])):
            if owners[(kind, rec["id"])] in held_out:
                identifiers |= _identifiers(kind, rec)
    labels = frozenset(r["id"] for r in list(pool["eligibility_results"]) + list(case_records.get("eligibility_results", [])))
    return OwnershipGraph(owners=MappingProxyType(owners), golden_candidates=golden, held_out_candidates=held_out,
                          held_out_identifiers=frozenset(identifiers), label_ids=labels)


# ---------------------------------------------------------------------------
# Scoped construction (A6)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AdmittedScope:
    case_id: str
    candidates: frozenset[str]
    eligibility: EligibilityContext
    capabilities: Mapping[SourceSystem, SourceSystemCapabilities]
    source_refs: frozenset[SourceReference]
    constructed: frozenset[tuple[str, str]]


def construct(kind: str, raw: Mapping[str, Any], scope_candidates: frozenset[str], graph: OwnershipGraph):
    """Construct one candidate-scoped contract model, only if owned by an in-scope golden candidate."""
    owner = graph.owner(kind, raw)
    if owner is not None and owner in graph.held_out_candidates:
        raise AdmissionAbort("A6", "held_out_construction", f"a held-out-owned {kind} record reached construction")
    if owner is not None and owner not in scope_candidates:
        raise AdmissionAbort("A6", "cross_scope_construction", f"a {kind} record owned outside the case scope")
    if owner is None and kind != "evidence":
        raise AdmissionAbort("A6", "unowned_scoped_record", kind)
    try:
        return _MODELS[kind].model_validate(raw)
    except ValidationError as exc:
        raise AdmissionAbort("A6", "model_validation_error", f"{kind}: {exc.error_count()} error(s)") from None


def select(kind: str, pool: Mapping[str, Any], graph: OwnershipGraph, cands: frozenset[str]) -> list[Mapping[str, Any]]:
    """Raw records of one scoped kind owned by an in-scope candidate (shared evidence handled separately)."""
    return [r for r in pool[kind] if graph.owner(kind, r) in cands]


def build_scope(case: EvaluationCase, pool: Mapping[str, Any], case_records: Mapping[str, Any],
                graph: OwnershipGraph) -> AdmittedScope:
    cands = frozenset(case.scope.candidates)
    if not cands <= graph.golden_candidates or cands & graph.held_out_candidates:
        raise AdmissionAbort("A6", "scope_not_golden", case.id)
    chosen: dict[str, list] = {kind: select(kind, pool, graph, cands) for kind in CONSTRUCTED_KINDS}
    for rid in case.scope.include_records:
        hits = [(k, r) for k in SCOPED_KINDS for r in case_records.get(k, []) if r["id"] == rid]
        if len(hits) != 1:
            raise AdmissionAbort("A5", "include_record_unresolvable", f"{case.id}: {rid}")
        kind, rec = hits[0]
        if graph.owner(kind, rec) not in cands:
            raise AdmissionAbort("A5", "include_record_out_of_scope", f"{case.id}: {rid}")
        if kind not in CONSTRUCTED_KINDS:
            raise AdmissionAbort("A6", "include_record_kind_not_supported", f"{case.id}: {kind}")
        chosen[kind].append(rec)
    built = {kind: tuple(construct(kind, r, cands, graph) for r in chosen[kind]) for kind in CONSTRUCTED_KINDS}
    shared_evidence = [e for e in pool["evidence"] if graph.owner("evidence", e) is None]
    try:
        records = ContractRecordSet(
            candidates=built["candidates"], profiles=built["profiles"], applications=built["applications"],
            programs=tuple(Program.model_validate(r) for r in pool["programs"]),
            opportunities=tuple(Opportunity.model_validate(r) for r in pool["opportunities"]))
        eligibility = EligibilityContext(
            records=records,
            policies=tuple(PolicySet.model_validate(r) for r in pool["policies"]),
            requirements=tuple(OpportunityRequirement.model_validate(r) for r in pool["requirements"]),
            claims=built["claims"],
            participations=built["participations"],
            evidence=index_evidence(list(built["evidence"]) + [EvidenceRecord.model_validate(e) for e in shared_evidence]),
            vocabularies=tuple(ClaimVocabulary.model_validate(r) for r in pool["vocabularies"]))
        capabilities = MappingProxyType({c.source_system: c for c in (
            SourceSystemCapabilities.model_validate(x) for x in pool["capabilities"])})
    except ValidationError as exc:
        raise AdmissionAbort("A6", "model_validation_error", f"shared base: {exc.error_count()} error(s)") from None
    refs: set[SourceReference] = set()
    for rec in records.profiles + records.applications + records.opportunities + records.programs:
        refs.add(rec.source_ref)
    refs |= {e.source_ref for e in eligibility.evidence.values()}
    refs |= {r.source_ref for r in eligibility.requirements} | {p.source_ref for p in eligibility.policies}
    constructed = frozenset((k, r["id"]) for k in CONSTRUCTED_KINDS for r in chosen[k])
    return AdmittedScope(case_id=case.id, candidates=cands, eligibility=eligibility, capabilities=capabilities,
                         source_refs=frozenset(refs), constructed=constructed)


# ---------------------------------------------------------------------------
# Label key projection (A7)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LabelKey:
    """The only label content the runner reads: the assessment key."""

    label_id: str
    organization_id: str
    candidate_id: str
    opportunity_id: str
    policy: PolicyPin

    def canonical(self) -> dict:
        return {"label_id": self.label_id, "organization_id": self.organization_id, "candidate_id": self.candidate_id,
                "opportunity_id": self.opportunity_id, "policy": self.policy.model_dump(mode="json")}

    def assessment(self) -> tuple:
        p = self.policy
        return (self.organization_id, self.candidate_id, self.opportunity_id, p.policy_set_id, p.version, p.source_ref)


#: Fields of a label record the runner may read.
LABEL_KEY_FIELDS = ("id", "organization_id", "candidate_id", "opportunity_id", "policy")


def project_label_key(raw: Mapping[str, Any]) -> LabelKey:
    try:
        return LabelKey(label_id=raw["id"], organization_id=raw["organization_id"], candidate_id=raw["candidate_id"],
                        opportunity_id=raw["opportunity_id"], policy=PolicyPin.model_validate(raw["policy"]))
    except (KeyError, TypeError, ValidationError):
        raise AdmissionAbort("A7", "label_key_invalid", "a label lacks a valid key") from None
