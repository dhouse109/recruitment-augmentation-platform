"""F3 (RAP-F3-PLAN-2026-11-04 rev. 1.1): golden v2 scenario separation on the runner.

g002 v2 is B x web (availability unknown only) and g008 v2 is G x data (qualification contested only). These
tests record what the unmodified engine produces on the pinned synthetic inputs and that the runner's admission,
case-local label rules (F3-D3, L1-L5), definitions pins and historical non-comparability fail closed. Agreement
with the PROPOSED, unadjudicated labels is not reviewed correctness.
"""

from __future__ import annotations

import builtins
import copy
import io
import json
import shutil
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from helpers import AS_OF, LazyClassFixture, TempDirTest, admitted, case_doc, config, copy_allowed, products, tampered
from rap_baseline import Assessed, assess
from rap_contracts.claims import CandidateClaim
from rap_contracts.eligibility import EligibilityContext, EligibilityResult
from rap_contracts.evaluation import EvaluationDatasetManifest, StepStatus, pin_manifest
from rap_contracts.evidence import EvidenceRecord
from rap_contracts.models import CONTRACT_VERSION

from rap_evaluation import EXECUTED_BY, EXIT_RUNNER, AdmissionAbort, BindingFailure, __main__ as cli
from rap_evaluation import fixtures as fx
from rap_evaluation.authority import FixtureMockAuthority
from rap_evaluation.execute import EligibilityRequest
from rap_evaluation.identity import verify_repeat
from rap_evaluation.run import run_evaluation

PRINCIPAL = "principal_demo_coordinator"
GOLDEN_V1 = "evaluation-golden-v0.2.0-dev.json"


def case_record(golden: dict, kind: str, record_id: str) -> dict:
    return next(r for r in golden["case_records"][kind] if r["id"] == record_id)


def non_pass(result: EligibilityResult) -> list[tuple[str, str, str]]:
    return [(o.rule_id, o.result.value, o.reason_code) for o in result.rule_outcomes if o.result.value != "pass"]


# ---------------------------------------------------------------------------------------------------------------
# E1, E2, E13: the real run on golden v2
# ---------------------------------------------------------------------------------------------------------------


