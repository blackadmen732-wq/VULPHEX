#!/usr/bin/env python3
# VULPHEX: seven learning trading bots, built from Edge Bot's research engine (owner: Mark, Nov 24 2026).
# PAPER ONLY. Nothing here places an order or touches a broker.
#
# Each night, for each of the 7 bots (bots.json):
#   1. its neural network (neuron / forest / Rocket / Rocket Team "experts") trains walk-forward through 8 levels
#      of history and, if it gets through, takes the locked exam on the newest 30% of days it never trained on
#   2. the AI COACH, an uncensored ("abliterated") Qwen model running on this machine, reads how the bot did and
#      suggests changes in Lina Sigra; Lina checks them; each accepted idea becomes a challenger with the same brain kind
#   3. the bot, two mutations and the coach's challengers all face the same exams; the best one becomes the bot
#   4. LUCK FILTER: an exam only counts as PASSED if it beats a bar that rises with every brain ever tried, by any bot
#   5. PAPER DESK: the bot picks real stocks for tomorrow; later nights score those picks with what really happened
# A bot can only ever be called PROVEN by the luck filter plus its forward record. Real money is not wired in.
#
# Usage:  python3 vulphex.py                      (downloads data, runs all 7 bots, writes report.md)
#         python3 vulphex.py --stocks 300 --bots Rocket,Hydra
#         COACH_MODEL=huihui-ai/Qwen2.5-7B-Instruct-abliterated-v2 python3 vulphex.py   (bigger coach, needs a GPU)
import argparse, json, os, random, re, sys, time, urllib.request, urllib.error
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "engine"))
import warnings; warnings.filterwarnings("ignore")
import numpy as np
import bootcamp as bc
import brains
import paperdesk

# The coach's brain: uncensored (refusals removed), small enough for a laptop CPU or Kaggle. Apache-2.0.
os.environ.setdefault("COACH_MODEL", "Goekdeniz-Guelmez/Josiefied-Qwen2.5-1.5B-Instruct-abliterated-v1")
UA = {"User-Agent": "Mozilla/5.0"}
STATE = os.path.join(HERE, "state")


def load_json(p, default):
    try: return json.load(open(p))
    except (OSError, ValueError): return default


def save_json(p, obj):
    os.makedirs(os.path.dirname(p), exist_ok=True); tmp = p + ".tmp"
    json.dump(obj, open(tmp, "w"), indent=1, default=lambda o: o.tolist() if hasattr(o, "tolist") else str(o)); os.replace(tmp, p)


# ------------------------------------------------------------------ data (free daily prices from Yahoo)
def universe(n, seed=7):
    syms = set()
    for name in ("nasdaqlisted", "otherlisted"):
        txt = urllib.request.urlopen(urllib.request.Request(f"https://www.nasdaqtrader.com/dynamic/SymDir/{name}.txt", headers=UA), timeout=60).read().decode()
        for line in txt.splitlines()[1:]:
            f = line.split("|")
            if len(f) > 6 and (f[3] if name == "nasdaqlisted" else f[6]) == "N" and f[6 if name == "nasdaqlisted" else 4] == "N": syms.add((f[0], f[1]))
    bad = re.compile(r"warrant|right|unit|preferred|depositary share|notes|debenture|%|trust|fund|etn|acquisition", re.I)
    pool = sorted(s for s, nm in syms if re.fullmatch(r"[A-Z]{1,5}", s) and not bad.search(nm) and "common" in nm.lower())
    random.Random(seed).shuffle(pool); return pool[:n]


def fetch(sym, path):
    if os.path.exists(path) and os.path.getsize(path) > 2000 and time.time() - os.path.getmtime(path) < 20 * 3600: return True
    for a in range(4):
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1d&period1=-1400000000&period2={int(time.time())}"
            data = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30).read()
            open(path, "wb").write(data); time.sleep(0.3); return True
        except urllib.error.HTTPError as e:
            if e.code == 429: time.sleep(5 * (a + 1)); continue
            return False
        except Exception: return False
    return False


def market(data_dir, n_stocks, years=20):
    os.makedirs(data_dir, exist_ok=True)
    got = sum(fetch(s, os.path.join(data_dir, s + ".json")) for s in universe(n_stocks))
    O, L, C, V, days = bc.load_yahoo(data_dir); syms = list(bc.LAST_SYMBOLS); H = bc.LAST_HIGH
    keep = 252 * years
    if len(days) > keep: O, L, C, V, H, days = O[:, -keep:], L[:, -keep:], C[:, -keep:], V[:, -keep:], H[:, -keep:], days[-keep:]
    return bc.Market(O, L, C, V, days, H=H), syms, got


# ------------------------------------------------------------------ one bot, one night
def challengers(g, ideas, rnd, n_mut=2):
    """The bot itself, the coach's ideas and a few mutations, all with the bot's own kind of brain."""
    out = [dict(g)]
    for c in list(ideas) + [brains.mutate(g, rnd) for _ in range(n_mut * 3)]:
        c = {**c, "brain": g["brain"]}
        if c not in out: out.append(c)
        if len(out) >= 1 + len(ideas) + n_mut: break
    return out


