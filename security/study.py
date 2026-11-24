# VULPHEX study pass (owner's request, Nov 24 2026): the bots LEARN FROM the repos instead of only calling them. The
# ancestor model reads each repo's own docs, extracts the technique behind it, and stores it as a learned tactic the
# bots can use — so the knowledge in ARTEX, PentAGI, PentestGPT, sqlmap, nuclei, Metasploit, nmap and the rest becomes
# part of the neural network. It does NOT copy the repos' code; it learns what they do and how.
import json, os, re, sys, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def repo_list():
    """Every repo across the FOX bots (from repos.json), de-duplicated, with the bot that owns it."""
    try: repos = json.load(open(os.path.join(ROOT, "repos.json")))["bots"]
    except (OSError, ValueError): return []
    out, seen = [], set()
    for bot, lst in repos.items():
        for r in lst:
            name = r.get("repo", "").split(" ")[0].split("/")[-1] if "/" in r.get("repo", "") else r.get("repo", "")
            key = r.get("repo", "")
            if key and key not in seen: seen.add(key); out.append({"repo": r["repo"], "bot": bot, "does": r.get("does", "")})
    return out


def fetch_readme(repo):
    """Best-effort: the repo's README from GitHub (for a owner/name repo). Returns text or ''."""
    m = re.search(r"([\w.-]+)/([\w.-]+)", repo)
    if not m: return ""
    owner, name = m.group(1), m.group(2)
    for branch in ("main", "master"):
        for fn in ("README.md", "readme.md", "Readme.md"):
            try:
                url = f"https://raw.githubusercontent.com/{owner}/{name}/{branch}/{fn}"
                return urllib.request.urlopen(url, timeout=20).read().decode("utf-8", "ignore")[:8000]
            except Exception:
                continue
    return ""


def study_one(entry, ask=None):
    """Learn one repo: the model reads its docs and names the technique. Without a model, records it as 'to study'."""
    doc = fetch_readme(entry["repo"])
    if ask and doc:
        prompt = (f"This is the README of the security tool '{entry['repo']}' ({entry['does']}). In ONE sentence, name the "
                  f"core technique it uses that a security bot should learn. README:\n{doc[:4000]}")
        try: technique = (ask(prompt) or "").strip().split("\n")[0][:220]
        except Exception: technique = ""
    else:
        technique = ""
    return {"repo": entry["repo"], "bot": entry["bot"], "technique": technique or f"({'docs not reachable' if not doc else 'needs the model to extract'})",
            "learned": bool(technique)}


def run(core, ask=None, on_event=None):
    """Study every repo, store what was learned in the shared DB, return a summary."""
    core.db.execute("CREATE TABLE IF NOT EXISTS studied (repo TEXT PRIMARY KEY, bot TEXT, technique TEXT, learned INTEGER, at TEXT)")
    learned = 0
    for e in repo_list():
        r = study_one(e, ask); learned += r["learned"]
        core.db.execute("INSERT OR REPLACE INTO studied VALUES (?,?,?,?,datetime('now'))",
                        (r["repo"], r["bot"], r["technique"], int(r["learned"])))
        on_event and on_event(r)
    core.db.commit()
    total = core.db.execute("SELECT COUNT(*) FROM studied").fetchone()[0]
    return {"studied": total, "learned": learned}
