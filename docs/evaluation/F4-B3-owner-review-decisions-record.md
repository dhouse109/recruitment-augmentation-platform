# F4/B3 — Verify-Only Owner-Review Decision Record (PR-1)

**Document ID:** RAP-F4-B3-OWNER-REVIEW-DECISIONS-RECORD
**Status:** Verify-only machine-readable record of owner decisions; **no status semantics**
**Authorization:** owner decisions H-1, H-2, H-3 and H-4 (2026-11-06), approved with qualifications, implementing
*F4/B3 Owner-Review Architecture Assessment Rev. 2* (PR-1 only)
**Record:** [`contracts/fixtures/evaluation-owner-review-decisions-v1-v0.2.0-dev.json`](../../contracts/fixtures/evaluation-owner-review-decisions-v1-v0.2.0-dev.json)
(`evalreviewdecisions_golden` v1)
**Verifier:** [`contracts/tests/test_owner_review_decisions.py`](../../contracts/tests/test_owner_review_decisions.py) (test-only)
**Source decisions:** [`F4-B3-OBJECTIVE-GOLDEN-OWNER-REVIEW-2026-11-06.md`](F4-B3-OBJECTIVE-GOLDEN-OWNER-REVIEW-2026-11-06.md)
(RAP-F4-B3-OWNER-REVIEW-2026-11-06, merged PR #22, merge commit `4314deac7bc09e4b7914403a8bfd95c962d798fa`)
**Contract:** `0.2.0-dev.foundations.6`, proposed and **not frozen**
**Data:** synthetic only

> **Scope boundary.** This record transcribes the owner's 26 F4/B3 decisions into a machine-readable form and
> verifies that transcription. It **does not** change, determine, override or resolve any case's label status.
> Every golden v2 case still records `provenance.review_status: proposed` and `adjudication_status:
> not_adjudicated`. Mapping a recorded decision to an effective `owner_reviewed` status (PR-2 decisions R-1 and
> R-2) is **not approved**.

## 1. Purpose and exact scope

PR-1 adds three files and changes no existing file:

| File | Role |
|---|---|
| `contracts/fixtures/evaluation-owner-review-decisions-v1-v0.2.0-dev.json` | The decision record (v1) |
| `contracts/tests/test_owner_review_decisions.py` | Test-local, verify-only checks and the record's integrity pin |
| `docs/evaluation/F4-B3-owner-review-decisions-record.md` | This document |

The record holds, for each of the 26 golden v2 cases, only the case id, case version, case-content hash, review
batch and the decision `accepted_as_pinned` (the owner accepted the exact pinned case content). It carries no
expected outcome, no case limitation text, no applicant or source record and no held-out detail. The decisions'
case-specific limitations — including that g010 **must remain** `prompt_injection_compliance / not_observable`
and is not evidence of model resistance — remain authoritative in §4 of the PR #22 record.

**PR-1 establishes:**

- a machine-readable transcription of the PR #22 decisions;
- verified agreement with that record's §2 batch table and §3 binding table, and with its header manifest root;
- a verified binding to the `evalset_golden` v2 manifest root and to all 26 independently recomputed case hashes;
- a raw-byte integrity pin on the record, held outside it.

**PR-1 does not establish:** any change or resolution of a case's review status; that the F4/B3 label floor is
met; M2/M3 eligibility, measurement or reportability; trusted attestation; any coverage of golden v1 or of the
held-out split; independent subjective adjudication (F4 B2).

## 2. Owner decisions applied

| ID | Decision |
|---|---|
| H-1 | A machine-readable owner-review decision record. `accepted_as_pinned` is the sole decision value and `recorded_decisions_only` the interpretation. No effective-status semantics. |
| H-2 | A raw-byte SHA-256 integrity pin stored outside the record; immutable, versioned records; a separately authorized post-merge anchor sync. The sealed verification script stays in the PR description, not in the repository. |
| H-3 | Clean held-out-free tests, independent hash verification, negative-case coverage, schema-drift verification, baseline and runner regression tests and a reproducible runner-output comparison. The unmodified full contract suite is not mandatory. |
| H-4 | Implementation and one PR for PR-1 only, within the three-file scope above. |

## 3. Recorded decisions versus effective review status

The record uses no status vocabulary. Its verifier rejects any record that contains `review_status`,
`owner_reviewed`, `to_status`, `effective`, `adjudicat`, `resolv` or `proposed` anywhere in its text, and accepts
only the decision value `accepted_as_pinned`.

`verify_record` either returns `None` or raises `RecordRejected` with a specific code. It never returns, derives
or maps a label status. Every check is all-or-nothing: one fault rejects the whole record, with no partial
success, fallback or repair.

Interpreting this record as effective `owner_reviewed` status would change what a case's label status means. That
needs an explicit, recorded owner decision (R-1) and a separately authorized PR-2; whether self-attested review
satisfies the B3 floor for any reported result is a further decision (R-2). Neither is made here.

## 4. Integrity scheme

| Item | Value |
|---|---|
| Record digest | SHA-256 of the record file's **raw bytes**: `sha256:e74096ef8bbb45290eb3b44aeee78965a366260c9673930e826e60acf3516d36` |
| Where the digest is held | `RECORD_FILE_SHA256` in the test module — **never inside the record** |
| Source record digest (in the record) | raw-byte SHA-256 of the PR #22 Markdown record, `sha256:e7089720b0f0de14232fc6deb56548dd058a6f0c87a0568d680769d04a49a15a`, verified identical to the bytes at merge commit `4314deac` |
| Dataset binding (in the record) | `evalset_golden` v2, split `golden`, root `sha256:3bd060439f58ce4d28e5272d5169135fc93526d5cec8a78de3a8dc4dfbd4d25e` |

There is no self-reference: every hash inside the record points outward (dataset root, case hashes, source
record) and is recomputed during verification. The JSON parser rejects duplicate keys and non-finite constants.

**Limit.** The pin and the record live in a repository the owner controls. Changing both is visible in a diff:
this is repository-level tamper evidence for accidental or unreviewed change, **not trusted-service attestation**,
and it does not resist a deliberate rewrite by someone with write access. Because the record and its pin arrive
in the same PR, the reviewer must recompute the digest and the 26 bindings independently.

**Post-merge anchoring** (recording the PR-1 merge commit and the record's blob SHA, and synchronizing
`docs/CURRENT-STATUS.md`) is deferred to a separately authorized PR.

**Known exposure.** The repository has no `.gitattributes`; a checkout that converts line endings changes the
bytes and fails the pin closed (the same exposure as existing historical file pins).

## 5. Golden v2 binding and golden v1 exclusion

The record is bound to the **manifest root** of `evalset_golden` v2, not only to case hashes. This matters
because 24 of the 26 golden v2 (case id, version, hash) bindings are identical to golden v1, which records the
same cases as still unreviewed and is not covered by the PR #22 record. A record bound only to case hashes would
also match golden v1; the root binding excludes it. The verifier rejects golden v1 with `dataset_mismatch`, and a
test asserts both the 24-case overlap and the rejection.

## 6. Versioning and supersession

- Record v1 becomes **immutable after merge**. No in-place edit is permitted, including whitespace.
- Any correction, addition or withdrawal requires a **separately authorized successor** record (a new file and
  version) with an explicit supersession pin `{id, version, file_sha256}` to its predecessor. v1 is retained
  byte-for-byte with its pin.
- No automatic latest-version lookup, in-place correction, revocation semantics or status resolution is
  authorized. Any future consumer must pin an exact record version.
- The record covers golden v2 only. Any golden successor would need its own decisions or a separately decided
  carry-forward.

## 7. Tests and held-out access limitations

The verifier tests cover the positive bindings above and a negative matrix in which each fault must be rejected
with a specific code: malformed JSON and duplicate keys; unknown or missing fields; injected status or resolver
fields; wrong vocabulary; `trusted_attestation: true`; wrong record digest; wrong source digest or identity; wrong
dataset root, split, id or version; golden v1 supplied for v2; modified golden content; missing, duplicate and
extra entries; incorrect coverage count or kind; incorrect summary; incorrect case version or hash; unknown
decision value; and disagreement with the PR #22 batch or binding tables. Except where the digest itself is under
test, negative cases are verified against the mutated record's own digest, so each invariant holds independently
of the pin.

**Held-out boundary.** The verifier's reader opens only four files (the record, golden v2, golden v1 and the PR #22
Markdown record) and refuses any other name before opening it. The module does not import `eval_harness` and does
not load the base fixture layers or the nominal held-out case fixture.

