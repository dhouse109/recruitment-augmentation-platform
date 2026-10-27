"""D-004.02 -- profile / application / opportunity separation, submission preservation, lifecycle."""

import itertools
import unittest

from pydantic import ValidationError

import support
from rap_contracts.invariants import (
    ALLOWED_APPLICATION_TRANSITIONS,
    PINNED_VERSIONS_MAY_BE_ABSENT,
    ContractRecordSet,
    ContractViolation,
    check_application_transition,
    check_application_update,
    check_profile_revision,
    check_record_set,
)
from rap_contracts.models import Application, ApplicationStatus, CandidateProfile, Opportunity
from rap_contracts.source_checks import resolve_submission_evidence
from rap_contracts.models import AccessStatus, VersionStatus
from rap_contracts.invariants import application_submission_ref


def _app(record_id):
    return support.by_id(support.records().applications, record_id)


def _profile_version(revision):
    return next(p for p in support.records().profiles
                if p.id == "profile_demo_a" and p.source_ref.version.revision_id == revision)


class IndependentApplicationTests(unittest.TestCase):
    def test_one_candidate_two_independent_applications(self):
        data, web = _app("application_demo_a_data"), _app("application_demo_a_web")
        self.assertEqual(data.candidate_id, web.candidate_id)
        self.assertNotEqual(data.id, web.id)
        self.assertNotEqual(data.source_ref.entity, web.source_ref.entity)
        # Each pins the profile version current at its own submission time.
        self.assertEqual(data.submission.profile_ref.version.revision_id, "101")
        self.assertEqual(web.submission.profile_ref.version.revision_id, "102")

    def test_withdrawing_one_application_leaves_the_other_untouched(self):
        data, web = _app("application_demo_a_data"), _app("application_demo_a_web")
        withdrawn = data.model_dump()
        withdrawn["status"] = "withdrawn"
        withdrawn["source_ref"]["version"]["revision_id"] = "712"
        withdrawn = Application.model_validate(withdrawn)
        check_application_update(data, withdrawn)
        self.assertEqual(withdrawn.submission, data.submission)  # history kept
        self.assertEqual(_app("application_demo_a_web"), web)
        self.assertIs(web.status, ApplicationStatus.SUBMITTED)


class SubmissionPreservationTests(unittest.TestCase):
    def test_profile_revision_does_not_mutate_submitted_snapshot(self):
        r101, r102 = _profile_version("101"), _profile_version("102")
        check_profile_revision(r101, r102)
        data = _app("application_demo_a_data")
        # The later profile revision exists in the record set, but the snapshot still pins 101.
        self.assertEqual(data.submission.profile_ref, r101.source_ref)
        self.assertNotEqual(data.submission.profile_ref, r102.source_ref)

    def test_rewriting_pinned_profile_to_newer_revision_rejected(self):
        data = _app("application_demo_a_data")
        rewritten = data.model_dump()
        rewritten["submission"]["profile_ref"]["version"]["revision_id"] = "102"
        with self.assertRaises(ContractViolation) as ctx:
            check_application_update(data, Application.model_validate(rewritten))
        self.assertEqual(ctx.exception.code, "submission_rewrite")

    def test_removing_submission_rejected(self):
        data = _app("application_demo_a_data")
        removed = {**data.model_dump(), "status": "withdrawn", "submission": None}
        with self.assertRaises(ContractViolation) as ctx:
            check_application_update(data, Application.model_validate(removed))
        self.assertEqual(ctx.exception.code, "submission_rewrite")

    def test_submission_added_only_by_draft_to_submitted(self):
        draft = _app("application_demo_b_program")
        submitted = draft.model_dump()
        submitted["status"] = "submitted"
        submitted["source_ref"]["version"]["revision_id"] = "732"
        submitted["submission"] = {
            "submitted_at": "2026-10-24T10:00:00Z",
            "profile_id": "profile_demo_b",
            "profile_ref": support.raw_record("profiles", "profile_demo_b")["source_ref"],
            "application_version": {"kind": "native_revision", "revision_id": "732"},
        }
        check_application_update(draft, Application.model_validate(submitted))
        withdrawn_with_sub = {**submitted, "status": "withdrawn"}
        with self.assertRaises(ContractViolation) as ctx:
            check_application_update(draft, Application.model_validate(withdrawn_with_sub))
        self.assertEqual(ctx.exception.code, "submission_without_submit")

    def test_pinning_another_candidates_profile_rejected(self):
        bad = support.raw_record("applications", "application_demo_a_data")
        bad["submission"]["profile_id"] = "profile_demo_b"
        bad["submission"]["profile_ref"] = support.raw_record("profiles", "profile_demo_b")["source_ref"]
        recs = support.records()
        apps = tuple(a for a in recs.applications if a.id != bad["id"]) + (Application.model_validate(bad),)
        with self.assertRaises(ContractViolation) as ctx:
            check_record_set(ContractRecordSet(**{**recs.__dict__, "applications": apps}))
        self.assertEqual(ctx.exception.code, "submission_profile_mismatch")

    def test_profile_ref_that_does_not_locate_the_named_profile_rejected(self):
        bad = support.raw_record("applications", "application_demo_a_data")
        bad["submission"]["profile_ref"]["entity"]["entity_id"] = "5002"
        recs = support.records()
        apps = tuple(a for a in recs.applications if a.id != bad["id"]) + (Application.model_validate(bad),)
        with self.assertRaises(ContractViolation) as ctx:
            check_record_set(ContractRecordSet(**{**recs.__dict__, "applications": apps}))
        self.assertEqual(ctx.exception.code, "submission_profile_mismatch")

    def test_profile_versions_must_share_owner_and_source_entity(self):
        r101 = _profile_version("101")
        moved = r101.model_dump()
        moved["source_ref"]["entity"]["entity_id"] = "5999"
        with self.assertRaises(ContractViolation) as ctx:
            check_profile_revision(r101, CandidateProfile.model_validate(moved))
        self.assertEqual(ctx.exception.code, "profile_source_entity_changed")


