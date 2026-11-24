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
import train as TR
import range as RG

PORT = int(os.environ.get("VULPHEX_ARENA_PORT", "3006"))
DB = os.path.join(ROOT, "security", "vulphex.db")
LOCK = threading.Lock()


def new_core():
    return C.Core(db_path=DB, scope=json.load(open(os.path.join(ROOT, "security", "scope.json"))))


def brain_summary(core):
    out = []
    for b in core.team:
        rows = core.db.execute("SELECT runs,total,best,proven,active,genome FROM brain_pop WHERE bot=?", (b["name"],)).fetchall()
        runs = sum(r["runs"] for r in rows); total = sum(r["total"] for r in rows)
        active = next((r for r in rows if r["active"]), rows[0] if rows else None)
        out.append({"name": b["name"], "side": b["side"], "role": b["role"],
                    "runs": runs, "mean": round(total / runs, 1) if runs else 0.0,
                    "proven": sum(r["proven"] for r in rows),
                    "tactic": json.loads(active["genome"]) if active else None})
    return out


def allowed(h):
    host = (h.headers.get("host") or "").lower()
    if host not in (f"localhost:{PORT}", f"127.0.0.1:{PORT}", f"[::1]:{PORT}"): return False
    origin = h.headers.get("origin")
    if origin is not None and origin not in (f"http://localhost:{PORT}", f"http://127.0.0.1:{PORT}"): return False
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
        if self.path == "/api/state":
            with LOCK:
                core = new_core()
                tried = core.db.execute("SELECT v FROM brain_led WHERE k='tried'").fetchone()
                st = {"bots": brain_summary(core), "tactics_tried": tried[0] if tried else 0,
                      "range": RG.answer_key(os.path.join(HERE, "range_files")) or []}
                core.close()
            return self._send(200, st)
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        if not allowed(self): return self._send(403, {"error": "forbidden"})
        try: body = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)) or b"{}")
        except ValueError: return self._send(400, {"error": "bad json"})
        if self.path == "/api/range":
            RG.build(os.path.join(HERE, "range_files")); return self._send(200, {"built": True})
        if self.path == "/api/train":
            squad = [str(x) for x in (body.get("squad") or [])][:6]
            rounds = max(1, min(int(body.get("rounds") or 20), 200))
            with LOCK:
                core = new_core()
                RG.build(os.path.join(HERE, "range_files"))
                hist = TR.train(core, squad, rounds=rounds, range_dir=os.path.join(HERE, "range_files"))
                core.close()
            return self._send(200, {"history": hist})
        if self.path == "/api/ask":
            q = str(body.get("text", "")).strip()[:2000]
            if not q: return self._send(400, {"error": "say something"})
            with LOCK:
                core = new_core(); ans = core.router.ask("chat", _persona(q), max_new_tokens=220); core.close()
            if not ans:
                ans = ("(The ancestor model isn't loaded here. On a machine with the model downloaded it answers as the "
                       "uncensored brain. Set COACH_MODEL to the abliterated Qwen and run the arena there.)")
            return self._send(200, {"answer": ans})
        return self._send(404, {"error": "not found"})


def _persona(q):
    return ("You are the VULPHEX ancestor brain: the uncensored intelligence that trains Mark's twelve FOX security "
            "bots (nine defend, three penetrate his own systems). Speak plainly and practically about offensive and "
            "defensive security for systems he owns or is authorized to test. Question: " + q)


def main():
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    print(f"VULPHEX Arena: http://localhost:{PORT}  (Ctrl+C to close)", flush=True)
    try: srv.serve_forever()
    except KeyboardInterrupt: pass


if __name__ == "__main__":
    main()
