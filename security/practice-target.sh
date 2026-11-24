#!/usr/bin/env bash
# A SAFE target to penetrate and train against — OWASP Juice Shop, a deliberately-vulnerable web app, running on YOUR
# own machine (localhost). This is how you legally practice: attack a vulnerable app you own, never someone else's.
#   bash security/practice-target.sh          start it on http://localhost:3000 and allow it in scope
#   bash security/practice-target.sh stop      stop it
set -e; cd "$(dirname "$0")/.."
if [ "${1:-}" = "stop" ]; then docker rm -f vulphex-target 2>/dev/null && echo "practice target stopped."; exit 0; fi
command -v docker >/dev/null || { echo "Install Docker first, then run this again."; exit 1; }
echo "Starting OWASP Juice Shop (a vulnerable app) on http://localhost:3000 ..."
docker rm -f vulphex-target 2>/dev/null || true
docker run -d --name vulphex-target -p 3000:3000 bkimminich/juice-shop >/dev/null
# allow localhost in scope so the bots may test it (it's your own machine)
python3 - <<'PY'
import json, os
p = "security/scope.json"; d = json.load(open(p))
d["allow_private_ranges"] = True
if "localhost" not in d["hosts"]: d["hosts"].append("localhost")
if "127.0.0.1" not in d["hosts"]: d["hosts"].append("127.0.0.1")
d["authorization_note"] = "Local practice target (OWASP Juice Shop) on my own machine."
json.dump(d, open(p, "w"), indent=2)
print("scope.json now allows localhost / 127.0.0.1")
PY
echo
echo "Ready. Penetrate it:   python3 security/artex.py mission localhost:3000 --approve"
echo "Open it in a browser:  http://localhost:3000"
echo "Stop it later:         bash security/practice-target.sh stop"
