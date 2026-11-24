#!/usr/bin/env python3
# VULPHEX Security: nine AI agents over real scanning tools, with a planner, shared evidence, dedup, a human-approval
# gate and an auto report writer. The brain is the same uncensored model the trading bots use (no API, no cost).
#
# SAFETY (owner's rule and the law): VULPHEX only scans what you own or are authorized to test.
#   - local agents (code audit, secret hunt, dependency audit, promptfoo) read files you point them at: always allowed.
#   - active agents (web scan, nuclei, recon, garak, pyrit) reach a target over the network. They run ONLY when the
#     target matches security/scope.json AND you approve the run. Out of scope = refused, every time.
# It never exploits, never evades defenses, never touches a third party. It is for finding and fixing holes in your
# own systems before someone else does.
#
# Usage:
#   python3 security/artex.py code .                      # audit a local folder (all local agents)
#   python3 security/artex.py scan example.com --approve  # active scan, only if example.com is in scope.json
#   python3 security/artex.py plan "check my web app and its code"   # the AI planner picks agents (still gated)
import argparse, fnmatch, hashlib, ipaddress, json, os, re, socket, sys, time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(ROOT, "engine"))
import tools as T

SEV_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


def load(name, default):
    try: return json.load(open(os.path.join(HERE, name)))
    except (OSError, ValueError): return default


TEAM = load("team.json", {"agents": []})["agents"]
BYNAME = {a["name"].lower(): a for a in TEAM}


# ---------------------------------------------------------------- the authorization gate
def _is_private(host):
    try: return ipaddress.ip_address(host).is_private
    except ValueError: return host in ("localhost",) or host.endswith(".local")


def in_scope(target, scope=None):
    """True only for a target you are authorized to test. Local paths are always yours; hosts must match scope.json."""
    scope = scope if scope is not None else load("scope.json", {})
    if os.path.exists(target): return True                                   # a local file/folder you own
    host = re.sub(r"^\w+://", "", target).split("/")[0].split(":")[0]
    if _is_private(host) and not scope.get("allow_private_ranges"): return False
    for pat in scope.get("hosts", []):
        if fnmatch.fnmatch(host, pat): return True
    return False


class NotAuthorized(Exception):
    pass


# ---------------------------------------------------------------- evidence store (shared memory)
def key(f, kind):
    return hashlib.sha1(f"{kind}|{f['title']}|{f['where']}".encode()).hexdigest()[:12]


def merge(store, new, agent):
    """Add findings, skip duplicates (same kind+title+place). Returns how many were new."""
    added = 0
    for f in new:
        k = key(f, agent["finds"])
        if k in store: continue
        store[k] = {**f, "id": k, "agent": agent["name"], "tool": agent["tool"]}; added += 1
    return added


# ---------------------------------------------------------------- run one agent
def run_agent(agent, target, store, scope, approved, log):
    runner = T.RUNNERS.get(agent["tool"])
    if runner is None: log.append(f"  - {agent['name']}: no runner for {agent['tool']}"); return
    if agent["kind"] == "active":
        if not in_scope(target, scope):
            log.append(f"  - {agent['name']} ({agent['role']}): REFUSED — {target} is not in your authorized scope (edit security/scope.json)"); return
        if not approved:
            log.append(f"  - {agent['name']} ({agent['role']}): needs your approval for an active scan (pass --approve)"); return
    try:
        found = runner(target) or []
        n = merge(store, found, agent)
        log.append(f"  - {agent['name']} ({agent['role']}, {agent['tool']}): {len(found)} findings, {n} new")
    except T.ToolMissing as e:
        log.append(f"  - {agent['name']}: {e}")
    except Exception as e:
        log.append(f"  - {agent['name']}: error {type(e).__name__}: {str(e)[:120]}")


