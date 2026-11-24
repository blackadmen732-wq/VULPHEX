# Learning-bot evolution (owner's request, Nov 18 2026). Paper research only, no orders.
# The recipe bots evolve every night; this gives the learning brains (neuron, forest, rocket) the same treatment:
#   - their SETTINGS are genes: brain type, hidden size, practice amount, crash penalty, holding days, which inputs
#     they see, how picky they are, forest depth
#   - a population per market each night: the best breed (mutation / crossover), the worst die
#   - the best genomes carry over to the next night (Supabase storage: brains/<market>.json)
#   - ROCKETS LEARN FROM ROCKETS: the best rocket's trained weights are saved and the next night's rockets start
#     from them instead of from zero (when the inputs match)
#   - a TEAM BRAIN: the best neuron, forest and rocket vote (average their buy probabilities)
#   - same rules as everyone: 8 walk-forward levels, the locked exam, and an exam bar that rises with every brain
#     ever tried (all-time luck filter)
import math, random
import numpy as np
import bootcamp as bc
import futures as fu

GENES = {"brain": ["neuron", "forest", "rocket", "rocket", "experts", "experts"], "hidden": [8, 16, 32, 64], "iters": [400, 1200, 3000],
         "crash": [-0.05, -0.10, -0.20], "hold": [1, 3, 5, 10, 20], "inputs": ["chart", "chart+reasons", "chart+indicators", "chart+context", "all"],
         "pick": [0.05, 0.10, 0.20], "depth": [4, 6, 8]}
COLS = {"chart": list(range(7)), "indicators": list(range(7, 15)), "reasons": [15, 16, 17], "context": []}   # set per market by set_groups()

def context(m):
    """What the rule bots already see but the brains didn't (Nov 20): strength vs the market, insider buying,
    market mood (crash / trend), time of year, and how wild the stock has been lately."""
    S, T = m.C.shape; b = lambda x: np.broadcast_to(np.asarray(x, np.float32)[None, :], (S, T))
    mon = getattr(m, "month", np.ones(T)); mood = getattr(m, "mood", {})
    with np.errstate(all="ignore"):
        r2 = np.nan_to_num(np.asarray(m.ret[1], np.float64) ** 2); c = np.cumsum(r2, 1); c[:, 20:] = c[:, 20:] - c[:, :-20]
        vol = np.sqrt(c / 20)
    f = [getattr(m, "rel20", np.zeros((S, T))), getattr(m, "insider", np.zeros((S, T))).astype(np.float32),
         b(mood.get("crash", np.zeros(T))), b(mood.get("trend", np.zeros(T))),
         b(np.sin(2 * np.pi * mon / 12)), b(np.cos(2 * np.pi * mon / 12)), vol]
    free = getattr(m, "free", {}) or {}                       # Nov 20: free outside data (freedata.py), fixed order, unknown = 0
    for k in FREE_NAMES:
        if k in free: a = np.asarray(free[k], np.float32); f.append(np.nan_to_num(a if a.ndim == 2 else b(a)))
    return np.stack([np.asarray(x, np.float32) for x in f], -1)

FREE_NAMES = ["curve", "rate20", "credit", "jobs", "cpi", "spx_lev", "euro_lev", "gold_mm", "crude_mm", "shortz", "buzz", "news", "macro_news"]   # = freedata.NAMES

def set_groups(m, d_base):
    """Where each input group sits for this market (indicators exist for stocks, fear/rates only when downloaded)."""
    i = 7; COLS["indicators"] = list(range(i, i + 8)) if hasattr(m, "lens") else []; i += len(COLS["indicators"])
    COLS["reasons"] = list(range(i, d_base)); n = 7 + sum(k in (getattr(m, "free", {}) or {}) for k in FREE_NAMES)
    COLS["context"] = list(range(d_base, d_base + n))
    free = getattr(m, "free", {}) or {}                       # a name for every column, in order (what saved weights must match)
    NAMES[:] = (["ret1", "ret5", "ret20", "vs_hi55", "vol_vs_avg", "gap", "above_ma200"]
                + [f"indicator{j}" for j in range(len(COLS["indicators"]))] + [f"reason{j}" for j in range(len(COLS["reasons"]))]
                + ["rel20", "insider", "crash", "trend", "month_sin", "month_cos", "vol20"] + [k for k in FREE_NAMES if k in free])

