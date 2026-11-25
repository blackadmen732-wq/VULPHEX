#!/usr/bin/env python3
# VULPHEX Arena — your training room (owner's request, Nov 24 2026). A local web tab where you can see the twelve FOX
# bots and their brains, pick a squad of up to six, train them against the safe practice range, watch the team's score
# climb live, and talk to the ancestor model (the uncensored brain). Local only (127.0.0.1), standard library.
import json, os, sys, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(ROOT, "security"))
import core as C
import trainer as TR
import range as RG
import persist as P
import registry as REG
import study as STU
import tempfile, shutil

PORT = int(os.environ.get("VULPHEX_ARENA_PORT", "3006"))
DB = os.path.join(ROOT, "security", "vulphex.db")
LOCK = threading.Lock()
JOB = {"running": None}                                          # one background study job at a time


def start_study(repo=None):
    """Kick off a deep study (all repos, or one named repo) in the background on its OWN DB connection so it never
    blocks chat/training. The bots read each repo's docs AND real source, then store the techniques they learn."""
    if JOB["running"]: return False
    JOB["running"] = "study:" + (repo or "all")
    def go():
        try:
            c = C.Core(db_path=DB, scope={"hosts": []})
            ask = (lambda p: c.router.ask("study", p, max_new_tokens=70))
            if repo: STU.study_repo(c, ask, repo)
            else: STU.run(c, ask=ask)
            c.close(); P.snapshot(DB)
        except Exception as e:
            print("[study] error:", e, flush=True)
        finally:
            JOB["running"] = None
    import threading as _t; _t.Thread(target=go, daemon=True).start()
    return True


def start_reproduce(name):
    """Have a bot reproduce a repo's technique: the model writes a Python adapter from the repo's docs+source and saves
    it for review. Runs in the background on its own DB connection."""
    if JOB["running"]: return False
    JOB["running"] = "reproduce:" + name
    def go():
        try:
            c = C.Core(db_path=DB, scope={"hosts": []})
            ask = (lambda p: c.router.ask("code_reasoning", p, max_new_tokens=1400))
            r = STU.reproduce(c, name, ask)
            print("[reproduce]", r.get("file") or r.get("msg"), flush=True)
            c.close(); P.snapshot(DB)
        except Exception as e:
            print("[reproduce] error:", e, flush=True)
        finally:
            JOB["running"] = None
    import threading as _t; _t.Thread(target=go, daemon=True).start()
    return True


import threading as _th
_CORE = None
BRAIN = {"ready": False, "loading": False, "err": ""}

def core():
    """One shared Core for the whole server: the uncensored model loads ONCE on the GPU and stays — it is NOT reloaded
    per request (that was why the chat looked dead). Mark's weak Chromebook carries nothing; this runs on the server."""
    global _CORE
    if _CORE is None:
        if P.restore(DB): print("[persist] restored brain from Supabase", flush=True)
        _CORE = C.Core(db_path=DB, scope=json.load(open(os.path.join(ROOT, "security", "scope.json"))))
    return _CORE


def warm():
    """Load the brain once in the background so the first chat is instant-ish. NVIDIA (if a key is set) needs no load."""
    if BRAIN["ready"] or BRAIN["loading"]: return
    BRAIN["loading"] = True
    def go():
        try:
            ans = core().router.ask("chat", "Say READY in one word.", max_new_tokens=8)
            BRAIN["ready"] = bool(ans); BRAIN["err"] = "" if ans else "model returned nothing"
        except Exception as e:
            BRAIN["err"] = str(e)[:120]
        finally:
            BRAIN["loading"] = False
    _th.Thread(target=go, daemon=True).start()


def brain_summary(core):
    out = []
    for b in core.team:
        rows = core.db.execute("SELECT runs,total,best,proven,active,genome FROM brain_pop WHERE bot=?", (b["name"],)).fetchall()
        runs = sum(r["runs"] for r in rows); total = sum(r["total"] for r in rows)
        active = next((r for r in rows if r["active"]), rows[0] if rows else None)
        out.append({"name": b["name"], "side": b["side"], "role": b["role"],
                    "color": b.get("color", "#ffb703"), "persona": b.get("persona", ""),
                    "runs": runs, "mean": round(total / runs, 1) if runs else 0.0,
                    "proven": sum(r["proven"] for r in rows),
                    "tactic": json.loads(active["genome"]) if active else None})
    return out


