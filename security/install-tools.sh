#!/usr/bin/env bash
# Install the real tools VULPHEX's FOX bots drive. Each from its OFFICIAL source only (pinned) — never a random fork;
# trojaned ARTEX/pentest images are known to circulate. VULPHEX runs without any of these (built-in fallbacks for
# secrets and dependencies), but the real tools go far deeper. You are responsible for only testing systems you own
# or are authorized to test.
set -e
echo "== Blue team (read your own code/infra) =="
pip install -q semgrep || echo "semgrep: pip install semgrep"
command -v gitleaks >/dev/null || (curl -sSfL https://raw.githubusercontent.com/gitleaks/gitleaks/master/scripts/install.sh | sh -s -- -b "$HOME/.local/bin" 2>/dev/null || echo "gitleaks: github.com/gitleaks/gitleaks/releases")
command -v trivy    >/dev/null || (curl -sSfL https://raw.githubusercontent.com/aquasecurity/trivy/main/contrib/install.sh | sh -s -- -b "$HOME/.local/bin" 2>/dev/null || echo "trivy: github.com/aquasecurity/trivy/releases")
pip install -q garak || echo "garak: pip install garak"
echo
echo "== Optional deeper tools (install what you use) =="
cat <<'TOOLS'
  nuclei     : go install github.com/projectdiscovery/nuclei/v3/cmd/nuclei@latest
  OWASP ZAP  : docker run -t ghcr.io/zaproxy/zaproxy:stable        (official image)
  promptfoo  : npm install -g promptfoo
  PyRIT      : pip install pyrit
  == Red team (PENTEST YOUR OWN SYSTEMS — official sources) ==
  sqlmap     : github.com/sqlmapproject/sqlmap        (pip install sqlmap-dev)
  metasploit : docs.metasploit.com (official installer)
  PentestGPT : pip install pentestgpt                 (GreyDGL/PentestGPT)
  Strix      : pip install strix-agent                (usestrix/strix)
  ARTEX      : jiwoochris/artex-global OFFICIAL docker image only
  PentAGI    : vxcontrol/pentagi OFFICIAL docker image only
  Nebula     : github.com/berylliumsec/nebula
TOOLS
echo
echo "Done. Audit your own code now:  python3 security/artex.py code /path/to/your/project"
echo "Full repo -> bot map is in repos.json."