class PinnedVersionMembershipTests(unittest.TestCase):
    """check_record_set treatment of the exact pinned profile version (complete vs partial record sets)."""

    def _without_r101(self):
        recs = support.records()
        profiles = tuple(p for p in recs.profiles
                         if not (p.id == "profile_demo_a" and p.source_ref.version.revision_id == "101"))
        return ContractRecordSet(**{**recs.__dict__, "profiles": profiles})

    def test_complete_fixture_set_contains_every_pinned_version(self):
        check_record_set(support.records())  # default: must_be_present

    def test_complete_set_missing_pinned_version_rejected(self):
        with self.assertRaises(ContractViolation) as ctx:
            check_record_set(self._without_r101())
        self.assertEqual(ctx.exception.code, "unpinned_profile_version")

    def test_complete_set_pinning_nonexistent_version_rejected(self):
        bad = support.raw_record("applications", "application_demo_a_data")
        bad["submission"]["profile_ref"]["version"]["revision_id"] = "199"  # right profile entity, unknown version
        recs = support.records()
        apps = tuple(a for a in recs.applications if a.id != bad["id"]) + (Application.model_validate(bad),)
        with self.assertRaises(ContractViolation) as ctx:
            check_record_set(ContractRecordSet(**{**recs.__dict__, "applications": apps}))
        self.assertEqual(ctx.exception.code, "unpinned_profile_version")

    def test_partial_set_defers_to_resolver_which_fails_closed(self):
        partial = self._without_r101()
        check_record_set(partial, pinned_versions=PINNED_VERSIONS_MAY_BE_ABSENT)  # documented assumption
        app = support.by_id(partial.applications, "application_demo_a_data")
        authority = support.FixtureSourceAuthority()  # MOCK: pinned 101 not retained; 102 is current
        authority.set(support.COORDINATOR, app.submission.profile_ref, VersionStatus.UNAVAILABLE, AccessStatus.ALLOWED)
        authority.set(support.COORDINATOR, application_submission_ref(app), VersionStatus.CURRENT, AccessStatus.ALLOWED)
        authority.set(support.COORDINATOR, _profile_version("102").source_ref, VersionStatus.CURRENT, AccessStatus.ALLOWED)
        with self.assertRaises(ContractViolation) as ctx:
            resolve_submission_evidence(app, authority, support.COORDINATOR)
        self.assertEqual(ctx.exception.code, "source_unavailable")
        self.assertEqual(authority.calls, [app.submission.profile_ref])  # stopped; never fell back to 102

    def test_partial_set_resolves_when_authority_still_retains_pinned_version(self):
        partial = self._without_r101()
        check_record_set(partial, pinned_versions=PINNED_VERSIONS_MAY_BE_ABSENT)
        app = support.by_id(partial.applications, "application_demo_a_data")
        authority = support.FixtureSourceAuthority()
        authority.set(support.COORDINATOR, app.submission.profile_ref, VersionStatus.SUPERSEDED, AccessStatus.ALLOWED)
        authority.set(support.COORDINATOR, application_submission_ref(app), VersionStatus.CURRENT, AccessStatus.ALLOWED)
        profile_result, _ = resolve_submission_evidence(app, authority, support.COORDINATOR)
        self.assertEqual(profile_result.source, app.submission.profile_ref)

    def test_unknown_mode_rejected(self):
        with self.assertRaises(ValueError):
            check_record_set(support.records(), pinned_versions="trust_me")


