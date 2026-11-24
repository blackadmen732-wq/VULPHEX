# VULPHEX: notes for Claude

Owner: Mark. Paper/research + authorized-security only. Keep his decisions; explain changes simply.

## Layout
- `engine/`: copied from Edge Bot `backtest/` (bootcamp, futures, brains, paperdesk, coach, local_llm, lina/). Refresh by re-copying.
- `vulphex.py` + `bots.json`: 9 (currently 7 listed; owner may want 9) learning bots. run_bot trains a bot's brain (brains.walk),
  adds the AI coach's Lina ideas + 2 mutations as challengers, keeps the best, updates the luck ledger (state/ledger.json),
  runs the paper desk. Per-bot state in state/<name>.json. COACH_MODEL defaults to the abliterated Qwen 1.5B.
- `security/`: the nine FOX bots on a command core.
  - `team.json`: 9 FOX bots (SCOUT/ATLAS/AUDITOR/INSPECTOR/BASTION/PROOF/AEGIS/FORGE/WATCH), each requests capabilities.
  - `registry.py`: capability -> vetted tool adapter, each tagged read-only / active-test / restricted.
  - `tools.py`: one wrapper per scanner; built-in Python fallbacks for secrets (builtin_secret_scan) and deps; recon() is a
    connect-only port check. Never add an exploit/evasion runner.
  - `core.py` (command core): Policy (scope.json + approval + risk), SQLite evidence DB (assets/findings/tasks), ModelRouter
    (cheap vs strong), and the mission() pipeline. FOX PROOF re-reads source to confirm findings (no inventing). FOX FORGE
    drafts fixes, never applies. scope.json = authorized targets.
  - SAFETY, do not weaken: active/restricted tasks need host in scope.json AND approve=True; local reads of your own files are
    allowed. Keep the policy gate; never let it hit a target not in scope.json; never pull third-party ARTEX/pentest images.
- Tests: `python3 -m unittest tests/test_vulphex.py tests/test_security.py`.
