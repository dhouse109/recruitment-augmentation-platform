"""Engine request and the three mutually exclusive outcomes (runtime-local, not contracts).

* ``Assessed`` -- an ``EligibilityResult`` that the unmodified contract
  validators accepted, plus runtime provenance.
* ``Refused`` -- a designed fail-closed stop (scope, reference, structure,
  source integrity/authorization, contradictory records). INTERNAL ONLY: codes
  must not be shown to callers or reviewers.
* ``Errored`` -- an engine or request defect. Never converted into a refusal or
  an eligibility outcome.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from pydantic import AwareDatetime

from rap_contracts.eligibility import EligibilityResult, PolicyPin
from rap_contracts.models import CandidateId, ContractModel, OpportunityId, OrganizationId
from rap_contracts.review import PrincipalId

from .provenance import AssessmentProvenance


class EligibilityRequest(ContractModel):
    """Assess ONE candidate for ONE opportunity under ONE explicitly pinned policy version.

    ``principal_id`` is an opaque caller identifier for source checks; passing it
    is not authentication (a real deployment derives it from Drupal). ``as_of``
    must be timezone-aware; it becomes ``evaluated_at`` after UTC normalization.
    """

    organization_id: OrganizationId
    candidate_id: CandidateId
    opportunity_id: OpportunityId
    policy: PolicyPin
    principal_id: PrincipalId
    as_of: AwareDatetime


class Stage(str, Enum):
    REQUEST = "request"
    REFERENCE = "reference"          # P1: targets and organization guard (no authority call)
    PROJECTION = "projection"        # P2-P3: metadata projection and organization guard (no authority call)
    STRUCTURE = "structure"          # P4: structural validators (no authority call)
    SOURCE_GATE = "source_gate"      # P5: exact-version source admission
    CONTEXT = "context"              # P6: first value-dependent validation (existing wrapper)
    RESULT = "result"                # P7-P9: decision inputs, rules, result construction
    POST_CHECK = "post_check"        # P10: wrapper post-check and provenance subset
    PROVENANCE = "provenance"        # P11: output digest and provenance record construction


#: Stages whose refusals are guaranteed to make zero authority calls.
PRE_AUTHORITY_STAGES = frozenset({Stage.REQUEST, Stage.REFERENCE, Stage.PROJECTION, Stage.STRUCTURE})


@dataclass(frozen=True)
class Refused:
    stage: Stage
    code: str
    detail: str
    authority_calls: int
    visibility: str = "internal_only"


@dataclass(frozen=True)
class Errored:
    stage: Stage
    code: str
    detail: str
    authority_calls: int


@dataclass(frozen=True)
class Assessed:
    result: EligibilityResult
    provenance: AssessmentProvenance
