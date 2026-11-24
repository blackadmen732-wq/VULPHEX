# VULPHEX security tools: one thin wrapper per real scanner. Each returns a list of findings in one shape:
#   {"severity": critical|high|medium|low|info, "title": str, "where": "file:line" or "host/url", "detail": str}
# A wrapper shells out to the real tool when it's installed and parses its JSON; if the tool is missing it says so
# (except the two pure-Python fallbacks, which always work). Nothing here attacks anything: local tools read your
# files; active tools are gated by security/scope.py before they are ever called.
import json, os, re, shutil, subprocess

SEV = ("critical", "high", "medium", "low", "info")


def _run(cmd, timeout=1800, **kw):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, **kw)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "timed out"
    except FileNotFoundError:
        return -2, "", "not installed"


def have(tool):
    return shutil.which(tool) is not None


class ToolMissing(Exception):
    def __init__(self, tool, how): super().__init__(f"{tool} is not installed. {how}"); self.tool = tool


# ---------------------------------------------------------------- built-in code scanner (no install needed)
_CODE_PATTERNS = [
    ("high",   "SQL built by string concatenation", re.compile(r"(?i)(execute|cursor\.execute|query)\s*\(.*['\"]\s*\+\s*")),
    ("high",   "Command injection via os.system/popen", re.compile(r"(?i)\b(os\.system|os\.popen|subprocess\.(call|run|Popen))\s*\(.*\+")),
    ("high",   "Dangerous eval/exec on input", re.compile(r"(?i)\b(eval|exec)\s*\(")),
    ("high",   "Insecure deserialization (pickle/yaml.load)", re.compile(r"(?i)\b(pickle\.loads?|yaml\.load)\s*\(")),
    ("medium", "Shell=True in subprocess", re.compile(r"(?i)shell\s*=\s*True")),
    ("medium", "Weak hash (md5/sha1)", re.compile(r"(?i)hashlib\.(md5|sha1)\s*\(")),
    ("medium", "Request with TLS verification off", re.compile(r"(?i)verify\s*=\s*False")),
    ("low",    "Debug mode left on", re.compile(r"(?i)debug\s*=\s*True")),
]


def builtin_code_scan(target):
    findings = []
    files = [target] if os.path.isfile(target) else []
    if not files:
        for root, dirs, names in os.walk(target):
            dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
            for n in names:
                if n.endswith((".py", ".js", ".ts", ".php", ".rb", ".java", ".go", ".sh")): files.append(os.path.join(root, n))
    for f in files[:20000]:
        try:
            if os.path.getsize(f) > 2_000_000: continue
            for i, line in enumerate(open(f, errors="ignore"), 1):
                if len(line) > 2000: continue
                for sev, title, rx in _CODE_PATTERNS:
                    if rx.search(line):
                        findings.append({"severity": sev, "title": title, "where": f"{f}:{i}", "detail": "matched a risky code pattern (install semgrep for a deeper audit)"})
                        break
        except (OSError, UnicodeError):
            continue
    return findings


# ---------------------------------------------------------------- Cinder: source-code audit (semgrep)
def semgrep(target):
    if not have("semgrep"): return builtin_code_scan(target)          # works with no install; semgrep goes deeper
    code, out, err = _run(["semgrep", "--config", "auto", "--json", "--quiet", target])
    if not out.strip(): return builtin_code_scan(target)
    res = json.loads(out).get("results", [])
    smap = {"ERROR": "high", "WARNING": "medium", "INFO": "low"}
    findings = []
    for r in res:
        ex = r.get("extra", {})
        findings.append({"severity": smap.get(ex.get("severity", "INFO"), "low"),
                         "title": (ex.get("message") or r.get("check_id", "issue")).strip()[:160],
                         "where": f"{r.get('path')}:{r.get('start', {}).get('line', '?')}",
                         "detail": r.get("check_id", "")})
    return findings


# ---------------------------------------------------------------- Vault: secret hunting (gitleaks, else built-in)
_SECRET_PATTERNS = [
    ("high", "AWS access key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("high", "Private key block", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----")),
    ("high", "Slack token", re.compile(r"xox[baprs]-[0-9A-Za-z-]{10,}")),
    ("high", "GitHub token", re.compile(r"gh[opsu]_[0-9A-Za-z]{36}")),
    ("high", "OpenAI/Anthropic-style key", re.compile(r"sk-[A-Za-z0-9_-]{20,}")),
    ("medium", "Google API key", re.compile(r"AIza[0-9A-Za-z_-]{35}")),
    ("medium", "Generic secret assignment", re.compile(r"(?i)(password|passwd|secret|api[_-]?key|token)\s*[=:]\s*['\"][^'\"\s]{8,}['\"]")),
]
_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".mypy_cache"}


