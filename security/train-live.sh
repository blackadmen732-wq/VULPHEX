#!/usr/bin/env bash
# Train the bots by penetrating a target over and over — each run, their brains learn from what they confirmed.
# Point it at YOUR practice target (or a system you are authorized to test).
#   bash security/train-live.sh localhost:3000 20      run 20 penetration missions, learning each time
set -e; cd "$(dirname "$0")/.."
TARGET="${1:?usage: train-live.sh <target> [rounds]}"; ROUNDS="${2:-10}"
for i in $(seq 1 "$ROUNDS"); do
  echo "== penetration round $i/$ROUNDS against $TARGET =="
  python3 security/artex.py mission "$TARGET" --approve >/dev/null 2>&1 || true
done
echo "Done. What the bots learned:"
python3 security/artex.py bots
echo; echo "Findings so far:"; python3 security/artex.py findings | head -20