class PinnedEvidenceResolutionTests(unittest.TestCase):
    """Fail-closed resolution of pinned versions. MOCK authority: plumbing only, not Drupal ACL/retention."""

    def setUp(self):
        self.app = _app("application_demo_a_data")
        self.authority = support.FixtureSourceAuthority()
        self.profile_ref = self.app.submission.profile_ref
        self.app_ref = application_submission_ref(self.app)
        p = support.COORDINATOR
        self.authority.set(p, self.profile_ref, VersionStatus.SUPERSEDED, AccessStatus.ALLOWED)  # 102 is newer
        self.authority.set(p, self.app_ref, VersionStatus.CURRENT, AccessStatus.ALLOWED)
        self.authority.set(p, _profile_version("102").source_ref, VersionStatus.CURRENT, AccessStatus.ALLOWED)

    def test_pinned_superseded_version_resolves_without_substitution(self):
        profile_result, app_result = resolve_submission_evidence(self.app, self.authority, support.COORDINATOR)
        self.assertEqual(profile_result.source, self.profile_ref)
        self.assertEqual(app_result.source, self.app_ref)
        self.assertEqual(self.authority.calls, [self.profile_ref, self.app_ref])  # never asked for 102

    def _expect(self, code):
        with self.assertRaises(ContractViolation) as ctx:
            resolve_submission_evidence(self.app, self.authority, support.COORDINATOR)
        self.assertEqual(ctx.exception.code, code)

    def test_unavailable_pinned_version_fails_closed_without_fallback(self):
        self.authority.set(support.COORDINATOR, self.profile_ref, VersionStatus.UNAVAILABLE, AccessStatus.ALLOWED)
        self._expect("source_unavailable")
        self.assertNotIn(_profile_version("102").source_ref, self.authority.calls)

    def test_withdrawn_pinned_version_fails_closed(self):
        self.authority.set(support.COORDINATOR, self.profile_ref, VersionStatus.WITHDRAWN, AccessStatus.ALLOWED)
        self._expect("source_withdrawn")

    def test_deleted_pinned_version_fails_closed(self):
        self.authority.set(support.COORDINATOR, self.app_ref, VersionStatus.DELETED, AccessStatus.ALLOWED)
        self._expect("source_deleted")

    def test_no_longer_authorized_fails_closed(self):
        self.authority.set(support.COORDINATOR, self.profile_ref, VersionStatus.SUPERSEDED, AccessStatus.DENIED)
        self._expect("source_access_denied")

    def test_unknown_principal_fails_closed(self):
        with self.assertRaises(ContractViolation) as ctx:
            resolve_submission_evidence(self.app, self.authority, "principal_demo_unrelated")
        self.assertEqual(ctx.exception.code, "source_access_denied")

    def test_authority_substituting_newer_profile_rejected(self):
        self.authority.substitute[self.profile_ref] = _profile_version("102").source_ref
        self._expect("source_substitution")

    def test_authority_error_fails_closed(self):
        self.authority.raise_error = True
        self._expect("source_check_error")

    def test_withdrawn_application_is_not_active_evidence(self):
        withdrawn = Application.model_validate({**self.app.model_dump(), "status": "withdrawn"})
        with self.assertRaises(ContractViolation) as ctx:
            resolve_submission_evidence(withdrawn, self.authority, support.COORDINATOR)
        self.assertEqual(ctx.exception.code, "application_withdrawn")

    def test_draft_has_no_submission_evidence(self):
        with self.assertRaises(ContractViolation) as ctx:
            resolve_submission_evidence(_app("application_demo_b_program"), self.authority, support.COORDINATOR)
        self.assertEqual(ctx.exception.code, "no_submission")


