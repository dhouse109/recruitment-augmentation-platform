# Slice 0 PR-S1 — Deterministic Eligibility Engine: Design, Traceability, Evidence and Limits

**Document ID:** RAP-SLICE0-PR-S1
**Scope:** PR-S1 only, the deterministic eligibility engine (`baseline/rap_baseline`) and its tests
**Authorization:** owner, 2026-10-31. PR-S1 only; PR-S2 (explanations), PR-S3 (offline runner), F3, PR-C, Drupal integration, recommendation generation, reviewer writes, CI and paid inference are **not** authorized
**Design sources:** RAP-SLICE0-PLAN-2026-10-29 and RAP-SLICE0-PR-S1-ADDENDUM-2026-10-31 (reviewed with the owner; shared packet documents, not repository files)
**Base:** `main` @ `219a36efec4a3dc5a78b976841708aff976ceb00` (merge of PR #11); contract `0.2.0-dev.foundations.5`, **unchanged and not frozen**
**Data:** synthetic only

## 1. Approved decisions applied

| ID | Decision | Where |
|---|---|---|
| SD-1 | Standalone `baseline/rap_baseline`; imports `rap_contracts` via `PYTHONPATH=../contracts`; no new dependency | package layout |
| SD-2 | Explicit request: organization, candidate, opportunity, `PolicyPin`, principal, timezone-aware `as_of` | `request.py` |
| SD-3 | Two-phase ordering; gate the projection's full decision-relevant source set; phase-2 validation on the projection only | `engine.py`, `inputs.py` |
| SD-4 | Precedence matrix (§4) | `rules.py` |
| SD-5 | Citation policy (§4) | `rules.py` |
| SD-14 | No nominal held-out records or labels in PR-S1 development tests | `tests/builders.py`, `test_label_blindness.py` |
| SD-15 | Disagreement with a proposed label goes to the owner register; never edit the engine or a label to force agreement | `test_golden_scope_keys.py` |
| SD-17 | Result id = f(input fingerprint, UTC `as_of`); principal excluded from identity, recorded in provenance | `identity.py`, `provenance.py` |
| SD-18 | Mixed-basis contradiction: verification first, citing the verification-backed subset. **PR-S1 only; limitation G12** | `rules.py` |
| SD-19 | A verified contradiction of a self-declared skill yields `needs_information` **only** when preserved as one contested claim | `rules.py`, `test_precedence.py` |

**Owner qualifications (2026-10-31), each implemented and tested:**
1. **Identity canonicalization.** All timezone-aware datetimes in fingerprinted structures are normalized to UTC, including nested `LogicalSnapshot.captured_at`. Equivalent representations are tested. The result id identifies a deterministic assessment, not necessarily a globally unique execution event. Principal and individual source checks are kept separately.
2. **Source dependencies** are enumerated in §3. Every decision-relevant authoritative source is gated. Structural metadata that must come from a pre-authorized adapter is listed. The synthetic test authority is not Drupal authorization.
3. **SD-18 / G12** is recorded as a limitation (§4.4). Results are not an exhaustive account of every failed qualification and are not sufficient for reviewer-facing explanations.
4. **SD-19.** Neither source is discarded and no authoritative resolution is fabricated. Two conflicting declared claims are refused (`unresolved_conflict`). Revoking either alternative's source refuses the assessment.
5. **Held-out separation.** PR-S1 tests use new test-local synthetic records (`*_s1_*`). The golden-scope diagnostic loads only golden-split candidates; the fixture's `additional_records` section, which holds the nominal held-out candidates, is never read. A test scans `baseline/` for held-out identifiers. **The earlier read-only desk check (2026-10-31, outside the repository) referenced the already-exposed nominal held-out candidates D and E. It provides no independent held-out evidence.**
6. **Post-check testing.** A schema-valid but semantically unsupported outcome fails the post-check (`Errored(post_check_failed)`). An invalid reason code fails earlier, at model construction (`Errored(result_construction_failed)`).

## 2. Execution ordering

| Phase | Step | Existing functions | Failure → | Authority calls |
|---|---|---|---|---|
| 0 | Request; `as_of` aware and UTC-normalized | Pydantic | `Errored(request, invalid_request)` | 0 |
| 1 | P1 targets, organization guard, policy pin/scope, participation program | — | `Refused(reference, …)` | 0 |
| 1 | P2 metadata projection (rule kinds, requirement kind/code, claim type/code/evidence ids, participation program/evidence ids) | — | `Refused(projection, invalid_citation)` | 0 |
| 1 | P3 organization guard over every projected record and gated source; evidence resolution | `resolve_evidence_ids` | `Refused(projection, …)` | 0 |
| 1 | P4 structural validators that take no claims or participations | `check_record_set`, `check_record_set_versions`, `check_evidence_records`, `check_policy_sets`, `check_requirements` | `Refused(structure, …)` | 0 |
| Gate | P5 every decision-relevant source (§3) | `require_sources_admissible` via a recording wrapper | `Refused(source_gate, …)` | ≥ 1 |
| 2 | P6 first value-dependent step | `validate_recommendation_inputs(RecommendationContext(eligibility=P, eligibility_results=MappingProxyType({}), capabilities=caps))` | `Refused(context, …)` | — |
| 2 | P7 freeze `DecisionInputs` (the only rule input; also the fingerprinted object) | — | — | — |
| 2 | P8–P9 rules, `derive_decision`, `EligibilityResult` | contract models | `Errored(result, rule_evaluation_failed \| result_construction_failed)` | — |
| 2 | P10 post-check and provenance subset | the same wrapper with `{result.id: result}`; `eligibility_source_refs ⊆ gated` | `Errored(post_check, post_check_failed \| provenance_not_gated)` | — |

Only `rules.py` reads claim values, claim states, contested alternatives, participation statuses, opportunity status or required hours. An AST test enforces this; `identity.py` reads only `Enum.value` during canonicalization. Contract model validators run when records are deserialized, before the engine. That is the loader's or adapter's shape validation, not engine use.

## 3. Source-dependency enumeration (owner qualification 2)

**Gated in P5 (decision-relevant, exact version):**

| Source | Why it is decision-relevant |
|---|---|
| Assessed opportunity `source_ref` | `status` (active rule), `program_id` (scope), and the source of its requirements |
| Policy `source_ref` | rules, rule versions, program scope |
| Each selected `OpportunityRequirement.source_ref` | required hours and mandatory codes (always the opportunity's or the covering policy's source) |
| Evidence `source_ref` of every selected claim: declared, **inferred**, and **every contested alternative** | claim values and states, and the reason choice (inferred-only vs not evidenced) |
| Evidence `source_ref` of every selected participation | participation status |

Unknown-state claims carry no evidence and therefore no source to gate. Their absence-of-value is an adapter assertion (see completeness, §7).

**Structural metadata, not gated. It must arrive from a pre-authorized adapter (`load_authorized_case`):**

| Record | Used by | Why not gated |
|---|---|---|
| `Candidate` (id, organization, `identity_source`) | organization guard, identity-mapping check, evidence subject | identity locator is unversioned; no field is read by rules |
| `CandidateProfile` versions, `Application` (target, status, submission pins) | `check_record_set`, statement-evidence provenance (entity membership) | the exact versions whose content backs claims are gated through evidence refs |
| `Program` (logical snapshot) | existence/organization of referenced programs | only ids are used; no program field is read by rules |
| Other opportunities targeted by the candidate's applications | referential integrity | never read by rules |
| `ClaimVocabulary` | code membership | has no `source_ref` (open decision **O3**); cannot be gated |
| `SourceSystemCapabilities` | version-kind checks | adapter configuration, not a source record |

Tests: exact gate set for a qualification opportunity; no skill source gated when no qualification is required; both contested alternatives and inferred evidence gated; programs and unselected sources never checked; every result dependency ⊆ gated set.

## 4. Rules: precedence (SD-4) and citations (SD-5)

**SD-5 citation policy:**
- (a) pass/fail cite every authoritative input of the decisive state, plus the requirement(s) compared;
- (b) unknown cites every non-declared claim of the undetermined key(s), plus, for qualifications, the undetermined requirements;
- (c) never cite a satisfied key's records in a non-pass outcome, and never cite a non-declared claim in pass/fail;
- (d) ids are sorted.

Rule outcomes follow policy rule order.

### 4.1 Active status (O1: pass/fail only)
`active` → pass `opportunity_active`; `paused`/`closed` → fail `opportunity_paused`/`opportunity_closed`. Nothing cited.

### 4.2 Program participation
No record for (candidate, rule program) → unknown `participation_not_recorded`. All `confirmed` → pass, citing all. All `not_participating` → fail, citing all. Mixed records are refused at P6 (`participation_conflict`).

### 4.3 Availability (first match wins)
1. No published `weekly_hours` → unknown `required_hours_not_published`, nothing cited.
2. A contested availability claim → unknown `availability_contested`, citing the contested and any inferred claims.
3. No declared availability → unknown `availability_not_declared`, citing unknown-state and inferred claims.
4. Otherwise (declared values, equal after P6) → pass if hours ≥ required, else fail. Cites every declared claim and the requirement.

### 4.4 Mandatory qualifications (several codes, mixed bases)
Each required code is classified as `HAS` / `LACKS` (declared), `CONTESTED`, `INFERRED_ONLY` or `NONE`. The rows below apply in order:
- **Row 0:** no requirement → pass `no_mandatory_qualification`.
- **Row 1:** any `LACKS` with verification evidence → fail `qualification_contradicted_by_verification`, citing those claims and their requirements only.
- **Row 2:** otherwise any `LACKS` → fail `…_by_declaration`, citing all lacks claims and their requirements.
- **Rows 3–5:** otherwise any undetermined code → unknown, with precedence `contested` > `only_inferred` > `not_evidenced`. Cites the non-declared claims and the requirements of **all** undetermined codes.
- **Row 6:** all `HAS` and every code verified → pass `qualification_independently_verified`.
- **Row 7:** otherwise → pass `qualification_declared`. Rows 6–7 cite every declared claim and every requirement.

**Limitation G12 (SD-18, approved for PR-S1 only).** The contract cannot express "contradicted by verification on one code and by declaration on another" in one `RuleOutcome`. In that situation the result cites only the verification-backed contradiction. **The declaration-backed contradiction is omitted from the citations.** The decision (`ineligible`) is unaffected, but the result is **not an exhaustive account of every failed qualification and is not sufficient for reviewer-facing explanations.** Resolving G12 needs a future contract revision.

**SD-19.** A verified *lacks* that conflicts with a self-declared *has* must arrive as one contested claim preserving both sources. It then yields `needs_information`. Delivered as two declared claims, it is refused. Inferred claims never change any rule result or decision.

Contradictory records are refused, never turned into outcomes:
- At P6: `participation_conflict`, `unresolved_conflict`, `contested_not_exclusive`, `unknown_conflicts_with_value`.
- At P4: `requirement_conflict`.
- At P1: `policy_version_conflict`.

Defence in depth: if P6 were bypassed, the rules raise `RuleEvaluationError` (→ `Errored`).

## 5. Identity and provenance

| Identity | Definition |
|---|---|
| `DecisionInputs` | request organization, candidate, and the opportunity, policy, selected requirements, claims, participations, cited evidence and pinned vocabularies, plus engine identity (`evaluated_by`, `sd4-precedence/1`, `sd5-citations/1`) |
| Input fingerprint (IF) | `sha256-canonical-json/v1` over the canonical form of `DecisionInputs` (UTC datetimes, enum values, sorted sets, records sorted by id; floats and naive datetimes rejected) |
| Output digest (OD) | the same hash over the result excluding `id` and `evaluated_at` |
| Result id | `eligibility_` + first 40 hex of the hash of {IF, UTC `as_of`} (52 characters) |
| `evaluated_at` / `evaluated_by` | UTC `as_of` / `rap-baseline.eligibility/0.1.0` |
| Provenance (runtime-local) | result id, IF, OD, principal, UTC `as_of`, engine identity, sorted gated refs, the authority's `SourceCheckResult`s |

Equal IF and equal `as_of` give byte-identical results. Equal IF with a different `as_of` gives a different id and an equal OD. Every material input change tested changes IF and id, including those that leave the decision and citations unchanged: a requirement value, an evidence revision, the evidence basis or field path, evidence ids, the declared hours value, a vocabulary under the same pin, and the opportunity, policy or participation revision. Logical-snapshot references in the result are re-emitted with UTC `captured_at`; they are equal under `==` to the source record.

**Contract constraint (unchanged):** `check_eligibility_results` admits at most one result per (candidate, opportunity, policy id, version) in one record set, regardless of revision. Assessment history is a later storage concern.

## 6. Test evidence

107 tests in 11 modules (`baseline/tests`):

| Module | Tests | Covers |
|---|---|---|
| `test_rules.py` | 4 | every (kind, result, reason) in `REASON_CODES` (19) produced and post-checked; rule order; sorted citations |
| `test_precedence.py` | 24 | SD-4/SD-5 rows incl. several codes and mixed bases; losing alternatives supportable; rejected alternatives rejected; contradictory records refused; SD-19 |
| `test_fail_closed.py` | 10 | 7 failure modes × 8 gated categories; unknown principal; version-kind refusal pre-authority; source-dependency regressions |
| `test_gate_ordering.py` | 21 | event-ordered spy; AST value-access scan; zero authority calls for every pre-gate refusal; unselected sources; projection immutability |
| `test_identity.py` | 13 | non-aliasing (11 mutations); engine identity; equivalent and exact replay; UTC and nested `captured_at` normalization |
| `test_determinism.py` | 3 | repeat; shuffled inputs; two processes with different `PYTHONHASHSEED` |
| `test_isolation.py` | 7 | opportunity, program and organization isolation; no candidate-level field |
| `test_metamorphic.py` | 6 | inferred claims never change results; verification upgrades reason only; hours monotonicity; requirement removal; contradiction |
| `test_label_blindness.py` | 6 | no label input or evaluation import; label-flip invariance; held-out identifier scan; golden-only loader |
| `test_golden_scope_keys.py` | 2 | **diagnostic only:** output vs proposed labels for the 5 golden keys |
| `test_context_validation.py` | 11 | wrapper called twice with empty then produced results; projection/full-context verdict equality; post-check, construction and provenance failures are `Errored`; defence in depth |

**Failure-first demonstrations.** Each mutation was run on a scratch copy, one at a time. Counts include failing subtests.

| # | Invariant disabled | Failures (failing test methods) |
|---|---|---|
| M01 | P6 value-dependent validation moved before the gate | 5 (4) |
| M02 | gate failures ignored | 62 (5) |
| M03 | contested-alternative evidence not gated | 28 (18) |
| M04 | inferred-claim evidence not gated | 11 (5) |
| M05 | P6 on the full context instead of the projection | 4 (4) |
| M06 | organization guard over the projection removed | 6 (6) |
| M07 | P1 candidate/opportunity organization checks removed | 1 (1) |
| M08 | result id omits the input fingerprint | 13 (2) |
| M09 | `as_of` not normalized | 2 (2) |
| M10 | nested `captured_at` not normalized | 2 (2) |
| M11 | principal included in the fingerprint | 1 (1) |
| M12 | declaration preferred over verification | 2 (2) |
| M13 | full mixed-basis lacks set cited | 1 (1) |
| M14 | `not_evidenced` preferred over `only_inferred` | 2 (2) |
| M15 | inferred treated as declared | 8 (6) |
| M16 | `not_declared` preferred over `contested` | 2 (2) |
| M17 | unpublished hours checked after declared/contested | 1 (1) |
| M18 | post-check removed | 4 (4) |
| M19 | provenance subset check removed | 1 (1) |
| M20 | deterministic ordering removed | 18 (8) |
| M21 | gate checks only opportunity and policy | 137 (59) |
| M22 | rules evaluate conflicting participation instead of failing closed (defence in depth) | 1 (1) |

All 22 are caught. M22 was not caught by the first suite, because P6 makes the branch unreachable end to end. `DefenceInDepthTests` was added and catches it.

The PR description records exact commands, versions and fresh-clone results.

## 7. Guarantees NOT established

1. **Drupal authorization, currentness and completeness.** The test authority is synthetic. Absence-based outcomes (`participation_not_recorded`, `availability_not_declared`, `required_hours_not_published`, `qualification_not_evidenced`) assume the supplied context is complete; only the authority can establish that. **T4 only.**
2. **Any evaluation evidence.** No evaluation run, case observation, metric value, T3 or T4 evidence, accuracy, latency or cost is produced. The golden-scope check compares with **proposed, AI-assisted, unreviewed** labels. Agreement is a common-mode diagnostic, not a measurement.
3. **Explanations.** None (PR-S2). G12 makes citations non-exhaustive for mixed-basis contradictions.
4. **Fairness or legal appropriateness** of the fictional rules and precedence choices (D-004.06 review needed before real use).
5. **Declared-versus-inferred honesty at the source**, and the binding of content to an exact revision. These are adapter obligations.
6. **Assessment history or uniqueness across record sets.** See the contract constraint in §5.

## 8. Traceability

| Requirement | Evidence |
|---|---|
| D-004.05 opportunity/policy-scoped, no candidate-level outcome | `test_isolation.py`; result type unchanged |
| D-004.06 deterministic, versioned rules; unknowns never become failures | `test_rules.py`, `test_precedence.py`, `test_metamorphic.py` |
| D-004.07 exact versions; fail closed on stale/withdrawn/denied | `test_fail_closed.py`, `test_gate_ordering.py` |
| D-004.10 inferred non-authoritative; contested preserved | `test_precedence.py` (SD-19, Q9), `test_metamorphic.py` |
| D-004.11 organization scope before access; checks before use | `test_gate_ordering.py` |
| ADR-0003 decision 2, D-004 deterministic baseline first | engine without model calls; pins in `identity.py` |
| Freeze criterion 5 (a real producer) | `EligibilityResult` produced and accepted by unmodified validators; `Recommendation`, `VerificationResult` and `EvaluationRun` remain unproven |
