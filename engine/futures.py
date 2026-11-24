# Future simulator + learning bots (research only, no orders). Owner-approved Nov 15 2026.
#
# FUTURE SIMULATOR: builds many believable "futures" by stitching together random 20-day chunks of real market
# history (all stocks move together inside a chunk, so crashes and rallies stay real), plus sudden crash weeks.
# A bot's signals are recomputed on each future. Survival = share of futures where it beats the average stock
# after costs. One lucky history is not enough: a real edge should survive most futures.
#
# LEARNING BOTS: the owner's neuron math (dashboard/desk/math-core.mjs: predict, error, gradient step), as a
# logistic neuron over 7 chart features, trained WALK-FORWARD: it only ever learns from days before the level
# it is tested on, retrains at each level, and must pass all 8 levels and then the locked exam, like any bot.
import math
import numpy as np
import bootcamp as bc

# ---------------- future simulator ----------------
def make_future(O, L, C, V, days, rs, block=20, crash_rate=1 / 500, index=False):
    S, T = C.shape
    with np.errstate(all="ignore"):
        rc = C[:, 1:] / C[:, :-1]; ro = O[:, 1:] / C[:, :-1]; rl = L[:, 1:] / C[:, :-1]
    n = T - 1; idx = []
    while len(idx) < n:
        s = int(rs.integers(0, n - block)); idx.extend(range(s, s + block))
    idx = np.array(idx[:n])
    rc, ro, rl, v = rc[:, idx], ro[:, idx], rl[:, idx], V[:, 1:][:, idx]
    crash = rs.random(n) < crash_rate                                  # a sudden bad week now and then
    for t in np.nonzero(crash)[0]:
        rc[:, t:t + 5] *= 0.96; ro[:, t:t + 5] *= 0.96; rl[:, t:t + 5] *= 0.96
    C2 = np.full_like(C, np.nan); C2[:, 0] = C[:, 0]
    with np.errstate(all="ignore"):
        C2[:, 1:] = C[:, :1] * np.cumprod(np.where(np.isfinite(rc), rc, 1.0), axis=1)
        prev = C2[:, :-1]; O2 = np.full_like(C, np.nan); L2 = np.full_like(C, np.nan); V2 = np.full_like(C, np.nan)
        O2[:, 1:] = prev * ro; L2[:, 1:] = np.minimum(prev * rl, np.minimum(O2[:, 1:], C2[:, 1:])); V2[:, 1:] = v
        alive = np.isfinite(C[:, 1:][:, idx]); C2[:, 1:] = np.where(alive, C2[:, 1:], np.nan)
    return bc.Market(O2, L2, C2, V2, days, index=index)          # keep index mode: same bands, benchmark and costs as the real market

def survival(O, L, C, V, days, genomes, n=50, seed=5, index=False):
    """Per genome: (share of ALL futures it beat the benchmark in, avg return/trade, futures with enough trades to grade).
    A future with too few trades is 'not graded', not 'lost money'; the survival share still counts it as a miss."""
    rs = np.random.default_rng(seed); wins = [0] * len(genomes); means = [[] for _ in genomes]
    for _ in range(n):
        m = make_future(O, L, C, V, days, rs, index=index)
        for i, g in enumerate(genomes):
            t, ex = bc.trades(m, g)
            if ex.size >= bc.MIN_TRADES:
                means[i].append(float(ex.mean())); wins[i] += ex.mean() > 0
    return [(w / n, float(np.mean(mm)) if mm else 0.0, len(mm)) for w, mm in zip(wins, means)]

# ---------------- learning bots ----------------
def features(m):
    with np.errstate(all="ignore"):
        f = [m.ret[1], m.ret[5], m.ret[20], m.C / m.hi[55] - 1, np.log(m.V / m.avgv), m.gap, (m.C > m.ma200).astype(np.float32)]
    return np.stack(f, -1).astype(np.float32)                         # stocks x days x 7

def train_neuron(X, y, steps=300, rate=0.5):
    """The owner's neuron, logistic version: p = sigmoid(w.x + b); loss gradient (p - y) x; step w -= rate * grad."""
    mu, sd = X.mean(0), X.std(0) + 1e-9; Xs = (X - mu) / sd
    w = np.zeros(X.shape[1], np.float32); b = 0.0
    for _ in range(steps):
        p = 1 / (1 + np.exp(-(Xs @ w + b))); e = p - y
        w -= rate * (Xs.T @ e) / len(y); b -= rate * float(e.mean())
    return w, b, mu, sd

