# VULPHEX Security: the authorization gate, the built-in secret scanner, dedup, and the report. No network, no tools.
import json, os, sys, tempfile, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "security"))
import tools as T
import artex


class ScopeGateTest(unittest.TestCase):
    def test_local_paths_are_always_in_scope(self):
        self.assertTrue(artex.in_scope(str(ROOT), {}))                 # your own files
        self.assertTrue(artex.in_scope(__file__, {}))

    def test_outside_hosts_are_refused_unless_listed(self):
        self.assertFalse(artex.in_scope("example.com", {"hosts": []}))
        self.assertFalse(artex.in_scope("https://evil.test/x", {"hosts": ["example.com"]}))
        self.assertTrue(artex.in_scope("example.com", {"hosts": ["example.com"]}))
        self.assertTrue(artex.in_scope("api.example.com", {"hosts": ["*.example.com"]}))

    def test_private_ranges_are_off_by_default(self):
        self.assertFalse(artex.in_scope("192.168.1.10", {"hosts": ["192.168.1.10"]}))
        self.assertTrue(artex.in_scope("192.168.1.10", {"hosts": ["192.168.1.10"], "allow_private_ranges": True}))

    def test_an_active_agent_refuses_an_unauthorized_target(self):
        store, log = {}, []
        agent = next(a for a in artex.TEAM if a["kind"] == "active")
        artex.run_agent(agent, "someone-elses-site.com", store, {"hosts": []}, approved=True, log=log)
        self.assertEqual(store, {}); self.assertIn("REFUSED", log[0])

    def test_an_active_agent_in_scope_still_needs_approval(self):
        store, log = {}, []
        agent = next(a for a in artex.TEAM if a["kind"] == "active")
        artex.run_agent(agent, "example.com", store, {"hosts": ["example.com"]}, approved=False, log=log)
        self.assertEqual(store, {}); self.assertIn("approval", log[0])


class SecretScanTest(unittest.TestCase):
    def test_finds_a_planted_key_with_no_tool_installed(self):
        d = tempfile.mkdtemp()
        open(os.path.join(d, "config.py"), "w").write("AWS_KEY = 'AKIAIOSFODNN7EXAMPLE'\npassword = 'hunter2hunter2'\n")
        open(os.path.join(d, "clean.py"), "w").write("x = 1 + 1\n")
        found = T.gitleaks(d)                                          # falls back to the built-in scanner
        titles = " ".join(f["title"] for f in found)
        self.assertIn("AWS", titles); self.assertTrue(any(f["severity"] == "high" for f in found))


class StoreAndReportTest(unittest.TestCase):
    def test_duplicate_findings_are_merged(self):
        store = {}; agent = {"name": "Vault", "finds": "secrets", "tool": "gitleaks"}
        f = [{"severity": "high", "title": "Secret: X", "where": "a.py:3", "detail": ""}]
        self.assertEqual(artex.merge(store, f, agent), 1)
        self.assertEqual(artex.merge(store, f, agent), 0)              # same finding again: not added
        self.assertEqual(len(store), 1)

    def test_report_ranks_by_severity(self):
        store = {}
        for sev, t in [("low", "L"), ("critical", "C"), ("medium", "M")]:
            artex.merge(store, [{"severity": sev, "title": t, "where": "w", "detail": ""}], {"name": "A", "finds": t, "tool": "x"})
        body, counts = artex.write_report("m", "t", store, ["  - A: ok"])
        self.assertLess(body.index("[CRITICAL]"), body.index("[MEDIUM]"))
        self.assertLess(body.index("[MEDIUM]"), body.index("[LOW]"))
        self.assertEqual(counts["critical"], 1)


class TeamTest(unittest.TestCase):
    def test_nine_agents_each_with_a_real_tool(self):
        self.assertEqual(len(artex.TEAM), 9)
        for a in artex.TEAM:
            self.assertIn(a["tool"], T.RUNNERS); self.assertIn(a["kind"], ("local", "active"))


if __name__ == "__main__":
    unittest.main()
