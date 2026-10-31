"""Deterministic replay: repeated, permuted and cross-process (different PYTHONHASHSEED) executions agree."""

import json
import os
import random
import subprocess
import sys
import unittest
from pathlib import Path

from builders import ANA, BEN, CY, DATA, OPS, PILOT, WEB, BETA_JOB, BETA_POLICY, World, run
from rap_baseline import Assessed

BASELINE = Path(__file__).resolve().parents[1]
CONTRACTS = BASELINE.parent / "contracts"
SCENARIOS = [(ANA, DATA, PILOT), (ANA, WEB, PILOT), (ANA, OPS, PILOT), (BEN, DATA, PILOT), (CY, BETA_JOB, BETA_POLICY)]

SCRIPT = """
import json, sys
from builders import World, run, ANA, BEN, CY, DATA, OPS, WEB, PILOT, BETA_JOB, BETA_POLICY
out = []
for cand, opp, pin in [(ANA, DATA, PILOT), (ANA, WEB, PILOT), (ANA, OPS, PILOT), (BEN, DATA, PILOT), (CY, BETA_JOB, BETA_POLICY)]:
    o, _ = run(World(), cand, opp, pin)
    out.append({"result": o.result.model_dump(mode="json"), "provenance": o.provenance.canonical()})
sys.stdout.write(json.dumps(out, sort_keys=True))
"""


def snapshot_all():
    out = []
    for cand, opp, pin in SCENARIOS:
        o, _ = run(World(), cand, opp, pin)
        assert isinstance(o, Assessed), o
        out.append({"result": o.result.model_dump(mode="json"), "provenance": o.provenance.canonical()})
    return json.dumps(out, sort_keys=True)


class DeterminismTests(unittest.TestCase):
    def test_repeated_in_process_execution_is_identical(self):
        self.assertEqual(snapshot_all(), snapshot_all())

    def test_shuffled_record_order_is_identical(self):
        reference = {}
        for seed in range(6):
            rng = random.Random(seed)
            for cand, opp, pin in SCENARIOS:
                w = World()
                for name in ("candidates", "programs", "opportunities", "profiles", "applications", "policies",
                             "vocabularies", "requirements", "evidence", "claims", "participations"):
                    rng.shuffle(getattr(w, name))
                # rule order inside a policy is policy content and is deliberately not shuffled
                o, _ = run(w, cand, opp, pin)
                key = (cand, opp)
                dumped = o.result.model_dump_json()
                with self.subTest(seed=seed, key=key):
                    self.assertEqual(reference.setdefault(key, dumped), dumped)

    def test_cross_process_with_different_hash_seeds(self):
        outputs = []
        for seed in ("0", "12345"):
            env = {**os.environ, "PYTHONHASHSEED": seed,
                   "PYTHONPATH": os.pathsep.join([str(CONTRACTS), str(BASELINE), str(BASELINE / "tests")])}
            proc = subprocess.run([sys.executable, "-c", SCRIPT], capture_output=True, text=True, env=env, check=True,
                                  cwd=str(BASELINE))
            outputs.append(proc.stdout)
        self.assertTrue(outputs[0])
        self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(json.loads(outputs[0]), json.loads(snapshot_all()))


if __name__ == "__main__":
    unittest.main()
