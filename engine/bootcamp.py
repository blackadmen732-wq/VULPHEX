# Bootcamp (research only, no orders). Owner-approved design, Nov 13 2026: docs/strategy-pipeline.md stage 1.
#
#   Training years are cut into 8 levels, oldest first. A bot must pass every level, each on time it has never
#   traded, with a bar that rises per level. Fail one level: deleted. Judged on many trades per level, never one.
#   The crowd bar: a graduate must also clear a z that rises with every bot that ever tried (luck filter).
#   Copy only bots that reached the highest levels; a copy that does worse than its parent dies, parent stays.
#   Graveyard: rule pieces that keep appearing in dead bots and never in survivors are banned for new bots.
#   Variety: two bots with the same trades can't both live; the better one stays.
#   Exam: the newest years are locked. Graduates trade them once. Pass -> paper trading candidate.
#   Alarm (run first, every time): pure noise must give 0 graduates; a planted pattern must be found.
#
# Usage: python3 bootcamp.py <dir of Yahoo daily JSON (stocks_fetch_daily.py)> [generations=30] [population=300]
import glob, json, math, os, random, sys
from collections import Counter
import numpy as np, pandas as pd

HOLDS = [1, 2, 3, 5, 10, 20]
COST = {"ugly": 0.006, "popular": 0.001}
LEVELS = 8
LEVEL_Z = [None, 0.0, 0.0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5]   # level 1 = "works at all"; then the bar rises
MIN_TRADES = 30

