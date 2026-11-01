"""B8: execution, configuration, specification and output identities; ``verify-repeat`` verdicts; determinism
across repeated runs, hash seeds and record order."""

from __future__ import annotations

import dataclasses
import io
import json
import os
import random
import subprocess
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from helpers import LazyClassFixture, TempDirTest, config
from rap_baseline import Assessed, assess
from rap_contracts.evaluation import configuration_fingerprint, EvaluationRun

from rap_evaluation import BindingFailure, __main__ as cli, admission, identity
from rap_evaluation.artifacts import IDENTITY_FILE, OBSERVATIONS_FILE, SIDECAR_FILE
from rap_evaluation.identity import DETERMINISM_FAILURE, NOT_COMPARABLE, NOT_INDEPENDENT, PASS, verify_repeat
from rap_evaluation.run import run_evaluation

EVALUATION = Path(__file__).resolve().parents[1]
REPO = EVALUATION.parent


def seeded_text(request, context, authority, capabilities):
    """A synthetic non-determinism: the explanation text differs (not cross-checked by X1-X9)."""
    out = assess(request, context, authority, capabilities)
    if isinstance(out, Assessed):
        out = dataclasses.replace(out, explanation=dataclasses.replace(out.explanation, rendered_text="seeded difference"))
    return out


class VerifyRepeatTests(LazyClassFixture):
    @classmethod
    def _fixture(cls):
        import shutil
        import tempfile
        cls.dir = Path(tempfile.mkdtemp(prefix="rap-eval-id-"))
        cls.addClassCleanup(shutil.rmtree, cls.dir, True)
        cls.r1 = run_evaluation(config(cls.dir / "r1"))
        cls.r2 = run_evaluation(config(cls.dir / "r2"))

    def ident(self, d):
        return json.loads((d / IDENTITY_FILE).read_text())

    def test_two_runs_pass(self):
        report = verify_repeat(self.r1, self.r2)
        self.assertEqual(report["verdict"], PASS)
        self.assertNotEqual(report["a"]["execution_id"], report["b"]["execution_id"])
        self.assertEqual(report["a"]["output_digest"], report["b"]["output_digest"])

    def test_same_directory_twice_is_not_independent(self):
        self.assertEqual(verify_repeat(self.r1, self.r1)["verdict"], NOT_INDEPENDENT)

    def test_different_as_of_is_not_comparable_but_decisions_are_identical(self):
        r3 = run_evaluation(config(self.tmp / "r3", as_of=datetime(2026, 11, 2, tzinfo=timezone.utc)))
        self.assertEqual(verify_repeat(self.r1, r3)["verdict"], NOT_COMPARABLE)

        def view(d):
            obs = json.loads((d / OBSERVATIONS_FILE).read_text())
            return [(o["case_id"], o["outcome"], [(s["step_id"], s["status"], (s.get("observed") or {}).get("decision"),
                                                   json.dumps((s.get("observed") or {}).get("rule_outcomes")))
                                                  for s in o["steps"]]) for o in obs]
        self.assertEqual(view(self.r1), view(r3))
        self.assertNotEqual(self.ident(self.r1)["output_digest"], self.ident(r3)["output_digest"])

    def test_seeded_output_difference_is_a_determinism_failure(self):
        seeded = run_evaluation(config(self.tmp / "seeded"), assess_fn=seeded_text)
        self.assertEqual(verify_repeat(self.r1, seeded)["verdict"], DETERMINISM_FAILURE)

    def test_execution_ids_are_random_and_well_formed(self):
        ids = {identity.new_execution_id() for _ in range(50)}
        self.assertEqual(len(ids), 50)
        self.assertTrue(all(len(i) == len("evalrun_") + 32 for i in ids))

    def test_configuration_and_specification_identities_are_deterministic(self):
        a, b = self.ident(self.r1), self.ident(self.r2)
        self.assertEqual(a["configuration_fingerprint"], b["configuration_fingerprint"])
        self.assertEqual((a["specification"], a["specification_digest"]), (b["specification"], b["specification_digest"]))
        run = EvaluationRun.model_validate(json.loads((self.r1 / "run.json").read_text()))
        self.assertEqual(configuration_fingerprint(run), a["configuration_fingerprint"])

    def test_output_digest_excludes_run_id_and_wall_clock_only(self):
        a = json.loads((self.r1 / SIDECAR_FILE).read_text())
        b = json.loads((self.r2 / SIDECAR_FILE).read_text())
        strip = lambda s: [{k: v for k, v in e.items() if k != "wall_clock"} for e in s["entries"]]  # noqa: E731
        self.assertEqual(strip(a), strip(b))

    def test_tampered_directory_fails_verification(self):
        import shutil
        bad = self.tmp / "bad"
        shutil.copytree(self.r2, bad)
        side = json.loads((bad / SIDECAR_FILE).read_text())
        side["entries"][0]["input_fingerprint"] = "sha256:" + "4" * 64
        (bad / SIDECAR_FILE).write_text(json.dumps(side))
        with self.assertRaises(BindingFailure):
            verify_repeat(self.r1, bad)

    def test_cli_verify_repeat_exit_codes(self):
        def run(a, b):
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                code = cli.main(["verify-repeat", str(a), str(b)])
            return code, out.getvalue()
        code, text = run(self.r1, self.r2)
        self.assertEqual((code, json.loads(text)["verdict"]), (0, PASS))
        code, text = run(self.r1, self.r1)
        self.assertEqual((code, json.loads(text)["verdict"]), (1, NOT_INDEPENDENT))