Some existing contract tests read the nominal held-out case fixture, so the complete contract suite cannot run
without opening it. PR-1 evidence therefore uses an explicitly selected held-out-free contract subset under a
guard that refuses to open that file, and reports the excluded tests and the reason. The existing runner parses
the shared base layers, which contain held-out-owned synthetic records; that is distinct from opening the nominal
held-out case fixture, and PR-1 claims no stronger isolation than the runner already documents. Exact counts are
reported in the PR description and are local results, not CI.

## 8. Why PR-1 does not establish the B3 label floor or M2/M3 results

- **B3 floor.** F4/B3 requires each objective golden label to reach at least `owner_reviewed` before it
  contributes to reported M2/M3 results. No accepted decision yet lets a record outside the case determine its
  label status; R-1 has not been approved, so no case is machine-recognized as `owner_reviewed`.
- **M2/M3.** No metric is produced or measured. The offline runner pins draft metrics v1, whose M2/M3 text has no
  label floor; the floor appears only in draft metrics v2. The runner produces only `partial` runs (4 of 26 cases)
  and is unchanged by PR-1. Metrics v1 and v2, safety-gate policies v1–v3 and reviewer rubrics remain
  `status: draft`. Genuine reportability also needs a trusted evaluation-record service, which does not exist.
- **Provenance.** The decisions are **self-attested** owner statements, not authenticated or attested by any
  trusted service.

## 9. Decisions still required (not made by PR-1)

| ID | Decision |
|---|---|
| R-1 | Whether, and under which fail-closed conditions, a pinned decision record may determine an effective objective-label status (`accepted_as_pinned` → `owner_reviewed`). Required before any PR-2. |
| R-2 | Whether self-attested `owner_reviewed` satisfies the B3 label floor, and what attestation any *reported* M2/M3 result requires. |
| R-3 | Placement of any resolver (test-only reference versus contract-level). A contract model, schema or `CONTRACT_VERSION` change, or any runner integration, needs separate authorization. |
| R-5 | Withdrawal and correction vocabulary for successor records, if needed. |
| — | Post-merge anchor and `CURRENT-STATUS.md` synchronization (separate PR). |

Contract v0.2 remains proposed and not frozen. No definition approval, metric, adjudication, T4 claim, Drupal
integration or deployment is made or implied.
