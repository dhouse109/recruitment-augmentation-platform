"""D-004.11 -- evidence citations and fail-closed retrieval admission.

All admission tests use MOCK authority and MOCK store implementations. They
demonstrate ordering and fail-closed plumbing, not live Drupal ACLs, index
invalidation, or model behavior.
"""

import copy
import json
import unittest

from pydantic import ValidationError

import support
from rap_contracts.evidence import (
    AdmittedChunk,
    DenialCode,
    EvidenceSubject,
    RetrievalChunk,
    RetrievalRequest,
    RetrievalResponse,
    admit_chunks,
    content_sha256,
    resolve_evidence_ids,
)
from rap_contracts.invariants import ContractViolation
from rap_contracts.models import AccessStatus, VersionStatus

ORG = "org_demo_001"


class AdmissionHarness(unittest.TestCase):
    def setUp(self):
        self.index = support.ext_chunk_index()
        self.authority = support.scenario_authority()
        self.store = support.FixtureChunkStore()
        self.caps = support.ext_capabilities()

    def admit(self, *chunk_ids, principal=support.COORDINATOR, org=ORG):
        request = RetrievalRequest(organization_id=org, purpose="model_context", chunk_ids=chunk_ids)
        return admit_chunks(request, self.index, self.authority, self.store, principal, self.caps)

    def denial(self, outcome, chunk_id):
        return next(d.code for d in outcome.denied if d.chunk_id == chunk_id)

    def assert_not_loaded(self, chunk_id):
        self.assertNotIn(self.index[chunk_id].text_pointer, self.store.loads) if chunk_id in self.index else None


class FixtureTests(unittest.TestCase):
    def test_chunk_hashes_match_store_except_tampered(self):
        doc = support.ext_raw()
        for chunk in doc["chunks"]:
            with self.subTest(chunk=chunk["id"]):
                matches = content_sha256(doc["chunk_store"][chunk["text_pointer"]]) == chunk["content_hash"]
                self.assertEqual(matches, chunk["id"] != "chunk_d_tampered")

    def test_chunk_scope_and_shape(self):
        base = support.ext_raw()["chunks"][0]
        bad_scope = copy.deepcopy(base)
        bad_scope["source_ref"]["organization_id"] = "org_demo_002"
        for label, payload in (("source in another org", bad_scope),
                               ("url pointer", {**base, "text_pointer": "https://example.invalid/x"}),
                               ("bad hash", {**base, "content_hash": "md5:abc"}),
                               ("self-declared authorization field", {**base, "access_status": "allowed"})):
            with self.subTest(label), self.assertRaises(ValidationError):
                RetrievalChunk.model_validate(payload)

    def test_request_shape(self):
        base = support.ext_raw()["retrieval_requests"][0]
        for label, payload in (("duplicate ids", {**base, "chunk_ids": ["chunk_a_app_answer"] * 2}),
                               ("empty", {**base, "chunk_ids": []}),
                               ("too many", {**base, "chunk_ids": [f"chunk_x{i}" for i in range(101)]}),
                               ("client-supplied principal", {**base, "principal_id": "principal_demo_coordinator"}),
                               ("client-supplied role", {**base, "role": "admin"})):
            with self.subTest(label), self.assertRaises(ValidationError):
                RetrievalRequest.model_validate(payload)