class OrderAndHashSeedTests(TempDirTest):
    def test_shuffled_raw_record_order_gives_an_equal_output_digest(self):
        base = run_evaluation(config(self.tmp / "base"))
        real = admission.raw_pool

        def shuffled(layers):
            pool = real(layers)
            rng = random.Random(20261101)
            out = {}
            for kind, value in pool.items():
                if isinstance(value, list):
                    value = list(value)
                    rng.shuffle(value)
                out[kind] = value
            return out
        with mock.patch.object(admission, "raw_pool", side_effect=shuffled):
            shuf = run_evaluation(config(self.tmp / "shuffled"))
        self.assertEqual(verify_repeat(base, shuf)["verdict"], PASS)

    def test_hash_seeds_0_1_2_give_equal_output_digests(self):
        code = ("import sys; from pathlib import Path; from datetime import datetime, timezone;"
                "from rap_contracts.evaluation import CodeRevision;"
                "from rap_evaluation.admission import RunConfig; from rap_evaluation.run import run_evaluation;"
                "run_evaluation(RunConfig(as_of=datetime(2026,11,1,tzinfo=timezone.utc), out=Path(sys.argv[1]),"
                " code_revision=CodeRevision(status='recorded', commit='a'*40, dirty=False)))")
        dirs = []
        for seed in ("0", "1", "2"):
            env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHASHSEED")}
            env.update(PYTHONHASHSEED=seed, PYTHONPATH=os.pathsep.join([str(EVALUATION), str(REPO / "contracts"),
                                                                        str(REPO / "baseline")]))
            target = self.tmp / f"seed{seed}"
            subprocess.run([sys.executable, "-c", code, str(target)], env=env, cwd=self.tmp, check=True, timeout=300,
                           capture_output=True)
            dirs.append(target)
        digests = {json.loads((d / IDENTITY_FILE).read_text())["output_digest"] for d in dirs}
        self.assertEqual(len(digests), 1)
        self.assertEqual(verify_repeat(dirs[0], dirs[1])["verdict"], PASS)
        self.assertEqual(verify_repeat(dirs[0], dirs[2])["verdict"], PASS)


if __name__ == "__main__":
    unittest.main()