def builtin_secret_scan(target):
    findings = []
    if os.path.isfile(target): files = [target]
    else:
        files = []
        for root, dirs, names in os.walk(target):
            dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
            for n in names: files.append(os.path.join(root, n))
    for f in files[:20000]:
        try:
            if os.path.getsize(f) > 2_000_000: continue
            with open(f, "r", errors="ignore") as fh:
                for i, line in enumerate(fh, 1):
                    if len(line) > 2000: continue
                    for sev, title, rx in _SECRET_PATTERNS:
                        if rx.search(line):
                            findings.append({"severity": sev, "title": f"Possible {title}", "where": f"{f}:{i}", "detail": "matched a secret pattern"})
                            break
        except (OSError, UnicodeError):
            continue
    return findings


def gitleaks(target):
    if not have("gitleaks"):
        return builtin_secret_scan(target)                 # pure-Python fallback: always runs
    rep = os.path.join(target if os.path.isdir(target) else ".", ".vulphex-gitleaks.json")
    _run(["gitleaks", "detect", "--source", target, "--no-git", "--report-format", "json", "--report-path", rep])
    try:
        data = json.load(open(rep)); os.remove(rep)
    except (OSError, ValueError):
        return builtin_secret_scan(target)
    return [{"severity": "high", "title": f"Secret: {d.get('RuleID', 'leak')}",
             "where": f"{d.get('File')}:{d.get('StartLine', '?')}", "detail": d.get("Description", "")[:160]} for d in data]


# ---------------------------------------------------------------- Sieve: dependencies / containers (trivy, else built-in)
def trivy(target):
    if have("trivy"):
        code, out, err = _run(["trivy", "fs", "--quiet", "--format", "json", target])
        if out.strip():
            findings = []
            for res in json.loads(out).get("Results", []):
                for v in res.get("Vulnerabilities", []) or []:
                    findings.append({"severity": (v.get("Severity") or "LOW").lower(),
                                     "title": f"{v.get('PkgName')} {v.get('InstalledVersion')}: {v.get('VulnerabilityID')}",
                                     "where": res.get("Target", target), "detail": (v.get("Title") or "")[:160]})
            return findings
    return _builtin_dep_note(target)


def _builtin_dep_note(target):
    manifests = ("requirements.txt", "package.json", "pom.xml", "go.mod", "Gemfile", "Cargo.toml", "Dockerfile")
    hits = []
    for root, dirs, names in os.walk(target):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for n in names:
            if n in manifests: hits.append(os.path.join(root, n))
    if not hits: return []
    return [{"severity": "info", "title": "Install trivy for real dependency CVE scanning",
             "where": h, "detail": "found a dependency manifest; trivy would check its libraries against CVE databases"} for h in hits[:20]]


# ---------------------------------------------------------------- active tools (gated by scope before calling)
def nuclei(target):
    if not have("nuclei"): raise ToolMissing("nuclei", "see github.com/projectdiscovery/nuclei")
    code, out, err = _run(["nuclei", "-target", target, "-jsonl", "-silent"])
    findings = []
    for line in out.splitlines():
        try: j = json.loads(line)
        except ValueError: continue
        info = j.get("info", {})
        findings.append({"severity": info.get("severity", "info"), "title": info.get("name", j.get("template-id", "finding")),
                         "where": j.get("matched-at", target), "detail": (info.get("description") or "")[:160]})
    return findings


def zap(target):
    if not (have("zap.sh") or have("zap-baseline.py")): raise ToolMissing("zap", "see owasp.org/zap or run the ZAP docker image")
    bin_ = "zap-baseline.py" if have("zap-baseline.py") else "zap.sh"
    rep = ".vulphex-zap.json"
    _run([bin_, "-t", target, "-J", rep, "-I"], timeout=2400)
    try: data = json.load(open(rep)); os.remove(rep)
    except (OSError, ValueError): return []
    rmap = {"3": "high", "2": "medium", "1": "low", "0": "info"}
    findings = []
    for site in data.get("site", []):
        for al in site.get("alerts", []):
            findings.append({"severity": rmap.get(str(al.get("riskcode", "0")), "info"), "title": al.get("name", "alert"),
                             "where": site.get("@name", target), "detail": re.sub("<[^>]+>", "", al.get("desc", ""))[:160]})
    return findings


