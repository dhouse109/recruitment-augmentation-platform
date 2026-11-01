"""TEST-ONLY failure-first mutation harness for PR-S2 acceptance A3 and A16.

Each mutation disables one invariant by an exact, single-occurrence text replacement
in a scratch copy of the repository, runs the baseline suite there, and reports
failures (including failing subtests) and failing test methods. A mutation is
"caught" when the suite fails; ``must_fail`` names the discriminating test(s) that
must be among the failures. The working tree is never modified.

M01-M25 re-create the PR-S1 failure-first demonstrations on the PR-S2 code (the
PR-S1 scripts were not committed; descriptions follow docs/baseline/slice-0-eligibility-engine.md
section 6). M26-M44 are the PR-S2 mutations of plan rev. 2.2 section 10.

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
]

FAIL_LINE = re.compile(r"^(FAIL|ERROR): (\w+) \(([\w.]+)\)")


def run_suite(root: Path) -> tuple[int, int, set[str], str]:
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHASHSEED")}
    env["PYTHONPATH"] = str(root / "contracts")
    proc = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests"], cwd=root / "baseline",
                          capture_output=True, text=True, env=env, timeout=600)
    text = proc.stderr
    hits = [m for m in (FAIL_LINE.match(line) for line in text.splitlines()) if m]
    ran = re.search(r"^Ran (\d+) tests?", text, re.M)
    methods = {m.group(2) for m in hits}
    return len(hits), int(ran.group(1)) if ran else -1, methods, text[-400:]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", default="")
    args = parser.parse_args()
    only = set(filter(None, args.only.split(",")))
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "repo"
        shutil.copytree(REPO, root, ignore=shutil.ignore_patterns(".git", "__pycache__", ".venv*"))
        base_failures, base_ran, _, tail = run_suite(root)
        print(f"baseline: ran={base_ran} failures={base_failures}")
        if base_failures:
            print(tail)
            return 2
        missing = 0
        for mid, desc, edits, must_fail in MUTATIONS:
            if only and mid not in only:
                continue
            originals = {}
            for path, old, new in edits:
                target = root / path
                text = originals.setdefault(path, target.read_text(encoding="utf-8")) if path not in originals else target.read_text(encoding="utf-8")
                if text.count(old) != 1:
                    print(f"{mid}: anchor not found exactly once in {path}")
                    return 3
                target.write_text(text.replace(old, new), encoding="utf-8")
            failures, ran, methods, tail = run_suite(root)
            for path, text in originals.items():
                (root / path).write_text(text, encoding="utf-8")
            absent = [t for t in must_fail if t not in methods]
            caught = (failures > 0 or ran < 0) and not absent
            missing += 0 if caught else 1
            print(f"{mid} | {desc} | failures={failures} methods={len(methods)} ran={ran} | "
                  f"{'CAUGHT' if caught else 'NOT CAUGHT'}{' missing discriminators: ' + ','.join(absent) if absent else ''}")
        return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