class AdmissionTests(AdmissionHarness):
    def test_authorized_current_chunk_admitted_as_untrusted_data(self):
        outcome = self.admit("chunk_a_app_answer")
        self.assertEqual(outcome.denied, ())
        (chunk,) = outcome.admitted
        self.assertEqual(chunk.trust, "untrusted_data")
        self.assertEqual(chunk.text, support.ext_raw()["chunk_store"]["store/fixture/chunk_a_app_answer"])
        self.assertEqual(chunk.source_ref, self.index["chunk_a_app_answer"].source_ref)
        self.assertEqual(self.authority.calls, [self.index["chunk_a_app_answer"].source_ref])
        self.assertEqual(self.store.loads, ["store/fixture/chunk_a_app_answer"])

    def test_guessed_chunk_id_denied_without_any_lookup(self):
        outcome = self.admit("chunk_guess_0001")
        self.assertEqual(self.denial(outcome, "chunk_guess_0001"), DenialCode.UNKNOWN_CHUNK)
        self.assertEqual((self.authority.calls, self.store.loads), ([], []))

    def test_cross_org_chunk_denied_before_authority_or_store(self):
        outcome = self.admit("chunk_c_profile")
        self.assertEqual(self.denial(outcome, "chunk_c_profile"), DenialCode.CROSS_ORG)
        self.assertEqual((self.authority.calls, self.store.loads), ([], []))

    def test_revoked_access_denied_even_with_permissive_metadata(self):
        chunk = self.index["chunk_b_profile"]
        self.assertEqual(chunk.access_scope_hint, "public")
        self.authority.set(support.COORDINATOR, chunk.source_ref, VersionStatus.CURRENT, AccessStatus.DENIED)
        outcome = self.admit("chunk_b_profile")
        self.assertEqual(self.denial(outcome, "chunk_b_profile"), DenialCode.ACCESS_DENIED)
        self.assertEqual(self.store.loads, [])

    def test_stale_index_entry_denied(self):
        outcome = self.admit("chunk_a_profile_old")  # index still holds a chunk for superseded profile v101
        self.assertEqual(self.denial(outcome, "chunk_a_profile_old"), DenialCode.NOT_CURRENT)
        self.assertEqual(self.store.loads, [])

    def test_withdrawn_and_deleted_sources_denied(self):
        outcome = self.admit("chunk_b_withdrawn")
        self.assertEqual(self.denial(outcome, "chunk_b_withdrawn"), DenialCode.WITHDRAWN)
        self.authority.set(support.COORDINATOR, self.index["chunk_a_app_answer"].source_ref,
                           VersionStatus.DELETED, AccessStatus.ALLOWED)
        outcome = self.admit("chunk_a_app_answer")
        self.assertEqual(self.denial(outcome, "chunk_a_app_answer"), DenialCode.DELETED)
        self.assertEqual(self.store.loads, [])

    def test_unknown_principal_denied(self):
        outcome = self.admit("chunk_a_app_answer", principal="principal_demo_unrelated")
        self.assertEqual(self.denial(outcome, "chunk_a_app_answer"), DenialCode.ACCESS_DENIED)
        self.assertEqual(self.store.loads, [])

    def test_authority_error_fails_closed(self):
        self.authority.raise_error = True
        outcome = self.admit("chunk_a_app_answer")
        self.assertEqual(self.denial(outcome, "chunk_a_app_answer"), DenialCode.SOURCE_CHECK_FAILED)
        self.assertEqual(self.store.loads, [])

    def test_wrong_version_kind_denied(self):
        bad = self.index["chunk_a_app_answer"].model_dump(mode="json")
        bad["source_ref"]["version"] = support.raw()["programs"][0]["source_ref"]["version"]  # snapshot for native type
        self.index["chunk_a_app_answer"] = RetrievalChunk.model_validate(bad)
        outcome = self.admit("chunk_a_app_answer")
        self.assertEqual(self.denial(outcome, "chunk_a_app_answer"), DenialCode.INVALID_SOURCE_VERSION)
        self.assertEqual((self.authority.calls, self.store.loads), ([], []))

    def test_tampered_content_never_exposed(self):
        outcome = self.admit("chunk_d_tampered")
        self.assertEqual(self.denial(outcome, "chunk_d_tampered"), DenialCode.CONTENT_INTEGRITY)
        response = json.dumps(outcome.external_response().model_dump(mode="json"))
        self.assertNotIn("altered", response)

    def test_store_failure_fails_closed(self):
        del self.store.contents["store/fixture/chunk_a_app_answer"]
        outcome = self.admit("chunk_a_app_answer")
        self.assertEqual(self.denial(outcome, "chunk_a_app_answer"), DenialCode.CONTENT_UNAVAILABLE)
        self.assertEqual(outcome.admitted, ())

    def test_mixed_request_admits_only_allowed_chunks(self):
        outcome = self.admit("chunk_a_app_answer", "chunk_c_profile", "chunk_a_profile_old", "chunk_guess_0001")
        self.assertEqual([c.chunk_id for c in outcome.admitted], ["chunk_a_app_answer"])
        self.assertEqual(self.store.loads, ["store/fixture/chunk_a_app_answer"])