class GoldenV2RunTests(LazyClassFixture):
    @classmethod
    def _fixture(cls):
        cls.p = products()
        cls.entries = {(e.case_id, e.step_id): e for e in cls.p.entries}

    def test_e1_all_steps_match_and_counts_are_preserved(self):
        executed = [o for o in self.p.observations if o.execution_status == "executed"]
        self.assertEqual([o.case_id for o in executed],
                         ["evalcase_g002", "evalcase_g003", "evalcase_g008", "evalcase_g025"])
        self.assertEqual({s.status for o in executed for s in o.steps}, {StepStatus.MATCHED})
        c = self.p.coverage
        self.assertEqual((c["pinned_cases"], c["executed_cases"], c["not_run_cases"], c["executed_steps"],
                          c["engine_steps"], c["validator_steps"], c["engine_invocations"], c["distinct_assessments"]),
                         (26, 4, 22, 6, 5, 1, 5, 4))
        self.assertNotIn("f3_shared_scenario", c)
        self.assertEqual(self.p.run.status, "partial")
        self.assertIsNone(self.p.run.completed_at)

    def test_e1_run_pins_golden_v2_policy_v3_and_metrics_v1(self):
        run = self.p.run
        self.assertEqual([(m.id, m.version) for m in run.manifests], [("evalset_golden", 2)])
        self.assertEqual((run.definitions.id, run.definitions.version), ("evaldefs_metrics", 1))
        self.assertEqual((run.safety_policy.id, run.safety_policy.version), ("evaldefs_safety_gate", 3))

    def test_e1_f3_cases_produce_the_isolated_outcomes(self):
        g002, g008 = self.entries[("evalcase_g002", "s1")].result, self.entries[("evalcase_g008", "s1")].result
        self.assertEqual((g002.candidate_id, g002.opportunity_id), ("candidate_demo_b", "opportunity_demo_web"))
        self.assertEqual(non_pass(g002), [("PILOT-AVAIL-003", "unknown", "availability_not_declared")])
        self.assertEqual((g008.candidate_id, g008.opportunity_id), ("candidate_demo_g", "opportunity_demo_data"))
        self.assertEqual(non_pass(g008), [("PILOT-SKILL-004", "unknown", "qualification_contested")])
        self.assertEqual((g002.decision.value, g008.decision.value), ("needs_information", "needs_information"))

    def test_e2_four_independent_assessment_identities(self):
        e = self.entries
        g002, g008 = e[("evalcase_g002", "s1")], e[("evalcase_g008", "s1")]
        self.assertNotEqual(g002.key.assessment(), g008.key.assessment())
        self.assertNotEqual(g002.provenance["input_fingerprint"], g008.provenance["input_fingerprint"])
        self.assertNotEqual(g002.result.id, g008.result.id)
        self.assertEqual(e[("evalcase_g003", "s1")].result.id, e[("evalcase_g025", "s2")].result.id)  # A x ops
        self.assertEqual(len({x.result.id for x in self.p.entries}), 4)
        self.assertEqual(len({x.key.assessment() for x in self.p.entries}), 4)

    def test_e13_contract_version_provenance(self):
        self.assertEqual(self.p.spec["manifest_contract_version"], "0.2.0-dev.foundations.6")
        self.assertEqual(self.p.spec["contract_version"], CONTRACT_VERSION)
        self.assertEqual(self.p.run.contract_version, CONTRACT_VERSION)
        self.assertEqual(self.p.run.executed_by, EXECUTED_BY)
        self.assertEqual(EXECUTED_BY, "rap-evaluation.runner/0.2.0")


# ---------------------------------------------------------------------------------------------------------------
# E3, E4: isolation counterfactuals (in memory, the merged engine, the admitted scope)
# ---------------------------------------------------------------------------------------------------------------