class LifecycleTests(unittest.TestCase):
    ALLOWED = {
        ("draft", "submitted"), ("draft", "withdrawn"),
        ("submitted", "withdrawn"), ("submitted", "closed"),
    }

    def test_full_transition_matrix(self):
        for src, dst in itertools.product(ApplicationStatus, repeat=2):
            with self.subTest(src=src.value, dst=dst.value):
                if src is dst or (src.value, dst.value) in self.ALLOWED:
                    check_application_transition(src, dst)
                else:
                    with self.assertRaises(ContractViolation) as ctx:
                        check_application_transition(src, dst)
                    self.assertEqual(ctx.exception.code, "forbidden_transition")

    def test_withdrawn_and_closed_are_terminal(self):
        self.assertEqual(ALLOWED_APPLICATION_TRANSITIONS[ApplicationStatus.WITHDRAWN], frozenset())
        self.assertEqual(ALLOWED_APPLICATION_TRANSITIONS[ApplicationStatus.CLOSED], frozenset())

    def test_reopen_via_update_rejected(self):
        closed = Application.model_validate({**_app("application_demo_a_data").model_dump(), "status": "closed"})
        reopened = Application.model_validate({**closed.model_dump(), "status": "submitted"})
        with self.assertRaises(ContractViolation) as ctx:
            check_application_update(closed, reopened)
        self.assertEqual(ctx.exception.code, "forbidden_transition")

    def test_status_submission_coupling(self):
        submitted = support.raw_record("applications", "application_demo_a_data")
        draft = support.raw_record("applications", "application_demo_b_program")
        cases = [
            ({**submitted, "status": "draft"}, False),
            ({**submitted, "submission": None}, False),
            ({**submitted, "status": "closed", "submission": None}, False),
            ({**submitted, "status": "closed"}, True),
            ({**submitted, "status": "withdrawn"}, True),  # withdrawn after submission keeps history
            ({**draft, "status": "withdrawn"}, True),      # withdrawn from draft has none
        ]
        for payload, ok in cases:
            with self.subTest(status=payload["status"], has_submission=payload.get("submission") is not None):
                if ok:
                    Application.model_validate(payload)
                else:
                    with self.assertRaises(ValidationError):
                        Application.model_validate(payload)

    def test_immutable_application_fields(self):
        data = _app("application_demo_a_data")
        for field, value in (("candidate_id", "candidate_demo_b"), ("target", {"opportunity_id": "opportunity_demo_web"})):
            with self.subTest(field=field):
                changed = Application.model_validate({**data.model_dump(), field: value})
                with self.assertRaises(ContractViolation) as ctx:
                    check_application_update(data, changed)
                self.assertEqual(ctx.exception.code, "application_immutable_field")

    def test_submission_timestamps_must_be_timezone_aware(self):
        bad = support.raw_record("applications", "application_demo_a_data")
        bad["submission"]["submitted_at"] = "2026-10-20T14:00:00"
        with self.assertRaises(ValidationError):
            Application.model_validate(bad)

    def test_submission_version_kind_must_match_application_source(self):
        bad = support.raw_record("applications", "application_demo_a_data")
        bad["submission"]["application_version"] = support.raw()["programs"][0]["source_ref"]["version"]
        with self.assertRaises(ValidationError):
            Application.model_validate(bad)


class TargetTests(unittest.TestCase):
    def _check(self, target):
        bad = support.raw_record("applications", "application_demo_b_program")
        bad["id"] = "application_demo_b_target"
        bad["target"] = target
        recs = support.records()
        recs = ContractRecordSet(**{**recs.__dict__, "applications": recs.applications + (Application.model_validate(bad),)})
        check_record_set(recs)

    def test_valid_target_shapes(self):
        for target in ({"program_id": "program_demo_001"}, {"opportunity_id": "opportunity_demo_web"},
                       {"program_id": "program_demo_001", "opportunity_id": "opportunity_demo_web"}):
            with self.subTest(target=target):
                self._check(target)

    def test_empty_target_rejected(self):
        bad = support.raw_record("applications", "application_demo_b_program")
        for target in ({}, {"program_id": None, "opportunity_id": None}):
            with self.subTest(target=target), self.assertRaises(ValidationError):
                Application.model_validate({**bad, "target": target})

    def test_unknown_target_rejected(self):
        with self.assertRaises(ContractViolation) as ctx:
            self._check({"opportunity_id": "opportunity_demo_missing"})
        self.assertEqual(ctx.exception.code, "unknown_reference")

    def test_opportunity_outside_targeted_program_rejected(self):
        opp = support.raw_record("opportunities", "opportunity_demo_web")
        opp["program_id"] = None
        recs = support.records()
        opps = tuple(o for o in recs.opportunities if o.id != opp["id"]) + (Opportunity.model_validate(opp),)
        bad = support.raw_record("applications", "application_demo_b_program")
        bad["target"] = {"program_id": "program_demo_001", "opportunity_id": "opportunity_demo_web"}
        apps = tuple(a for a in recs.applications if a.id != bad["id"]) + (Application.model_validate(bad),)
        with self.assertRaises(ContractViolation) as ctx:
            check_record_set(ContractRecordSet(**{**recs.__dict__, "opportunities": opps, "applications": apps}))
        self.assertEqual(ctx.exception.code, "target_program_mismatch")


class PortabilityTests(unittest.TestCase):
    def test_job_opportunity_uses_same_contracts(self):
        job = support.by_id(support.records().opportunities, "opportunity_demo_job")
        self.assertEqual(job.opportunity_type, "job")
        app = _app("application_demo_c_job")
        self.assertIsInstance(app, Application)
        self.assertEqual(app.target.opportunity_id, job.id)


if __name__ == "__main__":
    unittest.main()