class ExternalIndistinguishabilityTests(AdmissionHarness):
    """Refinement 4: callers cannot tell nonexistent from inaccessible chunks or records."""

    def test_every_denial_mode_produces_the_same_external_shape(self):
        self.authority.set(support.COORDINATOR, self.index["chunk_b_profile"].source_ref,
                           VersionStatus.CURRENT, AccessStatus.DENIED)
        modes = {
            "chunk_guess_0001": DenialCode.UNKNOWN_CHUNK,
            "chunk_c_profile": DenialCode.CROSS_ORG,
            "chunk_b_profile": DenialCode.ACCESS_DENIED,
            "chunk_a_profile_old": DenialCode.NOT_CURRENT,
            "chunk_b_withdrawn": DenialCode.WITHDRAWN,
            "chunk_d_tampered": DenialCode.CONTENT_INTEGRITY,
        }
        shapes = set()
        for chunk_id, internal in modes.items():
            with self.subTest(chunk_id=chunk_id):
                outcome = self.admit(chunk_id)
                self.assertEqual(self.denial(outcome, chunk_id), internal)  # specific internally
                external = outcome.external_response().model_dump(mode="json")
                shapes.add(json.dumps(external, sort_keys=True).replace(chunk_id, "<requested>"))
                # Exactly the requested id, nothing else: no reason, code, count or record detail.
                self.assertEqual(external, {"organization_id": ORG, "admitted": [], "unavailable_chunk_ids": [chunk_id]})
        self.assertEqual(len(shapes), 1, shapes)

    def test_response_lists_unavailable_ids_in_sorted_order_without_reasons(self):
        outcome = self.admit("chunk_guess_0001", "chunk_c_profile", "chunk_a_app_answer")
        response = outcome.external_response()
        self.assertEqual(response.unavailable_chunk_ids, ("chunk_c_profile", "chunk_guess_0001"))
        self.assertEqual(set(RetrievalResponse.model_fields), {"organization_id", "admitted", "unavailable_chunk_ids"})


class PromptInjectionTests(AdmissionHarness):
    INJECTION = "chunk_e_injection"

    def test_injected_text_admitted_verbatim_as_untrusted_data_only(self):
        outcome = self.admit(self.INJECTION, "chunk_c_profile")
        (chunk,) = outcome.admitted
        self.assertEqual(chunk.text, support.ext_raw()["chunk_store"]["store/fixture/chunk_e_injection"])
        self.assertIn("IGNORE ALL PREVIOUS INSTRUCTIONS", chunk.text)
        self.assertEqual(chunk.trust, "untrusted_data")
        self.assertEqual(set(AdmittedChunk.model_fields), {"chunk_id", "source_ref", "field_path", "trust", "text"})
        self.assertEqual(self.denial(outcome, "chunk_c_profile"), DenialCode.CROSS_ORG)  # unaffected by the text

    def test_text_claiming_authorization_cannot_override_denial(self):
        chunk = self.index[self.INJECTION]
        self.assertEqual(chunk.access_scope_hint, "public")
        self.authority.set(support.COORDINATOR, chunk.source_ref, VersionStatus.CURRENT, AccessStatus.DENIED)
        outcome = self.admit(self.INJECTION)
        self.assertEqual(self.denial(outcome, self.INJECTION), DenialCode.ACCESS_DENIED)
        self.assertEqual(self.store.loads, [])  # the text was never read

    def test_embedded_json_is_not_interpreted(self):
        outcome = self.admit(self.INJECTION)
        dumped = outcome.external_response().model_dump(mode="json")
        self.assertEqual(set(dumped), {"organization_id", "admitted", "unavailable_chunk_ids"})
        self.assertNotIn("decision", dumped["admitted"][0])
        self.assertNotIn("access_status", dumped["admitted"][0])


class CitationTests(unittest.TestCase):
    def setUp(self):
        self.evidence = support.ext_context().evidence
        self.subject_a = EvidenceSubject(kind="candidate", id="candidate_demo_a")

    def _expect(self, ids, org, subject, code):
        with self.assertRaises(ContractViolation) as ctx:
            resolve_evidence_ids(ids, self.evidence, org, subject)
        self.assertEqual(ctx.exception.code, code)

    def test_valid_citations_resolve(self):
        resolved = resolve_evidence_ids(["evidence_a_profile_hours"], self.evidence, ORG, self.subject_a)
        self.assertEqual(resolved[0].source_ref.version.revision_id, "102")

    def test_invalid_citations_rejected(self):
        self._expect(["evidence_nonexistent"], ORG, self.subject_a, "invalid_citation")
        self._expect(["evidence_d_profile_hours"], ORG, self.subject_a, "invalid_citation")
        self._expect(["evidence_c_profile_hours"], ORG, EvidenceSubject(kind="candidate", id="candidate_demo_c"),
                     "cross_org_reference")

    def test_evidence_record_shape(self):
        base = support.ext_raw()["evidence"][0]
        for label, payload in (("copied text", {**base, "excerpt": "Synthetic"}),
                               ("statement about an opportunity", {**base, "subject": {"kind": "opportunity", "id": "opportunity_demo_data"}}),
                               ("mismatched subject prefix", {**base, "subject": {"kind": "opportunity", "id": "candidate_demo_a"}}),
                               ("bad field path", {**base, "field_path": "Skills/Python"})):
            with self.subTest(label), self.assertRaises(ValidationError):
                type(self.evidence["evidence_a_profile_hours"]).model_validate(payload)


if __name__ == "__main__":
    unittest.main()