NAMES = []

def input_names(c):
    return [NAMES[i] if i < len(NAMES) else f"col{i}" for i in c]

def cols_for(g, d):
    want = {"chart": ["chart"], "chart+reasons": ["chart", "reasons"], "chart+indicators": ["chart", "indicators"],
            "chart+context": ["chart", "context"], "all": ["chart", "reasons", "indicators", "context"]}[g["inputs"]]
    c = sorted({i for w in want for i in COLS[w] if i < d})
    return c or list(range(min(7, d)))

def rand_g(r): return {k: r.choice(v) for k, v in GENES.items()}
def mutate(g, r): c = dict(g); k = r.choice(list(GENES)); c[k] = r.choice(GENES[k]); return c
def cross(a, b, r): return {k: r.choice([a[k], b[k]]) for k in GENES}

class WarmRocket(fu.Rocket):
    """A Rocket that can start from saved weights (yesterday's best rocket) and have its own hidden size."""
    def __init__(self, X, rew, seed, iters, hidden, crash, init=None):
        rs = np.random.default_rng(seed)
        self.mu, self.sd = X.mean(0), X.std(0) + 1e-9; Xs = (X - self.mu) / self.sd; d = X.shape[1]
        if init and np.array(init["W1"]).shape == (d, hidden):
            self.W1, self.b1, self.w2 = (np.array(init[k], float) for k in ("W1", "b1", "w2")); self.b2 = float(init["b2"])
        else:
            self.W1 = rs.normal(0, 0.3, (d, hidden)); self.b1 = np.zeros(hidden); self.w2 = rs.normal(0, 0.3, hidden); self.b2 = 0.0
        base, lr, flights, steps = 0.0, 0.05, 64, 20
        for _ in range(iters):
            idx = rs.integers(0, len(Xs), (flights, steps)); x = Xs[idx]; r = rew[idx]
            h = np.tanh(x @ self.W1 + self.b1); p = 1 / (1 + np.exp(-(h @ self.w2 + self.b2)))
            a = (rs.random(p.shape) < p).astype(float); got = a * r
            flight = got.sum(1, keepdims=True); pen = np.where(flight < crash, crash, 0.0) * a / np.maximum(a.sum(1, keepdims=True), 1)
            adv = got + pen - base * a
            if a.any(): base = 0.9 * base + 0.1 * float(got[a > 0].mean())
            g = (a - p) * adv; dh = g[..., None] * self.w2 * (1 - h ** 2); n = flights * steps
            self.w2 += lr * (g[..., None] * h).reshape(n, -1).sum(0) / n * 10; self.b2 += lr * g.mean() * 10
            self.W1 += lr * np.einsum("fsd,fsk->dk", x, dh) / n * 10; self.b1 += lr * dh.reshape(n, -1).mean(0) * 10
    known_by = None                                  # last market day this rocket's training could see (set by the caller)
    inputs = None                                    # the input names, in column order
    def weights(self): return {"W1": self.W1.tolist(), "b1": self.b1.tolist(), "w2": self.w2.tolist(), "b2": float(self.b2),
                               "known_by": self.known_by, "inputs": self.inputs}