class IsolationCounterfactualTests(TempDirTest):
    def assess_with(self, case_id: str, claims=None, evidence=None) -> EligibilityResult:
        adm = admitted()
        scope, key = adm.scopes[case_id], adm.keys[(case_id, "s1")]
        ev = dict(scope.eligibility.evidence) if evidence is None else evidence
        ctx = EligibilityContext(**{**scope.eligibility.__dict__,
                                    "claims": scope.eligibility.claims if claims is None else claims, "evidence": ev})
        refs = set(scope.source_refs) | {e.source_ref for e in ev.values()}
        out = assess(EligibilityRequest(organization_id=key.organization_id, candidate_id=key.candidate_id,
                                        opportunity_id=key.opportunity_id, policy=key.policy, principal_id=PRINCIPAL,
                                        as_of=AS_OF), ctx, FixtureMockAuthority([PRINCIPAL], refs, AS_OF), scope.capabilities)
        self.assertIsInstance(out, Assessed)
        return out.result

    def replace_claim(self, case_id, claim_id, **changes):
        out = []
        for c in admitted().scopes[case_id].eligibility.claims:
            if c.id == claim_id:
                d = c.model_dump(mode="json")
                for k in changes.pop("_drop", ()):
                    d.pop(k)
                d.update(changes)
                c = CandidateClaim.model_validate(d)
            out.append(c)
        return tuple(out)

    def test_e3_g002_cannot_be_influenced_by_b_contested_skill(self):
        base = self.assess_with("evalcase_g002")
        claims = tuple(c for c in admitted().scopes["evalcase_g002"].eligibility.claims if c.id != "claim_b_python")
        self.assertEqual(self.assess_with("evalcase_g002", claims=claims).id, base.id)  # identical result id

    def test_e3_g002_flipping_only_availability_removes_the_only_unknown(self):
        scope = admitted().scopes["evalcase_g002"]
        src = scope.eligibility.evidence["evidence_b_profile_interest"].model_dump(mode="json")
        src.update(id="evidence_b_profile_hours_cf", field_path="availability.weekly_hours")
        ev = {**scope.eligibility.evidence, "evidence_b_profile_hours_cf": EvidenceRecord.model_validate(src)}
        for hours, decision, rules in ((10, "eligible", []),
                                       (8, "ineligible", [("PILOT-AVAIL-003", "fail", "availability_below_required_hours")])):
            claims = self.replace_claim("evalcase_g002", "claim_b_availability", state="declared",
                                        value={"kind": "availability", "hours_per_week": hours},
                                        evidence_ids=["evidence_b_profile_hours_cf"])
            r = self.assess_with("evalcase_g002", claims=claims, evidence=ev)
            with self.subTest(hours=hours):
                self.assertEqual((r.decision.value, non_pass(r)), (decision, rules))

    def test_e4_g008_flipping_only_the_skill_claim_removes_the_only_unknown(self):
        claims = self.replace_claim("evalcase_g008", "claim_g_python", _drop=("alternatives",), state="declared",
                                    value={"kind": "skill", "presence": "has"}, evidence_ids=["evidence_g_profile_python"])
        r = self.assess_with("evalcase_g008", claims=claims)
        self.assertEqual((r.decision.value, non_pass(r)), ("eligible", []))

    def test_e4_g008_availability_is_a_live_rule_away_from_the_boundary(self):
        cases = ((10, "ineligible", [("PILOT-AVAIL-003", "fail", "availability_below_required_hours"),
                                     ("PILOT-SKILL-004", "unknown", "qualification_contested")]),
                 (12, "needs_information", [("PILOT-SKILL-004", "unknown", "qualification_contested")]))
        for hours, decision, rules in cases:
            claims = self.replace_claim("evalcase_g008", "claim_g_availability",
                                        value={"kind": "availability", "hours_per_week": hours})
            r = self.assess_with("evalcase_g008", claims=claims)
            with self.subTest(hours=hours):
                self.assertEqual((r.decision.value, non_pass(r)), (decision, rules))


# ---------------------------------------------------------------------------------------------------------------
# E5, E6, E8, E12: admission (every abort exits 3 and writes nothing)
# ---------------------------------------------------------------------------------------------------------------


