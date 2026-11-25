# VULPHEX study pass (owner's request, Nov 24 2026): the bots LEARN FROM the repos instead of only calling them. The
# ancestor model reads each repo's own docs, extracts the TECHNIQUES behind it, and stores them as learned tactics the
# bots can use — so the knowledge in ARTEX, PentAGI, PentestGPT, sqlmap, nuclei, Metasploit, nmap and the rest becomes
# part of the neural network. It does NOT copy the repos' code; it learns what they do and how.
#
# "Deep" study (this version): for each repo it reads the README AND a few more doc files (docs, ARCHITECTURE, USAGE,
# the GitHub "about"/topics) and asks the model for SEVERAL concrete techniques — not one sentence — each stored as its
# own learned tactic row. Every technique is one thing a FOX bot should actually be able to do.
import json, os, re, shutil, subprocess, sys, tempfile, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# doc files worth reading beyond the README, in priority order (best-effort; most repos have one or two)
DOC_FILES = ["README.md", "readme.md", "Readme.md", "docs/README.md", "ARCHITECTURE.md", "USAGE.md", "docs/usage.md"]


def _code_candidates(name):
    """Likely entry-point source files to read so the bot understands the actual CODE (not just the docs). Covers
    Python, Go, JS/TS and a few others — best-effort across the many languages these repos are written in."""
    n = name.replace("-", "_")
    return [  # python
            f"{name}.py", f"{n}.py", "main.py", "cli.py", "app.py", "__main__.py", "run.py",
            f"src/{name}.py", f"src/{n}.py", f"{name}/__main__.py", f"{n}/cli.py", "core.py", "engine.py",
            # go
            "main.go", "cmd/main.go", f"cmd/{name}/main.go", f"cmd/{n}/main.go", f"{name}.go",
            # js / ts
            "index.js", "src/index.js", "src/index.ts", "cli.js", "bin/cli.js",
            # others
            "main.rb", "lib/main.rb", "src/main.rs", "main.c"]


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


def fetch_code(repo):
    """Best-effort: read a couple of the repo's real SOURCE files from GitHub so the bot learns from the code itself,
    not only the prose. Returns concatenated snippets (capped), or ''."""
    owner, name = _owner_name(repo)
    if not owner: return ""
    chunks, got = [], 0
    for branch in ("main", "master"):
        for fn in _code_candidates(name):
            if got >= 2: break
            try:
                url = f"https://raw.githubusercontent.com/{owner}/{name}/{branch}/{fn}"
                txt = urllib.request.urlopen(url, timeout=15).read().decode("utf-8", "ignore")
                if txt.strip(): chunks.append(f"--- {fn} ---\n{txt[:5000]}"); got += 1
            except Exception:
                continue
        if chunks: break
    return "\n\n".join(chunks)[:10000]


_CODE_EXT = (".py", ".go", ".js", ".ts", ".rb", ".rs", ".c", ".cpp", ".java", ".php", ".sh")
_CLONE_SKIP = {".git", "node_modules", "vendor", "dist", "build", "test", "tests", "docs", "examples", "__pycache__"}


def clone_source(repo, max_files=5, max_bytes=18000, timeout=150):
    """Actually CLONE the repo (shallow) and read several real source files, so the bot learns from the whole code —
    not just the entry file. Cleans up the clone afterward. Returns concatenated snippets, or '' on failure."""
    owner, name = _owner_name(repo)
    if not owner: return ""
    tmp = tempfile.mkdtemp(prefix="vulphex_clone_")
    root = os.path.join(tmp, "r")
    try:
        env = {**os.environ, "GIT_LFS_SKIP_SMUDGE": "1", "GIT_TERMINAL_PROMPT": "0"}
        r = subprocess.run(["git", "clone", "--depth", "1", f"https://github.com/{owner}/{name}", root],
                           capture_output=True, text=True, timeout=timeout, env=env)
        if r.returncode != 0 or not os.path.isdir(root): return ""
        chunks, got, total = [], 0, 0
        for dp, dirs, names in os.walk(root):
            dirs[:] = [d for d in dirs if d not in _CLONE_SKIP]
            for n in sorted(names):
                if got >= max_files or total >= max_bytes: break
                if n.endswith(_CODE_EXT):
                    p = os.path.join(dp, n)
                    try:
                        if os.path.getsize(p) > 200000: continue
                        t = open(p, errors="ignore").read()[:5000]
                        if t.strip(): chunks.append(f"--- {os.path.relpath(p, root)} ---\n{t}"); got += 1; total += len(t)
                    except Exception:
                        continue
            if got >= max_files or total >= max_bytes: break
        return "\n\n".join(chunks)[:max_bytes]
    except Exception:
        return ""
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def study_one(entry, ask=None):
    """Learn one repo: the model reads its docs AND real source code, then names the concrete techniques a bot should
    learn — including how the code does it. Returns a dict with a list of techniques."""
    doc = fetch_docs(entry["repo"])
    code = fetch_code(entry["repo"])
    techniques = []
    material = doc + (("\n\nSOURCE CODE:\n" + code) if code else "")
    if ask and material.strip():
        seen_code = "and its SOURCE CODE " if code else ""
        prompt = ("You are training a cybersecurity bot to REPRODUCE a tool's capability. From the documentation "
                  f"{seen_code}of '{entry['repo']}' ({entry['does']}), list 3-4 CONCRETE techniques the bot should learn "
                  "— each a short imperative phrase describing HOW it works (no numbering, no preamble). "
                  f"Material:\n{material}")
        try: techniques = _parse_techniques(ask(prompt))
        except Exception: techniques = []
    return {"repo": entry["repo"], "bot": entry["bot"], "techniques": techniques,
            "read_code": bool(code),
            "note": "" if techniques else ("sources not reachable" if not material.strip() else "needs the model to extract"),
            "learned": len(techniques)}


