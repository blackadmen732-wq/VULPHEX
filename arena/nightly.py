#!/usr/bin/env python3
# VULPHEX nightly training — point a server at this (cron / systemd / a loop) and the squad keeps getting better:
# it runs the curriculum against the practice range, evolves each bot's brain under the luck filter, and (if the
# uncensored model is reachable) lets the Lina coach propose tactics. Brain state persists in security/vulphex.db,
# so progress carries across runs and machines. Offline and safe — it trains on the range, not real targets.
#   python3 arena/nightly.py                 one pass
#   python3 arena/nightly.py --loop 3600     keep training, a pass every hour
import argparse, os, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(os.path.dirname(HERE), "security"))
import core as C
import trainer as TR
import persist as P

SQUAD = ["FOX SCOUT", "FOX AUDITOR", "FOX INSPECTOR", "FOX BASTION", "FOX BREACH", "FOX WRAITH"]
DB = os.path.join(os.path.dirname(HERE), "security", "vulphex.db")


def one_pass(per=15):
    if P.restore(DB): print("[persist] restored brain from Supabase", flush=True)
    core = C.Core(db_path=DB, scope={"hosts": []})
    ask = None
    try:                                                       # use the uncensored model as the Lina coach if present
        g = core.router.ask("coach", "ping", max_new_tokens=4)
        if g is not None: ask = lambda p: core.router.ask("coach", p, max_new_tokens=40)
    except Exception: pass
    hist = TR.curriculum(core, SQUAD, per=per, seed=int(time.time()) % 100000, ask=ask)
    proven = core.db.execute("SELECT COUNT(*) FROM brain_pop WHERE proven=1").fetchone()[0]
    tried = core.db.execute("SELECT v FROM brain_led WHERE k='tried'").fetchone()
    last = hist[-1]["team_reward"] if hist else 0
    core.close()
    if P.snapshot(DB): print("[persist] saved brain to Supabase", flush=True)
    return {"rounds": len(hist), "team_reward_end": last, "proven_tactics": proven, "tactics_tried": tried[0] if tried else 0, "coach": ask is not None}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--loop", type=int, default=0, help="seconds between passes (0 = one pass)")
    ap.add_argument("--per", type=int, default=15); a = ap.parse_args()
    while True:
        r = one_pass(a.per)
        print(f"[{time.strftime('%Y-%m-%d %H:%M')}] pass done: {r['rounds']} rounds, end reward {r['team_reward_end']}, "
              f"{r['proven_tactics']} proven tactics, {r['tactics_tried']} tried, coach {'on' if r['coach'] else 'off'}", flush=True)
        if not a.loop: break
        time.sleep(a.loop)


if __name__ == "__main__":
    main()
