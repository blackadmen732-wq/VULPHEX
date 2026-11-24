# Brain paper desk (owner's choice, Nov 22 2026: "A and B"). PAPER ONLY: nothing here places an order.
# B: the brains keep training every night under the luck filter, exactly as before.
# A: meanwhile the night's best learning brain also picks real stocks for the NEXT day, and later nights check how
#    those picks really did. It is a true forward test: each pick is made before its outcome exists.
#    A pick: buy at the next day's open, sell at the close `hold` trading days later, judged against the band's
#    average move and minus the real cost (same maths as every exam). $100 of paper money per pick.
#    Being on the desk proves nothing: only the luck filter + Black Fox's forward record can earn real money.
import numpy as np
import brains

STAKE, MAX_PICKS, MAX_OPEN = 100.0, 10, 200

def today_picks(m, band, g, F, syms, init=None, seed=1):
    """Train on everything whose outcome is known, then score the newest day. Returns [(symbol, prob)]."""
    model = brains.fit_brain(m, band, g, F, 60, m.T, np.random.default_rng(seed), seed, init)
    if model is None: return []
    hold = g["hold"]; c = brains.cols_for(g, F.shape[-1]); _, ok = brains.target_ok(m, band, hold)
    thr = brains.train_cutoff(lambda Z: model.prob(Z[:, c]), ok, F, m.T, hold, g["pick"])
    t = m.T - 1; live = m.band[band][:, t] & np.isfinite(m.C[:, t])
    if not live.any(): return []
    idx = np.flatnonzero(live); p = model.prob(F[idx, t][:, c])
    keep = [(syms[i], float(q)) for i, q in zip(idx, p) if q >= thr]
    return sorted(keep, key=lambda x: -x[1])[:MAX_PICKS]

def settle(book, m, band, syms):
    """Close every open pick whose holding period is now over. Returns how many closed tonight."""
    pos = {s: i for i, s in enumerate(syms)}; dayix = {int(d): i for i, d in enumerate(m.days)}; closed = 0; still = []
    for x in book.get("open", []):
        s, t, h = pos.get(x["symbol"]), dayix.get(x["day"]), x["hold"]
        if s is None or t is None or t + h >= m.T: still.append(x); continue      # not over yet (or stock left the data)
        ex = float(m.fwd[h][s, t] - np.broadcast_to(brains.bc.bench(m, band, h), m.C.shape)[s, t] - m.cost[s, t])
        if not np.isfinite(ex): still.append(x); continue
        ex = max(-0.9, min(1.0, ex)); book.setdefault("closed", []).append({**x, "result": round(ex, 5), "pnl": round(STAKE * ex, 2)}); closed += 1
    book["open"] = still; book["closed"] = book.get("closed", [])[-2000:]
    return closed

def update(book, m, band, g, F, syms, init=None, seed=1):
    """One night: settle old picks, add today's. Returns (book, report line)."""
    book = book or {"open": [], "closed": []}; n = settle(book, m, band, syms)
    day = int(m.days[-1]); new = []
    if not any(x["day"] == day for x in book["open"]) and len(book["open"]) < MAX_OPEN:
        new = today_picks(m, band, g, F, syms, init, seed)
        book["open"] += [{"symbol": s, "day": day, "hold": g["hold"], "brain": g["brain"], "prob": round(q, 4)} for s, q in new]
    c = book["closed"]; pnl = sum(x["pnl"] for x in c); wins = sum(x["pnl"] > 0 for x in c)
    line = (f"paper desk ({band}): {g['brain']} brain picked {len(new)} stocks for tomorrow (hold {g['hold']}d); "
            f"{n} picks closed tonight; all-time {len(c)} closed, {wins} won, paper P&L ${pnl:+.2f}, {len(book['open'])} open. Paper only, not proven.")
    return book, line
