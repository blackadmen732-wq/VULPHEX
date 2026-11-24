# VULPHEX tool registry: the one place that maps a CAPABILITY a bot asks for to a vetted tool adapter.
# A bot (FOX AUDITOR, ...) never learns each tool's command line; it requests "source_code_analysis" and the registry
# hands back the approved adapters, each tagged with a risk level the policy engine checks before anything runs.
#   read-only   : reads files/data you own (local). Always allowed.
#   active-test : reaches a target over the network. Needs scope.json + approval.
#   restricted  : intrusive proof / exploitation-adjacent. Needs explicit per-run approval; VULPHEX ships none that attack.
import tools as T

# capability -> ordered list of {tool, risk}. First installed adapter wins; built-in fallbacks always run.
CAPABILITIES = {
    "asset_discovery":      [{"tool": "nmap",      "risk": "active-test"}, {"tool": "recon", "risk": "active-test"}],
    "source_code_analysis": [{"tool": "semgrep",   "risk": "read-only"}],
    "secret_detection":     [{"tool": "gitleaks",  "risk": "read-only"}],     # built-in fallback
    "dependency_audit":     [{"tool": "trivy",     "risk": "read-only"}],     # built-in fallback
    "web_app_scan":         [{"tool": "zap",       "risk": "active-test"}, {"tool": "nuclei", "risk": "active-test"}],
    "ai_security":          [{"tool": "garak",     "risk": "active-test"}, {"tool": "promptfoo", "risk": "read-only"}, {"tool": "pyrit", "risk": "active-test"}],
    "exploit_validation":   [{"tool": "sqlmap",    "risk": "active-test"}, {"tool": "metasploit", "risk": "active-test"}],
    "autonomous_pentest":   [{"tool": "pentestgpt","risk": "active-test"}, {"tool": "artex", "risk": "active-test"}, {"tool": "pentagi", "risk": "active-test"}],
    "adversary_sim":        [{"tool": "nuclei",    "risk": "active-test"}, {"tool": "sqlmap", "risk": "active-test"}],
    # these three are served by the core itself (graph/verify/fix/watch), listed so bots can request them:
    "system_mapping":       [{"tool": "graph",     "risk": "read-only"}],
    "finding_verification": [{"tool": "verify",    "risk": "read-only"}],
    "repair":               [{"tool": "fix",       "risk": "read-only"}],
    "monitoring":           [{"tool": "watch",     "risk": "read-only"}],
    "agentic_coding":       [{"tool": "coder",     "risk": "read-only"}],
}

CORE_TOOLS = {"graph", "verify", "fix", "watch", "coder"}     # handled in core.py, not in tools.RUNNERS


def adapters(capability):
    return CAPABILITIES.get(capability, [])


def risk_of(capability, tool):
    for a in adapters(capability):
        if a["tool"] == tool: return a["risk"]
    return "active-test"


def installed(tool):
    """A real scanner is 'ready' only if its binary is present; the two built-in fallbacks and core tools always are."""
    if tool in CORE_TOOLS or tool in ("recon",): return True
    if tool in ("gitleaks", "trivy", "semgrep"): return True       # pure-Python fallback inside tools.py
    return T.have(tool)                                       # external tools/repos: ready only when installed from their official source


def run(tool, target):
    """Run one adapter and return normalized findings. Core tools are not here (core.py handles them)."""
    runner = T.RUNNERS.get(tool)
    if runner is None: raise T.ToolMissing(tool, "no adapter")
    return runner(target) or []
