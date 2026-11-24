# VULPHEX: notes for Claude

Owner: Mark. Paper/research + authorized-security only. Keep his decisions; explain changes simply.

## Layout
- `engine/`: copied from Edge Bot `backtest/` (bootcamp, futures, brains, paperdesk, coach, local_llm, lina/). Refresh by re-copying.
- VULPHEX is a CYBERSECURITY platform (owner removed the trading side Nov 24). `engine/` (Edge Bot's bootcamp/brains/
  coach/local_llm/lina) stays — it is the learning brain, reused by security/brain.py.
- `security/`: twelve FOX bots on a command core.
  - `team.json`: 12 bots — 9 blue (defend) + 3 red (FOX BREACH/REAPER/WRAITH, pentest OWNED systems). `repos.json` maps
    every research repo to a bot (2-3 each) with how it's driven (cli/python/mcp/docker/api), official sources only.
  - `registry.py`: capability -> vetted adapter + risk tag. `tools.py`: wrappers; built-in fallbacks for secrets/deps;
    offensive adapters (sqlmap/metasploit/artex/pentagi/pentestgpt/strix/nebula) call the installed binary or explain install.
  - `core.py` (command core): Policy is ADVISORY (classify + audit table), NOT blocking — owner's call, his systems; it
    labels risk and logs whether a target is in scope.json. SQLite evidence DB (assets/findings/tasks/audit). mission()
    pipeline: scout->atlas->audit->inspect->bastion->aegis->breach->reaper->wraith->proof->forge->watch. FOX PROOF re-reads
    source to confirm findings. FOX FORGE drafts fixes, never applies.
  - `brain.py`: the ancestor brain applied to security — per-bot playbook genomes evolve, scored by confirmed findings
    minus cost, PROVEN only past the rising luck bar (bc.required_z). Stored in the shared DB (brain_pop/brain_led).
- SAFETY (kept, protects Mark, not a restriction on him): install from OFFICIAL sources only (trojaned forks exist);
    the audit log stays; don't add DoS/worm/mass-internet-scan/detection-evasion code; red bots target what he declares.
- `arena/`: the training room (owner wants to train them personally and watch). range.py = safe local practice range
  (planted vulns + answer key, localhost/files only). train.py = squad trains over rounds, brains evolve, team reward
  tracked (deterministic, offline). server.py + index.html = dashboard at 127.0.0.1:3006 (Jarvis-style guard): see the
  12 bots + brains, pick a squad of <=6, Train, watch the chart, and chat to the ancestor model (/api/ask -> router).
  open-arena.sh launches it. SAFETY: the arena never scans a real target; keep it to the range.
- Tests: `python3 -m unittest tests/test_security.py tests/test_arena.py`.
