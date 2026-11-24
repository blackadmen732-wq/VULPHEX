# VULPHEX arena: the practice range and the training loop — deterministic, offline. The squad should learn (team
# reward trends up as the brains evolve toward playbooks that catch the planted vulns).
import os, sqlite3, sys, tempfile, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "arena")); sys.path.insert(0, str(ROOT / "security"))
import range as RG
import train as TR
import core as C


def temp_core():
    return C.Core(db_path=tempfile.mktemp(suffix=".db"), scope={"hosts": []})


class RangeTest(unittest.TestCase):
    def test_range_builds_files_and_an_answer_key(self):
        d = tempfile.mkdtemp(); plants = RG.build(d)
        self.assertTrue(os.path.exists(os.path.join(d, "config.py")))
        self.assertTrue(os.path.exists(os.path.join(d, "range.json")))
        self.assertEqual(RG.answer_key(d), plants); self.assertGreaterEqual(len(plants), 10)


class AttemptTest(unittest.TestCase):
    def test_depth_gates_hard_vulns_and_keep_bar_skips_low_severity(self):
        import random
        shallow = {"depth": "shallow", "keep": "info", "persist": False, "retry": True}
        deep = {"depth": "deep", "keep": "info", "persist": True, "retry": True}
        hard = {"capability": "x", "severity": "critical", "difficulty": "deep", "note": ""}
        self.assertFalse(TR.attempt(shallow, hard, random.Random(1))[0])     # too shallow for a deep vuln
        self.assertTrue(TR.attempt(deep, hard, random.Random(1))[0])         # deep playbook catches it
        picky = {"depth": "deep", "keep": "high", "persist": True, "retry": True}
        low = {"capability": "x", "severity": "low", "difficulty": "shallow", "note": ""}
        self.assertFalse(TR.attempt(picky, low, random.Random(1))[0])        # below the keep-bar


class TrainTest(unittest.TestCase):
    def test_a_squad_trains_and_improves(self):
        core = temp_core()
        squad = ["FOX SCOUT", "FOX AUDITOR", "FOX INSPECTOR", "FOX BASTION", "FOX BREACH", "FOX WRAITH"]  # 6 together
        d = tempfile.mkdtemp()
        hist = TR.train(core, squad, rounds=30, range_dir=d, seed=3)
        self.assertEqual(len(hist), 30)
        first = sum(h["team_reward"] for h in hist[:5]) / 5
        last = sum(h["team_reward"] for h in hist[-5:]) / 5
        self.assertGreater(last, first, f"team should improve: {first:.1f} -> {last:.1f}")
        self.assertGreaterEqual(core.db.execute("SELECT COUNT(*) FROM brain_pop").fetchone()[0], 6)


if __name__ == "__main__":
    unittest.main()
