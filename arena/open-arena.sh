#!/usr/bin/env bash
# Open the VULPHEX Arena training room in your browser.
set -e; cd "$(dirname "$0")/.."
if ! curl -fs -m 2 http://localhost:3006/api/state >/dev/null 2>&1; then
  nohup python3 arena/server.py >"$HOME/.vulphex-arena.log" 2>&1 &
  for _ in $(seq 1 20); do curl -fs -m 1 http://localhost:3006/api/state >/dev/null 2>&1 && break; sleep 0.3; done
fi
xdg-open http://localhost:3006 2>/dev/null || echo "Open http://localhost:3006 in your browser."
