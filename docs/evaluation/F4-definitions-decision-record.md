# F4 Evaluation-Definitions Decision Record

**Document ID:** RAP-F4-DECISIONS  
**Records:** owner decision record RAP-F4-STAGE-A-2026-10-29 (B1–B5, N1–N3) and the PR-A specification decisions D1–D5  
**Decision date:** 2026-10-29  
**Authority:** explicit approval by the project owner on 2026-10-29, first documented outside GitHub; this file records it in the repository through the separately authorized PR-A  
**Basis:** *F4 Stage A — final decision brief* (2026-10-29) and independent architecture review; accepted ADR-0002, ADR-0003, ADR-0004  
**Verified `main` when the decisions were prepared:** `f45a9368b24dd10d7f8c7afe51f67da713ebf623`  
**Related:** [`contract-v0.2-evaluation.md`](../models/contract-v0.2-evaluation.md#f4-draft-definitions-v2-pr-a), draft fixture `contracts/fixtures/evaluation-definitions-v2-v0.2.0-dev.json`

> **These are policy and specification decisions, not approval of any definition record.** `evaldefs_metrics` (v1 and v2), `evaldefs_safety_gate` (v1 and v2) and `rubric_reviewer_usefulness` v1 all remain `status: draft`. Contract v0.2 is not frozen. No metric is produced, measured or reportable. Each PR, each merge, each change to `status: approved`, any contract freeze, Slice 0 and any later implementation need separate explicit owner approval.

## Decision authorization boundary

The owner expressly approved **B1–B5 and N1–N3** as recommended, **with qualifications on reviewer independence and unstable results**. These are policy decisions, **not** approval of the current or proposed definition records. `evaldefs_metrics`, `evaldefs_safety_gate`, and `rubric_reviewer_usefulness` remain `draft`. No contract freeze, PR implementation, branch, PR creation, merge, Slice 0 implementation, paid inference, hosted services, CI, real-applicant processing, or publication was authorized. Each PR and each merge needs separate owner approval.

## Approved decisions (Stage A)

### B1 — Research selection distinct from formal promotion

Adopt a separate offline research-selection record, with proposed outcomes `select_for_further_study`, `reject`, `not_determined`. It selects what to **study next**, not what to promote or deploy. Require comparable golden shared-core cases, prohibit tuning on held-out cases, and disqualify a candidate for any observed unblocked zero-tolerance violation. Integrated-only safety obligations are `not_assessable_offline`, never passed. The research-selection decision does not change the reference baseline or confer integrated-system authority.

ADR-0003 decision 10 **is not narrowed** to the integrated system. If whether a change requires formal promotion governance is unclear, use the conservative interpretation. Properly qualified offline T3 experiments may support later analysis, but neither they nor a research-selection record substitute for T4 safety evidence, trusted held-out custody, or formal promotion approval. Changing the reference baseline itself needs a separate explicit decision.

### B2 — Independent subjective review

Use **two independent primary human reviewers for every applicable rubric dimension** of every produced output. If they agree on a score or justified N/A, derive that final label directly. If they disagree on score or applicability, use a **distinct third adjudicator**, whose reasoned resolution becomes the final label. Without resolution, retain a counted `disputed`/`unresolved` result, not a reportable final label. Only a trusted service can authenticate reviewer roles and attest independence.

**Owner qualification:** Someone who authored/tuned the configuration under evaluation, or authored the reference labels used for the same judged item, does not count as independent for that item; separate account IDs are insufficient. Prefer blinding reviewers to configuration identity. No reviewer or adjudicator has been appointed. Whether the owner qualifies as a reviewer depends on per-case conflicts, not a blanket designation. Until staffing and trusted attestation exist, subjective usefulness reporting is deferred; a single-owner review is **non-reportable calibration**.

### B3 — Objective golden labels

Require each objective golden label to reach at least `owner_reviewed` before it contributes to reported M2/M3 results. The owner will review the **26 golden cases**; track remaining `proposed` labels as exclusions, never as measured correctness. Resolve **F3**, separate scenarios for g002 and g008, before reviewing those two labels. All five exposed nominal held-out cases remain **non-evidential as blinded held-out cases**, independent of review.

### B4 — Individual regression acknowledgement

List and acknowledge every shared-core `regressed` or `unstable` case individually in both research-selection and formal-promotion records, retaining case identity, version, and replicate evidence when relevant. Do not hide regressions by netting improvements; acknowledgement is **not** a safety waiver. Defer numeric or named critical-regression thresholds until justified by measurement.

**Owner qualification:** An unstable result is **not automatically acceptable formal promotion evidence**. Formal handling of unstable mandatory correctness/unknown-preservation cases remains a separate decision for PR-C. Use structured acknowledgement references, rather than forcing all details into the current short free-text rationale.

### B5 — Missing ADR-0003 metrics

Include seven additional definitions as **draft, deferred, `report_only`, `not_compared`**: reviewer correction rate; retry rate; escalation rate (separate from verifier false alarms); non-critical unsupported-claim rate; citation coverage (separate from precision); p50 latency; review elapsed time. Define applicable count/denominator units and future producer honestly. This creates no measured results or mandatory thresholds.

### N1 — Resolution procedure

Use `third_reviewer` for the v1 corrected rubric; remove `recorded_discussion` as a reportable disagreement policy in a separately authorized adjudication-contract PR (proposed PR-B).

### N2 — Fault-specific verifier recall

A verifier signal on an unexpected check code is `detected_other_check`, reported separately and **not credited** toward fault-specific detection recall. Versioned injected faults must declare acceptable check codes in advance. Implementation remains dependent on a verifier being in scope for Slice 0.

### N3 — Deterministic baseline repeatability

Validate determinism rather than assuming it. When comparing strategies, baseline and candidate use the same declared replicate count *R*. Differing baseline replicate results invalidate that deterministic reference run. A standalone baseline with *R* = 1 needs a separate repeat-run equality check. No model-run replicate count or statistical uncertainty method is yet approved.

## Approved direction / retained safeguards

- Retain all **eight zero-tolerance categories**. Any observed unblocked violation blocks, even when found through lower-tier test logic; **passing** requires complete mandatory coverage at an accepted evidence basis. Synthetic gate-logic tests do not prove integrated safety.
- Retain the **two `required_observed` core metrics** and the defensive `no_observed_outcome_metric` check for now.
- Support the three-set coverage **concept** (shared core, component-specific, safety obligations), **not** its specific case membership or executable mapping before Slice 0 planning.
- Treat justified rubric N/A differently from no output and generation failure; keep failure counts visible.
- Future trusted services must derive metric membership and arithmetic from recorded observations; a declared case-set hash is only a cross-check.
- Do not set non-safety thresholds, confidence intervals, statistical claims, or approve definitions prior to the necessary evidence and owner action.

## PR-A specification decisions D1–D5 (approved 2026-10-29)

Approved by the owner together with the authorization to implement PR-A, subject to the stated qualifications.

| ID | Decision | Owner qualification |
|---|---|---|
| D1 | Metric versions in definitions v2: metrics whose text changed are version 2 (13); unchanged metrics keep version 1 (4); metrics new in v2 start at version 1 (8). | — |
| D2 | Retry rate is a bounded ratio: calls retried at least once over calls attempted. | Retry rate uses distinct logical model calls as its denominator, not individual retry attempts. |
| D3 | Reviewer correction rate measures reviewer changes to suggestions. | Reviewer correction rate measures substantive changes to suggestions, distinct from `ReviewCorrectionCommand` audit corrections. |
| D4 | Review elapsed time uses the p50 statistic (`review_elapsed_time_p50`). | Review elapsed time uses p50; the current duration-statistic validation gap remains documented and deferred. |
| D5 | Integrated-review metrics are included, declared against generating run kinds. | Integrated-review metrics may be included as draft specifications, but generating run kinds do not establish integrated review or measurement. Use `not_measured` where genuine review evidence does not exist. Do not imply those metrics are executable or reportable today. |

## Outstanding decisions and dependencies

| Item | Outstanding condition |
|---|---|
| F3 and B3 | Separate g002/g008 scenarios before those labels are reviewed; **no** objective labels have yet been approved by this decision. |
| B2 staffing | No independent reviewers, adjudicator, or trusted authentication/attestation service yet. |
| Rubric/definitions approval | All current and proposed versions remain `draft`; explicit later approval required. |
| Slice 0 | Generating operations, case applicability, seeded-fault inventory, verifier scope, repeat execution and coverage design not approved for implementation. |
| PR-C instability policy | Formal-promotion treatment of unstable mandatory cases remains open; no implicit waiver. |
| Later measurement | Thresholds, replicates for model runs, uncertainty method and held-out custody remain open. |
| Other project work | O3, O4, remainder O5, Drupal/RAG integration, F2 publication/history concerns and contract freeze remain open. |

## Where each decision is encoded

| Decision | Encoded in PR-A | Deferred to |
|---|---|---|
| B1 | Recorded here only | Research-selection record (proposed PR-F) |
| B2, N1 | Recorded here; M6 v2 text | Adjudication contracts and rubric v2 (proposed PR-B) |
| B3 | M2/M3 v2 text (label floor; proposed labels as exclusions) | Owner label review after F3; a producer (Slice 0) |
| B4 | Recorded here only | Comparison and decision records (proposed PR-C, PR-F) |
| B5 | Seven `report_only`, `not_compared` v2 definitions | Producers (Slice 0 and later) |
| N2 | M5 v2 text | Verifier observation contracts (proposed PR-D) |
| N3 | Recorded here only | Replicate contracts (proposed PR-C) |
| Zero-tolerance detection | M8 v2 text; regression tests `BasisIndependentBlockingTests` | — (the gate already behaves this way) |
| D1–D5 | v2 fixture | Duration-statistic and integrated run-kind gaps: a later contract PR |