def run_bot(m, F, syms, bot, st, ledger, coach_fn, seed):
    g = st.get("genome") or bot["genome"]; band = bot["band"]; lines = []
    ideas, clines = coach_fn({"genomes": [g], "last": st.get("last", []), "stuck": st.get("stuck", 0)}, brains.GENES)
    lines += [l.replace("- AI coach", "  - AI coach", 1) for l in clines]
    rnd = random.Random(seed); results = []
    for i, c in enumerate(challengers(g, ideas, rnd)):
        init = st.get("rocket") if c["brain"] == "rocket" else None
        res, model = brains.walk(m, band, c, F, seed=seed + i, init=init)
        ledger["tried"] = ledger.get("tried", 0) + 1; results.append((res, model, c in ideas))
    bar = max(2.0, bc.required_z(ledger["tried"]))
    for res, _, _ in results:
        e = res["exam"]; res["passed"] = bool(e and e["n"] >= bc.MIN_TRADES and e["mean"] > 0 and e["z"] >= bar)
    results.sort(key=lambda x: -x[0]["score"]); best, model, from_coach = results[0]
    improved = best["score"] > st.get("score", -1e9)
    if improved or "genome" not in st:
        st.update(genome=best["genome"], score=best["score"])
        if best["genome"]["brain"] == "rocket" and isinstance(model, brains.WarmRocket): st["rocket"] = model.weights()
    st["stuck"] = 0 if improved else st.get("stuck", 0) + 1
    st["last"] = [{"genome": r["genome"], "levels_passed": r["levels_passed"], "passed": r["passed"]} for r, _, _ in results[:3]]
    st["nights"] = st.get("nights", 0) + 1
    ex = best["exam"]; gg = st["genome"]
    lines.insert(0, f"- **{bot['name']}** ({gg['brain']}, {gg['hidden']} neurons, holds {gg['hold']}d, {band} stocks): "
                    f"best tonight passed {best['levels_passed']}/8 levels"
                    + (f", exam {ex['n']} trades {ex['mean'] * 100:+.2f}% z {ex['z']:+.1f} vs luck bar {bar:.1f} -> {'PASSED' if best['passed'] else 'failed'}" if ex else "")
                    + (" (the coach's idea won)" if from_coach and improved else "") + ("; new best settings" if improved else ""))
    try:
        book, dline = paperdesk.update(st.get("desk"), m, band, gg, F, syms, init=st.get("rocket"))
        st["desk"] = book; lines.append("  - " + dline.replace("paper desk", "paper desk", 1))
    except Exception as e: lines.append(f"  - paper desk problem: {e}")
    return lines


def main(argv=None):
    ap = argparse.ArgumentParser(description="VULPHEX: 7 learning paper-trading bots")
    ap.add_argument("--stocks", type=int, default=int(os.environ.get("VULPHEX_STOCKS", "400")))
    ap.add_argument("--bots", default="", help="comma-separated names (default: all 7)")
    ap.add_argument("--data", default=os.path.join(HERE, "data"))
    ap.add_argument("--no-coach", action="store_true", help="skip the AI coach (no model download)")
    a = ap.parse_args(argv)
    cfg = load_json(os.path.join(HERE, "bots.json"), {})["bots"]
    if a.bots: cfg = [b for b in cfg if b["name"].lower() in {x.strip().lower() for x in a.bots.split(",")}]
    t0 = time.time(); now = datetime.now(timezone.utc)
    lines = [f"## {now:%Y-%m-%d %H:%M} UTC (paper only)"]
    m, syms, got = market(a.data, a.stocks)
    lines.append(f"- data: {got} of {a.stocks} stocks downloaded, {m.T} trading days")
    F = brains.brain_inputs(m)
    if a.no_coach: coach_fn = lambda saved, genes: ([], ["- AI coach: off (--no-coach)"])
    else:
        import coach; coach_fn = coach.coach
    ledger = load_json(os.path.join(STATE, "ledger.json"), {"tried": 0})
    for i, bot in enumerate(cfg):
        p = os.path.join(STATE, f"{bot['name'].lower()}.json"); st = load_json(p, {})
        try: lines += run_bot(m, F, syms, bot, st, ledger, coach_fn, seed=int(time.time()) % 100000 + i * 1000)
        except Exception as e: lines.append(f"- **{bot['name']}**: error {type(e).__name__}: {e}")
        save_json(p, st); save_json(os.path.join(STATE, "ledger.json"), ledger)
    lines.append(f"- luck filter: {ledger['tried']} brains tried all-time; exam bar now z {max(2.0, bc.required_z(ledger['tried'])):.2f}")
    lines.append(f"- took {(time.time() - t0) / 60:.1f} minutes")
    rep = os.path.join(HERE, "report.md"); old = open(rep).read() if os.path.exists(rep) else "# VULPHEX nightly report (paper only)\n"
    head, _, rest = old.partition("\n"); open(rep, "w").write(head + "\n\n" + "\n".join(lines) + "\n" + rest)
    print("\n".join(lines))


if __name__ == "__main__":
    main()
