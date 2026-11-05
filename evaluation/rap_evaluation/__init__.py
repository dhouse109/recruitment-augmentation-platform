"""Slice 0 PR-S3b offline deterministic evaluation runner (``rap-evaluation.runner``).

Runs the merged Slice 0 engine (``rap_baseline.assess``) on four pinned golden
cases (g002, g003, g008, g025), validates each GENERATED ``EligibilityResult``
with the contract's ``check_eligibility_result`` and compares it with the case's
PROPOSED, unadjudicated label. Everything else in the golden manifest is
recorded as ``not_run``.

Version 0.2.0 (F3, RAP-F3-PLAN-2026-11-04 rev. 1.1) reads golden manifest
``evalset_golden`` v2, in which g002 and g008 are separate scenarios, and the
draft safety-gate policy v3. Runs of 0.1.0 against golden v1 are reproducible
only at their recorded commit and are not comparable with 0.2.0 runs.

What a run establishes: the engine executed on pinned synthetic golden inputs
(evidence tier T3, basis ``deterministic_baseline_execution``) and its results
agreed or disagreed with proposed labels. What it does NOT establish: correctness,
accuracy, safety, live Drupal authorization or currentness (T4), or any metric.
The source authority is a fixture mock. No held-out case file is opened, no
metric, gate, comparison or promotion API is called, and no artifact is committed.
"""

RUNNER_COMPONENT = "rap-evaluation.runner"
RUNNER_VERSION = "0.2.0"
EXECUTED_BY = f"{RUNNER_COMPONENT}/{RUNNER_VERSION}"
MOCK_AUTHORITY_ID = "rap-evaluation.fixture-mock/0.1.0"

#: The contract version this runner was written against (PR-S3a, generated-result binding).
EXPECTED_CONTRACT_VERSION = "0.2.0-dev.foundations.6"

EXIT_OK = 0
EXIT_VERDICT = 1  # verify-repeat: a verdict other than PASS
EXIT_USAGE = 2
EXIT_ADMISSION = 3  # admission abort: nothing written
EXIT_RUNNER = 4  # runner failure or binding failure after admission: nothing published


class AdmissionAbort(Exception):
    """An admission check (A1-A8) failed. No engine call has been made and nothing is written."""

    def __init__(self, check: str, code: str, detail: str = "") -> None:
        super().__init__(f"{check} {code}: {detail}")
        self.check, self.code, self.detail = check, code, detail


class RunnerFailure(Exception):
    """An unexpected failure after admission, including a failed publication check. Nothing is published."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}")
        self.code, self.detail = code, detail


class BindingFailure(RunnerFailure):
    """A cross-artifact binding check (X1-X9) or publication validation failed."""

    def __init__(self, check: str, detail: str) -> None:
        super().__init__(f"binding_{check.lower()}", detail)
        self.check = check
