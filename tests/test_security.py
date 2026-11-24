# VULPHEX Security: 12 FOX bots, advisory policy + audit log, shared evidence DB, verification, and the evolving brain.
# No network, no external tools: the built-in secret scanner + temp SQLite make it run anywhere.
import json, os, random, sys, tempfile, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "security"))
import tools as T
import registry as R
import core as C
import brain as B


def temp_core(scope=None, approve=False):
    return C.Core(db_path=tempfile.mktemp(suffix=".db"), scope=scope or {"hosts": []}, approve=approve)


class TeamTest(unittest.TestCase):
    def test_twelve_fox_bots_nine_blue_three_red(self):
        team = json.load(open(ROOT / "security/team.json"))["bots"]
        self.assertEqual(len(team), 12)
        self.assertEqual(sum(b["side"] == "blue" for b in team), 9)
        self.assertEqual(sum(b["side"] == "red" for b in team), 3)
        for b in team:
            for cap in b["capabilities"]: self.assertIn(cap, R.CAPABILITIES, cap)

    def test_every_repo_in_the_map_belongs_to_a_real_bot(self):
        team = {b["name"] for b in json.load(open(ROOT / "security/team.json"))["bots"]}
        repos = json.load(open(ROOT / "repos.json"))["bots"]
        self.assertEqual(set(repos), team)
        for bot, lst in repos.items():
            self.assertTrue(2 <= len(lst) <= 3, f"{bot} has {len(lst)} repos")


class PolicyTest(unittest.TestCase):
    def test_policy_is_advisory_never_blocks_but_flags_out_of_scope(self):
        p = C.Policy({"hosts": ["example.com"]}, approve=False)
        risk, declared = p.classify("source_code_analysis", "semgrep", str(ROOT))
        self.assertTrue(declared)                                         # local files you own
        risk, declared = p.classify("exploit_validation", "sqlmap", "someone-else.com")
        self.assertEqual(risk, "active-test"); self.assertFalse(declared)  # flagged, not blocked
        risk, declared = p.classify("exploit_validation", "sqlmap", "example.com")
        self.assertTrue(declared)

    def test_an_out_of_scope_active_task_runs_but_is_audited_and_warned(self):
        core = temp_core(scope={"hosts": []})
        bot = {"name": "FOX SCOUT", "role": "x"}
        # recon on a host that won't connect: still audited, still warned
        log = []
        core.run_capability(bot, "asset_discovery", "127.0.0.1", log)     # localhost connect check, harmless
        aud = core.db.execute("SELECT target, in_scope FROM audit").fetchall()
        self.assertTrue(aud and aud[0]["target"] == "127.0.0.1")
        self.assertTrue(any("OUTSIDE your declared scope" in l for l in log))


class EvidenceAndProofTest(unittest.TestCase):
    def test_verify_confirms_a_real_line_and_flags_a_gone_one(self):
        d = tempfile.mkdtemp(); real = os.path.join(d, "c.py"); open(real, "w").write("x=1\nAWS='AKIAIOSFODNN7EXAMPLE'\n")
        core = temp_core()
        core.add_finding("FOX AUDITOR", "secret_detection", {"severity": "high", "title": "AWS", "where": f"{real}:2", "detail": ""}, "gitleaks")
        core.add_finding("FOX AUDITOR", "secret_detection", {"severity": "high", "title": "Ghost", "where": f"{d}/x.py:9", "detail": ""}, "gitleaks")
        core.verify_all([])
        by = {f["title"]: f["status"] for f in core.findings()}
        self.assertEqual(by["AWS"], "verified"); self.assertEqual(by["Ghost"], "inconclusive")


