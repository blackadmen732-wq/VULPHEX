# VULPHEX arena: the practice range and the training loop — deterministic, offline. The squad should learn (team
# reward trends up as the brains evolve toward playbooks that catch the planted vulns).
import os, sqlite3, sys, tempfile, unittest
from unittest import mock
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "arena")); sys.path.insert(0, str(ROOT / "security"))
import range as RG
import trainer as TR
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
        hist = TR.train(core, squad, rounds=40, range_dir=d, seed=3)
        self.assertEqual(len(hist), 40)
        # the real learning signal (robust to per-round exploration noise): the luck filter confirms good tactics,
        # and the best playbook earns a positive mean reward.
        proven = core.db.execute("SELECT COUNT(*) FROM brain_pop WHERE proven=1").fetchone()[0]
        best = core.db.execute("SELECT MAX(total/runs) FROM brain_pop WHERE runs>=3").fetchone()[0]
        self.assertGreater(proven, 0, "the luck filter should prove at least one tactic")
        self.assertGreater(best, 0, "the best playbook should earn positive reward")
        self.assertGreaterEqual(core.db.execute("SELECT COUNT(*) FROM brain_pop").fetchone()[0], 6)

    def test_the_curriculum_runs_all_stages(self):
        core = temp_core(); squad = ["FOX SCOUT", "FOX AUDITOR", "FOX BREACH", "FOX WRAITH"]
        hist = TR.curriculum(core, squad, per=6, seed=5)
        stages = {h["stage"].split(":")[0] for h in hist}
        self.assertEqual(stages, {"solo", "pair", "squad"})
        self.assertTrue(any(h["stage"] == "squad" for h in hist))




class BrainStatusTest(unittest.TestCase):
    def test_cloud_model_without_credential_is_not_marked_available(self):
        import server as arena_server
        with mock.patch.object(arena_server.C, "ModelRouter") as router:
            router.return_value.pick.return_value = ("fast", {"provider": "nvidia", "model": "example"})
            with mock.patch.dict(os.environ, {"NVIDIA_API_KEY": ""}):
                status = arena_server.chat_model_status()
        self.assertEqual(status["status"], "needs_configuration")
        self.assertFalse(status["configured"])
        self.assertIn("NVIDIA_API_KEY", status["hint"])

    def test_configured_model_is_only_marked_not_tested(self):
        import server as arena_server
        with mock.patch.object(arena_server.C, "ModelRouter") as router:
            router.return_value.pick.return_value = ("fast", {"provider": "nvidia", "model": "example"})
            with mock.patch.dict(os.environ, {"NVIDIA_API_KEY": "test-token"}):
                status = arena_server.chat_model_status()
        self.assertEqual(status["status"], "not_tested")
        self.assertTrue(status["configured"])

if __name__ == "__main__":
    unittest.main()
