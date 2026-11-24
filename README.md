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

## 2. Security team — `security/artex.py`
Nine AI agents (`security/team.json`) over **real** scanners, with a planner, shared evidence, dedup, a human-approval
gate and an auto report writer — the ARTEX idea, built defensively.

| Agent | Does | Tool |
|---|---|---|
| Cinder | audits your source code | semgrep |
| Vault | hunts leaked secrets/keys | gitleaks (built-in fallback) |
| Sieve | checks vulnerable dependencies | trivy (built-in fallback) |
| Warden | scans a web app | OWASP ZAP |
| Probe | checks known CVEs on a host | nuclei |
| Scout | maps exposed ports/services | built-in |
| Mirror | red-teams an LLM | garak |
| Crucible | tests an AI app for prompt-injection | pyrit |
| Ward | AI security regression checks | promptfoo |

**Safety, enforced in code:** local agents read files you own (always allowed). Active (network) agents run **only**
when the target matches `security/scope.json` *and* you pass `--approve`. Out of scope = refused. No exploitation,
no evasion, no third-party targets.

```bash
bash security/install-tools.sh                     # install the real scanners
python3 security/artex.py code /path/to/your/repo  # audit your own code (no approval needed)
# edit security/scope.json to add a host you own, then:
python3 security/artex.py scan your-own-site.com --approve
python3 security/artex.py plan "check my web app and its code" your-own-site.com --approve
```
