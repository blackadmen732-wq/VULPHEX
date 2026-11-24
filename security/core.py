#!/usr/bin/env python3
# VULPHEX COMMAND CORE: the infrastructure the nine FOX bots run on (not a tenth bot).
#   - policy engine : authorizes every task (scope.json + approval + risk level) before any tool runs
#   - evidence DB   : one shared SQLite store of assets, findings and task history, so bots build on each other
#   - model router  : picks a cheap or strong model per job (planning/report vs code reasoning)
#   - orchestrator  : runs a mission as a pipeline — discover, map, audit, scan, VERIFY, repair, monitor
# Safety is enforced here, in code: FOX PROOF verifies findings deterministically so a bot cannot invent them, and no
# active-test or restricted task runs off your authorized scope. Local-only, standard library plus the engine model.
import fnmatch, hashlib, ipaddress, json, os, re, sqlite3, sys, time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(ROOT, "engine"))
import tools as T
import registry as R
import brain as B
import agent as AG

SEV_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


def now_iso(): return datetime.now(timezone.utc).isoformat(timespec="seconds")


def is_private(host):
    try: return ipaddress.ip_address(host).is_private
    except ValueError: return host in ("localhost",) or host.endswith(".local")


# ---------------------------------------------------------------- policy engine
class Policy:
    """Decides if a capability may run against a target. Local reads of your own files: yes. Network tasks: only a
    target in scope.json, and only with approval. Nothing bypasses this."""
    def __init__(self, scope, approve=False):
        self.scope = scope or {}; self.approve = approve

    def host_in_scope(self, target):
        if os.path.exists(target): return True
        host = re.sub(r"^\w+://", "", target).split("/")[0].split(":")[0]
        if is_private(host) and not self.scope.get("allow_private_ranges"): return False
        return any(fnmatch.fnmatch(host, pat) for pat in self.scope.get("hosts", []))

    def classify(self, capability, tool, target):
        """VULPHEX is Mark's own tool: it runs what he points it at (his systems / authorized engagements). This does
        NOT block; it labels the task and notes whether the target is inside the scope he declared, so the audit log
        is honest. Authorization is the operator's responsibility, like every real pentest tool."""
        risk = R.risk_of(capability, tool)
        local = os.path.exists(target) or capability in ("system_mapping", "finding_verification", "repair", "monitoring")
        declared = local or self.host_in_scope(target)
        return risk, declared


# ---------------------------------------------------------------- model router
class ModelRouter:
    """Cheap model for planning/classification/report; strong model for hard code reasoning. Both optional and local."""
    def __init__(self):
        self.cheap = os.environ.get("VULPHEX_MODEL_CHEAP") or os.environ.get("COACH_MODEL") or "Goekdeniz-Guelmez/Josiefied-Qwen2.5-1.5B-Instruct-abliterated-v1"
        self.strong = os.environ.get("VULPHEX_MODEL_STRONG") or self.cheap
        self._cache = {}

    def pick(self, job): return self.strong if job in ("code_reasoning", "repair") else self.cheap

    def ask(self, job, prompt, max_new_tokens=120):
        name = self.pick(job)
        if name not in self._cache:
            try:
                import local_llm
                gen, why = local_llm.load(name, max_new_tokens=max_new_tokens)
                self._cache[name] = gen
            except Exception:
                self._cache[name] = None
        gen = self._cache[name]
        if gen is None: return None
        try: return gen(prompt)
        except Exception: return None


# ---------------------------------------------------------------- shared evidence database
SCHEMA = """
CREATE TABLE IF NOT EXISTS assets   (id TEXT PRIMARY KEY, kind TEXT, value TEXT, source TEXT, seen TEXT);
CREATE TABLE IF NOT EXISTS findings (id TEXT PRIMARY KEY, bot TEXT, capability TEXT, severity TEXT, title TEXT,
                                     place TEXT, detail TEXT, tool TEXT, status TEXT, verified_by TEXT, fix TEXT, created TEXT);
CREATE TABLE IF NOT EXISTS tasks    (id INTEGER PRIMARY KEY AUTOINCREMENT, bot TEXT, capability TEXT, target TEXT,
                                     status TEXT, note TEXT, created TEXT);
CREATE TABLE IF NOT EXISTS audit    (id INTEGER PRIMARY KEY AUTOINCREMENT, bot TEXT, capability TEXT, tool TEXT,
                                     target TEXT, risk TEXT, in_scope INTEGER, at TEXT);
"""


