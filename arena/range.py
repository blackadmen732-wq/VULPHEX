# VULPHEX practice range (owner's request, Nov 24 2026): a SAFE, local cyber-range the bots train against. It is a
# folder of deliberately-weak sample files on your own machine with a known answer key (range.json). Nothing here
# touches the internet; training is scored against the planted vulnerabilities, so the bots get a real signal and you
# get a real benchmark (precision/recall) without attacking anything. This is a lab, like a CTF, not a live target.
import json, os, random

# Each planted vuln: the capability that should find it, a severity, and a 'difficulty' = the minimum search depth a
# bot's playbook needs ("shallow" easiest, "deep" hardest). A pickier keep-bar trades recall for fewer false alarms.
PLANTS = [
    {"capability": "secret_detection",     "severity": "high",     "difficulty": "shallow", "note": "AWS key hardcoded in config"},
    {"capability": "secret_detection",     "severity": "high",     "difficulty": "normal",  "note": "private key committed"},
    {"capability": "source_code_analysis", "severity": "high",     "difficulty": "normal",  "note": "SQL built by string concat"},
    {"capability": "source_code_analysis", "severity": "medium",   "difficulty": "deep",    "note": "command injection via os.system"},
    {"capability": "dependency_audit",     "severity": "high",     "difficulty": "shallow", "note": "known-vulnerable library pinned"},
    {"capability": "web_app_scan",         "severity": "high",     "difficulty": "normal",  "note": "reflected XSS on /search"},
    {"capability": "web_app_scan",         "severity": "medium",   "difficulty": "deep",    "note": "missing security headers"},
    {"capability": "exploit_validation",   "severity": "critical", "difficulty": "deep",    "note": "SQLi that dumps the users table"},
    {"capability": "ai_security",          "severity": "medium",   "difficulty": "normal",  "note": "prompt injection bypasses system rules"},
    {"capability": "asset_discovery",      "severity": "high",     "difficulty": "shallow", "note": "debug port left open"},
    {"capability": "adversary_sim",        "severity": "high",     "difficulty": "deep",    "note": "chained low-sev issues into account takeover"},
    {"capability": "autonomous_pentest",   "severity": "critical", "difficulty": "deep",    "note": "full path from recon to admin"},
]


def build(path):
    """Write the sample weak files + the answer key. Safe to run anywhere; overwrites its own folder only."""
    os.makedirs(path, exist_ok=True)
    open(os.path.join(path, "config.py"), "w").write(
        "# sample weak config for the VULPHEX range (fake values)\n"
        "AWS_KEY = 'AKIAIOSFODNN7EXAMPLE'\nDB_PASSWORD = 'hunter2hunter2'\n")
    open(os.path.join(path, "app.py"), "w").write(
        "import os\n\ndef search(q):\n    sql = \"SELECT * FROM items WHERE name = '\" + q + \"'\"  # SQL by concat\n    return sql\n\n"
        "def ping(host):\n    return os.system('ping -c1 ' + host)  # command injection\n")
    open(os.path.join(path, "requirements.txt"), "w").write("flask==0.12.2\nrequests==2.19.1\n")  # old, vulnerable
    json.dump({"plants": PLANTS, "built": True}, open(os.path.join(path, "range.json"), "w"), indent=1)
    return PLANTS


def answer_key(path):
    try: return json.load(open(os.path.join(path, "range.json")))["plants"]
    except (OSError, ValueError, KeyError): return []
