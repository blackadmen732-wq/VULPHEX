#!/usr/bin/env python3
# VULPHEX Security — the command line for the nine FOX bots. The real work is in core.py (the command core).
#
# SAFETY (owner's rule and the law): VULPHEX only scans what you own or are authorized to test. Local code/secret/
# dependency audits read your own files. Active (network) bots run ONLY on a target in security/scope.json, and only
# with --approve. Nothing exploits, evades defenses, or touches a third party. See CLAUDE.md.
#
# Usage:
#   python3 security/artex.py code .                         # audit a folder you own (local FOX bots)
#   python3 security/artex.py mission your-site.com --approve  # full team, only if your-site.com is in scope.json
#   python3 security/artex.py plan "check my web app and code" your-site.com --approve   # AI planner picks the bots
#   python3 security/artex.py findings                       # show the shared evidence database
import argparse, json, os, re, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import core as C

BLUE_LOCAL = {"FOX AUDITOR", "FOX BASTION", "FOX ATLAS", "FOX PROOF", "FOX FORGE", "FOX WATCH"}


def plan(core, mission):
    """Let the cheap model pick FOX bots from a plain-English mission; fall back to all of them."""
    names = {b["name"] for b in core.team}
    prompt = ("You are a security mission planner for the FOX team: " +
              "; ".join(f"{b['name']}={b['role']}" for b in core.team) +
              f". Mission: {mission}. Reply ONLY a comma-separated list of the FOX bot names that fit.")
    text = core.router.ask("plan", prompt) or ""
    picked = {n for n in names if re.search(re.escape(n), text, re.I)}
    return (picked or names), ("AI planner" if picked else "all bots")