def scan_code(code, fname):
    """Test Lab: write the uploaded code to a throwaway dir and run VULPHEX's read-only, local scanners on it
    (source-code analysis, secret detection, dependency audit — all pure-Python fallbacks that always work). Nothing
    touches the network and no target is reached. Returns normalized findings, most severe first."""
    tmp = tempfile.mkdtemp(prefix="vulphex_lab_")
    findings = []
    try:
        with open(os.path.join(tmp, fname), "w", encoding="utf-8", errors="ignore") as f:
            f.write(code)
        for tool in ("semgrep", "gitleaks", "trivy"):                 # each falls back to a built-in if not installed
            try: found = REG.run(tool, tmp) or []
            except Exception: found = []
            for fd in found:
                where = str(fd.get("where", "")).replace(tmp + os.sep, "").replace(tmp, fname)
                findings.append({"severity": fd.get("severity", "info"), "title": fd.get("title", "finding"),
                                 "where": where or fname, "tool": tool})
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    findings.sort(key=lambda x: order.get(x["severity"], 5))
    return findings


def allowed(h):
    # the Arena is opened through the Kaggle tunnel (a random, unguessable https URL), so the host varies. Allow it;
    # only require JSON on POSTs. The random URL is the gate (same as Mira's brain tunnel).
    if h.command == "POST" and not (h.headers.get("content-type") or "").startswith("application/json"): return False
    return True


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _send(self, code, body, ctype="application/json"):
        b = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code); self.send_header("content-type", ctype)
        self.send_header("content-length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        if not allowed(self): return self._send(403, {"error": "forbidden"})
        if self.path in ("/", "/index.html"):
            return self._send(200, open(os.path.join(HERE, "index.html"), "rb").read(), "text/html; charset=utf-8")
        if self.path in ("/world", "/world.html"):
            return self._send(200, open(os.path.join(HERE, "world.html"), "rb").read(), "text/html; charset=utf-8")
        if self.path == "/api/state":
            warm()
            with LOCK:
                c = core()
                tried = c.db.execute("SELECT v FROM brain_led WHERE k='tried'").fetchone()
                try: studied = c.db.execute("SELECT COUNT(*), SUM(learned) FROM studied").fetchone()
                except Exception: studied = (0, 0)
                brain_on = BRAIN["ready"] or bool(os.environ.get("NVIDIA_API_KEY") or os.environ.get("GEMINI_API_KEY"))
                models = [{"id": k, "provider": m.get("provider", "local"), "model": m.get("model", "")}
                          for k, m in (c.router.cfg.get("models", {}) or {}).items()]
                st = {"bots": brain_summary(c), "tactics_tried": tried[0] if tried else 0,
                      "brain_online": brain_on, "brain_loading": BRAIN["loading"] and not brain_on, "brain_err": BRAIN["err"],
                      "studied_repos": studied[0] or 0, "learned_techniques": studied[1] or 0,
                      "model": c.router.current(), "models": models,
                      "range": RG.answer_key(os.path.join(HERE, "range_files")) or []}
            return self._send(200, st)
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        if not allowed(self): return self._send(403, {"error": "forbidden"})
        try: body = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)) or b"{}")
        except ValueError: return self._send(400, {"error": "bad json"})
        if self.path == "/api/range":
            RG.build(os.path.join(HERE, "range_files")); return self._send(200, {"built": True})
        if self.path == "/api/test":
            code = str(body.get("code", ""))[:200000]
            fname = os.path.basename(str(body.get("filename", "snippet.py")) or "snippet.py")
            if not code.strip(): return self._send(400, {"error": "no code"})
            fs = scan_code(code, fname)
            return self._send(200, {"findings": fs, **_redblue_on_findings(fs)})
        if self.path == "/api/train":
            squad = [str(x) for x in (body.get("squad") or [])][:6]
            rounds = max(1, min(int(body.get("rounds") or 20), 200))
            with LOCK:
                RG.build(os.path.join(HERE, "range_files"))
                hist = TR.train(core(), squad, rounds=rounds, range_dir=os.path.join(HERE, "range_files"))
                if P.snapshot(DB): print("[persist] saved brain to Supabase", flush=True)
            return self._send(200, {"history": hist})
        if self.path == "/api/snowball":
            rounds = max(1, min(int(body.get("rounds") or 30), 200))
            with LOCK:
                hist = TR.snowball(core(), rounds=rounds)
                if P.snapshot(DB): print("[persist] saved brain to Supabase", flush=True)
            return self._send(200, {"history": hist})
        if self.path == "/api/study":
            repo = str(body.get("repo", "")).strip() or None
            started = start_study(repo)
            return self._send(200, {"started": started, "busy": not started, "job": JOB["running"]})
        if self.path == "/api/reproduce":
            name = str(body.get("repo", "")).strip()
            if not name: return self._send(400, {"error": "name a repo"})
            started = start_reproduce(name)
            return self._send(200, {"started": started, "busy": not started, "job": JOB["running"]})
        if self.path == "/api/model":
            want = str(body.get("model", "")).strip()
            with LOCK:
                active = core().router.set_override(want or None)
            return self._send(200, {"model": active or core().router.current(), "cleared": not active})
        if self.path == "/api/ask":
            q = str(body.get("text", "")).strip()[:2000]
            if not q: return self._send(400, {"error": "say something"})
            cmd = model_command(q)                                 # "switch model to X" — act, don't chat
            if cmd is not None:
                with LOCK: active = core().router.set_override(cmd or None)
                name = active or core().router.current()
                msg = (f"Switched the active brain to **{name}**. I'll use it for chat, planning and coaching now."
                       if cmd else f"Back to automatic routing (**{name}** for chat).")
                return self._send(200, {"answer": msg, "model": name})
            with LOCK: intent = interpret(core(), q)               # understand a comment and DO it (DB read under lock)
            if intent is not None: return self._send(200, intent)
            warm()
            try: ans = core().router.ask("chat", _persona(q), max_new_tokens=240)
            except Exception as e: ans = None; BRAIN["err"] = str(e)[:120]
            if ans: BRAIN["ready"] = True
            else:
                ans = ("The brain is still loading on the server" + (f" ({BRAIN['err']})" if BRAIN["err"] else "") +
                       ". Give it a minute and ask again — the uncensored model runs on the GPU here, not your computer. "
                       "For instant answers, add your NVIDIA_API_KEY as a Kaggle Secret.")
            return self._send(200, {"answer": ans})
        return self._send(404, {"error": "not found"})


