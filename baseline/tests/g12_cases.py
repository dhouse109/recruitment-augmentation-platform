"""TEST-ONLY synthetic case matrix for PR-S2 (plan rev. 2.2 section 6.1): C01-C19.

Every case is built on the test-local ``World`` in ``builders.py`` (``*_s1_*`` records).
No contract fixture, golden or nominal held-out record is used. Each case function
returns ``(world, candidate_id, run_kwargs)`` for ``builders.run(world, cand, DATA, **kw)``.

This module is also imported by ``tools/dump_scenarios.py`` to compare result and
provenance bytes between the PR-S1 base commit and PR-S2. It therefore uses only
``builders`` APIs that exist unchanged at the PR-S1 base.
"""

from __future__ import annotations

from builders import ANA, BEN, CY, DATA, HAS, LACKS, StubAuthority, World
from rap_contracts.models import VersionStatus

R_PY, R_SH = "requirement_s1_data_python", "requirement_s1_data_spreadsheets"
R_HOURS = "requirement_s1_data_hours"


def two_codes() -> World:
    w = World()
    w.add_skill_requirement(DATA, "spreadsheets")
    return w


def drop(w: World, code: str, cand: str = ANA) -> None:
    for c in [c for c in w.claims if c["candidate_id"] == cand and c.get("subject_code") == code]:
        w.remove_claim(c["id"])


def py_lacks_stmt(w: World) -> None:
    w.add_statement(ANA, "evidence_s1_ana_python_screen", "answers.python_screening", source="application")
    w.add_claim("claim_s1_ana_python_lacks", ANA, "python", "declared", LACKS, ["evidence_s1_ana_python_screen"])


def sh_lacks_ver(w: World) -> None:
    w.add_verification(ANA, "evidence_s1_ana_sheets_check", "9203", "assessments.spreadsheets")
    w.add_claim("claim_s1_ana_sheets_lacks", ANA, "spreadsheets", "declared", LACKS, ["evidence_s1_ana_sheets_check"])


def sh_lacks_stmt(w: World, cand: str = ANA, cid: str = "claim_s1_ana_sheets_lacks_stmt",
                  eid: str = "evidence_s1_ana_sheets_stmt") -> None:
    w.add_statement(cand, eid, "skills.spreadsheets")
    w.add_claim(cid, cand, "spreadsheets", "declared", LACKS, [eid])


def py_inferred(w: World) -> None:
    w.add_statement(ANA, "evidence_s1_ana_project", "answers.project", source="application")
    w.add_claim("claim_s1_ana_python_inferred", ANA, "python", "inferred", HAS, ["evidence_s1_ana_project"])


def c01():
    return World(), ANA, {}


def c02():  # G12a
    w = two_codes(); drop(w, "python"); py_lacks_stmt(w); sh_lacks_ver(w)
    return w, ANA, {}


def c03():  # G12b, not evidenced (A')
    w = two_codes(); drop(w, "python"); sh_lacks_ver(w)
    return w, ANA, {}


def c04():  # G12b, contested
    w = two_codes(); sh_lacks_stmt(w, BEN, "claim_s1_ben_sheets", "evidence_s1_ben_sheets")
    return w, BEN, {}


def c05():  # G12b, only inferred
    w = two_codes(); drop(w, "python"); py_inferred(w); sh_lacks_stmt(w)
    return w, ANA, {}


def c06():  # G12c, same code, two claims
    w = World(); drop(w, "python")
    w.add_verification(ANA, "evidence_s1_ana_py_check", "9204", "assessments.python")
    w.add_claim("claim_s1_ana_python_lacks_v", ANA, "python", "declared", LACKS, ["evidence_s1_ana_py_check"])
    py_lacks_stmt(w)
    return w, ANA, {}


def c07():  # one claim, two evidence bases
    w = World(); drop(w, "python")
    w.add_verification(ANA, "evidence_s1_ana_py_check", "9204", "assessments.python")
    w.add_statement(ANA, "evidence_s1_ana_python_screen", "answers.python_screening", source="application")
    w.add_claim("claim_s1_ana_python_lacks", ANA, "python", "declared", LACKS,
                ["evidence_s1_ana_py_check", "evidence_s1_ana_python_screen"])
    return w, ANA, {}


def c08():  # lacks (statement) + inferred has on the same code
    w = World(); drop(w, "python"); py_lacks_stmt(w); py_inferred(w)
    return w, ANA, {}


def c09():  # G12a + G12c
    w = two_codes(); drop(w, "python"); py_lacks_stmt(w); sh_lacks_ver(w); sh_lacks_stmt(w)
    return w, ANA, {}


def c10():  # both codes lack by verification (negative control: no omission)
    w = two_codes(); drop(w, "python"); sh_lacks_ver(w)
    w.add_verification(ANA, "evidence_s1_ana_py_check", "9204", "assessments.python")
    w.add_claim("claim_s1_ana_python_lacks_v", ANA, "python", "declared", LACKS, ["evidence_s1_ana_py_check"])
    return w, ANA, {}


def c11():  # default Ben: contested python, unknown availability
    return World(), BEN, {}


def c12():  # inferred only
    w = World(); drop(w, "python"); py_inferred(w)
    return w, ANA, {}


def c13():  # pass, python verified, spreadsheets self-declared
    w = two_codes()
    w.add_verification(ANA, "evidence_s1_ana_python_verified", "9201", "assessments.python")
    w.add_claim("claim_s1_ana_python_verified", ANA, "python", "declared", HAS, ["evidence_s1_ana_python_verified"])
    w.add_statement(ANA, "evidence_s1_ana_sheets", "skills.spreadsheets")
    w.add_claim("claim_s1_ana_sheets", ANA, "spreadsheets", "declared", HAS, ["evidence_s1_ana_sheets"])
    return w, ANA, {}


def c14():  # hours not published
    w = World(); w.remove_requirement(R_HOURS)
    return w, ANA, {}


def c15():  # declared has vs lacks on one code -> refused
    w = World(); py_lacks_stmt(w)
    return w, ANA, {}


def c16():  # C02 with the uncited python statement's source superseded -> refused at the gate
    w, cand, _ = c02()
    a = StubAuthority()
    a.set(w.evidence_record("evidence_s1_ana_python_screen")["source_ref"], VersionStatus.SUPERSEDED)
    return w, cand, {"authority": a}


def c17():  # contested + declared on one code -> refused
    w = World()
    w.add_statement(BEN, "evidence_s1_ben_python_extra", "skills.python_extra")
    w.add_claim("claim_s1_ben_python_decl", BEN, "python", "declared", HAS, ["evidence_s1_ben_python_extra"])
    return w, BEN, {}


def c18():  # participation not recorded
    w = World(); w.participations = [p for p in w.participations if p["candidate_id"] != ANA]
    return w, ANA, {}


def c19():  # candidate in another organization -> refused before any authority call
    return World(), CY, {}


CASES = {"C01": c01, "C02": c02, "C03": c03, "C04": c04, "C05": c05, "C06": c06, "C07": c07, "C08": c08,
         "C09": c09, "C10": c10, "C11": c11, "C12": c12, "C13": c13, "C14": c14, "C15": c15, "C16": c16,
         "C17": c17, "C18": c18, "C19": c19}
ASSESSED = ("C01", "C02", "C03", "C04", "C05", "C06", "C07", "C08", "C09", "C10", "C11", "C12", "C13", "C14", "C18")
REFUSED = {"C15": ("context", "unresolved_conflict"), "C16": ("source_gate", "source_not_current"),
           "C17": ("context", "contested_not_exclusive"), "C19": ("reference", "cross_org_reference")}
