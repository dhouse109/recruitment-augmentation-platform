# Contract Review Gate — Proposed Checklist

**Review status:** NOT YET APPROVED  
**Accepted decisions in force:** D-001, D-002, D-003  
**Artifact version:** 0.1.0

## Decisions to confirm before treating contracts as stable

- [ ] Does one Drupal account map to one Candidate per organization, or can a candidate maintain multiple separate identities? Pilot defaults to one synthetic account per candidate.
- [ ] Are profile claims, application records, and recruitment opportunities represented by distinct, versionable Drupal entities? Exact implementation remains open.
- [ ] Is coordinator the correct first pilot reviewer role? Does `approve_for_follow_up` fully express first-slice authority?
- [ ] Should review a failed verification allow `request_information` rather than normal `approve_for_follow_up`? Current model treats escalations as a separate human-handling path.
- [ ] Does an `ineligible` program-specific *opportunity* appropriately mean not eligible to consider this opportunity, not rejection of the applicant?
- [ ] Confirm the four fictional pilot policies; real-world application of any skills/availability rules needs fairness/accommodation and legal review.
- [ ] Is the `SourceReference` logical-version exception for Drupal `User` acceptable, pending exact entity choice?
- [ ] Choose where human-review idempotency and append-only audit are actually enforced; Pydantic cannot enforce storage guarantees.
- [ ] Confirm whether `ReviewDecision.reason` must always be nonempty or should support standard reason codes plus optional comment.
- [ ] Approve the minimum candidate-profile claim vocabulary and prohibit unreviewed attributes/irrelevant demographic signals.
- [ ] Confirm RAG context authorization, source freshness and withdrawal contract before starting index implementation.
- [ ] Convert proposed synthetic evaluation labels into actual scenario fixtures and have reviewers adjudicate them.

## Gate exit conditions

1. Domain owner explicitly accepts or revises the portable types and enums.
2. Each mandatory relationship has a planned integration/negative test.
3. Source-of-truth/derived-RAG boundaries are documented and authorized-person model chosen.
4. No invented performance or quality claims; baseline is explicitly unmeasured.
5. Implementation technology choices remain in an OPEN register until selected by separate ADRs.

**Next deliverables after approval:** contract v0.2 with revised schemas, deterministic policy evaluation spec, complete synthetic fixture set and a Slice 0 executable baseline plan. The current pack is **a modeling artifact and a local validation spike**, not Slice 0 completion.