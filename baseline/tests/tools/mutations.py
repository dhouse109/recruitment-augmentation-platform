"""TEST-ONLY failure-first mutation harness for PR-S2 acceptance A3 and A16.

Each mutation disables one invariant by an exact, single-occurrence text replacement
in a scratch copy of the repository, runs the baseline suite there, and reports
failures and errors (including failing subtests) and failing test methods. The
working tree is never modified.

Classification (review repair R1): a mutation is CAUGHT only when the suite ran to
completion, ran exactly the number of tests the loader discovers in the unmutated
copy, reported genuine failure blocks consistent with its summary, and every
discriminating test in ``must_fail`` is among them. A runner timeout or crash, a
missing or ambiguous test count, an incomplete or resized run, a module import
failure, or a missing anchor is a HARNESS_ERROR, never a detection. Two controls
(a no-op edit and an import-breaking edit) must classify as NOT_CAUGHT and
HARNESS_ERROR before any mutation is judged. Exit status: 0 all caught; 1 some not
caught; 2 any harness error.

M01-M25 re-create the PR-S1 failure-first demonstrations on the PR-S2 code (the
PR-S1 scripts were not committed; descriptions follow docs/baseline/slice-0-eligibility-engine.md
section 6). M26-M44 are the PR-S2 mutations of plan rev. 2.2 section 10; M45-M46 cover
review repair R2 (explanation completeness).

    python -I baseline/tests/tools/mutations.py [--only M32,M38]
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
E, R, I, D = "baseline/rap_baseline/engine.py", "baseline/rap_baseline/rules.py", "baseline/rap_baseline/inputs.py", \
    "baseline/rap_baseline/identity.py"
FC, SC, X, F = "baseline/rap_baseline/findings_check.py", "baseline/rap_baseline/selection_check.py", \
    "baseline/rap_baseline/explanation.py", "baseline/rap_baseline/findings.py"

P6_CALL = """        # P6: first value-dependent step -- existing wrapper, empty read-only results map
        stage = Stage.CONTEXT
        validate_recommendation_inputs(RecommendationContext(
            eligibility=projected, eligibility_results=MappingProxyType({}), capabilities=capabilities))
"""
GATE_CALL = """        # P5: exact-version admission of every decision-relevant source
        stage = Stage.SOURCE_GATE
        require_sources_admissible(refs, recorder, req.principal_id, capabilities)