def main(argv=None):
    ap = argparse.ArgumentParser(description="VULPHEX Security: nine FOX bots, one command core (authorized targets only)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("code", help="local FOX bots on a folder/file you own"); c.add_argument("target")
    m = sub.add_parser("mission", help="the full FOX team on an authorized target"); m.add_argument("target"); m.add_argument("--approve", action="store_true")
    p = sub.add_parser("plan", help="AI planner picks the bots for a mission"); p.add_argument("mission"); p.add_argument("target"); p.add_argument("--approve", action="store_true")
    sub.add_parser("findings", help="print the shared evidence database")
    sub.add_parser("audit", help="print the audit log of every task VULPHEX ran")
    sub.add_parser("bots", help="list the twelve FOX bots")
    imp = sub.add_parser("improve", help="VULPHEX audits code, then FOX FORGE fixes the top issue with Claude's hands (learns from it)")
    imp.add_argument("path", nargs="?", default="."); imp.add_argument("--bot", default="FOX FORGE")
    sub.add_parser("coder-stats", help="how the coding bots are doing (success rate, learning)")
    sub.add_parser("study", help="the bots study every repo and learn its technique into the neural network")
    ag = sub.add_parser("agent", help="give a bot Claude Code + the uncensored brain to do a task")
    ag.add_argument("bot"); ag.add_argument("mission"); ag.add_argument("--cwd", default=".")
    a = ap.parse_args(argv)
    scope = json.load(open(os.path.join(HERE, "scope.json")))

    if a.cmd == "bots":
        core = C.Core(scope=scope)
        for b in core.team: print(f"  {b['side'].upper():4} {b['name']:14} {b['role']}")
        core.close(); return
    if a.cmd == "audit":
        core = C.Core(scope=scope)
        rows = core.db.execute("SELECT bot,capability,tool,target,risk,in_scope,at FROM audit ORDER BY id").fetchall()
        print(f"{len(rows)} audited task(s):")
        for r in rows: print(f"  {r['at']}  {r['bot']:14} {r['tool']:10} {r['risk']:11} {'in-scope' if r['in_scope'] else 'OUT-OF-SCOPE'}  {r['target']}")
        core.close(); return
    if a.cmd == "study":
        import study as ST
        core = C.Core(scope=scope)
        ask = None
        try:
            if core.router.ask("study", "ping", max_new_tokens=3) is not None:
                ask = lambda q: core.router.ask("study", q, max_new_tokens=60)
        except Exception: pass
        print("Studying the repos" + ("" if ask else " (no model loaded — records them to study; run on Kaggle with the brain to learn)") + " ...")
        res = ST.run(core, ask=ask, on_event=lambda r: print(f"  · {r['bot']:12} learned from {r['repo'][:40]}: {r['technique'][:70]}"))
        core.close(); print(f"\nStudied {res['studied']} repos, learned {res['learned']} techniques into the brain."); return
    if a.cmd == "coder-stats":
        core = C.Core(scope=scope)
        rows = core.db.execute("SELECT bot, COUNT(*) n, SUM(ok) ok, AVG(steps) st FROM coder GROUP BY bot").fetchall()
        if not rows: print("No coding runs yet. Try:  python3 security/artex.py improve .")
        for r in rows: print(f"  {r['bot']:14} {r['ok'] or 0}/{r['n']} fixes landed, avg {r['st']:.0f} steps")
        core.close(); return
    if a.cmd == "improve":
        core = C.Core(scope=scope)
        print(f"[FOX team] auditing {a.path} ...")
        core.mission(a.path, want={"FOX AUDITOR", "FOX BASTION", "FOX PROOF"})
        top = sorted(core.findings("verified") or core.findings(), key=lambda f: {"critical":0,"high":1,"medium":2,"low":3,"info":4}.get(f["severity"],9))
        if not top: print("Nothing to fix. Clean."); core.close(); return
        f = top[0]; print(f"[{a.bot}] fixing: [{f['severity'].upper()}] {f['title']} at {f['place']}\n")
        mission = f"Fix this security finding: {f['title']} at {f['place']}. {f.get('detail','')}. Make the smallest safe change and verify it."
        res = core.code(a.bot, mission, cwd=a.path, on_event=lambda k,v: print(f"  · {v if k=='say' else v.get('tool','')+' '+v.get('input','')}"[:140]))
        core.close(); print("\n" + res["summary"]); return
    if a.cmd == "agent":
        core = C.Core(scope=scope)
        name = next((b["name"] for b in core.team if b["name"].upper() == a.bot.upper() or a.bot.lower() in b["name"].lower()), None)
        if not name: core.close(); sys.exit("No such bot. Try: " + ", ".join(b["name"] for b in core.team))
        print(f"[{name}] working with Claude Code + the uncensored brain...\n")
        res = core.code(name, a.mission, cwd=a.cwd, on_event=lambda k, v: print(f"  · {v if k=='say' else v.get('tool','')+' '+v.get('input','')}"[:140]))
        core.close(); print("\n" + res["summary"]); return
    if a.cmd == "findings":
        core = C.Core(scope=scope); items = core.findings()
        print(f"{len(items)} findings in the evidence database:")
        for x in items: print(f"  [{x['severity'].upper():8}] {x['status']:12} {x['title'][:60]}  {x['place']}  ({x['bot']})")
        core.close(); return

    core = C.Core(scope=scope, approve=getattr(a, "approve", False))
    if a.cmd == "code":
        if not os.path.exists(a.target): sys.exit(f"{a.target} is not a local path. Use `mission` for a host.")
        body, _ = core.mission(a.target, want=BLUE_LOCAL)
    elif a.cmd == "mission":
        if not core.policy.host_in_scope(a.target):
            print(f"[audit] {a.target} is outside the scope you declared in security/scope.json. VULPHEX will run the full team against it and log every action — you are responsible for being authorized to test it.\n")
        body, _ = core.mission(a.target, want=None)   # the whole team: blue + red
    else:
        want, how = plan(core, a.mission)
        body, _ = core.mission(a.target, want)
        body = f"- planner: {how} chose {', '.join(sorted(want))}\n" + body
    core.close(); print(body)


if __name__ == "__main__":
    main()
