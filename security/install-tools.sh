#!/usr/bin/env bash
# Install the real scanners VULPHEX's agents drive. Run what you need; each agent works once its tool is here.
# VULPHEX runs without any of these (the secret and dependency agents have built-in fallbacks), but the real tools
# find much more. ONLY scan systems you own or are authorized to test.
set -e
echo "Installing the local (safe, read-your-own-code) scanners..."
pip install -q semgrep || echo "semgrep failed"
# gitleaks (secrets) and trivy (dependencies/containers): official installers
command -v gitleaks >/dev/null || (curl -sSfL https://raw.githubusercontent.com/gitleaks/gitleaks/master/scripts/install.sh | sh -s -- -b "$HOME/.local/bin" 2>/dev/null || echo "gitleaks: see github.com/gitleaks/gitleaks/releases")
command -v trivy    >/dev/null || (curl -sSfL https://raw.githubusercontent.com/aquasecurity/trivy/main/contrib/install.sh | sh -s -- -b "$HOME/.local/bin" 2>/dev/null || echo "trivy: see github.com/aquasecurity/trivy/releases")
echo
echo "Active (network) scanners are optional and only run on targets in security/scope.json:"
echo "  nuclei    : go install github.com/projectdiscovery/nuclei/v3/cmd/nuclei@latest"
echo "  OWASP ZAP : docker run -t zaproxy/zap-stable  (or owasp.org/zap)"
echo "  garak     : pip install garak      (AI model red-teaming)"
echo "  promptfoo : npm install -g promptfoo"
echo
echo "Done. Audit your own code now:  python3 security/artex.py code /path/to/your/project"