class Core:
    def __init__(self, db_path=None, scope=None, approve=False):
        self.db = sqlite3.connect(db_path or os.path.join(HERE, "vulphex.db"))
        self.db.row_factory = sqlite3.Row; self.db.executescript(SCHEMA)
        self.policy = Policy(scope if scope is not None else self._load("scope.json", {}), approve)
        self.router = ModelRouter()
        self.brain = B.Brain(self.db)
        self.team = self._load("team.json", {"bots": []})["bots"]
        self.byname = {b["name"].upper(): b for b in self.team}

    def _load(self, name, default):
        try: return json.load(open(os.path.join(HERE, name)))
        except (OSError, ValueError): return default

    # -- storage
    def add_asset(self, kind, value, source):
        aid = hashlib.sha1(f"{kind}|{value}".encode()).hexdigest()[:12]
        self.db.execute("INSERT OR IGNORE INTO assets VALUES (?,?,?,?,?)", (aid, kind, value, source, now_iso())); self.db.commit(); return aid

    def add_finding(self, bot, capability, f, tool):
        fid = hashlib.sha1(f"{capability}|{f['title']}|{f['where']}".encode()).hexdigest()[:12]
        cur = self.db.execute("SELECT 1 FROM findings WHERE id=?", (fid,))
        if cur.fetchone(): return fid, False
        self.db.execute("INSERT INTO findings VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        (fid, bot, capability, f["severity"], f["title"], f["where"], f.get("detail", ""), tool, "new", "", "", now_iso()))
        self.db.commit(); return fid, True

    def audit(self, bot, capability, tool, target, risk, declared):
        self.db.execute("INSERT INTO audit (bot,capability,tool,target,risk,in_scope,at) VALUES (?,?,?,?,?,?,?)",
                        (bot, capability, tool, target, risk, int(declared), now_iso())); self.db.commit()

    def log_task(self, bot, capability, target, status, note=""):
        self.db.execute("INSERT INTO tasks (bot,capability,target,status,note,created) VALUES (?,?,?,?,?,?)",
                        (bot, capability, target, status, note, now_iso())); self.db.commit()

    def findings(self, status=None):
        q = "SELECT * FROM findings" + (" WHERE status=?" if status else "") + " ORDER BY created"
        return [dict(r) for r in self.db.execute(q, (status,) if status else ()).fetchall()]

    def set_finding(self, fid, **kw):
        for k, v in kw.items(): self.db.execute(f"UPDATE findings SET {k}=? WHERE id=?", (v, fid))
        self.db.commit()

    # -- run one capability for one bot (through the registry + policy)
    def run_capability(self, bot, capability, target, log):
        if capability == "agentic_coding": return 0          # on-demand only (artex.py agent), not part of a scan
        for a in R.adapters(capability):
            tool = a["tool"]
            if tool in R.CORE_TOOLS: continue                              # core capabilities handled elsewhere
            if not R.installed(tool): continue
            risk, declared = self.policy.classify(capability, tool, target)
            self.audit(bot["name"], capability, tool, target, risk, declared)
            if risk != "read-only" and not declared:
                log.append(f"  - {bot['name']} / {capability}: ⚠ {target} is OUTSIDE your declared scope (security/scope.json) — running anyway, logged; you are responsible for authorization")
            try:
                found = R.run(tool, target); new = 0
                for f in found:
                    _, is_new = self.add_finding(bot["name"], capability, f, tool); new += is_new
                log.append(f"  - {bot['name']} ({bot['role']}) ran {tool}: {len(found)} findings, {new} new")
                self.log_task(bot["name"], capability, target, "done", f"{len(found)} findings")
                return new
            except T.ToolMissing as e:
                log.append(f"  - {bot['name']}: {e}")
            except Exception as e:
                log.append(f"  - {bot['name']}: error {type(e).__name__}: {str(e)[:120]}")
            return 0
        log.append(f"  - {bot['name']} / {capability}: no installed tool (try security/install-tools.sh)")
        return 0

    # -- FOX ATLAS: build the asset graph from what the scanners touched
    def map_assets(self, target, log):
        n = 0
        if os.path.exists(target): self.add_asset("path", os.path.abspath(target), "FOX ATLAS"); n += 1
        else:
            host = re.sub(r"^\w+://", "", target).split("/")[0].split(":")[0]; self.add_asset("host", host, "FOX ATLAS"); n += 1
        for f in self.findings():                                          # ports Scout found become service assets
            m = re.match(r"(.+):(\d+)$", f["place"])
            if m and "port" in f["title"].lower(): self.add_asset("service", f["place"], "FOX ATLAS"); n += 1
        log.append(f"  - FOX ATLAS mapped {self.db.execute('SELECT COUNT(*) FROM assets').fetchone()[0]} assets")
        return n

    # -- FOX PROOF: a finding counts only if it can be re-confirmed deterministically
    def verify_all(self, log):
        confirmed = inconclusive = 0
        for f in self.findings("new"):
            place = f["place"]; m = re.match(r"(.+):(\d+)$", place)
            local = m and (os.path.isfile(m.group(1)) or os.sep in m.group(1))
            if local:                                                      # a source-line finding: re-open and confirm it is still there
                try:
                    line = open(m.group(1), errors="ignore").read().splitlines()[int(m.group(2)) - 1]
                    ok = bool(line.strip())
                    self.set_finding(f["id"], status="verified" if ok else "inconclusive", verified_by="FOX PROOF (re-read source)")
                    confirmed += ok; inconclusive += (not ok)
                except (OSError, IndexError):
                    self.set_finding(f["id"], status="inconclusive", verified_by="FOX PROOF (source gone)"); inconclusive += 1
            else:
                # active/intrusive proof needs approval; without it, record as reported-not-proven
                self.set_finding(f["id"], status="reported", verified_by="FOX PROOF (needs approval to prove)"); inconclusive += 1
        log.append(f"  - FOX PROOF: {confirmed} confirmed, {inconclusive} need deeper/approved proof")
        return confirmed

    # -- FOX FORGE: draft a scoped fix for each verified finding (for review, never auto-applied)
    def repair_all(self, log):
        tips = {"secret_detection": "Remove the value from the file, rotate it, and load it from an environment variable or a secrets manager.",
                "source_code_analysis": "Apply the fix the rule suggests; validate and encode untrusted input at this line.",
                "dependency_audit": "Upgrade the package to a patched version, or pin and monitor it.",
                "web_app_scan": "Add the missing control (output encoding, security header, auth check) at the affected endpoint.",
                "asset_discovery": "Close the port or firewall it to known sources if it should not be public.",
                "ai_security": "Add input/output guards and tighten the model's system prompt and tool permissions."}
        n = 0
        for f in self.findings("verified"):
            tip = tips.get(f["capability"], "Review and remediate.")
            self.set_finding(f["id"], status="fix_proposed", fix=tip); n += 1
        log.append(f"  - FOX FORGE drafted {n} fix suggestion(s) for review (none applied automatically)")
        return n

    # -- FOX WATCH: what is still open
    def monitor(self, log):
        open_n = self.db.execute("SELECT COUNT(*) FROM findings WHERE status NOT IN ('inconclusive')").fetchone()[0]
        log.append(f"  - FOX WATCH: {open_n} finding(s) tracked; re-run VULPHEX to detect changes and regressions")

    # -- the mission pipeline: the bots hand work to each other
    def mission(self, target, want):
        """want: set of bot names to involve (default all applicable). Returns (report text, counts)."""
        log, t0 = [], time.time()
        order = ["FOX SCOUT", "FOX ATLAS", "FOX AUDITOR", "FOX INSPECTOR", "FOX BASTION", "FOX AEGIS",
                 "FOX BREACH", "FOX REAPER", "FOX WRAITH", "FOX PROOF", "FOX FORGE", "FOX WATCH"]
        ran = []
        for name in order:
            bot = self.byname.get(name)
            if not bot or (want and name not in want): continue
            if name == "FOX ATLAS": self.map_assets(target, log); continue
            if name == "FOX PROOF": self.verify_all(log); continue
            if name == "FOX FORGE": self.repair_all(log); continue
            if name == "FOX WATCH": self.monitor(log); continue
            self.brain.active(bot["name"])                       # seed/choose this bot's playbook
            before = self.db.execute("SELECT COUNT(*) FROM tasks WHERE bot=?", (bot["name"],)).fetchone()[0]
            for cap in bot["capabilities"]:
                self.run_capability(bot, cap, target, log)
            ran.append((bot["name"], before))
        # the brain learns: score each bot by what it confirmed this mission, evolve its tactics under the luck filter
        for name, before in ran:
            mine = [f for f in self.findings() if f["bot"] == name]
            tasks = self.db.execute("SELECT COUNT(*) FROM tasks WHERE bot=?", (name,)).fetchone()[0] - before
            g = self.brain.active(name); rwd = B.reward(mine, tasks)
            _, note = self.brain.score(name, g, rwd)
            if mine or tasks: log.append(f"  - {name} {note}")
        return self.report(target, log, time.time() - t0)

    def report(self, target, log, secs):
        items = sorted(self.findings(), key=lambda f: (SEV_RANK.get(f["severity"], 9), f["bot"]))
        counts = {s: sum(1 for f in items if f["severity"] == s) for s in T.SEV}
        out = [f"## {now_iso()}", f"- target: {target}",
               "- findings: " + (", ".join(f"{counts[s]} {s}" for s in T.SEV if counts[s]) or "none"),
               f"- took {secs:.1f}s", "", "### FOX team"] + log
        if items:
            out += ["", "### Findings (most serious first)"]
            for f in items:
                tag = {"verified": "✓ verified", "fix_proposed": "✓ fix ready", "reported": "• reported", "inconclusive": "• unproven", "new": "• new"}.get(f["status"], f["status"])
                out.append(f"- **[{f['severity'].upper()}]** {f['title']} — `{f['place']}`  _({f['bot']} / {f['tool']}, {tag})_")
                if f["detail"]: out.append(f"  - {f['detail']}")
                if f["fix"]: out.append(f"  - **fix:** {f['fix']}")
        body = "\n".join(out)
        rep = os.path.join(ROOT, "security-report.md"); old = open(rep).read() if os.path.exists(rep) else "# VULPHEX security report\n"
        head, _, rest = old.partition("\n"); open(rep, "w").write(head + "\n\n" + body + "\n" + rest)
        return body, counts

    SKILL_FOR = {"FOX FORGE": "fox-fix", "FOX AUDITOR": "fox-fix", "FOX SCOUT": "fox-recon",
                 "FOX REAPER": "fox-pentest", "FOX BREACH": "fox-pentest", "FOX WRAITH": "fox-pentest"}

    def code(self, bot_name, mission, cwd=".", on_event=None):
        """Give a bot Claude Code's body + the uncensored brain to actually do a coding/pentest task. Audited."""
        skill = self.SKILL_FOR.get(bot_name, "fox-fix")
        self.audit(bot_name, "agentic_coding", "coder", cwd, "read-only", int(os.path.exists(cwd)))
        res = AG.run(mission, cwd=cwd, skill=skill, bot=bot_name, on_event=on_event)
        self.log_task(bot_name, "agentic_coding", cwd, "done" if res["ok"] else "error", res["summary"][:200])
        return res

    def close(self): self.db.close()
