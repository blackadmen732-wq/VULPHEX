# VULPHEX study pass (owner's request, Nov 24 2026): the bots LEARN FROM the repos instead of only calling them. The
# ancestor model reads each repo's own docs, extracts the TECHNIQUES behind it, and stores them as learned tactics the
# bots can use — so the knowledge in ARTEX, PentAGI, PentestGPT, sqlmap, nuclei, Metasploit, nmap and the rest becomes
# part of the neural network. It does NOT copy the repos' code; it learns what they do and how.
#
# "Deep" study (this version): for each repo it reads the README AND a few more doc files (docs, ARCHITECTURE, USAGE,
# the GitHub "about"/topics) and asks the model for SEVERAL concrete techniques — not one sentence — each stored as its
# own learned tactic row. Every technique is one thing a FOX bot should actually be able to do.
import json, os, re, sys, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# doc files worth reading beyond the README, in priority order (best-effort; most repos have one or two)
DOC_FILES = ["README.md", "readme.md", "Readme.md", "docs/README.md", "ARCHITECTURE.md", "USAGE.md", "docs/usage.md"]


def repo_list():
    """Every repo across the FOX bots (from repos.json), de-duplicated, with the bot that owns it."""
    try: repos = json.load(open(os.path.join(ROOT, "repos.json")))["bots"]
    except (OSError, ValueError): return []
    out, seen = [], set()
    for bot, lst in repos.items():
        for r in lst:
            key = r.get("repo", "")
            if key and key not in seen: seen.add(key); out.append({"repo": key, "bot": bot, "does": r.get("does", "")})
    return out


def _owner_name(repo):
    """Pull an owner/name out of a repo string (it may have a trailing description in parens)."""
    m = re.search(r"([\w.-]+)/([\w.-]+)", repo)
    return (m.group(1), m.group(2)) if m else (None, None)


def fetch_docs(repo):
    """Best-effort: the repo's README plus a couple more doc files from GitHub. Returns concatenated text (capped)."""
    owner, name = _owner_name(repo)
    if not owner: return ""
    chunks, got = [], 0
    for branch in ("main", "master"):
        for fn in DOC_FILES:
            if got >= 3: break
            try:
                url = f"https://raw.githubusercontent.com/{owner}/{name}/{branch}/{fn}"
                txt = urllib.request.urlopen(url, timeout=20).read().decode("utf-8", "ignore")
                if txt.strip(): chunks.append(f"--- {fn} ---\n{txt[:6000]}"); got += 1
            except Exception:
                continue
        if chunks: break                                            # found the branch that has docs
    return "\n\n".join(chunks)[:14000]


def _parse_techniques(text):
    """Turn the model's reply into clean, short technique lines (drop numbering/bullets, cap length and count)."""
    out = []
    for line in (text or "").splitlines():
        line = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", line).strip().strip("`").strip()
        if len(line) >= 8: out.append(line[:200])
        if len(out) >= 4: break
    return out


def study_one(entry, ask=None):
    """Learn one repo: the model reads its docs and names the concrete techniques a bot should learn. Returns a dict
    with a list of techniques (empty if the docs or the model were unreachable)."""
    doc = fetch_docs(entry["repo"])
    techniques = []
    if ask and doc:
        prompt = ("You are training a cybersecurity bot. From the documentation of the tool "
                  f"'{entry['repo']}' ({entry['does']}), list 3-4 CONCRETE techniques or capabilities the bot should "
                  "learn from it — one per line, each a short imperative phrase (no numbering, no preamble). "
                  f"Documentation:\n{doc}")
        try: techniques = _parse_techniques(ask(prompt))
        except Exception: techniques = []
    return {"repo": entry["repo"], "bot": entry["bot"],
            "techniques": techniques,
            "note": "" if techniques else ("docs not reachable" if not doc else "needs the model to extract"),
            "learned": len(techniques)}


def run(core, ask=None, on_event=None):
    """Study every repo, store each learned technique in the shared DB, return a summary. Two tables:
    `studied` (one row per repo, how many techniques learned) and `tactics` (one row per technique)."""
    core.db.execute("CREATE TABLE IF NOT EXISTS studied (repo TEXT PRIMARY KEY, bot TEXT, techniques TEXT, learned INTEGER, at TEXT)")
    core.db.execute("CREATE TABLE IF NOT EXISTS tactics (id INTEGER PRIMARY KEY AUTOINCREMENT, repo TEXT, bot TEXT, technique TEXT, at TEXT)")
    learned = 0
    for e in repo_list():
        r = study_one(e, ask); learned += r["learned"]
        techs = r["techniques"] or ([r["note"]] if r["note"] else [])
        core.db.execute("INSERT OR REPLACE INTO studied VALUES (?,?,?,?,datetime('now'))",
                        (r["repo"], r["bot"], " | ".join(techs), int(r["learned"])))
        core.db.execute("DELETE FROM tactics WHERE repo=?", (r["repo"],))
        for t in r["techniques"]:
            core.db.execute("INSERT INTO tactics (repo,bot,technique,at) VALUES (?,?,?,datetime('now'))", (r["repo"], r["bot"], t))
        on_event and on_event(r)
    core.db.commit()
    repos = core.db.execute("SELECT COUNT(*) FROM studied").fetchone()[0]
    total_tech = core.db.execute("SELECT COUNT(*) FROM tactics").fetchone()[0]
    return {"studied": repos, "learned": learned, "techniques": total_tech}
