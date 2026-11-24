# VULPHEX training loop: a squad of bots works the practice range over many rounds; each bot's playbook brain evolves
# to catch more of the planted vulnerabilities with fewer false alarms. You watch the team's score climb. Deterministic
# and offline — no tools, no network — so you can train and understand the system before pointing it at anything real.
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(os.path.dirname(HERE), "security"))
import range as RG
import brain as B

DEPTH = {"shallow": 0, "normal": 1, "deep": 2}
SEVW = B.SEV_WEIGHT


def attempt(genome, plant, rnd):
    """Does a bot with this playbook catch this planted vuln? Deeper search finds harder vulns; a higher keep-bar
    ignores low-severity ones. 'persist' helps on the hardest. Returns (caught, weight)."""
    need = DEPTH[plant["difficulty"]]; have = DEPTH[genome["depth"]] + (1 if genome.get("persist") else 0)
    if B.KEEP_RANK.get(plant["severity"], 0) < B.KEEP_RANK.get(genome["keep"], 0): return False, 0   # below its keep-bar
    if have < need: return False, 0
    # a little noise so training isn't trivially solved; retry smooths it
    hit = rnd.random() < (0.75 if have == need else 0.95) or genome.get("retry")
    return (hit, SEVW.get(plant["severity"], 0)) if hit else (False, 0)


def false_alarms(genome, rnd):
    """A greedy tactic (deep + keep everything) raises false positives; cost scales with how loose it is."""
    loose = DEPTH[genome["depth"]] + (3 - B.KEEP_RANK.get(genome["keep"], 0))
    return sum(1 for _ in range(loose) if rnd.random() < 0.15)


def round_for_bot(brain, bot_name, capabilities, plants, rnd, ask=None):
    """One training round for one bot: pick its playbook, try the plants it owns, score it, and evolve — with the
    coach's Lina-validated ideas (if a model is given) joining as challengers."""
    g = brain.active(bot_name)
    mine = [p for p in plants if p["capability"] in capabilities]
    caught = weight = 0
    for p in mine:
        ok, w = attempt(g, p, rnd); caught += ok; weight += w
    fp = false_alarms(g, rnd)
    reward = weight - 1.0 * fp - 0.2 * len(capabilities)
    ideas, _ = brain.coach(bot_name, ask) if ask else ([], [])
    brain.score(bot_name, g, reward, coach_ideas=ideas)
    return {"bot": bot_name, "caught": caught, "of": len(mine), "false_alarms": fp, "reward": round(reward, 1), "coach": len(ideas)}


def train(core, squad, rounds=20, range_dir=None, seed=7, ask=None):
    """Train a squad (list of bot names) on the range for N rounds. Returns the per-round history for the dashboard."""
    import random
    rnd = random.Random(seed)
    range_dir = range_dir or os.path.join(HERE, "range_files")
    plants = RG.answer_key(range_dir) or RG.build(range_dir)
    caps = {b["name"]: b["capabilities"] for b in core.team}
    history = []
    for r in range(1, rounds + 1):
        rows = [round_for_bot(core.brain, name, caps.get(name, []), plants, rnd, ask=ask) for name in squad if name in caps]
        team_reward = round(sum(x["reward"] for x in rows), 1)
        team_caught = sum(x["caught"] for x in rows); team_of = sum(x["of"] for x in rows)
        history.append({"round": r, "team_reward": team_reward, "caught": team_caught, "of": team_of, "bots": rows})
    return history


def curriculum(core, squad, per=15, seed=7, ask=None):
    """The training pattern: each bot learns its own playbook SOLO, then in handoff PAIRS, then the whole SQUAD together,
    then a longer squad push while the luck bar keeps rising. Returns the full history, tagged by stage."""
    hist = []
    def tag(stage, h): return [{"stage": stage, **x} for x in h]
    for b in squad:                                             # stage 1: solo
        hist += tag("solo:" + b, train(core, [b], per, seed=seed, ask=ask))
    for i in range(0, len(squad), 2):                           # stage 2: pairs (SCOUT+ATLAS, AUDITOR+FORGE, ...)
        pair = squad[i:i + 2]
        if pair: hist += tag("pair:" + "+".join(pair), train(core, pair, per, seed=seed + 1, ask=ask))
    hist += tag("squad", train(core, squad, per * 2, seed=seed + 2, ask=ask))   # stage 3: all together, longer
    return hist