class Experts:
    """ROCKET TEAM (owner's idea, Nov 22 2026): a table of 8 small expert Rockets and a host (router) that, for every
    decision, asks only the 2 experts that fit the moment, instead of everyone talking to everyone. This is a
    Mixture of Experts, the way Mixtral and DeepSeek are built: 8x the brain, but each decision uses 2 experts.
      - each expert: inputs -> `hidden` tanh neurons -> a buy score
      - the host: inputs -> 8 scores; the top 2 answer, weighted by a softmax over their two scores
      - learns by REINFORCE like Rocket (same flights, rewards, crash penalty), host and experts together
      - nobody knows the answer at the start: the host learns who is good at what, and each expert gets better at
        its kind of day because it keeps getting those days. Noise in training lets every expert get tried, and a
        usage balance (a nudge to each expert's routing score, DeepSeek-V3 style) stops the host using only one
      - same 8 levels, locked exam and luck bar as every brain: a bigger brain only counts if it wins on new days"""
    E, K = 8, 2
    def __init__(self, X, rew, seed, iters, hidden, crash):
        rs = np.random.default_rng(seed); E, K = self.E, self.K
        self.mu, self.sd = X.mean(0), X.std(0) + 1e-9; Xs = (X - self.mu) / self.sd; d = X.shape[1]
        self.W1 = rs.normal(0, 0.3, (E, d, hidden)); self.b1 = np.zeros((E, hidden)); self.w2 = rs.normal(0, 0.3, (E, hidden)); self.b2 = np.zeros(E)
        self.Wr = rs.normal(0, 0.1, (d, E)); self.br = np.zeros(E); self.bal = np.zeros(E)
        base, lr, flights, steps = 0.0, 0.05, 64, 20; n = flights * steps
        for _ in range(iters):
            idx = rs.integers(0, len(Xs), (flights, steps)); x = Xs[idx].reshape(n, d); r = rew[idx]
            z, G, M, rows = self._forward(x, noise=rs.normal(0, 1.0, (n, E)))
            p = (1 / (1 + np.exp(-z))).reshape(flights, steps)
            a = (rs.random(p.shape) < p).astype(float); got = a * r
            flight = got.sum(1, keepdims=True); pen = np.where(flight < crash, crash, 0.0) * a / np.maximum(a.sum(1, keepdims=True), 1)
            adv = got + pen - base * a
            if a.any(): base = 0.9 * base + 0.1 * float(got[a > 0].mean())
            gz = ((a - p) * adv).reshape(n)                       # d log-prob / d final score, times advantage
            dL = np.zeros((n, E))
            for e, (j, h, ze) in rows.items():                    # ONLY the experts that were asked do any work
                dz = gz[j] * G[j, e]; dh = dz[:, None] * self.w2[e] * (1 - h ** 2)
                self.w2[e] += lr * (dz @ h) / n * 10; self.b2[e] += lr * dz.sum() / n * 10
                self.W1[e] += lr * (x[j].T @ dh) / n * 10; self.b1[e] += lr * dh.sum(0) / n * 10
                dL[j, e] = gz[j] * G[j, e] * (ze - z[j])          # the host leans towards experts that beat the mix
            self.Wr += lr * (x.T @ dL) / n * 10; self.br += lr * dL.sum(0) / n * 10
            self.bal -= 0.01 * np.sign(M.mean(0) / K - 1 / E)        # busy experts get picked a little less, idle ones more
        self.usage = self.share(X)
    def _forward(self, x, noise=None):
        L = x @ self.Wr + self.br + (0 if noise is None else noise)
        top = np.argsort(-(L + self.bal), 1)[:, :self.K]; M = np.zeros_like(L); np.put_along_axis(M, top, 1.0, 1)
        Ls = np.where(M > 0, L, -np.inf); G = np.exp(Ls - Ls.max(1, keepdims=True)); G /= G.sum(1, keepdims=True)
        z = np.zeros(len(x)); rows = {}
        for e in range(self.E):
            j = np.flatnonzero(M[:, e])
            if j.size == 0: continue
            h = np.tanh(x[j] @ self.W1[e] + self.b1[e]); ze = h @ self.w2[e] + self.b2[e]
            z[j] += G[j, e] * ze; rows[e] = (j, h, ze)
        return z, G, M, rows
    def prob(self, X):
        return 1 / (1 + np.exp(-self._forward((X - self.mu) / self.sd)[0]))
    def share(self, X, n=20_000):
        """How often each expert is asked, on up to n rows (sums to 1)."""
        x = (X[:n] - self.mu) / self.sd; M = self._forward(x)[2]; return (M.mean(0) / self.K).round(3).tolist()

def train_cutoff(prob, ok, F, lo, hold, pick, n=60_000, seed=0):
    """The 'top pick%' confidence line, set from TRAINING days only (owner's review, Nov 21): rows before lo whose
    outcome was known by lo. Picking it from the test window used scores from days that hadn't happened yet."""
    k = ok.copy(); k[:, :60] = False; k[:, max(60, lo - hold):] = False; idx = np.flatnonzero(k)
    if idx.size == 0: return np.inf
    if idx.size > n: idx = np.random.default_rng(seed).choice(idx, n, replace=False)
    S, T = k.shape; rows = F.reshape(S * T, -1)[idx]; p = prob(rows)
    return float(np.quantile(p, 1 - pick)) if np.isfinite(p).any() else np.inf