class F3AdmissionTests(TempDirTest):
    def assertAborts(self, check, code, fixture_dir=None):
        out = self.tmp / "out" / "run"
        engine = mock.MagicMock(name="assess")
        with self.assertRaises(AdmissionAbort) as cm:
            run_evaluation(config(out), fixture_dir=fixture_dir or fx.FIXTURE_DIR, assess_fn=engine)
        self.assertEqual((cm.exception.check, cm.exception.code), (check, code), str(cm.exception))
        engine.assert_not_called()
        self.assertNothingPublished(out)
        self.assertFalse((self.tmp / "out").exists())

    # --- E5: case-local label rules L1-L5 -----------------------------------------------------------
    def test_e5_l3_included_label_no_step_references(self):
        def extra(g):
            lab = dict(case_record(g, "eligibility_results", "eligibility_b_web"), id="eligibility_b_web_extra")
            g["case_records"]["eligibility_results"].append(lab)
            case_doc(g, "evalcase_g002")["scope"]["include_records"].append("eligibility_b_web_extra")
        with tampered(golden=extra):
            self.assertAborts("A6", "include_label_not_step_referenced")

    def test_e5_l2_another_candidates_label(self):
        with tampered(golden=lambda g: case_doc(g, "evalcase_g002")["scope"]["include_records"].append("eligibility_g_data")):
            self.assertAborts("A5", "include_record_out_of_scope")

    def test_e5_other_record_kinds_are_still_rejected(self):
        # Chunks, recommendations and verifications owned by candidate A, included in g003 (scope A).
        for rid in ("chunk_a_injection", "recommendation_a_ops", "verification_a_ops_lax"):
            with self.subTest(record=rid), \
                    tampered(golden=lambda g, rid=rid: case_doc(g, "evalcase_g003")["scope"]["include_records"].append(rid)):
                self.assertAborts("A6", "include_record_kind_not_supported")

    def test_e5_l5_case_local_label_must_be_declared(self):
        with tampered(golden=lambda g: case_doc(g, "evalcase_g002")["scope"].update(include_records=[])):
            self.assertAborts("A7", "label_not_declared_in_scope")

    def test_e5_l1_duplicate_case_local_label(self):
        def dup(g):
            g["case_records"]["eligibility_results"].append(dict(case_record(g, "eligibility_results", "eligibility_g_data")))
        with tampered(golden=dup):
            self.assertAborts("A5", "include_record_unresolvable")

    # --- E6: labels are references only ------------------------------------------------------------
    def test_e6_labels_are_never_constructed_or_given_to_the_engine(self):
        adm = admitted()
        for case_id, labels in (("evalcase_g002", {"eligibility_b_web"}), ("evalcase_g008", {"eligibility_g_data"}),
                                ("evalcase_g003", set()), ("evalcase_g025", set())):
            scope = adm.scopes[case_id]
            with self.subTest(case=case_id):
                self.assertEqual(set(scope.included_labels), labels)
                self.assertFalse([k for k, _ in scope.constructed if k == "eligibility_results"])
                self.assertFalse(hasattr(scope.eligibility, "eligibility_results"))
        seen = []

        def spy(request, context, authority, capabilities):
            seen.append(context)
            return assess(request, context, authority, capabilities)
        products(assess_fn=spy)
        for ctx in seen:
            self.assertIsInstance(ctx, EligibilityContext)
            self.assertFalse(hasattr(ctx, "eligibility_results"))

    # --- E8: definitions pins ----------------------------------------------------------------------
    def test_e8_policy_v1_and_v2_definitions_files_are_refused(self):
        for name, code in (("evaluation-definitions-v0.2.0-dev.json", "policy_pin_mismatch"),
                           ("evaluation-definitions-v2-v0.2.0-dev.json", "metrics_pin_mismatch")):
            doc = json.loads((fx.FIXTURE_DIR / name).read_text(encoding="utf-8"))  # test-only read
            with self.subTest(file=name), tampered(definitions=lambda d, doc=doc: (d.clear(), d.update(copy.deepcopy(doc)))):
                self.assertAborts("A4", code)

    def test_e8_policy_v1_pin_or_metrics_v2_pin_is_refused(self):
        with tampered(definitions=lambda d: d["safety_gate_policy"].update(version=1)):
            self.assertAborts("A4", "policy_pin_mismatch")
        with tampered(definitions=lambda d: d["metric_definitions"].update(version=2)):
            self.assertAborts("A4", "metrics_pin_mismatch")

    # --- E12: tampered G data fails closed ----------------------------------------------------------
    def edit_copy(self, mutate) -> Path:
        d = copy_allowed(self.tmp / "fixtures")
        path = d / fx.GOLDEN_FILE
        doc = json.loads(path.read_text(encoding="utf-8"))
        mutate(doc)
        path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return d

    def test_e12_g008_case_hash_tamper(self):
        d = self.edit_copy(lambda g: case_doc(g, "evalcase_g008").update(title="tampered title"))
        self.assertAborts("A3", "manifest_case_modified", fixture_dir=d)

    def test_e12_g_case_record_tamper(self):
        d = self.edit_copy(lambda g: case_record(g, "claims", "claim_g_availability")["value"].update(hours_per_week=11))
        self.assertAborts("A3", "case_records_digest_mismatch", fixture_dir=d)

    def test_e12_g_record_owned_by_another_or_held_out_candidate(self):
        for owner in ("candidate_demo_a", "candidate_demo_d"):
            with self.subTest(owner=owner), tampered(
                    golden=lambda g, owner=owner: case_record(g, "claims", "claim_g_python").update(candidate_id=owner)):
                self.assertAborts("A5", "include_record_out_of_scope")

    def test_e12_g_label_key_tampers(self):
        with tampered(golden=lambda g: case_record(g, "eligibility_results", "eligibility_g_data")["policy"].update(version=2)):
            self.assertAborts("A7", "key_policy_pin_mismatch")
        with tampered(golden=lambda g: case_record(g, "eligibility_results", "eligibility_g_data").update(
                organization_id="org_demo_002")):
            self.assertAborts("A7", "key_organization_mismatch")

    def test_e12_extra_scope_inclusion(self):
        with tampered(golden=lambda g: case_doc(g, "evalcase_g008")["scope"]["include_records"].append("claim_a_web_content_inferred")):
            self.assertAborts("A5", "include_record_out_of_scope")