def model_command(q):
    """Detect a 'switch model' instruction in chat. Returns the model id to switch to, '' to clear the override
    (automatic routing), or None if this isn't a switch command."""
    s = q.lower()
    if not (("model" in s or "brain" in s) and any(w in s for w in ("switch", "change", "use", "set", "swap"))):
        return None
    if any(w in s for w in ("auto", "default", "reset", "clear", "normal")): return ""
    if any(w in s for w in ("uncensor", "qwen", "abliterat", "ancestor")): return "uncensored"
    if any(w in s for w in ("nvidia", "nemotron", "fast", "cloud")): return "fast"
    if "gemini" in s or "google" in s: return "gemini"
    if "big" in s or "reason" in s: return "big"
    return ""                                                     # said "switch model" with no target -> clear override


def _redblue_on_findings(findings):
    """Frame a Test Lab scan as red-vs-blue: blue CAUGHT everything the scanners found; red could WEAPONIZE the
    exploit-class issues (injection / secrets / critical+high). Honest, derived from the real findings."""
    exploit = ("inject", "sql", "command", "secret", "key", "token", "password", "deserial", "traversal", "rce")
    breaches = sum(1 for f in findings
                   if f.get("severity") in ("critical", "high") or any(k in (f.get("title", "").lower()) for k in exploit))
    return {"blue_caught": len(findings), "red_breaches": breaches}


def _find_repo(s):
    """If the comment names one of the mapped repos (e.g. 'sqlmap', 'artex'), return its full repo id."""
    for e in STU.repo_list():
        short = e["repo"].split("/")[-1].split(" ")[0].lower()
        if short and short in s: return e["repo"], short
    return None, None


