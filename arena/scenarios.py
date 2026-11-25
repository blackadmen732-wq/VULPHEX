# VULPHEX scenario generator (owner's request, Nov 2026): to train FAST — "an hour = years" — the bots need far more
# than the 12 fixed practice plants. This makes a big, varied pile of synthetic practice scenarios instantly and for
# free (procedural, offline): each scenario is a different set of planted weaknesses, with randomized capability,
# severity and difficulty. Thousands of these + many rounds = a lot of training compressed into seconds. The models
# (Claude/NVIDIA) stay the TEACHER for study/reproduce/fine-tune; raw training speed comes from volume, not API calls.
import random

CAPS = ["secret_detection", "source_code_analysis", "dependency_audit", "web_app_scan", "exploit_validation",
        "ai_security", "asset_discovery", "adversary_sim", "autonomous_pentest"]
SEV = ["info", "low", "medium", "high", "critical"]
DIFF = ["shallow", "normal", "deep"]
# a few realistic notes per capability so the scenarios read like real findings, not just noise
NOTES = {
    "secret_detection": ["hardcoded AWS key", "committed private key", "token in config", "password in source"],
    "source_code_analysis": ["SQL by string concat", "command injection", "unsafe deserialization", "path traversal"],
    "dependency_audit": ["known-vuln library pinned", "outdated base image", "transitive CVE"],
    "web_app_scan": ["reflected XSS", "missing security headers", "open redirect", "IDOR on an endpoint"],
    "exploit_validation": ["SQLi dumps users table", "RCE via upload", "auth bypass"],
    "ai_security": ["prompt injection bypass", "system-prompt leak", "jailbreak via roleplay"],
    "asset_discovery": ["debug port open", "forgotten subdomain", "exposed admin panel"],
    "adversary_sim": ["chained low-sev to takeover", "lateral movement path", "privilege escalation"],
    "autonomous_pentest": ["full path recon to admin", "multi-step exploit chain"],
}


def _plant(rnd, i, j):
    cap = rnd.choice(CAPS)
    return {"capability": cap, "severity": rnd.choices(SEV, weights=[1, 3, 4, 4, 2])[0],
            "difficulty": rnd.choices(DIFF, weights=[4, 4, 3])[0],
            "note": f"{rnd.choice(NOTES.get(cap, ['planted weakness']))} (gen {i}.{j})"}


def generate(n=50, seed=0, size=(6, 14)):
    """n scenarios, each a list of planted weaknesses. Deterministic for a given seed, so runs are reproducible."""
    rnd = random.Random(seed)
    out = []
    for i in range(n):
        k = rnd.randint(size[0], size[1])
        out.append([_plant(rnd, i, j) for j in range(k)])
    return out
