"""A8: the fixed applicability class table for the 26 pinned golden cases (plan section 3, decision E1 strict).

Only classes A and B are executed. Every other case is recorded as ``not_run``
with its class and reason. Selection version 1 is exactly g002, g003, g008 and
g025; any change to the table or the selection is a new selection version.
"""

from __future__ import annotations

from typing import Iterable

from rap_contracts.evaluation import EvaluationCase, StepRole
from rap_contracts.source_checks import canonical_json_sha256

from . import AdmissionAbort

SELECTION_VERSION = 1

CLASS_REASONS = {
    "A": "directly executable: one target eligibility_support step (engine, T3)",
    "B": "prerequisite adapter: context_validation prerequisite (reference validator, T2) then engine targets (T3)",
    "C": "eligibility only as a prerequisite: needs a verifier or recommendation component (not implemented)",
    "D": "retrieval admission: no retrieval component in this runner",
    "E": "review commands: no review-write service in this runner",
    "F": "verification only: no verifier component in this runner",
    "G": "record-set validation: no generating component exercised",
}

_CLASSES = {
    "A": ("g002", "g003", "g008"),
    "B": ("g025",),
    "C": ("g001", "g005b", "g021", "g023", "g024"),
    "D": ("g004", "g006", "g007", "g009", "g010", "g011"),
    "E": ("g012", "g013", "g014", "g015", "g016", "g017", "g018", "g019", "g020"),
    "F": ("g005a",),
    "G": ("g022",),
}
CLASS_TABLE: dict[str, str] = {f"evalcase_{c}": cls for cls, cases in _CLASSES.items() for c in cases}
EXECUTED_CLASSES = frozenset({"A", "B"})
SELECTION: tuple[str, ...] = ("evalcase_g002", "evalcase_g003", "evalcase_g008", "evalcase_g025")
#: F3: these two cases share one scenario (B x data); they are one distinct assessment.
F3_SHARED_SCENARIO: tuple[str, ...] = ("evalcase_g002", "evalcase_g008")


def class_table_digest() -> str:
    return canonical_json_sha256({"v": "rap-evaluation.class-table/1", "selection_version": SELECTION_VERSION,
                                  "table": dict(sorted(CLASS_TABLE.items())), "selection": list(SELECTION),
                                  "reasons": CLASS_REASONS})


def _shape(case: EvaluationCase) -> None:
    cls = CLASS_TABLE[case.id]
    ops = [(s.role, s.operation) for s in case.steps]
    if cls == "A":
        ok = ops == [(StepRole.TARGET, "eligibility_support")]
    else:
        ok = (len(ops) >= 2 and ops[0] == (StepRole.PREREQUISITE, "context_validation")
              and all(o == (StepRole.TARGET, "eligibility_support") for o in ops[1:]))
    if not ok:
        raise AdmissionAbort("A8", "selected_case_shape", case.id)
    if case.assertions or case.initial_state.review_store != "none":
        raise AdmissionAbort("A8", "selected_case_has_assertions_or_store", case.id)
    if any(s.safety for s in case.steps):
        raise AdmissionAbort("A8", "selected_case_has_safety_expectations", case.id)


def check_applicability(cases: Iterable[EvaluationCase]) -> tuple[EvaluationCase, ...]:
    """Every pinned case is classified, and the executed selection is exactly ``SELECTION``."""
    cases = tuple(cases)
    ids = {c.id for c in cases}
    if ids != set(CLASS_TABLE) or len(ids) != len(cases):
        raise AdmissionAbort("A8", "classification_mismatch",
                             f"unclassified={sorted(ids - set(CLASS_TABLE))} missing={sorted(set(CLASS_TABLE) - ids)}")
    selected = tuple(c for c in cases if CLASS_TABLE[c.id] in EXECUTED_CLASSES)
    if tuple(c.id for c in selected) != SELECTION:
        raise AdmissionAbort("A8", "selection_mismatch", ",".join(c.id for c in selected))
    for case in selected:
        _shape(case)
    return selected