# ---------------------------------------------------------------- the planner (optional AI brain)
def plan_agents(mission, want_active):
    """Pick which agents to run from a plain-English mission. Uses the local model if available, else keywords."""
    local = [a for a in TEAM if a["kind"] == "local"]
    active = [a for a in TEAM if a["kind"] == "active"]
    try:
        import local_llm
        gen, why = local_llm.load(os.environ.get("COACH_MODEL"), max_new_tokens=40)
        if gen:
            names = ", ".join(a["name"] for a in TEAM)
            ask = (f"You are a security mission planner. Agents: {names}. "
                   f"For each, roles: " + "; ".join(f"{a['name']}={a['role']}" for a in TEAM) +
                   f". Mission: {mission}. Reply ONLY a comma-separated list of the agent names that fit.")
            text = gen(ask) or ""
            picked = [a for a in TEAM if re.search(rf"\b{a['name']}\b", text, re.I)]
            if picked: return [a for a in picked if want_active or a["kind"] == "local"], f"AI planner ({gen.model_name})"
    except Exception:
        pass
    return (local + active) if want_active else local, "keyword planner"


# ---------------------------------------------------------------- report
def write_report(mission, target, store, log, planner=""):
    items = sorted(store.values(), key=lambda f: (SEV_RANK.get(f["severity"], 9), f["agent"]))
    counts = {s: sum(1 for f in items if f["severity"] == s) for s in T.SEV}
    now = datetime.now(timezone.utc)
    out = [f"## {now:%Y-%m-%d %H:%M} UTC", f"- mission: {mission}", f"- target: {target}"]
    if planner: out.append(f"- planner: {planner}")
    out.append("- findings: " + ", ".join(f"{counts[s]} {s}" for s in T.SEV if counts[s]) or "- findings: none")
    out += ["", "### Agents"] + log
    if items:
        out += ["", "### Findings (most serious first)"]
        for f in items:
            out.append(f"- **[{f['severity'].upper()}]** {f['title']} — `{f['where']}`  _(found by {f['agent']} / {f['tool']})_")
            if f.get("detail"): out.append(f"  - {f['detail']}")
    else:
        out += ["", "No findings. (Install more tools, or widen the scan, for deeper coverage.)"]
    body = "\n".join(out)
    rep = os.path.join(ROOT, "security-report.md"); old = open(rep).read() if os.path.exists(rep) else "# VULPHEX security report\n"
    head, _, rest = old.partition("\n"); open(rep, "w").write(head + "\n\n" + body + "\n" + rest)
    return body, counts


def run(agents, mission, target, approve=False):
    scope = load("scope.json", {})
    store, log = {}, []
    for a in agents:
        run_agent(a, target, store, scope, approve, log)
    return write_report(mission, target, store, log)


def main(argv=None):
    ap = argparse.ArgumentParser(description="VULPHEX Security: 9 AI agents over real scanners (authorized targets only)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("code", help="run the local agents on a folder/file you own"); c.add_argument("target")
    s = sub.add_parser("scan", help="run active agents on an authorized host"); s.add_argument("target"); s.add_argument("--approve", action="store_true")
    p = sub.add_parser("plan", help="let the AI planner pick agents from a plain-English mission")
    p.add_argument("mission"); p.add_argument("target"); p.add_argument("--approve", action="store_true")
    one = sub.add_parser("agent", help="run a single agent by name"); one.add_argument("name"); one.add_argument("target"); one.add_argument("--approve", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "code":
        agents, mission = [x for x in TEAM if x["kind"] == "local"], f"audit local {a.target}"
        body, _ = run(agents, mission, a.target)
    elif a.cmd == "scan":
        if not in_scope(a.target): sys.exit(f"Refused: {a.target} is not in your authorized scope. Add it to security/scope.json only if you own it or have written permission.")
        agents, mission = [x for x in TEAM if x["kind"] == "active"], f"active scan of {a.target}"
        body, _ = run(agents, mission, a.target, approve=a.approve)
    elif a.cmd == "plan":
        agents, planner = plan_agents(a.mission, want_active=in_scope(a.target))
        store, log = {}, []; scope = load("scope.json", {})
        for ag in agents: run_agent(ag, a.target, store, scope, a.approve, log)
        body, _ = write_report(a.mission, a.target, store, log, planner)
    else:
        ag = BYNAME.get(a.name.lower())
        if not ag: sys.exit(f"No agent named {a.name}. Agents: " + ", ".join(x['name'] for x in TEAM))
        body, _ = run([ag], f"{ag['name']} on {a.target}", a.target, approve=a.approve)
    print(body)


if __name__ == "__main__":
    main()