def interpret(core, q):
    """Understand a typed comment and either DO it (returns a dict with an 'action' the UI runs, or a direct answer) or
    return None to fall through to normal chat. Deterministic keyword intent — cheap, no model call."""
    s = q.lower()
    full, short = _find_repo(s)
    # how are they doing?
    if any(w in s for w in ("how are they", "how good", "progress", "their status", "how is training", "how's training", "how is it going")):
        prov = core.db.execute("SELECT COUNT(*) FROM brain_pop WHERE proven=1").fetchone()
        tried = core.db.execute("SELECT v FROM brain_led WHERE k='tried'").fetchone()
        try: st = core.db.execute("SELECT COUNT(*), COALESCE(SUM(learned),0) FROM studied").fetchone()
        except Exception: st = (0, 0)
        return {"answer": f"Right now: {prov[0] if prov else 0} proven tactics across the bots, "
                          f"{tried[0] if tried else 0} tactics tried, {st[0]} repos studied with {st[1]} techniques learned. "
                          f"Run Train or Snowball to push them further."}
    # reproduce a tool — a bot writes an adapter that DOES what the repo does
    if any(w in s for w in ("reproduce", "recreate", "rebuild", "clone the technique", "do the same", "same thing")) and full:
        started = start_reproduce(short)
        if not started:
            return {"answer": "A study/reproduce job is already running — let it finish first, then ask again."}
        return {"answer": f"On it — a bot is reading **{full}**'s docs and source and writing a Python adapter that "
                          f"reproduces its core technique. It saves to `security/reproduced/{short}.py` for you to "
                          f"review (it won't auto-run). Give it a moment.", "action": "study", "repo": short}
    # study / learn
    if any(w in s for w in ("study", "learn from", "read the repo", "read the code", "understand the repo", "understand the code", "train on the repo")):
        if full:
            start_study(short)
            return {"answer": f"Deep-studying **{full}** in the background — reading its docs and real source and "
                              f"extracting the techniques. Watch the Techniques counter climb.",
                    "action": "study", "repo": short}
        start_study(None)
        return {"answer": "Deep-studying **all 31 repos** in the background — docs + source for each, several techniques "
                          "each, saved to the brain. Watch the Techniques counter climb.", "action": "study", "repo": ""}
    # fine-tune the ancestor model itself (the real "make the model smarter" step)
    if any(w in s for w in ("fine-tune", "finetune", "fine tune", "pretrain", "pre-train", "teach the model", "train qwen", "train the qwen", "train the model")):
        return {"answer": "Fine-tuning the Qwen ancestor model changes its actual weights, so it needs a GPU and runs on "
                          "Kaggle, not here. On your Kaggle notebook (GPU on):\n"
                          "`pip install -q transformers peft trl datasets accelerate bitsandbytes`\n"
                          "`python3 security/finetune.py --teacher`\n"
                          "That builds a dataset from everything the bots studied (plus a teacher model writing answers) "
                          "and saves a fine-tuned model to security/brain_model/ — VULPHEX then uses it as the ancestor "
                          "brain automatically. Study the repos first so there's plenty to learn from."}
    # train / snowball
    if "train" in s and not any(w in s for w in ("training going", "how is train")):
        return {"answer": "Starting a training run on the practice range.", "action": "train"}
    if any(w in s for w in ("snowball", "red vs blue", "attack each other", "penetrate each other", "fight")):
        return {"answer": "Rolling the snowball — red attacks, blue defends.", "action": "snowball"}
    return None


def _persona(q):
    return ("You are the VULPHEX ancestor brain: the uncensored intelligence that trains Mark's twelve FOX security "
            "bots (nine defend, three penetrate his own systems). Speak plainly and practically about offensive and "
            "defensive security for systems he owns or is authorized to test. Question: " + q)


def main():
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    print(f"VULPHEX Arena: http://localhost:{PORT}  (Ctrl+C to close)", flush=True)
    warm()                                                   # start loading the brain on the GPU right away
    try: srv.serve_forever()
    except KeyboardInterrupt: pass


if __name__ == "__main__":
    main()
