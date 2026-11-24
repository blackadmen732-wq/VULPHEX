# VULPHEX: notes for Claude

Owner: Mark. Paper/research + authorized-security only. Keep his decisions; explain changes simply.

## Layout
- `engine/`: copied from Edge Bot `backtest/` (bootcamp, futures, brains, paperdesk, coach, local_llm, lina/). Refresh by re-copying.
- `vulphex.py` + `bots.json`: 9 (currently 7 listed; owner may want 9) learning bots. run_bot trains a bot's brain (brains.walk),
  adds the AI coach's Lina ideas + 2 mutations as challengers, keeps the best, updates the luck ledger (state/ledger.json),
  runs the paper desk. Per-bot state in state/<name>.json. COACH_MODEL defaults to the abliterated Qwen 1.5B.
- `security/`: artex.py (orchestrator) + tools.py (one wrapper per scanner) + team.json (9 agents) + scope.json (authorized targets).
  - SAFETY, do not weaken: `in_scope()` lets local paths through (your files) but a host only if it matches scope.json;
    active agents also need `--approve`. tools.py has pure-Python fallbacks for secrets (builtin_secret_scan) and deps so it runs
    with nothing installed. recon() is a light connect-only port check, no exploitation. Never add an exploit/evasion runner,
    never remove the scope/approval gate, never let it hit a target not in scope.json.
- Tests: `python3 -m unittest tests/test_vulphex.py tests/test_security.py`.

## Rules
- Never commit keys. Paper trading only; no broker/orders. Security: owned/authorized targets only; keep the scope + approval gate.
- Don't pull third-party ARTEX/pentest Docker images or forks (trojaned versions exist). Drive vetted tools by name instead.
