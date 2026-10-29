# ADR-0003 — Versioned Evaluation and Prompt-Promotion Gates

**Decision ID:** D-003 (formerly proposal P-003)
**Status:** Accepted
**Date:** 2026-10-12
**Project:** Recruitment Augmentation Platform
**Decision owner:** Project owner, explicitly approved in conversation
**Implementation status:** Not built; thresholds will be calibrated using measured baselines

## Context

Changes to prompts, retrieval, models, or agent flows must be judged against fixed, versioned evidence. Informal or unversioned review cannot reliably show whether a change improves quality, and it cannot detect regressions case by case. The system therefore needs a repeatable, testable process for learning whether such changes improve quality **without introducing safety or business-policy regressions**. Observability traces alone do not supply ground-truth labels.

> **Editorial erratum (2026-10-29, follow-up F2):** a historical characterization of a prior engagement's evaluation practice was replaced in this section with a neutral statement of need. D-003's decision, rationale, requirements and decision date are unchanged. The earlier wording remains in Git history and GitHub PR refs.

## Decision

1. Treat **evaluation as a first-class product and engineering capability**, not a post-launch dashboard.
2. Start in **Slice 0** with versioned synthetic cases, deterministic eligibility assertions, evidence/source labels, unknown states, and structured review rubrics, even before paid LLM calls.
3. Maintain a golden regression dataset **and a separate held-out dataset**; avoid tuning on held-out cases. Synthetic records only for public examples.
4. Associate every experiment with pinned source fixture snapshot/revisions, policy version, retrieval/index version, prompt version, model identifier/configuration, agent strategy, run ID, timestamp, and code commit where available.
5. Record per-case and aggregate outcomes, including eligibility correctness, citation/evidence support, unsupported claims, unknown/abstain behavior, verification detection/false alarms, reviewer usefulness, correction rate, latency, retries, and model cost.
6. Make **permission leakage, cross-organization leakage, hard-eligibility violations, use of stale/withdrawn sources, and critical unsupported claims blocking failures** in acceptance evaluation; improved aggregate scores cannot offset them.
7. Compare deterministic/no-model baseline, a constrained single-model approach, and Profile → Placement → Verification multi-agent design on the **same** cases before asserting benefits.
8. Use human-adjudicated labels for subjective usefulness. Reviewer click-through or LLM-as-judge alone is not ground truth. An LLM judge, if used, is itself evaluated against human labels.
9. **LangFuse is the intended trace/experiment integration for the target reference architecture**, with privacy-preserving metadata and IDs correlated to Drupal source revisions, run, recommendation, and—if implemented—Temporal workflow. An offline versioned report remains useful independently of any vendor.
10. Require a documented baseline-vs-candidate comparison and an explicit pass/fail promotion decision for changes to prompts, models, retrieval behavior, verification, or routing.

## Rationale

- Turns 'ad-hoc' prompt tuning into falsifiable engineering comparisons.
- Makes regressions discoverable at the case level rather than hiding them in an uncalibrated match score.
- Measures value, false alarms, latency, and cost *together*.
- Creates a credible, independently repeatable portfolio artifact aligned with Staff-level AI engineering.

## Tradeoffs

- Curation and human adjudication of reference cases require time and explicit provenance.
- A synthetic dataset demonstrates correctness properties, **not** real-world hiring effectiveness or fairness.
- High model variance requires pinned configurations, repeated trials or documented uncertainty; bit-for-bit determinism of model text cannot be promised.
- No numeric improvement targets can be represented as outcomes until measured. Safety invariants apply immediately; non-safety thresholds require calibration.

## Metric and gate inventory (initial, without invented results)

| Metric | Evidence | Initial gate |
|---|---|---|
| Hard eligibility violations | Versioned policy assertions | **Zero accepted** |
| Unauthorized retrieval / cross-org leakage | Denial fixtures and negative tests | **Zero accepted** |
| Stale-source use | Drupal revision/withdrawal simulation | **Zero accepted** |
| Critical unsupported claims | Claim/evidence adjudication | **Zero accepted for promotion** |
| Citation support | Human-checked claim-to-evidence pairs | Report per case; calibrate threshold |
| Verification recall / false alarms | Seeded invalid and valid results | Report both; calibrate threshold |
| Unknown-state handling | Missing/conflicting fact cases | Do not invent facts |
| Reviewer corrections/usefulness | Reviewer rubric with explanations | Compare to baseline |
| Latency / retries / cost per reviewed recommendation | Correlated observations and usage | Record and compare; budget before paid calls |

## Acceptance evidence

- [ ] Runnable offline synthetic test dataset with machine-readable expected outcomes and explicit provenance.
- [ ] Separate held-out cases, not used for prompt selection.
- [ ] Reproducible baseline report, versioned and linked to code/policy/fixture versions.
- [ ] Per-case comparison report and aggregate metrics for candidate change.
- [ ] Safety regressions block promotion even when non-safety metric improves.
- [ ] Controlled LangFuse trace IDs map to experiment and recommendation IDs without exposing applicant PII.
- [ ] Prompt/retrieval/model change has a documented accept/reject record.

## Explicitly open

- Specific metric thresholds beyond invariant zero-tolerance cases.
- Eval implementation library/runner and report UI.
- Exact LangFuse deployment/instrumentation topology and retention.
- Model/judge providers, number of repeated trials, and experiment budget.
- How human reviewers adjudicate subjective labels and how disagreements are resolved.

## Related material

- `docs/decisions/ADR-0001-general-platform-nonprofit-pilot.md`
- `docs/decisions/ADR-0002-drupal-authoritative-reference-and-rag-boundaries.md`
- `docs/PROJECT-FOUNDATION.md` (v0.3.0)
- `docs/pilots/nonprofit-internship-placement.md`