class BrainTest(unittest.TestCase):
    def test_a_better_tactic_wins_and_proves_out_under_the_luck_filter(self):
        db = __import__("sqlite3").connect(":memory:"); db.row_factory = __import__("sqlite3").Row
        br = B.Brain(db, size=6, seed=1)
        g = br.active("FOX SCOUT")                                        # a seeded tactic
        self.assertEqual(set(g), set(B.GENES))
        # feed the same genome a strong reward many times: it should become proven
        proven_seen = False
        for _ in range(8):
            g = br.active("FOX SCOUT"); _, note = br.score("FOX SCOUT", g, 20.0)
            if "proven" in note and "0 proven" not in note: proven_seen = True
        self.assertTrue(proven_seen, "a consistently good tactic should pass the luck filter")

    def test_reward_counts_confirmed_findings_minus_cost(self):
        fs = [{"severity": "high", "status": "verified"}, {"severity": "low", "status": "verified"}, {"severity": "high", "status": "new"}]
        self.assertAlmostEqual(B.reward(fs, tasks=2), 5 + 1 - 0.4)        # new (unconfirmed) doesn't count

    def test_keep_bar_drops_low_severity_noise(self):
        picky = {"depth": "deep", "keep": "high", "persist": True, "retry": False}
        fs = [{"severity": "high"}, {"severity": "low"}, {"severity": "info"}]
        db = __import__("sqlite3").connect(":memory:")
        kept = B.Brain(db, seed=1).filter_findings(picky, fs)
        self.assertEqual([f["severity"] for f in kept], ["high"])


class PipelineTest(unittest.TestCase):
    def test_local_mission_runs_the_blue_team_and_the_brain_learns(self):
        d = tempfile.mkdtemp(); open(os.path.join(d, "app.py"), "w").write("API_KEY='AKIAIOSFODNN7EXAMPLE'\n")
        core = temp_core()
        body, counts = core.mission(d, want={"FOX AUDITOR", "FOX ATLAS", "FOX PROOF", "FOX FORGE", "FOX WATCH"})
        self.assertGreaterEqual(counts["high"], 1)
        self.assertIn("brain:", body); self.assertIn("confirmed", body); self.assertIn("fix", body)
        self.assertGreaterEqual(core.db.execute("SELECT COUNT(*) FROM brain_pop").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()


class CoderAgentTest(unittest.TestCase):
    def test_builds_a_claude_command_with_brain_tools_and_skill(self):
        import agent as AG
        cfg = {"model": "huihui_ai/qwen3-coder-abliterated:30b", "allowed_tools": ["Bash", "Read", "Edit"], "timeout_s": 10}
        cmd = AG.build_cmd("fix the SQLi in app.py", cfg, "fox-fix", bot="FOX FORGE")
        self.assertEqual(cmd[0], os.environ.get("VULPHEX_CLAUDE_BIN", "claude"))
        self.assertIn("-p", cmd); self.assertIn("fix the SQLi in app.py", cmd)
        self.assertIn("--allowedTools", cmd); self.assertIn("Edit", cmd)
        self.assertIn("--model", cmd); self.assertIn("huihui_ai/qwen3-coder-abliterated:30b", cmd)
        sysp = cmd[cmd.index("--append-system-prompt") + 1]
        self.assertIn("FOX FORGE", sysp); self.assertIn("smallest", sysp)        # the fox-fix skill text is injected

    def test_env_points_claude_at_the_uncensored_brain(self):
        import agent as AG
        os.environ["VULPHEX_BRAIN_TOKEN"] = "tok123"
        env = AG.env_for({"base_url": "https://brain.example/", "model": "m1"})
        self.assertEqual(env["ANTHROPIC_BASE_URL"], "https://brain.example/")
        self.assertEqual(env["ANTHROPIC_AUTH_TOKEN"], "tok123"); self.assertEqual(env["ANTHROPIC_MODEL"], "m1")
        del os.environ["VULPHEX_BRAIN_TOKEN"]

    def test_run_streams_steps_and_summary_from_a_fake_claude(self):
        import agent as AG
        lines = [
            json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Edit", "input": {"file_path": "app.py"}}]}}),
            json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {"command": "python -m pytest"}}]}}),
            json.dumps({"type": "result", "result": "Fixed the SQL injection in app.py by parameterizing the query; tests pass."}),
        ]
        seen = []
        res = AG.run("fix it", skill="fox-fix", bot="FOX FORGE", spawn=lambda cmd, cwd, t: iter(lines), on_event=lambda k, v: seen.append(k))
        self.assertTrue(res["ok"]); self.assertIn("parameteriz", res["summary"])
        self.assertEqual([s["tool"] for s in res["steps"]], ["Edit", "Bash"]); self.assertIn("step", seen)

    def test_three_bots_have_the_coder_capability(self):
        team = json.load(open(ROOT / "security/team.json"))["bots"]
        coders = [b["name"] for b in team if "agentic_coding" in b["capabilities"]]
        self.assertEqual(set(coders), {"FOX AUDITOR", "FOX FORGE", "FOX REAPER"})