"""

MUTATIONS = [
    # ---- PR-S1 (re-created on the PR-S2 code) ---------------------------------------
    ("M01", "P6 value-dependent validation moved before the gate", [(E, GATE_CALL + "\n" + P6_CALL, P6_CALL + "\n" + GATE_CALL)], []),
    ("M02", "gate failures ignored", [(E, "        require_sources_admissible(refs, recorder, req.principal_id, capabilities)\n",
                                       "        try:\n            require_sources_admissible(refs, recorder, req.principal_id, capabilities)\n"
                                       "        except ContractViolation:\n            pass\n")], []),
    ("M03", "contested-alternative evidence not gated", [(I, "    refs |= {e.source_ref for e in p.evidence.values()}\n",
                                                          "    alt_only = {e for c in p.claims for e in c.all_evidence_ids()} - {e for c in p.claims for e in c.evidence_ids}\n"
                                                          "    refs |= {e.source_ref for k, e in p.evidence.items() if k not in alt_only}\n")], []),
    ("M04", "inferred-claim evidence not gated", [(I, "    refs |= {e.source_ref for e in p.evidence.values()}\n",
                                                   "    inferred = {e for c in p.claims if c.inferred_by is not None for e in c.evidence_ids}\n"
                                                   "    refs |= {e.source_ref for k, e in p.evidence.items() if k not in inferred}\n")], []),
    ("M05", "P6 on the full context instead of the projection", [(E, "            eligibility=projected, eligibility_results=MappingProxyType({}), capabilities=capabilities))",
                                                                  "            eligibility=context, eligibility_results=MappingProxyType({}), capabilities=capabilities))")], []),
    ("M06", "organization guard over the projection removed", [(E, "        organization_guard(projected, targets, req.organization_id)\n", "")], []),
    ("M07", "P1 candidate/opportunity organization checks removed", [(I, '    _same_org(candidate.organization_id, org, "candidate")\n', ""),
                                                                     (I, '    _same_org(opportunity.organization_id, org, "opportunity")\n', "")], []),
    ("M08", "result id omits the input fingerprint", [(D, '"input_fingerprint": fingerprint,\n', "\n")], []),
    ("M09", "as_of not normalized", [(E, "        as_of = to_utc(req.as_of)\n", "        as_of = to_utc(req.as_of) and req.as_of\n")], []),
    ("M10", "nested captured_at not normalized", [(D, "    if isinstance(value, datetime):\n        return utc_text(value)",
                                                   "    if isinstance(value, datetime):\n        to_utc(value)\n        return value.isoformat()")], []),
    ("M11", "principal included in the fingerprint", [(E, "        fingerprint = input_fingerprint(inputs)\n",
                                                       "        fingerprint = input_fingerprint(inputs)[:-8] + req.principal_id[-8:].rjust(8, '0')\n")], []),
    ("M12", "declaration preferred over verification", [(R, "        if verified:\n            cited, reason = verified,",
                                                         "        if verified and len(verified) == len(lacks_claims):\n            cited, reason = verified,")], []),
    ("M13", "full mixed-basis lacks set cited", [(R, '            cited, reason = verified, "qualification_contradicted_by_verification"',
                                                  '            cited, reason = lacks_claims, "qualification_contradicted_by_verification"')], []),
    ("M14", "not_evidenced preferred over only_inferred", [(R, '        elif Qual.INFERRED_ONLY in states:\n            reason = "qualification_only_inferred"\n        else:\n            reason = "qualification_not_evidenced"',
                                                            '        elif Qual.NONE in states:\n            reason = "qualification_not_evidenced"\n        else:\n            reason = "qualification_only_inferred"')], []),
    ("M15", "inferred treated as declared", [(R, "    declared = [c for c in claims if c.state is ClaimState.DECLARED]\n    if declared:\n        presences",
                                              "    declared = [c for c in claims if c.state in (ClaimState.DECLARED, ClaimState.INFERRED)]\n    if declared:\n        presences")], []),
    ("M16", "not_declared preferred over contested", [(R, "    if any(c.state is ClaimState.CONTESTED for c in claims):              # row 2",
                                                       "    if declared and any(c.state is ClaimState.CONTESTED for c in claims):              # row 2")], []),
    ("M17", "unpublished hours checked after declared/contested", [(R, "    if not hours_reqs:                                                     # row 1\n        return _outcome(rule, RuleResult.UNKNOWN, \"required_hours_not_published\")\n",
                                                                    "    if not hours_reqs and not claims:                                      # row 1\n        return _outcome(rule, RuleResult.UNKNOWN, \"required_hours_not_published\")\n    if not hours_reqs and not declared:\n        return _outcome(rule, RuleResult.UNKNOWN, \"availability_not_declared\", claims=non_declared)\n    if not hours_reqs:\n        return _outcome(rule, RuleResult.UNKNOWN, \"required_hours_not_published\")\n")], []),
    ("M18", "post-check removed", [(E, "        validate_recommendation_inputs(RecommendationContext(\n            eligibility=projected, eligibility_results=MappingProxyType({result.id: result}), capabilities=capabilities))\n", "")], []),
    ("M19", "provenance subset check removed", [(E, "    if not dependencies <= set(refs):", "    if False and not dependencies <= set(refs):")], []),
    ("M20", "deterministic ordering removed", [(D, "    by_id = lambda items: tuple(sorted(items, key=lambda r: r.id))  # noqa: E731", "    by_id = lambda items: tuple(items)  # noqa: E731"),
                                               (R, "        claim_ids=tuple(sorted({c.id for c in claims})),", "        claim_ids=tuple(dict.fromkeys(c.id for c in claims)),")], []),
    ("M21", "gate checks only opportunity and policy", [(I, "    refs |= {r.source_ref for r in p.requirements}\n    refs |= {e.source_ref for e in p.evidence.values()}\n", "")], []),
    ("M22", "rules evaluate conflicting participation instead of failing closed",
     [(R, '    raise RuleEvaluationError("conflicting participation records reached the rules")',
       '    return _outcome(rule, RuleResult.PASS, "participation_confirmed", participations=records)')], []),
    ("M23", "P10 unexpected exceptions not caught (R2)", [(E, "    except Exception as exc:  # unexpected: fail closed inside the three-outcome boundary\n        return Errored(Stage.POST_CHECK, \"unexpected_exception\", type(exc).__name__, calls())\n", "")], []),
    ("M24", "P11 provenance construction exceptions not caught (R2)", [(E, "    except Exception as exc:\n        return Errored(Stage.PROVENANCE, \"unexpected_exception\", type(exc).__name__, calls())\n",
                                                                         "    except ZeroDivisionError as exc:\n        return Errored(Stage.PROVENANCE, \"unexpected_exception\", type(exc).__name__, calls())\n")], []),
    ("M25", "test builders read a contract file (R1)", [("baseline/tests/builders.py", "    def build(self) -> tuple[EligibilityContext, dict]:\n",
                                                         "    def build(self) -> tuple[EligibilityContext, dict]:\n        open(__file__.rsplit('/baseline/', 1)[0] + '/contracts/README.md').close()\n")], []),
    # ---- PR-S2 ----------------------------------------------------------------------------
    ("M26", "drop uncited_material contributions", [(R, "        contributions.append(_participation_contribution(item, c_role, d) if isinstance(item, ProgramParticipation)\n",
                                                     "        if c_role == \"uncited_material\":\n            continue\n        contributions.append(_participation_contribution(item, c_role, d) if isinstance(item, ProgramParticipation)\n")],
     ["test_c02_g12a_uncited_contradiction_is_material"]),
    ("M27", "merge G12c's two claims into one contribution", [(R, "    return SubjectFinding(kind=kind, program_id=program_id, skill_code=skill_code,",
                                                               "    if len(contributions) > 1 and all(c.claim_state == \"declared\" for c in contributions):\n"
                                                               "        contributions = [type(contributions[0])(**{**contributions[0].__dict__, \"evidence\": tuple(a for c in contributions for a in c.evidence)})]\n"
                                                               "    return SubjectFinding(kind=kind, program_id=program_id, skill_code=skill_code,")],
     ["test_c06_g12c_same_code_statement_is_material"]),
    ("M28", "omit the alternative index", [(R, '_attribution(d, e, "alternative_support", i, alt.value)', '_attribution(d, e, "alternative_support", None, alt.value)')],
     ["test_c04_g12b_contested_alternatives_attributed"]),
    ("M29", "inferred relation set to support", [(R, 'attributions = [_attribution(d, e, "inference_input") for e in c.evidence_ids]',
                                                 'attributions = [_attribution(d, e, "support") for e in c.evidence_ids]')],
     ["test_c05_g12b_only_inferred"]),
    ("M30", "L1 reuses rules classification (import)", [(FC, "from . import identity\n", "from . import identity\nfrom .rules import _classify as _producer_classify  # noqa: F401\n")],
     ["test_l1_imports"]),
    ("M31", "L1 reads the supplied context", [(E, "        verify_findings(findings, result, projected, provenance, ENGINE)", "        verify_findings(findings, result, context, provenance, ENGINE)")],
     ["test_assessed_cases_carry_findings_and_explanation"]),
    ("M32", "I10 weakened to the PR-S1 result-dependency subset check", [(FC, "    if _refs(fa.content) != set(gated):",
                                                                           "    if not {a.source_ref for r in fa.content.rules for s in r.subjects for c in s.contributions\n"
                                                                           "            if c.role == \"cited\" for a in c.evidence} <= set(gated):")],
     ["test_n5_uncited_input_source_not_gated"]),
    ("M33", "findings emitted on Refused", [("baseline/rap_baseline/request.py", '    visibility: str = "internal_only"\n', '    visibility: str = "internal_only"\n    findings: object = None\n')],
     ["test_refused_cases_carry_no_findings_or_explanation"]),
    ("M34", "engine identity or fingerprint changed", [(D, 'INPUT_FINGERPRINT_VERSION = "rap-baseline.input/1"', 'INPUT_FINGERPRINT_VERSION = "rap-baseline.input/2"')],
     ["test_id6_result_ids_pinned_to_the_pr_s1_base"]),
    ("M35", "as_of included in content_digest", [(F, "    digest = content_digest(content, findings_policy)\n",
                                                  "    digest = canonical_sha256({\"c\": content_digest(content, findings_policy), \"t\": result.evaluated_at})\n")],
     ["test_id2_as_of_changes_ids_and_rendered_time_only"]),
    ("M36", "information_gap mapping swapped (contested <-> unpublished)", [(R, '    "contested": "conflicting_sources",\n    "hours_not_published": "opportunity_requirement_unpublished",',
                                                                             '    "contested": "opportunity_requirement_unpublished",\n    "hours_not_published": "conflicting_sources",')],
     ["test_c04_g12b_contested_alternatives_attributed"]),
    ("M37", "template interpolates field_path", [(X, "    return template.format(**fields)",
                                                  "    if \"field_path\" in p:\n        template = template.replace(\"{field_path}\", p[\"field_path\"])\n    return template.format(**fields)")],
     ["test_source_strings_are_data_not_templates"]),
    ("M38", "L2 removed", [(E, "        verify_selection(context, targets, projected)\n", "")],
     ["test_n8a_omitted_selected_claim", "test_n8e_added_unselected_claim", "test_n8f_omitted_participation", "test_n8g_omitted_application"]),
    ("M39", "I7 relaxed to supportability", [(FC, "        expected_rules.append((rule, subjects, _expected_outcome(rule.kind, subjects, d), o))",
                                              "        expected_rules.append((rule, subjects, (o.result, o.reason_code, tuple(o.claim_ids), tuple(o.participation_ids), tuple(o.requirement_ids)), o))")],
     ["test_n1_mixed_basis_relabelled_by_declaration", "test_n2_all_verified_relabelled_declared", "test_n3_pass_citing_a_subset_of_declared_claims"]),
    ("M40", "build_findings routed through EVALUATORS", [(R, "        cited = set(o.claim_ids) | set(o.participation_ids)\n        rule_findings.append(",
                                                          "        cited = set(o.claim_ids) | set(o.participation_ids)\n        EVALUATORS[rule.kind](rule, d)\n        rule_findings.append(")],
     ["test_all_checks_precede_phase2_and_every_value_read"]),
    ("M41", "as_of rendered into rendered_body instead of the slot", [(X, '    body = "\\n".join(lines)\n', '    body = "\\n".join(lines).replace(SLOT, utc_text(fa.as_of))\n')],
     ["test_id2_as_of_changes_ids_and_rendered_time_only"]),
    ("M42", "L1 takes header values from provenance without recomputation", [(FC, "    if_star = identity.input_fingerprint(d)\n    od_star = identity.output_digest(result)\n",
                                                                               "    if_star = prov.input_fingerprint\n    od_star = prov.output_digest\n")],
     ["test_n10_wrong_provenance_values"]),
    ("M43", "L2 compares ids only, without object identity", [(SC, "    return len(expected) == len(actual) and all(a is b for a, b in zip(expected, actual))",
                                                               "    return len(expected) == len(actual) and all(getattr(a, 'id', a) == getattr(b, 'id', b) for a, b in zip(expected, actual))")],
     ["test_n8h_substituted_record_under_the_same_id"]),
    ("M44", "L2 omits application-target references", [(SC, "    opp_ids = {opportunity.id} | {m.target_opportunity_id for m in apps if m.target_opportunity_id}\n",
                                                         "    opp_ids = {opportunity.id}\n"),
                                                        (SC, "                   | {m.target_program_id for m in apps} | {m.program_id for m in opps}) - {None}",
                                                         "                   | {m.program_id for m in opps}) - {None}")],
     ["test_sweep_never_selection_errors"]),
    # ---- review repair R2: explanation completeness ------------------------------------------
    ("M45", "explanation drops uncited_material statements and its completeness self-check",
     [(X, '                cref = f"{sref}/input:{con.input_id}"\n                out.append((2, Statement(',
       '                if con.role == "uncited_material":\n                    continue\n'
       '                cref = f"{sref}/input:{con.input_id}"\n                out.append((2, Statement('),
      (X, "    _completeness(ea, fa)\n", "")],
     ["test_one_to_one_coverage_of_verified_findings", "test_c06_g12c_is_fully_represented"]),
    ("M46", "P14 explanation completeness self-check removed", [(X, "    _completeness(ea, fa)\n", "")],
     ["test_omitted_uncited_material_is_errored", "test_omitted_gap_is_errored", "test_omitted_attribution_is_errored"]),
]

FAIL_LINE = re.compile(r"^(FAIL|ERROR): (\w+) \(([\w.]+)\)")
RAN_LINE = re.compile(r"^Ran (\d+) tests? in [\d.]+s$", re.M)
SUMMARY_LINE = re.compile(r"^(OK|FAILED)(?: \(([^)]*)\))?$", re.M)

#: Outcome classes. A mutation is CAUGHT only when the suite ran to completion at the
#: expected size and reported genuine test failures; anything else is a HARNESS_ERROR,
#: never evidence of detection.
CAUGHT, NOT_CAUGHT, HARNESS_ERROR = "CAUGHT", "NOT_CAUGHT", "HARNESS_ERROR"


def classify(returncode: int | None, stderr: str, expected: int) -> dict:
    """Classify one unittest run (pure function; unit-tested in ``test_mutation_harness.py``).

    Returns ``{"status", "ran", "failures", "errors", "methods", "reason"}`` where ``status`` is
    ``"completed_ok"``, ``"completed_failed"`` or ``"harness_error"``. A run is a harness error when
    the process did not finish (no return code), did not print exactly one ``Ran N tests`` line and
    one final summary, ran a different number of tests than ``expected``, reported failures that do
    not match the per-test failure blocks, or failed to import a test module (``_FailedTest``).
    """
    out = {"status": "harness_error", "ran": None, "failures": 0, "errors": 0, "methods": set(), "reason": ""}
    if returncode is None:
        out["reason"] = "runner did not finish (timeout or crash)"
        return out
    ran = RAN_LINE.findall(stderr)
    summaries = SUMMARY_LINE.findall(stderr)
    if len(ran) != 1 or len(summaries) != 1:
        out["reason"] = "missing or ambiguous 'Ran N tests' line or final summary"
        return out
    out["ran"] = int(ran[0])
    verdict, detail = summaries[0]
    counts = dict(re.findall(r"(failures|errors|skipped|expected failures|unexpected successes)=(\d+)", detail or ""))
    hits = [m for m in (FAIL_LINE.match(line) for line in stderr.splitlines()) if m]
    out["failures"] = sum(1 for m in hits if m.group(1) == "FAIL")
    out["errors"] = sum(1 for m in hits if m.group(1) == "ERROR")
    out["methods"] = {m.group(2) for m in hits}
    if out["ran"] != expected:
        out["reason"] = f"ran {out['ran']} tests, expected {expected} (incomplete or altered suite)"
        return out
    if any("_FailedTest" in m.group(3) or "loader" in m.group(3) for m in hits):
        out["reason"] = "a test module failed to import (the mutation broke the code, not an invariant)"
        return out
    if (int(counts.get("failures", 0)), int(counts.get("errors", 0))) != (out["failures"], out["errors"]):
        out["reason"] = "summary counts do not match the reported failure blocks"
        return out
    if verdict == "OK":
        if returncode != 0 or hits:
            out["reason"] = "OK summary with a non-zero exit or failure blocks"
            return out
        out["status"] = "completed_ok"
        return out
    if returncode != 1 or not hits:
        out["reason"] = "FAILED summary without failure blocks or with an unexpected exit code"
        return out
    out["status"] = "completed_failed"
    return out


def run_suite(root: Path, expected: int) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHASHSEED")}
    env["PYTHONPATH"] = str(root / "contracts")
    try:
        proc = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests"], cwd=root / "baseline",
                              capture_output=True, text=True, env=env, timeout=600)
    except subprocess.TimeoutExpired:
        return classify(None, "", expected)
    result = classify(proc.returncode, proc.stderr, expected)
    result["tail"] = proc.stderr[-600:]
    return result


def discovered_count(root: Path) -> int:
    """Number of tests the loader finds in the unmutated copy (independent of running them)."""
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH",)}
    env["PYTHONPATH"] = str(root / "contracts")
    code = ("import unittest\n"
            "def n(s):\n"
            "    return sum(n(t) if isinstance(t, unittest.TestSuite) else 1 for t in s)\n"
            "print(n(unittest.defaultTestLoader.discover('tests')))\n")
    proc = subprocess.run([sys.executable, "-c", code], cwd=root / "baseline", capture_output=True, text=True,
                          env=env, timeout=300, check=True)
    return int(proc.stdout.strip())


def apply(root: Path, edits) -> dict | None:
    """Apply single-occurrence replacements; return the originals, or None if an anchor is not found once."""
    originals: dict[str, str] = {}
    for path, old, new in edits:
        target = root / path
        originals.setdefault(path, target.read_text(encoding="utf-8"))
        text = target.read_text(encoding="utf-8")
        if text.count(old) != 1:
            restore(root, originals)
            return None
        target.write_text(text.replace(old, new), encoding="utf-8")
    return originals


def restore(root: Path, originals: dict) -> None:
    for path, text in originals.items():
        (root / path).write_text(text, encoding="utf-8")


def judge(result: dict, must_fail: list[str]) -> tuple[str, str]:
    if result["status"] == "harness_error":
        return HARNESS_ERROR, result["reason"]
    if result["status"] == "completed_ok":
        return NOT_CAUGHT, "suite passed"
    absent = [t for t in must_fail if t not in result["methods"]]
    if absent:
        return NOT_CAUGHT, "discriminating test(s) did not fail: " + ",".join(absent)
    return CAUGHT, ""


#: Harness controls, run before the mutations: the harness must classify a no-op edit as
#: NOT_CAUGHT and an edit that breaks module import as HARNESS_ERROR (never CAUGHT).
CONTROLS = [
    ("CTRL-noop", "no-op edit (comment only)", [(E, "    # P0\n", "    # P0 (control: no-op)\n")], NOT_CAUGHT),
    ("CTRL-import", "edit that breaks module import", [(E, "    # P0\n", "    # P0\n    )\n")], HARNESS_ERROR),
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", default="")
    args = parser.parse_args()
    only = set(filter(None, args.only.split(",")))
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "repo"
        shutil.copytree(REPO, root, ignore=shutil.ignore_patterns(".git", "__pycache__", ".venv*"))
        expected = discovered_count(root)
        base = run_suite(root, expected)
        print(f"baseline: discovered={expected} ran={base['ran']} status={base['status']} {base['reason']}")
        if base["status"] != "completed_ok":
            print(base.get("tail", ""))
            return 2
        harness_errors = not_caught = 0
        for cid, desc, edits, want in CONTROLS:
            originals = apply(root, edits)
            if originals is None:
                print(f"{cid} | {desc} | HARNESS_ERROR anchor not found exactly once")
                return 2
            result = run_suite(root, expected)
            restore(root, originals)
            status, why = judge(result, [])
            ok = status == want
            print(f"{cid} | {desc} | classified={status} expected={want} | {'OK' if ok else 'CONTROL FAILED'} {why}")
            if not ok:
                return 2
        for mid, desc, edits, must_fail in MUTATIONS:
            if only and mid not in only:
                continue
            originals = apply(root, edits)
            if originals is None:
                harness_errors += 1
                print(f"{mid} | {desc} | HARNESS_ERROR anchor not found exactly once")
                continue
            result = run_suite(root, expected)
            restore(root, originals)
            status, why = judge(result, must_fail)
            harness_errors += status == HARNESS_ERROR
            not_caught += status == NOT_CAUGHT
            print(f"{mid} | {desc} | failures={result['failures']} errors={result['errors']} "
                  f"methods={len(result['methods'])} ran={result['ran']}/{expected} | {status}{(' ' + why) if why else ''}")
        print(f"summary: harness_errors={harness_errors} not_caught={not_caught}")
        return 2 if harness_errors else (1 if not_caught else 0)


if __name__ == "__main__":
    raise SystemExit(main())
