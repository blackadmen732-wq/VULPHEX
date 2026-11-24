# VULPHEX

A cybersecurity platform: **twelve FOX bots** — nine that defend and three that penetrate your own systems — driven by
one evolving brain (Edge Bot's learning neural network + a local **uncensored** Qwen model, no API, no cost per run).
**For systems you own or are authorized to test.** You declare your scope; VULPHEX logs every action.

## The twelve FOX bots
| | Bot | Role | Drives (see `repos.json`) |
|---|---|---|---|
|🔵| FOX SCOUT | asset discovery | ARL, ScopeSentry, Nemo |
|🔵| FOX ATLAS | maps assets, code & findings into one graph | Cairn, RedAmon |
|🔵| FOX AUDITOR | source code + leaked secrets | DeepAudit, Semgrep, Gitleaks |
|🔵| FOX INSPECTOR | web apps & APIs | ZAP, Nuclei, Shannon |
|🔵| FOX BASTION | dependencies, containers, AI infra | Trivy, AI-Infra-Guard, OpenEASD |
|🔵| FOX PROOF | **verifies** every finding (no inventing) | core + CAI (ref) |
|🔵| FOX AEGIS | red-teams your LLMs & AI apps | Garak, PyRIT, Promptfoo |
|🔵| FOX FORGE | drafts scoped fixes for review | Semgrep autofix, Strix |
|🔵| FOX WATCH | tracks what's open, catches regressions | ARL-Next, ScopeSentry, Osmedeus |
|🔴| FOX BREACH | proves a vuln by exploiting it on your host | sqlmap, Metasploit, AutoHunter |
|🔴| FOX REAPER | autonomous multi-agent pentest | ARTEX, PentAGI, PentestGPT |
|🔴| FOX WRAITH | adversary simulation / app attack | Strix, Nebula, XingRin |

`repos.json` is the full integration map: every repo from the research, assigned to a bot (2–3 each), with how VULPHEX
drives it (cli / python / mcp / docker / api). Nothing is merged into one codebase — each repo is an **adapter** a bot
calls, installed from its **official** source.

## The brain (the "ancestor" system from Edge Bot)
Each bot carries a **playbook** that evolves: which tools, how deep, how high to set its keep-bar. After every mission
the playbook is scored by what it actually **confirmed** (via FOX PROOF), minus cost, and the best tactics breed. The
**luck filter** (same rule as Edge Bot) only calls a tactic *proven* once it beats a bar that rises with every tactic
tried **and** holds on fresh runs — so VULPHEX learns what really works. The uncensored model plans missions and
proposes new tactics in **Lina Sigra**, which are checked before they join the population.

## The command core (`security/core.py`)
- **Policy (advisory + audit):** VULPHEX runs what you point it at; it labels each task's risk and logs every action to
  an audit trail, noting whether the target is inside the scope you declared in `security/scope.json`. It does not
  block — authorization is yours, like every real pentest tool. `python3 security/artex.py audit` prints the log.
- **Shared evidence database (SQLite):** assets, findings, verification status, fixes, task history, brain memory.
- **Model router:** cheap model for planning/reports, strong for code reasoning.

## Run it
```bash
bash security/install-tools.sh                         # install real tools (official sources)
python3 security/artex.py bots                          # the 12 FOX bots
python3 security/artex.py code /path/to/your/repo       # blue team on your own code
python3 security/artex.py mission your-own-host.com     # full team (declare it in scope.json first)
python3 security/artex.py findings                      # shared evidence database
python3 security/artex.py audit                         # audit log of every task
```

## Give a bot hands — the coding agent
Three bots (FOX AUDITOR, FOX FORGE, FOX REAPER) can use **Claude Code's body** — run commands, read/write/edit files,
build and fix code — with **your uncensored brain** behind it and a security **skill** loaded (`security/skills/`). This
is how FOX FORGE actually writes the fix and FOX REAPER scripts work against a target you declared.

```bash
# point it at your uncensored brain (e.g. Mira's Kaggle tunnel, or a local Ollama Anthropic endpoint):
#   edit security/agent.json  (base_url + model)   and   export VULPHEX_BRAIN_TOKEN=...
python3 security/artex.py agent "FOX FORGE" "fix the SQL injection in app.py" --cwd .
```
It streams each step and ends with a summary. Needs Claude Code installed (`curl -fsSL https://claude.ai/install.sh | bash`);
with no brain configured it uses whatever `claude` is logged into. Every agent run is written to the audit log.

## Train them yourself — the Arena
A local training room (a tab in your browser) to watch the brain learn and talk to the ancestor model:
```bash
bash arena/open-arena.sh          # opens http://localhost:3006
```
- Pick up to **six** FOX bots (a squad that learns to operate together — attack + defend).
- **Train** them against a safe local practice range (`arena/range.py`: planted vulnerabilities on your own machine,
  never the internet). Watch the team's reward climb and tactics get **proven** by the luck filter.
- **Talk to the ancestor brain** (the uncensored model) on the right — ask how to attack or defend your systems.
Nothing in the Arena touches a real target; it is a lab for understanding and training the squad.
