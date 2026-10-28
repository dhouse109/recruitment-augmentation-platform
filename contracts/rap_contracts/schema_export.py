"""Reproducible JSON Schema generation for the Contract v0.2 reference contracts.

Usage (from the ``contracts/`` directory):

    python -m rap_contracts.schema_export          # (re)write schemas/
    python -m rap_contracts.schema_export --check  # exit 1 on drift

Output is deterministic for a given Pydantic version: keys sorted, 2-space
indent, trailing newline. The Pydantic version is pinned in requirements.txt
because generator changes can alter output.

JSON Schema expresses structure only. Cross-record invariants (organization
equality across records, identity uniqueness, lifecycle transitions, version
kind vs. capability, source freshness/authorization) are NOT expressible here
and are enforced only by the Python invariant functions -- and, ultimately,
by the authoritative service.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import BaseModel

from .adjudication import AdjudicationRecord, ReviewerRubric
from .claims import CandidateClaim, ClaimVocabulary, ProgramParticipation
from .eligibility import EligibilityResult, OpportunityRequirement, PolicySet
from .evaluation import CaseObservation, EvaluationCase, EvaluationDatasetManifest, EvaluationRun
from .evidence import EvidenceRecord, RetrievalChunk, RetrievalRequest, RetrievalResponse
from .promotion import HeldOutGateAttestation, MetricDefinitionSet, PromotionDecision, SafetyGatePolicy
from .recommendation import Recommendation, VerificationResult
from .review import (
    AuditEvent,
    HumanReviewCommand,
    ReviewCorrectionCommand,
    ReviewDecision,
    ReviewOutcome,
    ReviewReasonVocabulary,
)
from .models import (
    CONTRACT_VERSION,
    Application,
    Candidate,
    CandidateProfile,
    Opportunity,
    Program,
    SourceCheckResult,
    SourceReference,
)

#: Stable identifier namespace. ``$id`` values are identifiers, not fetchable URLs.
SCHEMA_ID_BASE = "https://github.com/dhouse109/recruitment-augmentation-platform/contracts/schemas"
JSON_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"

EXPORTED_MODELS: dict[str, type[BaseModel]] = {
    "application": Application,
    "candidate": Candidate,
    "candidate-profile": CandidateProfile,
    "opportunity": Opportunity,
    "program": Program,
    "source-check-result": SourceCheckResult,
    "source-reference": SourceReference,
    # Added in 0.2.0-dev.foundations.2 (D-004.05/.06/.10/.11)
    "candidate-claim": CandidateClaim,
    "claim-vocabulary": ClaimVocabulary,
    "eligibility-result": EligibilityResult,
    "evidence-record": EvidenceRecord,
    "opportunity-requirement": OpportunityRequirement,
    "policy-set": PolicySet,
    "program-participation": ProgramParticipation,
    "retrieval-chunk": RetrievalChunk,
    "retrieval-request": RetrievalRequest,
    "retrieval-response": RetrievalResponse,
    # Added in 0.2.0-dev.foundations.3 (D-004.03/.04/.08/.09)
    "audit-event": AuditEvent,
    "human-review-command": HumanReviewCommand,
    "recommendation": Recommendation,
    "review-correction-command": ReviewCorrectionCommand,
    "review-decision": ReviewDecision,
    "review-outcome": ReviewOutcome,
    "review-reason-vocabulary": ReviewReasonVocabulary,
    "verification-result": VerificationResult,
    # Added in 0.2.0-dev.foundations.4 (D-004.12)
    "adjudication-record": AdjudicationRecord,
    "case-observation": CaseObservation,
    "evaluation-case": EvaluationCase,
    "evaluation-dataset-manifest": EvaluationDatasetManifest,
    "evaluation-run": EvaluationRun,
    "held-out-gate-attestation": HeldOutGateAttestation,
    "metric-definition-set": MetricDefinitionSet,
    "promotion-decision": PromotionDecision,
    "reviewer-rubric": ReviewerRubric,
    "safety-gate-policy": SafetyGatePolicy,
}

DEFAULT_SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schemas"


def schema_id(name: str) -> str:
    return f"{SCHEMA_ID_BASE}/{CONTRACT_VERSION}/{name}.schema.json"


def build_schema(name: str, model: type[BaseModel]) -> dict:
    body = model.model_json_schema(mode="validation")
    return {
        "$schema": JSON_SCHEMA_DIALECT,
        "$id": schema_id(name),
        "x-contract-version": CONTRACT_VERSION,
        "x-contract-status": "partial development version; proposed; NOT frozen",
        **body,
    }


def render(schema: dict) -> str:
    return json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def expected_files() -> dict[str, str]:
    return {f"{name}.schema.json": render(build_schema(name, model)) for name, model in EXPORTED_MODELS.items()}


def write_schemas(directory: Path = DEFAULT_SCHEMA_DIR) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    written = []
    for filename, text in expected_files().items():
        path = directory / filename
        path.write_text(text, encoding="utf-8", newline="\n")
        written.append(path)
    return written


def find_drift(directory: Path = DEFAULT_SCHEMA_DIR) -> list[str]:
    """Return human-readable drift problems; empty list means committed schemas match."""
    problems: list[str] = []
    expected = expected_files()
    present = {p.name for p in directory.glob("*.schema.json")} if directory.is_dir() else set()
    for filename in sorted(set(expected) - present):
        problems.append(f"missing: {filename}")
    for filename in sorted(present - set(expected)):
        problems.append(f"unexpected: {filename}")
    for filename in sorted(set(expected) & present):
        if (directory / filename).read_text(encoding="utf-8") != expected[filename]:
            problems.append(f"changed: {filename}")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="report drift instead of writing")
    parser.add_argument("--dir", type=Path, default=DEFAULT_SCHEMA_DIR)
    args = parser.parse_args(argv)
    if args.check:
        problems = find_drift(args.dir)
        for line in problems:
            print(line)
        print("schema drift: NONE" if not problems else f"schema drift: {len(problems)} problem(s)")
        return 1 if problems else 0
    for path in write_schemas(args.dir):
        print(f"wrote {path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
