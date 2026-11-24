# VULPHEX Security: the command core — policy engine, shared evidence DB, verification, and the FOX pipeline.
# No network, no external tools: the built-in secret scanner and a temp SQLite DB make it run anywhere.
import json, os, sys, tempfile, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "security"))
import tools as T
import registry as R
import core as C


def temp_core(scope=None, approve=False):
    db = tempfile.mktemp(suffix=".db")
    return C.Core(db_path=db, scope=scope or {"hosts": []}, approve=approve)


class PolicyTest(unittest.TestCase):
    def test_local_reads_are_allowed_but_remote_needs_scope_and_approval(self):
        p = C.Policy({"hosts": ["example.com"]}, approve=False)
        self.assertEqual(p.authorize("source_code_analysis", "semgrep", str(ROOT))[0], True)        # your files
        ok, why = p.authorize("web_app_scan", "zap", "someone-else.com")
        self.assertFalse(ok); self.assertIn("REFUSED", why)                                         # not in scope
        ok, why = p.authorize("web_app_scan", "zap", "example.com")
        self.assertFalse(ok); self.assertIn("approval", why)                                        # in scope, no approval
        p2 = C.Policy({"hosts": ["example.com"]}, approve=True)
        self.assertTrue(p2.authorize("web_app_scan", "zap", "example.com")[0])

    def test_private_ranges_off_by_default(self):
        self.assertFalse(C.Policy({"hosts": ["10.0.0.5"]}, True).host_in_scope("10.0.0.5"))
        self.assertTrue(C.Policy({"hosts": ["10.0.0.5"], "allow_private_ranges": True}, True).host_in_scope("10.0.0.5"))


class TeamAndRegistryTest(unittest.TestCase):
    def test_nine_fox_bots(self):
        team = json.load(open(ROOT / "security/team.json"))["bots"]
        self.assertEqual(len(team), 9)
        self.assertTrue(all(b["name"].startswith("FOX ") for b in team))
        for b in team:
            for cap in b["capabilities"]: self.assertIn(cap, R.CAPABILITIES, cap)

    def test_every_capability_has_a_known_risk(self):
        for cap, ads in R.CAPABILITIES.items():
            for a in ads: self.assertIn(a["risk"], ("read-only", "active-test", "restricted"))


class EvidenceDBTest(unittest.TestCase):
    def test_findings_are_stored_once_and_survive_reopen(self):
        core = temp_core(); db = core.db
        bot = {"name": "FOX AUDITOR", "role": "code"}
        f = {"severity": "high", "title": "Secret: X", "where": "a.py:3", "detail": ""}
        _, new1 = core.add_finding(bot["name"], "secret_detection", f, "gitleaks")
        _, new2 = core.add_finding(bot["name"], "secret_detection", f, "gitleaks")
        self.assertTrue(new1); self.assertFalse(new2); self.assertEqual(len(core.findings()), 1)

    def test_verify_confirms_a_real_source_line_and_flags_a_gone_one(self):
        d = tempfile.mkdtemp(); real = os.path.join(d, "c.py")
        open(real, "w").write("x=1\nAWS='AKIAIOSFODNN7EXAMPLE'\n")
        core = temp_core()
        core.add_finding("FOX AUDITOR", "secret_detection", {"severity": "high", "title": "Possible AWS key", "where": f"{real}:2", "detail": ""}, "gitleaks")
        core.add_finding("FOX AUDITOR", "secret_detection", {"severity": "high", "title": "Ghost", "where": f"{d}/missing.py:9", "detail": ""}, "gitleaks")
        core.verify_all([])
        by_title = {f["title"]: f for f in core.findings()}
        self.assertEqual(by_title["Possible AWS key"]["status"], "verified")
        self.assertEqual(by_title["Ghost"]["status"], "inconclusive")

    def test_forge_drafts_a_fix_only_for_verified_findings(self):
        d = tempfile.mkdtemp(); real = os.path.join(d, "c.py"); open(real, "w").write("pw='hunter2hunter2'\n")
        core = temp_core()
        core.add_finding("FOX AUDITOR", "secret_detection", {"severity": "high", "title": "secret", "where": f"{real}:1", "detail": ""}, "gitleaks")
        core.verify_all([]); n = core.repair_all([])
        self.assertEqual(n, 1); f = core.findings()[0]
        self.assertEqual(f["status"], "fix_proposed"); self.assertIn("environment variable", f["fix"])


class PipelineTest(unittest.TestCase):
    def test_a_local_mission_audits_verifies_and_reports(self):
        d = tempfile.mkdtemp()
        open(os.path.join(d, "app.py"), "w").write("API_KEY = 'AKIAIOSFODNN7EXAMPLE'\n")
        core = temp_core()
        body, counts = core.mission(d, want={"FOX AUDITOR", "FOX ATLAS", "FOX PROOF", "FOX FORGE", "FOX WATCH"})
        self.assertGreaterEqual(counts["high"], 1)
        self.assertIn("FOX PROOF", body); self.assertIn("confirmed", body); self.assertIn("fix", body)
        self.assertGreaterEqual(core.db.execute("SELECT COUNT(*) FROM assets").fetchone()[0], 1)   # Atlas mapped it

    def test_an_active_bot_is_blocked_off_scope_in_a_mission(self):
        core = temp_core(scope={"hosts": []}, approve=True)
        body, _ = core.mission("not-my-site.com", want={"FOX SCOUT"})
        self.assertIn("REFUSED", body)
        self.assertEqual(len(core.findings()), 0)


if __name__ == "__main__":
    unittest.main()
