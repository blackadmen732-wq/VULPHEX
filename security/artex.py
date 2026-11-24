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