def last_day(m, hi):
    """The last market day a model trained on columns before `hi` could see (None when the market has no dates)."""
    return int(m.days[min(hi, m.T) - 1]) if getattr(m, "days", None) is not None and hi > 0 else None

def safe_init(init, m, hi, inputs=None):
    """Saved weights may start a replay only if they PROVE they were trained before that replay's cutoff, on the
    SAME inputs in the SAME order. No date, a later date, or different inputs: start from scratch."""
    cut = last_day(m, hi)
    if not init or cut is None or init.get("known_by") is None: return None
    if inputs is not None and init.get("inputs") != list(inputs): return None
    return init if int(init["known_by"]) <= cut else None

def warm_rocket(m, hi, X, Rw, seed, iters, hidden, crash, init, inputs=None):
    r = WarmRocket(X, Rw, seed, iters, hidden, crash, safe_init(init, m, hi, inputs))
    r.known_by = last_day(m, hi); r.inputs = list(inputs) if inputs is not None else None; return r

def target_ok(m, band, hold):
    """What a brain is trying to beat (the move after `hold` days vs the band's average) and which rows count."""
    target = m.fwd[hold] - bc.bench(m, band, hold); return target, m.band[band] & np.isfinite(target) & np.isfinite(m.C)

def fit_brain(m, band, g, F, lo, hi, rs, seed=1, init=None):
    """Train one brain on days lo..hi, using only outcomes known by hi. None if there are too few rows."""
    hold = g["hold"]; target, ok = target_ok(m, band, hold); c = cols_for(g, F.shape[-1])
    k = ok.copy(); k[:, :lo] = False; k[:, max(lo, hi - hold):] = False   # labels must be known by hi (a label needs `hold` more days)
    X, Y, Rw = F[k][:, c], (target[k] > 0).astype(np.float32), np.clip((target - m.cost)[k], -0.5, 0.5)
    if len(Y) < 200: return None
    if len(Y) > 200_000: j = rs.choice(len(Y), 200_000, replace=False); X, Y, Rw = X[j], Y[j], Rw[j]
    if g["brain"] == "forest":
        f = fu.Forest.__new__(fu.Forest)
        from sklearn.ensemble import RandomForestClassifier
        f.mu, f.sd = X.mean(0), X.std(0) + 1e-9; n = min(len(Y), 100_000); jj = rs.choice(len(Y), n, replace=False)
        f.m = RandomForestClassifier(n_estimators=60, max_depth=g["depth"], min_samples_leaf=200, n_jobs=-1, random_state=seed).fit((X[jj] - f.mu) / f.sd, Y[jj])
        return f
    if g["brain"] == "rocket": return warm_rocket(m, hi, X, Rw, seed, g["iters"], g["hidden"], g["crash"], init, input_names(c))
    if g["brain"] == "experts": return Experts(X, Rw, seed, g["iters"], max(4, g["hidden"] // 2), g["crash"])
    w, b, mu, sd = fu.train_neuron(X, Y)
    class N:
        def prob(self, Z): return 1 / (1 + np.exp(-(((Z - mu) / sd) @ w + b)))
    return N()

def walk(m, band, g, F, seed=1, init=None, exam_frac=0.3):
    """One brain through the 8 walk-forward levels (+ exam if it passes). Returns (result, last trained model)."""
    hold = g["hold"]; exam_from = int(m.T * (1 - exam_frac)); cut = np.linspace(250, exam_from, bc.LEVELS + 1).astype(int)
    target, ok = target_ok(m, band, hold)
    c = cols_for(g, F.shape[-1]); rs = np.random.default_rng(seed); last = None
    def fit(lo, hi): return fit_brain(m, band, g, F, lo, hi, rs, seed, init)
    def test(model, lo, hi):
        k = ok.copy(); k[:, :lo] = False; k[:, hi:] = False; p = np.full(k.shape, np.nan, np.float32); p[k] = model.prob(F[k][:, c])
        if not np.isfinite(p).any(): return {"n": 0, "mean": 0.0, "z": 0.0}
        thr = train_cutoff(lambda Z: model.prob(Z[:, c]), ok, F, lo, hold, g["pick"])    # set on TRAINING days, not the test window
        sel = p >= thr; ex = (m.fwd[hold] - bc.bench(m, band, hold) - m.cost)[sel]
        t = np.nonzero(sel)[1]; keep = np.isfinite(ex); return bc.score(m, t[keep], np.clip(ex[keep], -0.9, 1.0), lo, hi, hold)
    passed, levels = 1, []
    for i in range(1, bc.LEVELS):
        model = fit(60, cut[i]); last = model
        if model is None: break
        s = test(model, cut[i], cut[i + 1]); levels.append(s)
        if s["n"] < bc.MIN_TRADES or s["mean"] <= 0 or s["z"] < bc.LEVEL_Z[i + 1]: break
        passed += 1
    exam = None
    if passed == bc.LEVELS:
        last = fit(60, exam_from); exam = test(last, exam_from, m.T) if last else None
    score = passed + (max(min(levels[-1]["z"], 5), -5) / 10 if levels else 0)          # level reached, then how close to the next
    return {"genome": g, "levels_passed": passed, "levels": levels, "exam": exam, "score": score}, last

def brain_inputs(m):
    """Everything a brain can see, per stock per day (chart, indicators, reasons, context). Built once per market."""
    if getattr(m, "_brain_F", None) is not None: return m._brain_F
    base = fu.features(m); set_groups(m, base.shape[-1])
    m._brain_F = np.nan_to_num(np.concatenate([base, context(m)], -1), nan=0.0, posinf=0.0, neginf=0.0).astype(np.float32)
    return m._brain_F

def evolve(m, band, saved=None, gens=4, size=10, seed=7, seeds=()):
    """saved: {'genomes': [...], 'rocket': weights, 'tried': n} from earlier nights. Returns results + what to save.
    seeds: extra genomes (the AI coach's ideas, coach.py) that join the first generation and face the same exams."""
    saved = saved or {}; r = random.Random(seed)
    F = brain_inputs(m)
    pop = [g for g in saved.get("genomes", []) if set(g) == set(GENES)][: size // 2]
    ideas = [dict(g) for g in seeds if set(g) == set(GENES) and g not in pop][: max(1, size // 4)]
    pop += ideas
    while len(pop) < size: pop.append(rand_g(r))
    coach = {}
    tried = saved.get("tried", 0); results = []; best_rocket, best_rocket_score = saved.get("rocket"), -1e9
    for gen in range(gens):
        scored = []
        for i, g in enumerate(pop):
            res, model = walk(m, band, g, F, seed=seed + gen * 100 + i, init=saved.get("rocket") if g["brain"] == "rocket" else None)
            tried += 1; scored.append(res); results.append(res)
            if gen == 0 and g in ideas: coach[json_key(g)] = res
            if g["brain"] == "rocket" and isinstance(model, WarmRocket) and res["score"] > best_rocket_score:
                best_rocket, best_rocket_score = model.weights(), res["score"]
        scored.sort(key=lambda x: -x["score"]); elite = [x["genome"] for x in scored[: max(2, size // 4)]]
        pop = elite + [cross(*r.sample(elite, 2), r) if r.random() < 0.4 else mutate(r.choice(elite), r) for _ in range(size - len(elite) - 1)] + [rand_g(r)]
    results.sort(key=lambda x: -x["score"])
    exam_bar = max(2.0, bc.required_z(max(tried, 1)))
    for x in results:
        e = x["exam"]; x["passed"] = bool(e and e["n"] >= bc.MIN_TRADES and e["mean"] > 0 and e["z"] >= exam_bar)
    # TEAM BRAIN: the best of each kind vote
    team = None
    leaders = {}
    for x in results:
        leaders.setdefault(x["genome"]["brain"], x["genome"])
    if len(leaders) >= 2:
        team = team_walk(m, band, list(leaders.values()), F, best_rocket)
    best = results[0]["levels_passed"] if results else 0
    stuck = 0 if best > max([x["levels_passed"] for x in saved.get("last", [])] or [-1]) else saved.get("stuck", 0) + 1
    last = [{"genome": x["genome"], "levels_passed": x["levels_passed"], "passed": x["passed"]} for x in results[:5]]
    return {"results": results[:5], "tried": tried, "exam_bar": exam_bar, "team": team,
            "coach": [{"genome": x["genome"], "levels_passed": x["levels_passed"], "passed": x["passed"],
                       "rank": results.index(x) + 1} for x in coach.values()],
            "save": {"genomes": [x["genome"] for x in results[:5]], "rocket": best_rocket, "tried": tried, "last": last, "stuck": stuck}}

def json_key(g): return tuple(sorted(g.items()))

def team_walk(m, band, genomes, F, rocket_init):
    """The leaders vote: average buy probability across brains; same levels and exam."""
    g0 = dict(genomes[0]); g0["brain"] = "team"; hold = g0["hold"]
    exam_from = int(m.T * (1 - 0.3)); cut = np.linspace(250, exam_from, bc.LEVELS + 1).astype(int)
    target = m.fwd[hold] - bc.bench(m, band, hold); ok = m.band[band] & np.isfinite(target) & np.isfinite(m.C)
    passed, levels = 1, []
    for i in range(1, bc.LEVELS):
        probs = []; team_models = []
        for k, g in enumerate(genomes):
            gg = {**g, "hold": hold}; _, model = walk_fit_only(m, band, gg, F, cut[i], rocket_init)
            if model is None: break
            team_models.append((model, gg))
            kk = ok.copy(); kk[:, :cut[i]] = False; kk[:, cut[i + 1]:] = False
            p = np.full(kk.shape, np.nan, np.float32); p[kk] = model.prob(F[kk][:, cols_for(gg, F.shape[-1])]); probs.append(p)
        if len(probs) < 2: break
        with np.errstate(all="ignore"): p = np.nanmean(probs, axis=0)
        thr = train_cutoff(lambda Z: np.mean([mdl.prob(Z[:, cols_for({**gg, "hold": hold}, F.shape[-1])]) for mdl, gg in team_models], 0), ok, F, cut[i], hold, g0["pick"])
        sel = p >= thr
        ex = (m.fwd[hold] - bc.bench(m, band, hold) - m.cost)[sel]; t = np.nonzero(sel)[1]; keep = np.isfinite(ex)
        s = bc.score(m, t[keep], np.clip(ex[keep], -0.9, 1.0), cut[i], cut[i + 1], hold); levels.append(s)
        if s["n"] < bc.MIN_TRADES or s["mean"] <= 0 or s["z"] < bc.LEVEL_Z[i + 1]: break
        passed += 1
    return {"members": [g["brain"] for g in genomes], "levels_passed": passed, "levels": levels}

def walk_fit_only(m, band, g, F, hi, rocket_init):
    """Train one brain on days before `hi` only (used by the team)."""
    res = {"genome": g}
    hold = g["hold"]; target = m.fwd[hold] - bc.bench(m, band, hold); ok = m.band[band] & np.isfinite(target) & np.isfinite(m.C)
    c = cols_for(g, F.shape[-1]); k = ok.copy(); k[:, :60] = False; k[:, max(60, hi - hold):] = False   # labels known by hi
    X, Y, Rw = F[k][:, c], (target[k] > 0).astype(np.float32), np.clip((target - m.cost)[k], -0.5, 0.5)
    if len(Y) < 200: return res, None
    rs = np.random.default_rng(3)
    if len(Y) > 200_000: j = rs.choice(len(Y), 200_000, replace=False); X, Y, Rw = X[j], Y[j], Rw[j]
    if g["brain"] == "rocket": return res, warm_rocket(m, hi, X, Rw, 3, min(g["iters"], 1200), g["hidden"], g["crash"], rocket_init, input_names(c))
    if g["brain"] == "experts": return res, Experts(X, Rw, 3, min(g["iters"], 1200), max(4, g["hidden"] // 2), g["crash"])
    if g["brain"] == "forest":
        f = fu.Forest.__new__(fu.Forest)
        from sklearn.ensemble import RandomForestClassifier
        f.mu, f.sd = X.mean(0), X.std(0) + 1e-9; n = min(len(Y), 100_000); jj = rs.choice(len(Y), n, replace=False)
        f.m = RandomForestClassifier(n_estimators=60, max_depth=g["depth"], min_samples_leaf=200, n_jobs=-1, random_state=3).fit((X[jj] - f.mu) / f.sd, Y[jj])
        return res, f
    w, b, mu, sd = fu.train_neuron(X, Y)
    class N:
        def prob(self, Z): return 1 / (1 + np.exp(-(((Z - mu) / sd) @ w + b)))
    return res, N()
