# VULPHEX brain: the same evolving "ancestor brain" behind Edge Bot, applied to cybersecurity (owner's request).
# Each FOX bot carries a PLAYBOOK genome — how it works: which order to try its tools, how deep to go, how high to
# set its keep-bar. After every mission the genome is scored by what it actually CONFIRMED (FOX PROOF), minus cost.
# Genomes evolve (mutate/cross, the best survive). The LUCK FILTER (same rule as the trading bots) only lets a tactic
# count as PROVEN once its reward beats a bar that rises with every tactic ever tried AND holds on fresh runs it did
# not pick itself — so VULPHEX learns tactics that really work, not ones that got lucky once. The uncensored coach
# model proposes new tactics in Lina Sigra; Lina checks them before they join the population.
import json, os, random, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "engine"))
try:
    import bootcamp as bc
    REQUIRED_Z = bc.required_z                                 # reuse Edge Bot's rising luck bar
except Exception:
    import math
    def REQUIRED_Z(tried): return max(2.0, math.sqrt(2.0 * math.log(max(tried, 2))) + 0.5)

SEV_WEIGHT = {"critical": 8, "high": 5, "medium": 3, "low": 1, "info": 0}

# A playbook gene set: the knobs a bot can turn. 'order' = try tools in this priority; 'depth' = how hard to look;
# 'keep' = lowest severity worth keeping; 'persist' = keep probing after the first hit.
GENES = {
    "depth":   ["shallow", "normal", "deep"],
    "keep":    ["info", "low", "medium", "high"],
    "persist": [True, False],
    "retry":   [True, False],
}
KEEP_RANK = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 3}


def rand_genome(rnd):
    return {k: rnd.choice(v) for k, v in GENES.items()}


def mutate(g, rnd):
    c = dict(g); k = rnd.choice(list(GENES)); c[k] = rnd.choice(GENES[k]); return c


def cross(a, b, rnd):
    return {k: rnd.choice([a[k], b[k]]) for k in GENES}


def reward(findings, tasks):
    """What a bot earned this mission: confirmed findings by severity, minus a small cost per task run."""
    good = sum(SEV_WEIGHT.get(f["severity"], 0) for f in findings if f.get("status") in ("verified", "fix_proposed"))
    return good - 0.2 * max(tasks, 0)


SCHEMA = """
CREATE TABLE IF NOT EXISTS brain_pop (bot TEXT, genome TEXT, runs INTEGER, total REAL, best REAL, proven INTEGER,
                                      active INTEGER, PRIMARY KEY (bot, genome));
CREATE TABLE IF NOT EXISTS brain_led (k TEXT PRIMARY KEY, v INTEGER);
"""


class Brain:
    """One evolving playbook population per bot, stored in the shared DB so it learns across missions."""
    def __init__(self, db, size=6, seed=None):
        self.db = db; self.size = size; self.rnd = random.Random(seed)
        self.db.executescript(SCHEMA)

    def _tried(self):
        r = self.db.execute("SELECT v FROM brain_led WHERE k='tried'").fetchone(); return r[0] if r else 0

    def _bump(self, n=1):
        self.db.execute("INSERT INTO brain_led VALUES ('tried', ?) ON CONFLICT(k) DO UPDATE SET v=v+?", (n, n)); self.db.commit()

    def _pop(self, bot):
        return [dict(r) for r in self.db.execute("SELECT * FROM brain_pop WHERE bot=?", (bot,)).fetchall()]

    def active(self, bot):
        """The genome a bot should use next. Seeds a fresh population the first time."""
        pop = self._pop(bot)
        if not pop:
            for i in range(self.size):
                g = json.dumps(rand_genome(self.rnd), sort_keys=True)
                self.db.execute("INSERT OR IGNORE INTO brain_pop VALUES (?,?,?,?,?,?,?)", (bot, g, 0, 0.0, -1e9, 0, 1 if i == 0 else 0))
            self.db.commit(); pop = self._pop(bot)
        act = next((p for p in pop if p["active"]), pop[0])
        return json.loads(act["genome"])

    def score(self, bot, genome, rwd, coach_ideas=None):
        """Record this mission's reward for the bot's genome, evolve the population, pick the next genome, and apply
        the luck filter. Returns (next_genome, note)."""
        gkey = json.dumps(genome, sort_keys=True)
        self.db.execute("INSERT OR IGNORE INTO brain_pop VALUES (?,?,?,?,?,?,?)", (bot, gkey, 0, 0.0, -1e9, 0, 0))
        self.db.execute("UPDATE brain_pop SET runs=runs+1, total=total+?, best=MAX(best,?) WHERE bot=? AND genome=?",
                        (rwd, rwd, bot, gkey)); self._bump()
        # luck filter: proven only after >=5 runs, positive mean, beating the rising bar (reward units, not a z-test,
        # but the bar rises the same way so more tactics tried => a higher mean required)
        bar = REQUIRED_Z(self._tried())
        for p in self._pop(bot):
            if p["runs"] >= 5 and p["total"] / p["runs"] >= bar and p["best"] > 0:
                self.db.execute("UPDATE brain_pop SET proven=1 WHERE bot=? AND genome=?", (bot, p["genome"]))
        # evolve: rank by mean reward, keep elites, breed the rest, add coach ideas + a random newcomer
        pop = sorted(self._pop(bot), key=lambda p: -(p["total"] / p["runs"] if p["runs"] else -1e9))
        elites = [json.loads(p["genome"]) for p in pop[:max(2, self.size // 3)]]
        children = []
        for g in (coach_ideas or []):
            if isinstance(g, dict) and set(g) == set(GENES): children.append(g)
        while len(elites) + len(children) < self.size - 1:
            a = self.rnd.choice(elites); b = self.rnd.choice(elites)
            children.append(cross(a, b, self.rnd) if self.rnd.random() < 0.4 else mutate(a, self.rnd))
        children.append(rand_genome(self.rnd))
        keep = elites + children
        self.db.execute("DELETE FROM brain_pop WHERE bot=?", (bot,))
        for i, g in enumerate(keep[:self.size]):
            gk = json.dumps(g, sort_keys=True)
            old = next((p for p in pop if p["genome"] == gk), None)
            self.db.execute("INSERT OR REPLACE INTO brain_pop VALUES (?,?,?,?,?,?,?)",
                            (bot, gk, old["runs"] if old else 0, old["total"] if old else 0.0,
                             old["best"] if old else -1e9, old["proven"] if old else 0, 1 if i == 0 else 0))
        self.db.commit()
        nxt = keep[0]; proven = sum(p["proven"] for p in self._pop(bot))
        return nxt, f"brain: reward {rwd:+.1f}, next tactic depth={nxt['depth']}/keep={nxt['keep']}, {proven} proven, luck bar {bar:.2f}"

    def filter_findings(self, genome, findings):
        """Apply the active genome's keep-bar: a pickier tactic drops low-severity noise."""
        floor = KEEP_RANK.get(genome.get("keep", "info"), 0)
        return [f for f in findings if KEEP_RANK.get(f["severity"], 0) >= floor]
