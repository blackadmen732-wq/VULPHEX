#!/usr/bin/env python3
# VULPHEX Security: an AI security engineering team (owner: Mark, Nov 24 2026). DEFENSIVE / AUTHORIZED USE ONLY.
# The ARTEX idea done safely: a planner, 9 specialist agents over real scanning tools, shared evidence, de-duplicated
# findings ranked by severity, a human approval gate for anything that touches the network, and an auto-written report.
#
#   python3 security/vulphex_sec.py ~/my-project              audit your own code: secrets, code, dependencies (no network)
#   python3 security/vulphex_sec.py https://my-site.com --approve   scan a site you OWN (must be in security/scope.json)
#
# Local agents (Cinder, Vault, Sieve, Ward) read your own files and always run. Active agents (Warden, Probe, Scout,
# Mirror, Crucible) run only when the target is listed in scope.json AND you pass --approve. The brain (the same
# uncensored local model as the trading bots) only writes the plan and the summary; it can never widen the scope.
import argparse, hashlib, json, os, sys, time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(ROOT, "engine"))
import scope as scope_mod
import tools

SEV_RANK = {s: i for i, s in enumerate(tools.SEV)}


def team(path=None):
    return json.load(open(path or os.path.join(HERE, "team.json")))["agents"]


def is_local(target):
    return os.path.exists(os.path.expanduser(str(target)))


def plan(target, agents):
    """Which agents fit this target. A local folder gets the local agents; a host/URL gets the active ones."""
    local = is_local(target)
    return [a for a in agents if (a["kind"] == "local") == local]


def fingerprint(f):
    key = (f.get("title", "").lower().strip(), str(f.get("where", "")).lower().strip())
    return hashlib.sha1(repr(key).encode()).hexdigest()[:12]


def dedup(findings):
    seen, out = {}, []
    for f in findings:
        fp = fingerprint(f)
        if fp in seen:
            seen[fp]["agents"] = sorted(set(seen[fp]["agents"]) | set(f.get("agents", [])))
            continue
        f = {**f, "id": fp}; seen[fp] = f; out.append(f)
    return sorted(out, key=lambda f: (SEV_RANK.get(f.get("severity", "info"), 9), f.get("title", "")))


def run(target, agents=None, approve=False, scope=None, runners=None, log=print):
    """Run the team on one target. Returns (findings, notes). Never scans out of scope."""
    agents = agents or team(); scope = scope or scope_mod.load(); runners = runners or tools.RUNNERS
    chosen = plan(target, agents); notes, raw = [], []
    if not is_local(target):                                   # ACTIVE: scope + approval, checked once, up front
        try: host = scope_mod.check(target, scope)
        except scope_mod.OutOfScope as e:
            return [], [f"REFUSED: {e}"]
        if not approve:
            return [], [f"Ready to scan {host} with {', '.join(a['name'] for a in chosen)}. Re-run with --approve to start."]
        notes.append(f"Authorized target {host} (scope owner: {scope['owner'] or 'not set'}).")
    target_path = os.path.expanduser(str(target))
    for a in chosen:
        fn = runners.get(a["tool"])
        if fn is None: notes.append(f"{a['name']}: no runner for {a['tool']}"); continue
        t0 = time.time()
        try:
            got = fn(target_path if is_local(target) else target)
            for f in got: f["agents"] = [a["name"]]; f["tool"] = a["tool"]
            raw += got; notes.append(f"{a['name']} ({a['tool']}): {len(got)} finding(s) in {time.time() - t0:.1f}s")
        except tools.ToolMissing as e:
            notes.append(f"{a['name']}: {e}")
        except Exception as e:
            notes.append(f"{a['name']}: error {type(e).__name__}: {str(e)[:120]}")
        log(notes[-1])
    return dedup(raw), notes


def summarize(findings, brain=None):
    """Plain-English summary. With the local model, it writes it; without, a counted summary."""
    counts = {s: sum(f["severity"] == s for f in findings) for s in tools.SEV}
    base = ", ".join(f"{n} {s}" for s, n in counts.items() if n) or "no findings"
    if not brain or not findings: return f"Found {len(findings)} issue(s): {base}."
    top = "\n".join(f"- [{f['severity']}] {f['title']} at {f['where']}" for f in findings[:12])
    try:
        return brain("You are a security engineer writing for the owner of this code or site. In 3 short plain sentences, "
                     "say what matters most and what to fix first. Findings:\n" + top).strip() or base
    except Exception:
        return f"Found {len(findings)} issue(s): {base}."


def report(target, findings, notes, summary):
    lines = [f"# VULPHEX security report", f"_{datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC · target: `{target}`_", "",
             "## Summary", summary, "", "## Findings (most severe first)"]
    if not findings: lines.append("None.")
    for f in findings:
        lines.append(f"- **{f['severity'].upper()}** · {f['title']} · `{f['where']}` · {', '.join(f.get('agents', []))}")
    lines += ["", "## What each agent did"] + [f"- {n}" for n in notes]
    lines += ["", "_Defensive use only: VULPHEX scans your own code, and only the network targets listed in scope.json._"]
    return "\n".join(lines) + "\n"


def remember(target, findings, path=None):
    """Shared evidence memory: every run's findings appended, so agents and later runs can compare."""
    p = path or os.path.join(ROOT, "state", "security-evidence.jsonl"); os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "a") as fh:
        for f in findings: fh.write(json.dumps({"at": datetime.now(timezone.utc).isoformat(), "target": str(target), **f}) + "\n")


def main(argv=None):
    ap = argparse.ArgumentParser(description="VULPHEX Security: defensive AI security team (authorized targets only)")
    ap.add_argument("target", help="a folder you own, or a host/URL listed in security/scope.json")
    ap.add_argument("--approve", action="store_true", help="allow active (network) scans of an in-scope target")
    ap.add_argument("--no-brain", action="store_true", help="skip the local AI summary (no model download)")
    ap.add_argument("--out", default=os.path.join(ROOT, "security-report.md"))
    a = ap.parse_args(argv)
    findings, notes = run(a.target, approve=a.approve)
    brain = None
    if not a.no_brain and findings:
        try:
            import local_llm
            os.environ.setdefault("LOCAL_MODEL", "Goekdeniz-Guelmez/Josiefied-Qwen2.5-1.5B-Instruct-abliterated-v1")
            brain, why = local_llm.load(max_new_tokens=160)
            if brain is None: notes.append(f"brain off: {why}")
        except Exception as e: notes.append(f"brain off: {e}")
    text