# ---------------- more brains (from the owner's ML / rocket videos) ----------------
class Forest:
    """Random forest: 100 decision trees vote (learns combined if-this-and-that rules). Needs scikit-learn."""
    def __init__(self, X, y, seed):
        from sklearn.ensemble import RandomForestClassifier
        self.mu, self.sd = X.mean(0), X.std(0) + 1e-9
        n = min(len(y), 120_000); j = np.random.default_rng(seed).choice(len(y), n, replace=False)
        self.m = RandomForestClassifier(n_estimators=100, max_depth=6, min_samples_leaf=200, n_jobs=-1, random_state=seed)
        self.m.fit((X[j] - self.mu) / self.sd, y[j])
    def prob(self, X):
        p = self.m.predict_proba((X - self.mu) / self.sd)
        if p.shape[1] == 1: return np.full(len(X), float(self.m.classes_[0] == 1))   # trained on one answer only (Nov 20 S&P crash)
        return p[:, list(self.m.classes_).index(1)]

class Rocket:
    """Reinforcement learning, like the rocket-landing video, built from scratch in numpy (no ML library).
    A small neural network (inputs -> 16 hidden -> buy probability) plays 'flights' of 20 decisions on past days.
    Reward: the trade's return vs the average stock after costs (0 if it stays out). Crash: a flight that loses more
    than 10% gets an extra -10% penalty, like the rocket's -100. It learns by REINFORCE: actions that led to
    better-than-usual rewards become more likely. It never sees the days it will be tested on."""
    def __init__(self, X, rew, seed, iters=1200, flights=64, steps=20, lr=0.05, crash=-0.10):
        rs = np.random.default_rng(seed); self.mu, self.sd = X.mean(0), X.std(0) + 1e-9; Xs = (X - self.mu) / self.sd
        d = X.shape[1]; self.W1 = rs.normal(0, 0.3, (d, 16)); self.b1 = np.zeros(16); self.w2 = rs.normal(0, 0.3, 16); self.b2 = 0.0
        base = 0.0
        for _ in range(iters):
            idx = rs.integers(0, len(Xs), (flights, steps)); x = Xs[idx]; r = rew[idx]
            h = np.tanh(x @ self.W1 + self.b1); p = 1 / (1 + np.exp(-(h @ self.w2 + self.b2)))
            a = (rs.random(p.shape) < p).astype(float); got = a * r
            flight = got.sum(1, keepdims=True); pen = np.where(flight < crash, crash, 0.0) * a / np.maximum(a.sum(1, keepdims=True), 1)
            adv = got + pen - base * a; base = 0.9 * base + 0.1 * float(got[a > 0].mean()) if a.any() else base
            g = (a - p) * adv                                   # d log-prob / d logit, times advantage
            dh = g[..., None] * self.w2 * (1 - h ** 2)
            n = flights * steps
            self.w2 += lr * (g[..., None] * h).reshape(n, 16).sum(0) / n * 10; self.b2 += lr * g.mean() * 10
            self.W1 += lr * np.einsum("fsd,fsk->dk", x, dh) / n * 10; self.b1 += lr * dh.reshape(n, 16).mean(0) * 10
    def prob(self, X):
        h = np.tanh(((X - self.mu) / self.sd) @ self.W1 + self.b1); return 1 / (1 + np.exp(-(h @ self.w2 + self.b2)))