# ---------------- market data -> feature arrays ----------------
LAST_SYMBOLS = []; LAST_HIGH = None     # highs kept aside so every caller keeps the 5-value return
def load_yahoo(d):
    series = {}
    for p in glob.glob(f"{d}/*.json"):
        try: r = json.load(open(p))["chart"]["result"][0]
        except Exception: continue
        ts = r.get("timestamp"); q = r["indicators"]["quote"][0]; adj = (r["indicators"].get("adjclose") or [{}])[0].get("adjclose")
        if ts and adj and len(ts) >= 300: series[os.path.basename(p)[:-5]] = (ts, q, adj)
    days = sorted({t // 86400 for ts, _, _ in series.values() for t in ts}); col = {x: i for i, x in enumerate(days)}
    S, T = len(series), len(days)
    O, L, C, V = (np.full((S, T), np.nan, np.float32) for _ in range(4)); H = np.full((S, T), np.nan, np.float32)
    for i, (ts, q, adj) in enumerate(series.values()):
        for j, t in enumerate(ts):
            c, a = q["close"][j], adj[j]
            if c is None or a is None or c <= 0 or q["open"][j] is None or q["low"][j] is None: continue
            f = a / c; k = col[t // 86400]
            O[i, k], L[i, k], C[i, k], V[i, k] = q["open"][j] * f, q["low"][j] * f, a, (q["volume"][j] or 0) / f
            if q.get("high") and q["high"][j] is not None: H[i, k] = q["high"][j] * f
    global LAST_SYMBOLS, LAST_HIGH; LAST_SYMBOLS = list(series); LAST_HIGH = H                 # row order, so outside data (insider filings) can line up
    return O, L, C, V, np.array(days)

def shift(x, n):
    y = np.full_like(x, np.nan)
    if n > 0: y[:, n:] = x[:, :-n]
    elif n < 0: y[:, :n] = x[:, -n:]
    else: y[:] = x
    return y
def roll(x, n, fn):
    return getattr(pd.DataFrame(x.T).rolling(n, min_periods=max(1, n * 3 // 4)), fn)().to_numpy(np.float32).T

class Market:
    def __init__(self, O, L, C, V, days, index=False, H=None):
        # index=True: one market index (e.g. S&P 500 since 1927). Every day counts as "popular", and a trade is
        # measured against simply holding the index for the same number of days on average (its long-run drift).
        self.T = C.shape[1]; self.days = days; self.week = days // 7; self.W = int(self.week.max()) + 1
        with np.errstate(all="ignore"):
            dv = roll(C * V, 60, "median")
            self.band = {"ugly": (dv >= 3e5) & (dv <= 2e7) & (C >= 2), "popular": (dv >= 2e8) & (C >= 2)}
            if index: self.band = {"ugly": np.zeros_like(C, bool), "popular": np.isfinite(C)}
            self.ma200 = roll(C, 200, "mean"); self.ma50 = roll(C, 50, "mean"); self.C = C
            self.avgv = roll(V, 50, "mean"); self.V = V
            self.ret = {k: C / shift(C, k) - 1 for k in (1, 2, 3, 5, 10, 20, 120)}
            self.hi = {n: roll(C, n, "max") for n in (20, 55, 120, 250)}
            self.gap = O / shift(C, 1) - 1
            self.nxt = shift(O, -1)
            self.fwd = {h: shift(C, -h) / self.nxt - 1 for h in HOLDS}
            self.minlow = {h: shift(roll(L, h, "min"), -h) for h in HOLDS}
            self.bench = {b: {h: np.nanmean(np.where(self.band[b], self.fwd[h], np.nan), axis=0) for h in HOLDS} for b in self.band}
            # index mode (one index, or many markets): each series is judged against simply holding THAT series
            # (its own long-run average move), so a fast-rising market like crypto can't make every rule look bad or good
            if index: self.bench["popular"] = {h: np.broadcast_to(np.nanmean(self.fwd[h], axis=1, keepdims=True), C.shape).astype(np.float32) for h in HOLDS}
            # MARKET MOOD (uses only past days): an equal-weight market line from all series. crash = market below its
            # 200-day average AND 20-day swings in its top 20% of the past year; trend = above the average with swings
            # below the past year's median; calm = everything else.
            mret = np.nanmedian(self.ret[1], axis=0); mret = np.where(np.isfinite(mret), mret, 0.0)
            ml = pd.Series(np.cumprod(1 + mret)); vol = ml.pct_change().rolling(20, min_periods=15).std()
            above = (ml > ml.rolling(200, min_periods=150).mean()).to_numpy()
            q80 = vol.rolling(252, min_periods=150).quantile(0.8).to_numpy(); q50 = vol.rolling(252, min_periods=150).quantile(0.5).to_numpy()
            v = vol.to_numpy(); crash = (~above) & (v > q80); trend = above & (v < q50); calm = ~(crash | trend)
            self.mood = {"any": np.ones(self.T, bool), "crash": crash, "trend": trend, "calm": calm}
            # CALENDAR (known in advance, so no peeking): weekday 0=Mon, month 1-12, the last day before / first day
            # after a weekday market holiday
            d = np.asarray(days, dtype=np.int64); self.weekday = (d + 3) % 7
            self.month = np.array([int(np.datetime64(int(x), "D").astype("datetime64[M]").astype(int) % 12 + 1) for x in d])
            gap = np.diff(d); hol = np.zeros(self.T, bool); hol[:-1] = (gap > 1) & ~((self.weekday[:-1] == 4) & (gap == 3))
            self.pre_holiday = hol; self.post_holiday = np.concatenate([[False], hol[:-1]])
            # STRENGTH VS THE MARKET: a stock's 20-day return minus the market's
            mk20 = pd.Series(np.cumprod(1 + mret)).pct_change(20).to_numpy(np.float32)
            self.rel20 = self.ret[20] - mk20[None, :]
            # VOLATILITY SQUEEZE: 20-day swings near their lowest of the past year
            sw = roll(np.abs(self.ret[1]), 20, "mean"); self.squeeze = sw <= 1.2 * roll(sw, 252, "min")
            self.insider = np.zeros_like(C, bool)                     # filled by the nightly job from SEC filings
            self.free = {}                                            # filled by the nightly job from freedata.py
            # REAL COST PER STOCK PER DAY (round trip): a half-spread that grows as trading thins out,
            # ~0.05% for a $1B-a-day stock, ~0.4% at $1M a day, capped at 2% a side; plus 0.05% fees and slippage.
            # An index is treated like an index fund: 0.05%.
            self.dv = dv
            half = np.clip(0.002 * (1e7 / np.maximum(dv, 1.0)) ** 0.3, 0.0001, 0.02)
            self.cost = np.where(np.isfinite(dv), 2 * half + 0.0005, 0.01).astype(np.float32)
            if index: self.cost = np.full_like(C, 0.0005)
        self._indicators(O, L, C, V, H)

    def _indicators(self, O, L, C, V, H):
        """Borrowed ideas, written fresh (no code copied):
          - AI Agent Lens (MIT, roan-maverick/tradingview-indicator-for-ai-agents): regime + 0-100 long confluence score
            from EMA 20/50/200, RSI 14, MACD histogram, DMI/ADX 14, relative volume, higher-timeframe bias.
          - Classic indicators (as in pandas-ta, MIT): RSI, Bollinger %B, MACD.
          - Qlib Alpha158-style factors (MIT, microsoft/qlib): position in the 20-day range (RSV), trend straightness
            (R-squared of 20 days of log price), share of up days in 20 (CNTP)."""
        ew = lambda x, **k: pd.DataFrame(x.T).ewm(adjust=False, **k).mean().to_numpy(np.float32).T
        if H is None: H = np.fmax(O, C)                               # no highs (simulations): lower bound
        with np.errstate(all="ignore"):
            ema20, ema50, ema200 = ew(C, span=20), ew(C, span=50), ew(C, span=200)
            d = C - shift(C, 1); up = ew(np.where(d > 0, d, 0), alpha=1 / 14); dn = ew(np.where(d < 0, -d, 0), alpha=1 / 14)
            self.rsi = 100 - 100 / (1 + up / dn)
            macd = ew(C, span=12) - ew(C, span=26); hist = macd - ew(macd, span=9); self.macd_hist = hist / C
            pc = shift(C, 1); tr = np.fmax(H - L, np.fmax(np.abs(H - pc), np.abs(L - pc)))
            upm, dnm = H - shift(H, 1), shift(L, 1) - L
            pdm = np.where((upm > dnm) & (upm > 0), upm, 0); ndm = np.where((dnm > upm) & (dnm > 0), dnm, 0)
            atr = ew(tr, alpha=1 / 14); dip, dim = 100 * ew(pdm, alpha=1 / 14) / atr, 100 * ew(ndm, alpha=1 / 14) / atr
            adx = ew(100 * np.abs(dip - dim) / (dip + dim), alpha=1 / 14); self.adx = adx
            relv = V / roll(V, 20, "mean"); htf = shift(C, 1) > shift(ew(C, span=250), 1)          # ~50-week EMA, yesterday's values
            high_vol = atr >= roll(atr, 100, "max") * 0.9                  # ATR near the top of its last 100 days
            trend_dn = (C < ema200) & (ema200 < shift(ema200, 5)) & (adx >= 20)
            lt = 7 * (ema20 > ema50) + 7 * (ema50 > ema200) + 6 * (C > ema20)
            lm = np.where(self.rsi > 50, np.where(self.rsi >= 75, 4, 10), 0) + 5 * (hist > 0) + 5 * (hist > shift(hist, 1))
            ls = 10 * (dip > dim) + 10 * ((dip > dim) & (adx >= 20))
            bull = C > O; lv = np.where(bull & (relv >= 1.5), 20, np.where(bull & (relv >= 1), 12, np.where(bull, 6, 0)))
            self.lens = (lt + lm + ls + lv + 20 * htf).astype(np.float32)
            self.lens_ok = ~trend_dn & ~high_vol
            ma20, sd20 = roll(C, 20, "mean"), roll(C, 20, "std"); self.pctb = (C - (ma20 - 2 * sd20)) / (4 * sd20)
            lo20 = roll(C, 20, "min"); self.rsv = (C - lo20) / (self.hi[20] - lo20)
            lc = np.log(C); tt = np.arange(self.T, dtype=np.float32)[None, :].repeat(C.shape[0], 0)
            cov = roll(lc * tt, 20, "mean") - roll(lc, 20, "mean") * roll(tt, 20, "mean")
            self.r2 = (cov / (roll(lc, 20, "std") * roll(tt, 20, "std") * 19 / 20)) ** 2; self.slope_up = cov > 0
            self.updays = roll((d > 0).astype(np.float32), 20, "mean")

# ---------------- bots ----------------
GENES = {"sig": ["drop", "rise", "breakout", "momentum", "gapdown", "volspike",
                 "weekday", "month", "preholiday", "postholiday", "strong", "weak", "squeeze", "capitulation", "insider", "shorty", "buzz", "goodnews",
                 "lens", "rsilow", "rsihigh", "bblow", "macdup", "rsvlow", "straight", "updays", "takeoff"],
         "sig2": ["none", "none", "none", "drop", "breakout", "momentum", "volspike", "strong", "weak", "squeeze", "insider", "shorty", "buzz", "goodnews",
                  "lens", "rsilow", "bblow", "straight"],
         "score": [60, 70, 80, 90],   # COMBO: both must agree
         "day": [0, 1, 2, 3, 4], "mon": list(range(1, 13)),
         "k": [1, 2, 3, 5, 10, 20],
         "x": [0.03, 0.05, 0.08, 0.12, 0.2, 0.3], "n": [20, 55, 120, 250], "v": [2, 3, 5], "trend": ["none", "up", "down"],
         "hold": HOLDS, "stop": [0, 0, 0.05, 0.1, 0.15], "band": ["ugly", "popular"],
         # game mode, chosen by the bot's own genes (never forced): "hard" = 3 children per breeding (faster improvement),
         # a level bar 0.25 higher, and in the wallet game 2 lives but every losing day shrinks its future winnings.
         "mode": ["normal", "normal", "hard"],
         # market-mood specialist: trades only in that mood (see Market.mood); "any" trades in every mood
         "mood": ["any", "any", "calm", "trend", "crash"]}

LESSONS = {"dead": Counter(), "alive": Counter()}   # carried across nights: how often each rule piece died or survived
def _pick(r, k):
    """Choose a gene value, steered by past lessons: pieces that keep dying are picked less, survivors more."""
    vals = GENES[k]; d, a = LESSONS["dead"], LESSONS["alive"]
    w = [max(0.05, (1 + a[f"{k}={v}"]) / (1 + 0.02 * d[f"{k}={v}"])) for v in vals]
    return r.choices(vals, weights=w)[0]
def random_bot(r, banned):
    for _ in range(50):
        g = {k: _pick(r, k) for k in GENES}
        if not pieces(g) & banned: return g
    return g
def mutate(g, r, banned):
    for _ in range(50):
        c = dict(g); k = r.choice(list(GENES)); c[k] = _pick(r, k)
        if c != g and not pieces(c) & banned: return c
    return dict(g)
def crossover(a, b, r, banned):
    """Two parents make a child: each gene comes from one parent or the other (like sexual reproduction)."""
    for _ in range(20):
        c = {k: r.choice([a.get(k, GENES[k][0]), b.get(k, GENES[k][0])]) for k in GENES}
        if not pieces(c) & banned: return c
    return dict(a)
def niche(g): return (g["band"], g.get("mood", "any"))   # an "island": bots compete mostly with their own kind

def pieces(g):  # the rule pieces a bot is built from (what the graveyard tracks)
    s = g["sig"]; p = {f"sig={s}", f"hold={g['hold']}", f"band={g['band']}", f"trend={g['trend']}", f"stop={g['stop']}", f"mode={g.get('mode', 'normal')}", f"mood={g.get('mood', 'any')}"}
    if s in ("drop", "rise"): p |= {f"k={g['k']}", f"x={g['x']}"}
    if s == "breakout": p.add(f"n={g['n']}")
    if s in ("momentum", "gapdown"): p.add(f"x={g['x']}")
    if s == "volspike": p.add(f"v={g['v']}")
    if s == "weekday": p.add(f"day={g.get('day')}")
    if s == "month": p.add(f"mon={g.get('mon')}")
    if s in ("strong", "weak", "capitulation"): p.add(f"x={g['x']}")
    if s == "takeoff": p |= {f"k={g['k']}", f"x={g['x']}"}
    if g.get("sig2", "none") != "none": p.add(f"sig2={g['sig2']}")
    if "lens" in (s, g.get("sig2")): p.add(f"score={g.get('score')}")
    return frozenset(p)

def base_signal(m, s, g):
    """One building block, as a stocks x days true/false grid (decided at the close; trades start next morning)."""
    S = m.C.shape[0]; row = lambda v: np.broadcast_to(v[None, :], (S, m.T))
    with np.errstate(all="ignore"):
        if s == "drop": return m.ret[g["k"]] <= -g["x"]
        if s == "rise": return m.ret[g["k"]] >= g["x"]
        if s == "breakout": return m.C >= m.hi[g["n"]]
        if s == "momentum": return (m.ret[120] >= g["x"] * 3) & (m.C > m.ma50)
        if s == "gapdown": return m.gap <= -g["x"]
        if s == "volspike": return (m.V >= g["v"] * m.avgv) & (m.ret[1] > 0)
        if s == "weekday": return row(m.weekday == g.get("day", 0)) & np.isfinite(m.C)
        if s == "month": return row(m.month == g.get("mon", 1)) & np.isfinite(m.C)
        if s == "preholiday": return row(m.pre_holiday) & np.isfinite(m.C)
        if s == "postholiday": return row(m.post_holiday) & np.isfinite(m.C)
        if s == "strong": return m.rel20 >= g["x"]
        if s == "weak": return m.rel20 <= -g["x"]
        if s == "squeeze": return m.squeeze & (m.C >= m.hi[20])
        if s == "capitulation": return (m.ret[1] <= -g["x"]) & (m.V >= 2 * m.avgv)
        if s == "insider": return m.insider.copy()
        if s in ("shorty", "buzz"):                               # Nov 20 free data: short selling / Wikipedia attention far above that stock's normal
            a = (getattr(m, "free", {}) or {}).get("shortz" if s == "shorty" else "buzz")
            return np.zeros_like(m.C, bool) if a is None or np.ndim(a) != 2 else np.nan_to_num(a) >= (2.0 if s == "shorty" else 1.5)
        if s == "goodnews":                                       # Claude scored last night's headlines / 8-Ks clearly good (news.py)
            a = (getattr(m, "free", {}) or {}).get("news")
            return np.zeros_like(m.C, bool) if a is None or np.ndim(a) != 2 else np.nan_to_num(a) >= 0.5
        if s == "lens": sc = g.get("score", 70); return (m.lens >= sc) & (shift(m.lens, 1) < sc) & m.lens_ok   # score crosses the bar
        if s == "rsilow": return m.rsi <= 30
        if s == "rsihigh": return m.rsi >= 70
        if s == "bblow": return m.pctb < 0
        if s == "macdup": return (m.macd_hist > 0) & (shift(m.macd_hist, 1) <= 0)
        if s == "rsvlow": return m.rsv <= 0.1
        if s == "straight": return (m.r2 >= 0.8) & m.slope_up
        if s == "updays": return m.updays >= 0.7
        if s == "takeoff":   # growth that is SPEEDING UP: up x over the last k days, and that's more than double the k days before
            k = g["k"] if g["k"] >= 5 else 20; now = m.ret[k] if k in m.ret else m.C / shift(m.C, k) - 1
            before = shift(m.C, k) / shift(m.C, 2 * k) - 1
            return (now >= g["x"]) & (now > 2 * np.maximum(before, 0))
    return np.zeros_like(m.C, bool)

def signal(m, g):
    s = g["sig"]
    x = base_signal(m, s, g)
    if g.get("sig2", "none") not in ("none", s): x = x & base_signal(m, g["sig2"], g)
    with np.errstate(all="ignore"):
        if g["trend"] == "up": x &= m.C > m.ma200
        elif g["trend"] == "down": x &= m.C < m.ma200
    return x & m.band[g["band"]] & m.mood[g.get("mood", "any")][None, :]

def bench(m, band, h):
    b = m.bench[band][h]; return b[None, :] if b.ndim == 1 else b

def trades(m, g, delay=0, cost_mult=1.0, rows=None):
    """Every trade the bot would make: (day index, return vs the average stock in its group, after costs).
    delay: enter this many days late (an honest edge survives a slow trader); cost_mult: stress the costs;
    rows: only these stocks (to check the edge isn't carried by a few names)."""
    h = g["hold"]; r = m.fwd[h]
    if g["stop"]:
        with np.errstate(all="ignore"): r = np.where(m.minlow[h] <= m.nxt * (1 - g["stop"]), -g["stop"] - 0.005, r)
    sig = signal(m, g)
    if delay: sig = np.concatenate([np.zeros((sig.shape[0], delay), bool), sig[:, :-delay]], 1)
    if rows is not None: keep = np.zeros(sig.shape[0], bool); keep[rows] = True; sig = sig & keep[:, None]
    ex = r - bench(m, g["band"], h) - m.cost * cost_mult
    ok = sig & np.isfinite(ex)
    return np.nonzero(ok)[1], np.clip(ex[ok], -0.9, 1.0)

def score(m, t, ex, lo, hi, hold=None):
    """Trades ENTERED on days lo..hi-1 that also EXIT before hi (owner's review, Nov 21: a trade entered just before a
    cutoff used to finish on prices after it, so the sealed exam leaked into practice scores). A trade signalled on
    day t enters at t+1's open and exits at t+hold's close; hold=None assumes the longest hold (safe side)."""
    h = max(HOLDS) if hold is None else hold
    k = (t >= lo) & (t < hi) & ((t + h < hi) | (hi >= m.T)); t, ex = t[k], ex[k]
    if ex.size < 3: return {"n": int(ex.size), "mean": 0.0, "z": 0.0}
    wk = m.week[t] - m.week[t].min(); s = np.bincount(wk, ex); c = np.bincount(wk); wm = s[c > 0] / c[c > 0]
    z = wm.mean() / (wm.std(ddof=1) / math.sqrt(wm.size)) if wm.size > 2 and wm.std() > 0 else 0.0
    return {"n": int(ex.size), "mean": float(ex.mean()), "z": float(z)}

def required_z(tried):
    p = 0.05 / max(tried, 1); t = math.sqrt(-2 * math.log(p))
    return t - (2.515517 + 0.802853 * t + 0.010328 * t * t) / (1 + 1.432788 * t + 0.189269 * t * t + 0.001308 * t ** 3)

# ---------------- the bootcamp ----------------
def run(m, gens=30, size=300, seed=1, exam_frac=0.3, quiet=False, seeds=None, tried_before=0, exams_before=0):
    """tried_before / exams_before: bots and exam attempts from ALL earlier nights. The luck bar and the exam bar
    count every try ever made, so running every night can't slowly fish out a lucky winner."""
    """seeds: bots proposed in advance (e.g. by the AI review); they enter round 1 and face the same tests."""
    exam_from = int(m.T * (1 - exam_frac)); start = 250            # first year only warms up the 250-day features
    cut = np.linspace(start, exam_from, LEVELS + 1).astype(int)
    r = random.Random(seed); dead_pieces = Counter(); alive_pieces = Counter()
    banned = {p for p, n in LESSONS["dead"].items() if n >= 200 and LESSONS["alive"][p] == 0}   # yesterday's graveyard still applies
    tried = tried_before; graduates = []; log = []; died_at = Counter()     # why bots died: which level (= which era) beat them
    def go(g):
        t, ex = trades(m, g); lv = []
        for i in range(LEVELS):
            s = score(m, t, ex, cut[i], cut[i + 1], g["hold"]); lv.append(s)
            need = MIN_TRADES if i == 0 else MIN_TRADES
            bar = LEVEL_Z[i + 1] + (0.25 if g.get("mode") == "hard" and i > 0 else 0)
            if s["n"] < need or (i > 0 and (s["mean"] <= 0 or s["z"] < bar)):
                return i, lv, t, ex          # reached level i (0-based count of levels passed)
        return LEVELS, lv, t, ex
    pop = []                                                    # (bot, levels passed, trade fingerprint, overall score)
    stale = 0; record = (-1, -99.0); extinctions = 0; born_by = Counter()
    for gen in range(1, gens + 1):
        # ISLANDS: parents are the best of EACH niche (band x mood), not just the overall best, so one idea can't take over
        P = max(1, size // 5); ranked = sorted(pop, key=lambda p: (-p[1], -p[3]["z"])); by_niche = {}
        for p in ranked: by_niche.setdefault(niche(p[0]), []).append(p)
        per = max(1, P // max(1, len(by_niche))); parents = [p for ps in by_niche.values() for p in ps[:per]][:P] or ranked[:P]
        # STAGNATION: no progress for 5 rounds -> bigger mutations; 12 rounds -> EXTINCTION: keep 5 survivors, restart the rest
        strength = 1 + min(stale // 5, 2)
        if stale >= 12: parents = ranked[:5]; stale = 0; extinctions += 1
        new = []
        if gen == 1 and seeds:
            new += [({**random_bot(r, set()), **{k: v for k, v in sd.items() if k in GENES and v in GENES[k]}}, None) for sd in seeds[: size // 2]]
        while len(new) < size:
            u = r.random()
            if parents and len(parents) > 1 and u < 0.35:                             # CROSSOVER: two parents, ideally from different islands
                a, b = r.sample(parents, 2); c = crossover(a[0], b[0], r, banned)
                if r.random() < 0.5: c = mutate(c, r, banned)
                new.append((c, max(a, b, key=lambda p: (p[1], p[3]["z"])))); born_by["crossover"] += 1
            elif parents and u < 0.85:                                                # MUTATION, stronger when progress stalls
                par = r.choice(parents)
                for _ in range(3 if par[0].get("mode") == "hard" else 1):
                    c = par[0]
                    for _ in range(strength): c = mutate(c, r, banned)
                    new.append((c, par)); born_by["mutation"] += 1
            else: new.append((random_bot(r, banned), None)); born_by["newcomer"] += 1
        tried += len(new); zr = required_z(tried); pop_next = [p for p in parents]
        fps = {p[2]: i for i, p in enumerate(pop_next)}
        for g, par in new:
            lvl, lv, t, ex = go(g)
            if lvl < LEVELS: died_at[lvl + 1] += 1
            overall = score(m, t, ex, cut[0], cut[-1], g["hold"])
            if par is not None and (lvl, overall["z"]) <= (par[1], par[3]["z"]):   # a copy that's no better than its parent dies
                dead_pieces.update(pieces(g)); continue
            if lvl < LEVELS and lvl < 3:                                           # failed early: deleted
                dead_pieces.update(pieces(g)); continue
            fp = hash(t.tobytes()) if t.size else 0
            if fp in fps:                                                         # same trades as a living bot: keep the better
                j = fps[fp]
                if (lvl, overall["z"]) <= (pop_next[j][1], pop_next[j][3]["z"]): continue
                pop_next[j] = (g, lvl, fp, overall); continue
            fps[fp] = len(pop_next); pop_next.append((g, lvl, fp, overall)); alive_pieces.update(pieces(g))
            if lvl == LEVELS and overall["z"] >= zr and g not in [x[0] for x in graduates]:
                graduates.append((dict(g), overall, score(m, t, ex, exam_from, m.T, g["hold"])))
        pop = sorted(pop_next, key=lambda p: (-p[1], -p[3]["z"]))[:size]
        LESSONS["dead"].update(dead_pieces); LESSONS["alive"].update(alive_pieces); dead_pieces.clear(); alive_pieces.clear()
        banned = {p for p, n in LESSONS["dead"].items() if n >= 200 and LESSONS["alive"][p] == 0}
        best = pop[0] if pop else None
        if best and (best[1], best[3]["z"]) > record: record = (best[1], best[3]["z"]); stale = 0
        else: stale += 1
        log.append((gen, tried, zr, len(banned), best))
        if not quiet and (gen in (1, gens) or gen % 10 == 0) and best:
            print(f"  gen {gen}: bots tried {tried}, crowd bar z {zr:.2f}, banned pieces {len(banned)}, "
                  f"best reached level {best[1]}/8: {best[3]['n']} trades {best[3]['mean'] * 100:+.2f}% z {best[3]['z']:+.1f}  {best[0]}")
    exam_bar = max(2.0, required_z(exams_before + len(graduates)))       # the locked exam's bar also rises with every attempt ever
    exam = [(g, o, e, e["n"] >= MIN_TRADES and e["mean"] > 0 and e["z"] >= exam_bar) for g, o, e in graduates]
    # TEAM (symbiosis): the best bot of each island trades together as one portfolio, splitting money equally each day.
    # Different specialists can cover each other's bad eras. The team is one more try for the luck bar and faces the
    # same 8 levels and locked exam.
    team = None
    leaders = []; seen = set()
    for p in sorted(pop, key=lambda p: (-p[1], -p[3]["z"])):
        if niche(p[0]) not in seen: seen.add(niche(p[0])); leaders.append(p[0])
    leaders = leaders[:6]
    if len(leaders) >= 2:
        daily = {}
        for g in leaders:
            t, ex = trades(m, g)
            for d in np.unique(t): daily.setdefault(int(d), []).append(float(ex[t == d].mean()))
        tt = np.array(sorted(daily)); ee = np.array([np.mean(daily[d]) for d in tt]); th = max(g["hold"] for g in leaders)
        tried += 1; lvl = 0
        for i in range(LEVELS):
            sc = score(m, tt, ee, cut[i], cut[i + 1], th)
            if sc["n"] < MIN_TRADES or (i > 0 and (sc["mean"] <= 0 or sc["z"] < LEVEL_Z[i + 1])): break
            lvl += 1
        e = score(m, tt, ee, exam_from, m.T, th) if lvl == LEVELS else None
        team = {"members": leaders, "level": lvl, "train": score(m, tt, ee, cut[0], cut[-1], th), "exam": e,
                "passed": bool(e and e["n"] >= MIN_TRADES and e["mean"] > 0 and e["z"] >= 2 and score(m, tt, ee, cut[0], cut[-1], th)["z"] >= required_z(tried))}
    eras = [(int(m.days[cut[i]]), int(m.days[min(cut[i + 1], m.T - 1)])) for i in range(LEVELS)] if hasattr(m, "days") else None
    return {"graduates": exam, "tried": tried, "banned": sorted(banned), "best": [(p[0], p[1], p[3]) for p in pop[:5]],
            "pool": [p[0] for p in pop[:40]],                                    # recruits for the groups (groups.py)
            "exam_bar": exam_bar, "exams": exams_before + len(graduates), "died_at": dict(sorted(died_at.items())), "eras": eras, "team": team, "extinctions": extinctions, "born_by": dict(born_by)}

# ---------------- alarm: noise must fail, a planted pattern must be found ----------------
def synthetic(S=300, T=1250, plant=False, seed=3, scramble_from=None):
    rs = np.random.default_rng(seed)
    ret = rs.normal(0.0003, 0.025, (S, T)).astype(np.float32)
    if scramble_from is not None:                         # cutoff alarm: different prices from this day on, same past
        ret[:, scramble_from:] = np.random.default_rng(seed + 999).normal(0.0, 0.05, (S, T - scramble_from)).astype(np.float32)
    if plant:  # after a 5-day fall of 12%+, the next 5 days drift up 1% a day
        C = 50 * np.exp(np.cumsum(ret, axis=1))
        for t in range(6, T - 6):
            hit = C[:, t] / C[:, t - 5] - 1 <= -0.12
            ret[hit, t + 1:t + 6] += 0.01
    C = (50 * np.exp(np.cumsum(ret, axis=1))).astype(np.float32)
    O = shift(C, 1); O[:, 0] = C[:, 0]
    L = np.minimum(O, C) * (1 - np.abs(rs.normal(0, 0.01, (S, T)))).astype(np.float32)
    V = np.full((S, T), 2e5, np.float32)                       # ~$10M a day: the "ugly" group
    return Market(O, L, C, V, np.arange(19000, 19000 + T) + (np.arange(T) // 5) * 2)

def cutoff_alarm(seed=4, exam_frac=0.3):
    """Owner's review, Nov 21: scores before a cutoff must not depend on ANY price after it. Same history, then every
    price from the exam cutoff on is replaced: practice levels and the practice score of every bot must not move."""
    T = 1250; cut_day = int(T * (1 - exam_frac))
    a, b2 = synthetic(plant=True, seed=seed), synthetic(plant=True, seed=seed, scramble_from=cut_day)
    r = random.Random(seed); bots = [random_bot(r, set()) for _ in range(40)] + [
        {"sig": "drop", "sig2": "none", "k": 5, "x": 0.12, "hold": h, "stop": 0, "trend": "none", "band": "ugly", "mood": "any",
         "score": 70, "day": 0, "mon": 1, "n": 20, "v": 2} for h in HOLDS]
    cut = np.linspace(250, cut_day, LEVELS + 1).astype(int); bad = []
    for g in bots:
        ta, ea = trades(a, g); tb, eb = trades(b2, g)
        sa = [score(a, ta, ea, cut[i], cut[i + 1], g["hold"]) for i in range(LEVELS)] + [score(a, ta, ea, cut[0], cut[-1], g["hold"])]
        sb = [score(b2, tb, eb, cut[i], cut[i + 1], g["hold"]) for i in range(LEVELS)] + [score(b2, tb, eb, cut[0], cut[-1], g["hold"])]
        if sa != sb: bad.append(g)
    return not bad, {"bots": len(bots), "practice_scores_changed_by_future_prices": len(bad)}

def alarm(gens, size):
    saved = {k: Counter(v) for k, v in LESSONS.items()}; LESSONS["dead"].clear(); LESSONS["alive"].clear()   # fake data must not teach real bots
    try: return _alarm(gens, size)
    finally:
        for k in LESSONS: LESSONS[k].clear(); LESSONS[k].update(saved[k])

def _alarm(gens, size):
    print("ALARM 1: pure noise, nothing should graduate")
    a = run(synthetic(plant=False), gens, size, quiet=True); n1 = sum(x[3] for x in a["graduates"])
    print(f"  graduates {len(a['graduates'])}, passed exam {n1}  -> {'OK' if n1 == 0 else 'BROKEN: luck got through'}")
    print("ALARM 2: planted pattern (buy after a 5-day 12% fall), it must be found")
    b = run(synthetic(plant=True), gens, size, quiet=True)
    found = [x for x in b["graduates"] if x[3] and x[0]["sig"] == "drop"]
    print(f"  graduates {len(b['graduates'])}, dip-buyers that passed the exam {len(found)}  -> {'OK' if found else 'BROKEN: missed a real pattern'}")
    c_ok, c = cutoff_alarm()
    print(f"ALARM 3: prices after the exam cutoff scrambled -> practice scores changed for {c['practice_scores_changed_by_future_prices']} of {c['bots']} bots  -> {'OK' if c_ok else 'BROKEN: the exam leaks into practice'}")
    return n1 == 0 and bool(found) and c_ok

if __name__ == "__main__":
    d = sys.argv[1]; gens = int(sys.argv[2]) if len(sys.argv) > 2 else 30; size = int(sys.argv[3]) if len(sys.argv) > 3 else 300
    if not alarm(gens, size): sys.exit("Alarm failed: bootcamp results can't be trusted. Fix before reading them.")
    m = Market(*load_yahoo(d))
    print(f"\nREAL DATA: {m.C.shape[0]} stocks, {m.T} days. Levels 1-8 on the training years, exam on the newest 30% (locked).")
    res = run(m, gens, size)
    print(f"\nbots tried {res['tried']}; graduates {len(res['graduates'])}; banned pieces: {', '.join(res['banned']) or 'none'}")
    for g, o, e, ok in res["graduates"]:
        print(f"  {'PASSED EXAM' if ok else 'failed exam'}: {g}\n     training {o['n']} trades {o['mean'] * 100:+.2f}% z {o['z']:+.1f} | exam {e['n']} trades {e['mean'] * 100:+.2f}% z {e['z']:+.1f}")