def recon(target):
    """Light, non-intrusive: which of a short list of common ports answer. No exploitation."""
    import socket
    host = re.sub(r"^https?://", "", target).split("/")[0].split(":")[0]
    ports = {21: "ftp", 22: "ssh", 23: "telnet", 25: "smtp", 80: "http", 110: "pop3", 143: "imap", 443: "https",
             445: "smb", 3306: "mysql", 3389: "rdp", 5432: "postgres", 6379: "redis", 8080: "http-alt", 9200: "elastic", 27017: "mongo"}
    findings = []
    for p, name in ports.items():
        s = socket.socket(); s.settimeout(1.5)
        try:
            if s.connect_ex((host, p)) == 0:
                sev = "high" if p in (23, 3389, 6379, 9200, 27017, 3306, 5432) else "info"
                findings.append({"severity": sev, "title": f"Open port {p} ({name})", "where": f"{host}:{p}",
                                 "detail": "exposed service" + (" — often should not be public" if sev == "high" else "")})
        except OSError:
            pass
        finally:
            s.close()
    return findings


def garak(target):
    if not have("garak"): raise ToolMissing("garak", "pip install garak")
    code, out, err = _run(["garak", "--model_type", "rest", "--model_name", target, "--report_prefix", ".vulphex-garak"], timeout=3600)
    return [{"severity": "info", "title": "garak LLM red-team run complete", "where": target, "detail": (out or err)[-160:]}]


def pyrit(target):
    raise ToolMissing("pyrit", "pip install pyrit; VULPHEX wires it per AI app, so configure the target first")


def promptfoo(target):
    if not have("promptfoo"): raise ToolMissing("promptfoo", "npm install -g promptfoo")
    code, out, err = _run(["promptfoo", "eval", "-c", target, "-o", ".vulphex-pf.json"], timeout=1800)
    try: data = json.load(open(".vulphex-pf.json")); os.remove(".vulphex-pf.json")
    except (OSError, ValueError): return []
    fails = (data.get("results", {}).get("stats", {}) or {}).get("failures", 0)
    return [{"severity": "medium" if fails else "info", "title": f"{fails} security check(s) failing", "where": target, "detail": "promptfoo eval"}]


# ---------------------------------------------------------------- offensive adapters (FOX BREACH / REAPER / WRAITH)
# VULPHEX drives these PUBLISHED tools; it does not contain exploits of its own. They run against the targets YOU give
# (your own systems / authorized engagements). Install each from its OFFICIAL source (see repos.json), never a fork.
def _external(tool, bins, how, build):
    found = next((b for b in bins if have(b)), None)
    if not found: raise ToolMissing(tool, how)
    code, out, err = _run(build(found), timeout=3600)
    note = (out or err or "").strip().splitlines()
    return [{"severity": "info", "title": f"{tool} run complete (review its own report)", "where": "", "detail": " ".join(note[-3:])[:200]}]


def sqlmap(target):
    return _external("sqlmap", ["sqlmap"], "pip install sqlmap, or github.com/sqlmapproject/sqlmap",
                     lambda b: [b, "-u", target, "--batch", "--level", "1", "--risk", "1"])


def metasploit(target):
    return _external("metasploit", ["msfconsole"], "official installer at docs.metasploit.com",
                     lambda b: [b, "-q", "-x", f"db_nmap -sV {re.sub(r'^\w+://','',target).split('/')[0]}; exit"])


def autohunter(target):  raise ToolMissing("autohunter", "install AutoHunter from its official repo, then VULPHEX will drive it")
def artex(target):       raise ToolMissing("artex", "run ARTEX from its OFFICIAL docker image (jiwoochris/artex-global); trojaned forks exist")
def pentagi(target):     raise ToolMissing("pentagi", "run PentAGI from its official docker image (vxcontrol/pentagi)")
def pentestgpt(target):  raise ToolMissing("pentestgpt", "pip install pentestgpt (GreyDGL/PentestGPT)")
def strix(target):       raise ToolMissing("strix", "pip install strix-agent (usestrix/strix)")
def nebula(target):      raise ToolMissing("nebula", "install Nebula from berylliumsec/nebula")


RUNNERS = {"semgrep": semgrep, "gitleaks": gitleaks, "trivy": trivy, "nuclei": nuclei, "zap": zap, "recon": recon,
           "garak": garak, "pyrit": pyrit, "promptfoo": promptfoo, "sqlmap": sqlmap, "metasploit": metasploit,
           "autohunter": autohunter, "artex": artex, "pentagi": pentagi, "pentestgpt": pentestgpt, "strix": strix, "nebula": nebula}