def learning_bot(m, band, hold=5, exam_frac=0.3, seed=1, brain="neuron"):
    """brain: 'neuron' (the desk's logistic neuron), 'forest' (random forest) or 'rocket' (reinforcement learning)."""
    exam_from = int(m.T * (1 - exam_frac)); cut = np.linspace(250, exam_from, bc.LEVELS + 1).astype(int)
    F = features(m); target = m.fwd[hold] - bc.bench(m, band, hold)
    F = np.nan_to_num(F, nan=0.0, posinf=0.0, neginf=0.0)            # a missing input (e.g. no volume in 1930) counts as neutral
    ok = m.band[band] & np.isfinite(target) & np.isfinite(m.C)
    rs = np.random.default_rng(seed); levels = []; passed = 0
    def segment(lo, hi):
        k = ok.copy(); k[:, :lo] = False; k[:, hi:] = False; return k
    def fit(lo, hi):
        k = segment(lo, max(lo, hi - hold)); X, Y, Rw = F[k], (target[k] > 0).astype(np.float32), np.clip((target - m.cost)[k], -0.5, 0.5)
        if len(Y) > 300_000: j = rs.choice(len(Y), 300_000, replace=False); X, Y, Rw = X[j], Y[j], Rw[j]
        if brain == "forest": return Forest(X, Y, seed)
        if brain == "rocket": return Rocket(X, Rw, seed)
        return train_neuron(X, Y)
    def test(model, lo, hi):
        k = segment(lo, hi); p = np.full(k.shape, np.nan, np.float32)
        if isinstance(model, tuple): w, b, mu, sd = model; p[k] = 1 / (1 + np.exp(-(((F[k] - mu) / sd) @ w + b)))
        else: p[k] = model.prob(F[k])
        def pr(Z):
            if isinstance(model, tuple): w, b, mu, sd = model; return 1 / (1 + np.exp(-(((Z - mu) / sd) @ w + b)))
            return model.prob(Z)
        import brains as _br                                                     # trade its 10% most confident calls, the line set on TRAINING days
        thr = _br.train_cutoff(pr, ok, F, lo, hold, 0.10) if np.isfinite(p).any() else 1.0
        g = {"sig": "drop", "k": 1, "x": 0.03, "n": 20, "v": 2, "trend": "none", "hold": hold, "stop": 0, "band": band}
        t = np.nonzero(p >= thr)[1]; ex = (m.fwd[hold] - bc.bench(m, band, hold) - m.cost)[p >= thr]
        keep = np.isfinite(ex); return bc.score(m, t[keep], np.clip(ex[keep], -0.9, 1.0), lo, hi, hold)
    for i in range(bc.LEVELS):
        lo = cut[i]; model = fit(cut[0] - 250 + 60, lo) if i else None
        if model is None: levels.append({"n": 0, "mean": 0.0, "z": 0.0}); passed += 1; continue   # level 1: nothing to learn from yet
        s = test(model, lo, cut[i + 1]); levels.append(s)
        if s["n"] < bc.MIN_TRADES or s["mean"] <= 0 or s["z"] < bc.LEVEL_Z[i + 1]: break
        passed += 1
    exam = test(fit(60, exam_from), exam_from, m.T) if passed == bc.LEVELS else None
    return {"band": band, "brain": brain, "levels_passed": passed, "levels": levels, "exam": exam,
            "exam_passed": bool(exam and exam["n"] >= bc.MIN_TRADES and exam["mean"] > 0 and exam["z"] >= 2)}

# ---------------- bot economy: to live, a bot must make money ----------------
def economy(m, g, start=20.0, frac=0.10, die_at=1.0):
    """Paper wallet: each trade risks `frac` of the current wallet, in date order; dead at `die_at`.
    Trades on the same day share the wallet; returns are already after costs and vs the average stock."""
    t, ex = bc.trades(m, g); order = np.argsort(t, kind="stable"); t, ex = t[order], ex[order]
    hard = g.get("mode") == "hard"; lives = 2 if hard else 1; payout = 1.0     # hard mode: 2 lives, losses shrink winnings
    w = start; low = start; deaths = 0
    for day in np.unique(t):
        r = float(ex[t == day].mean()); gain = frac * r * min(int((t == day).sum()), 5) / g["hold"]   # positions overlap for `hold` days: no hidden leverage
        w += w * (gain * payout if gain > 0 else gain)
        if hard and r < 0: payout = max(0.5, payout * 0.995)
        low = min(low, w)
        if w <= die_at:
            deaths += 1
            if deaths >= lives: w = 0.0; break
            w = start                                                           # second life: fresh $20, shrunken payout kept
    return {"start": start, "end": round(w, 2), "low": round(low, 2), "trades": int(t.size), "died": deaths >= lives,
            "mode": "hard" if hard else "normal", "lives_used": deaths, "payout": round(payout, 3)}

