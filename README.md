# VULPHEX

Two things that share one brain — a local **uncensored** ("abliterated") Qwen model, no API, no cost per run.
**Everything here is for research or for systems you own. Paper trading only. Authorized security targets only.**

## 1. Trading brains — `vulphex.py`
Nine learning bots (`bots.json`) built on Edge Bot's engine: neural networks (neuron, forest, Rocket, Rocket Team),
the rising **luck filter**, and a **paper desk** that picks real stocks and scores them forward. The uncensored
**AI coach** suggests tuning in Lina Sigra each night; only ideas that pass the exams survive. No orders, ever.

```bash
python3 vulphex.py                      # all bots, ~400 stocks, writes report.md
python3 vulphex.py --stocks 300 --bots Rocket,Hydra
```

## 2. Security team — `security/`
Nine **FOX bots**, one coordinated team on a shared command core — the ARTEX idea, built defensively. The bots hand
work to each other: discover → map → audit → scan → **verify** → repair → monitor.

| Bot | Role | Drives |
|---|---|---|
| FOX SCOUT | asset discovery (ports, services) | recon |
| FOX ATLAS | maps assets, code and findings into one graph | core |
| FOX AUDITOR | source code + leaked secrets | semgrep, gitleaks (built-in fallback) |
| FOX INSPECTOR | web apps and APIs | OWASP ZAP, nuclei |
| FOX BASTION | dependencies, containers, infra | trivy (built-in fallback) |
| FOX PROOF | **verifies** every finding so a bot can't invent one | core |
| FOX AEGIS | red-teams your LLMs and AI apps | garak, pyrit, promptfoo |
| FOX FORGE | drafts scoped fixes for review (never auto-applies) | core |
| FOX WATCH | tracks what's open, re-runs to catch regressions | core |

**The command core** (`security/core.py`): a policy engine (scope + approval + risk level), a shared SQLite evidence
database (assets, findings, task history), and a model router (cheap model for planning/reports, strong for code).

**Safety, enforced in code:** local bots read files you own (always allowed). Active (network) bots run **only** when
the target matches `security/scope.json` *and* you pass `--approve`. Out of scope = refused. No exploitation, no
evasion, no third-party targets, and no attack-framework images are pulled — vetted tools are driven by name.

```bash
bash security/install-tools.sh                         # install the real scanners
python3 security/artex.py code /path/to/your/repo      # local FOX bots on your own code
python3 security/artex.py findings                     # the shared evidence database
# add a host you own to security/scope.json, then:
python3 security/artex.py mission your-site.com --approve
python3 security/artex.py plan "check my web app and code" your-site.com --approve
```