def study_repo(core, ask, query):
    """Study just the repo(s) whose name matches `query` (e.g. 'sqlmap', 'artex'). Returns a short summary."""
    q = (query or "").strip().lower()
    hits = [e for e in repo_list() if q and q in e["repo"].lower()]
    if not hits: return {"matched": 0, "repo": None, "techniques": 0}
    core.db.execute("CREATE TABLE IF NOT EXISTS studied (repo TEXT PRIMARY KEY, bot TEXT, techniques TEXT, learned INTEGER, at TEXT)")
    core.db.execute("CREATE TABLE IF NOT EXISTS tactics (id INTEGER PRIMARY KEY AUTOINCREMENT, repo TEXT, bot TEXT, technique TEXT, at TEXT)")
    total = 0
    for e in hits:
        r = study_one(e, ask); total += r["learned"]
        core.db.execute("INSERT OR REPLACE INTO studied VALUES (?,?,?,?,datetime('now'))",
                        (r["repo"], r["bot"], " | ".join(r["techniques"]), int(r["learned"])))
        core.db.execute("DELETE FROM tactics WHERE repo=?", (r["repo"],))
        for t in r["techniques"]:
            core.db.execute("INSERT INTO tactics (repo,bot,technique,at) VALUES (?,?,?,datetime('now'))", (r["repo"], r["bot"], t))
    core.db.commit()
    return {"matched": len(hits), "repo": hits[0]["repo"], "techniques": total}


def _extract_code(text):
    """Pull the Python out of a model reply (strip ``` fences and any prose around them)."""
    t = (text or "").strip()
    if "```" in t:
        parts = t.split("```")
        for i in range(1, len(parts), 2):
            block = parts[i]
            if block.startswith("python"): block = block[6:]
            elif block.startswith("py"): block = block[2:]
            if block.strip(): return block.strip()
    return t


def reproduce(core, name, ask):
    """Teach a bot to DO what a repo does: read the repo's docs + source, have the model write a self-contained Python
    adapter that reproduces its core technique (VULPHEX tools.py style), and save it for review. Returns a summary.
    The generated code is SAVED, never auto-run — the owner reviews it first."""
    q = (name or "").strip().lower()
    hits = [e for e in repo_list() if q and q in e["repo"].lower()]
    if not hits: return {"ok": False, "repo": None, "msg": f"no mapped repo matches '{name}'"}
    e = hits[0]
    doc = fetch_docs(e["repo"])
    code = clone_source(e["repo"]) or fetch_code(e["repo"])        # clone the real repo for the full code; fall back to HTTP
    if not (doc or code): return {"ok": False, "repo": e["repo"], "msg": "could not read the repo's docs or source"}
    prompt = ("You are a security engineer. Reproduce the CORE technique of the tool "
              f"'{e['repo']}' ({e['does']}) as a VULPHEX adapter written in Python (stdlib only). "
              "Your ENTIRE answer must be Python code that STARTS with `def run(target):` and returns a list of finding "
              "dicts, each {\"severity\", \"title\", \"where\", \"detail\"}. No prose, no markdown, no other functions "
              f"before it.\n\nDOCS:\n{doc[:3500]}\n\nSOURCE (real code from the repo):\n{code[:5000]}")
    out = ""
    for _ in range(2):                                            # one retry if the model drifts off-format
        try: out = ask(prompt) or ""
        except Exception as ex: return {"ok": False, "repo": e["repo"], "msg": f"model error: {ex}"}
        if "def run" in _extract_code(out): break
    src = _extract_code(out)
    if "def run" not in src: return {"ok": False, "repo": e["repo"], "msg": "the model did not return a usable adapter"}
    short = e["repo"].split("/")[-1].split(" ")[0]
    outdir = os.path.join(HERE, "reproduced"); os.makedirs(outdir, exist_ok=True)
    path = os.path.join(outdir, f"{short}.py")
    header = f"# VULPHEX reproduction of {e['repo']} ({e['does']}) for {e['bot']}.\n# Model-written from the repo's docs+source. REVIEW before use; do not run against anything you don't own.\n"
    with open(path, "w", encoding="utf-8") as f: f.write(header + src + "\n")
    core.db.execute("CREATE TABLE IF NOT EXISTS reproduced (repo TEXT PRIMARY KEY, bot TEXT, file TEXT, lines INTEGER, at TEXT)")
    core.db.execute("INSERT OR REPLACE INTO reproduced VALUES (?,?,?,?,datetime('now'))",
                    (e["repo"], e["bot"], path, len(src.splitlines())))
    core.db.commit()
    return {"ok": True, "repo": e["repo"], "bot": e["bot"], "file": path, "lines": len(src.splitlines())}


def learn_all(core, ask=None, on_event=None):
    """The daily pipeline: for EVERY mapped repo, clone it, learn its code, and reproduce its core technique as a bot
    adapter — so the bots can do what all 31 repos do. Returns a summary. `ask` writes the adapters (code_reasoning)."""
    repos = repo_list()
    done = made = 0
    for e in repos:
        name = e["repo"].split("/")[-1].split(" ")[0]
        try:
            r = reproduce(core, name, ask) if ask else {"ok": False}
            made += 1 if r.get("ok") else 0
        except Exception:
            r = {"ok": False}
        done += 1
        on_event and on_event(name, done, len(repos), r.get("ok", False))
    return {"repos": done, "adapters": made}


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