# ---------------- reason inputs: market fear and interest rates ----------------
def macro_series(path, days):
    """A Yahoo daily series (e.g. ^VIX, ^TNX) aligned to `days`, carried forward; NaN before it starts."""
    import json
    r = json.load(open(path))["chart"]["result"][0]
    d = np.array([t // 86400 for t in r["timestamp"]]); c = np.array([x if x is not None else np.nan for x in r["indicators"]["quote"][0]["close"]], float)
    j = np.searchsorted(d, days, side="right") - 1
    out = np.where(j >= 0, c[np.clip(j, 0, len(c) - 1)], np.nan)
    return out.astype(np.float32)

MACRO = {}      # filled by nightly.py: {"vix": array over days, "tnx": array over days}

_old_features = features
def features(m):  # noqa: F811  chart features + reasons: fear level, fear jump, rate move over a month
    f = _old_features(m)
    if hasattr(m, "lens"):                                            # borrowed indicators (Lens score, RSI, %B, MACD, ADX, Qlib factors)
        extra = [m.rsi / 100, m.pctb, m.macd_hist * 100, m.adx / 100, m.lens / 100, m.r2, m.updays, m.rsv]
        f = np.concatenate([f, np.stack([np.asarray(x, np.float32) for x in extra], -1)], -1)
    if not MACRO: return f
    S = m.C.shape[0]; vix, tnx = MACRO["vix"], MACRO["tnx"]
    with np.errstate(all="ignore"):
        extra = [np.log(vix), np.log(vix) - np.log(np.roll(vix, 5)), tnx - np.roll(tnx, 20)]
    extra = [np.broadcast_to(x[None, :], (S, len(x))) for x in extra]
    return np.concatenate([f, np.stack(extra, -1).astype(np.float32)], -1)

# ---------------- capacity: how much money a bot could really trade ----------------
def capacity(m, g, share=0.01):
    """Max dollars per trade = 1% of the stock's typical daily dollar volume (more would move the price).
    Returns the median per trade and a rough yearly total if every trade were taken at that size."""
    t, ex = bc.trades(m, g)
    if t.size == 0: return {"per_trade": 0, "per_year": 0}
    sig = bc.signal(m, g); rows, cols = np.nonzero(sig & np.isfinite(m.dv))
    caps = share * m.dv[rows, cols]; per_year_trades = t.size / max(m.T / 252, 1)
    return {"per_trade": int(np.nanmedian(caps)), "trades_per_year": round(per_year_trades, 1)}

# ---------------- risk manager: how big each bet should be ----------------
def risk_manager(m, g, sizes=(0.02, 0.05, 0.10, 0.20, 0.35)):
    """Plays the $20 wallet game at several bet sizes; picks the size with the best ending wallet that never
    fell below half its start. Too small wastes an edge, too big dies of a losing streak."""
    runs = {f: economy(m, g, frac=f) for f in sizes}
    safe = {f: r for f, r in runs.items() if not r["died"] and r["low"] >= 10}
    pick = max(safe, key=lambda f: safe[f]["end"]) if safe else None
    if pick is not None and safe[pick]["end"] <= 20: pick = None          # every size loses money: the right bet is no bet
    return {"pick": pick, "ends": {f: r["end"] for f, r in runs.items()}}

# ---------------- the gauntlet: many different ways to catch a fake edge ----------------
def gauntlet(m, g, seed=7):
    """Extra tests a graduate must ALL pass before it is called PROVEN. Each one catches a different kind of fake:
      placebo   - random entries in the same stocks and days, same holding time: the real rule must beat 95% of 200 placebos
      late      - entering one day late must still make money (catches look-ahead bugs and too-fast-to-catch edges)
      costs x2  - double trading costs must still leave a profit (catches edges that only exist on paper)
      halves    - both halves of the stock list must be profitable on their own (catches edges carried by a few names)
      neighbors - most one-step variations of the rule must also make money (catches a lucky spike in the settings)"""
    rs = np.random.default_rng(seed); out = {}
    t, ex = bc.trades(m, g); real = float(ex.mean()) if ex.size else 0.0
    # placebo: same number of random (stock, day) entries from all valid ones in the bot's group
    h = g["hold"]; base = m.fwd[h] - bc.bench(m, g["band"], h) - m.cost
    pool = np.argwhere(m.band[g["band"]] & np.isfinite(base))
    if ex.size and len(pool) > ex.size:
        means = [float(np.clip(base[tuple(pool[rs.choice(len(pool), ex.size, replace=False)].T)], -0.9, 1.0).mean()) for _ in range(200)]
        out["placebo"] = float(np.mean(np.array(means) >= real)) <= 0.05
    else: out["placebo"] = False
    _, e1 = bc.trades(m, g, delay=1); out["late"] = bool(e1.size and e1.mean() > 0)
    _, e2 = bc.trades(m, g, cost_mult=2); out["costs x2"] = bool(e2.size and e2.mean() > 0)
    idx = np.arange(m.C.shape[0]); rs.shuffle(idx); halves = [bc.trades(m, g, rows=idx[: len(idx) // 2])[1], bc.trades(m, g, rows=idx[len(idx) // 2:])[1]]
    out["halves"] = all(x.size and x.mean() > 0 for x in halves) if m.C.shape[0] > 1 else True
    nb = []
    for k, vals in bc.GENES.items():
        if k in ("mode",) or g.get(k) not in vals: continue
        i = vals.index(g[k])
        for j in (i - 1, i + 1):
            if 0 <= j < len(vals) and vals[j] != g[k]:
                _, e = bc.trades(m, {**g, k: vals[j]}); nb.append(bool(e.size and e.mean() > 0))
    out["neighbors"] = bool(nb) and sum(nb) / len(nb) >= 0.6
    out["passed"] = all(out.values())
    return out