# ---------------------------------------------------------------------------------------------------------------
# E9: only the five allowed files are opened
# ---------------------------------------------------------------------------------------------------------------


class AllowedFilesTests(TempDirTest):
    def test_e9_golden_v1_and_definitions_v1_v2_are_never_opened(self):
        opened = []
        real_open = builtins.open

        def spy(file, *a, **k):
            opened.append(Path(str(file)).name)
            return real_open(file, *a, **k)
        with mock.patch("builtins.open", side_effect=spy):
            fx.load_fixtures()
        fixtures = [n for n in opened if n.endswith(".json")]
        self.assertEqual(sorted(fixtures), sorted(fx.ALLOWED_FILES))
        self.assertEqual(len(fx.ALLOWED_FILES), 5)
        for never in (GOLDEN_V1, "evaluation-definitions-v0.2.0-dev.json", "evaluation-definitions-v2-v0.2.0-dev.json"):
            self.assertNotIn(never, fixtures)
        self.assertFalse([n for n in opened if "held-out" in n])


# ---------------------------------------------------------------------------------------------------------------
# E11a: a run pinned to another golden manifest cannot be re-verified (no verdict; exit 4)
# ---------------------------------------------------------------------------------------------------------------


class ForeignManifestRunTests(LazyClassFixture):
    """Narrow claim: the runner rejects a run directory pinned to a different golden manifest (here golden v1).

    It does not exercise historical runner code; the reproducible historical-checkout check is E11b
    (tools/historical_v1_check.py)."""

    @classmethod
    def _fixture(cls):
        cls.dir = Path(tempfile.mkdtemp(prefix="rap-eval-f3-"))
        cls.addClassCleanup(shutil.rmtree, cls.dir, True)
        cls.r1 = run_evaluation(config(cls.dir / "r1"))
        cls.r2 = run_evaluation(config(cls.dir / "r2"))
        v1 = json.loads((fx.FIXTURE_DIR / GOLDEN_V1).read_text(encoding="utf-8"))  # test-only read of golden v1
        cls.v1_pin = pin_manifest(EvaluationDatasetManifest.model_validate(v1["manifest"])).model_dump(mode="json")
        run_path = cls.r1 / "run.json"
        run = json.loads(run_path.read_text(encoding="utf-8"))
        run["manifests"] = [cls.v1_pin]
        run_path.write_text(json.dumps(run, indent=2, sort_keys=True), encoding="utf-8")

    def test_e11a_v1_pinned_run_is_rejected_without_a_verdict(self):
        self.assertEqual(self.v1_pin["version"], 1)
        with self.assertRaises(BindingFailure) as cm:
            verify_repeat(self.r1, self.r2)
        self.assertEqual(cm.exception.check, "P1")

    def test_e11a_cli_exits_4(self):
        with redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()):
            code = cli.main(["verify-repeat", str(self.r1), str(self.r2)])
        self.assertEqual(code, EXIT_RUNNER)
        self.assertNotIn("verdict", out.getvalue())
