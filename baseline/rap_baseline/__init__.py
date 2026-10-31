"""Slice 0 deterministic eligibility baseline (PR-S1): engine only.

A producer of ``rap_contracts.eligibility.EligibilityResult`` from synthetic,
already-loaded records. It makes no model call, has no network access, writes
nothing, and never produces a candidate-level outcome. It is NOT an evaluation
runner (PR-S3), NOT an explanation generator (PR-S2) and NOT Drupal
integration. A source authority passed in tests is a synthetic stand-in: it
cannot establish real Drupal authorization (evidence tier T4).
"""

ENGINE_COMPONENT = "rap-baseline.eligibility"
ENGINE_VERSION = "0.1.0"
EVALUATED_BY = f"{ENGINE_COMPONENT}/{ENGINE_VERSION}"

from .engine import assess  # noqa: E402
from .request import Assessed, EligibilityRequest, Errored, Refused, Stage  # noqa: E402

__all__ = ["EVALUATED_BY", "Assessed", "EligibilityRequest", "Errored", "Refused", "Stage", "assess"]
