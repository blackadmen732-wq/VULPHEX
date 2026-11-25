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


# ---------------------------------------------------------------- SNOWBALL: red vs blue co-evolution
# The four red bots attack; the nine blue bots defend. Every attack that gets THROUGH rewards the red bot and raises the
# PRESSURE (difficulty) for the next round; every attack CAUGHT rewards the blue defender and eases the pressure. Both
# sides' playbooks evolve each round, so as red gets sharper blue is forced to get sharper to keep up, and vice-versa —
# the snowball. Deterministic and offline (no model needed); the practice range is never touched, this is bot-vs-bot.
#
# Which blue capabilities can catch which attack vector:
ATTACK_DEFENSE = {
    "exploit_validation": ["web_app_scan", "source_code_analysis", "finding_verification"],
    "adversary_sim":      ["monitoring", "asset_discovery", "system_mapping"],
    "autonomous_pentest": ["web_app_scan", "source_code_analysis", "monitoring", "finding_verification", "asset_discovery"],
}
_ALL_BLUE_CAPS = ["asset_discovery", "system_mapping", "source_code_analysis", "web_app_scan",
                  "dependency_audit", "finding_verification", "monitoring"]


def _power(g):
    """Attack strength / detection strength from a playbook: deeper + persistent = stronger."""
    return DEPTH[g["depth"]] + (1 if g.get("persist") else 0)


def snowball(core, rounds=30, seed=11, ask=None):
    """Co-evolve red (attack) and blue (defend). Returns per-round history for the dashboard: how many attacks got
    through, how many were caught, and the rising/falling pressure."""
    import random
    rnd = random.Random(seed)
    team = {b["name"]: b for b in core.team}
    red = [b["name"] for b in core.team if b.get("side") == "red"]
    blue = [b["name"] for b in core.team if b.get("side") != "red"]
    pressure = 0.0
    history = []
    for r in range(1, rounds + 1):
        blue_credit = {n: 0.0 for n in blue}
        through = caught = 0
        red_rewards = {}
        for rn in red:
            g = core.brain.active(rn)
            caps = [c for c in team[rn]["capabilities"] if c in ATTACK_DEFENSE] or ["autonomous_pentest"]
            vector = rnd.choice(caps)
            difficulty = _power(g) + pressure
            defenders = [n for n in blue if set(team[n]["capabilities"]) & set(ATTACK_DEFENSE.get(vector, _ALL_BLUE_CAPS))]
            hit_by = None
            for dn in sorted(defenders, key=lambda n: -_power(core.brain.active(n))):
                dg = core.brain.active(dn)
                if _power(dg) >= difficulty and (rnd.random() < 0.8 or dg.get("retry")):
                    hit_by = dn; break
            if hit_by:
                caught += 1; blue_credit[hit_by] += 4.0
                red_rewards[rn] = red_rewards.get(rn, 0.0) - 1.0
                pressure = max(0.0, pressure - 0.3)
            else:
                through += 1
                red_rewards[rn] = red_rewards.get(rn, 0.0) + 4.0
                pressure += 0.5                                  # red broke through -> the snowball grows
        # evolve red
        for rn in red:
            g = core.brain.active(rn)
            ideas, _ = core.brain.coach(rn, ask) if ask else ([], [])
            core.brain.score(rn, g, red_rewards.get(rn, 0.0), coach_ideas=ideas)
        # evolve blue (reward for catches, minus a small idle cost)
        blue_reward_total = 0.0
        for bn in blue:
            g = core.brain.active(bn)
            reward = blue_credit[bn] - 0.2 * len(team[bn]["capabilities"])
            blue_reward_total += reward
            ideas, _ = core.brain.coach(bn, ask) if ask else ([], [])
            core.brain.score(bn, g, reward, coach_ideas=ideas)
        history.append({"round": r, "red_through": through, "blue_caught": caught,
                        "pressure": round(pressure, 1),
                        "red_reward": round(sum(red_rewards.values()), 1),
                        "blue_reward": round(blue_reward_total, 1)})
    return history


def turbo(core, generations=100, rounds_each=30, seed=None, on_gen=None):
    """FAST-FORWARD training: generate many varied practice scenarios and run many rounds through each — thousands of
    generations of evolution compressed into seconds. Alternates defend-training and red-vs-blue snowball so both
    sides climb. Returns a compact per-batch history. Deterministic and offline."""
    import random, time, sys, os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import scenarios as SC
    seed = int(time.time()) % 100000 if seed is None else seed
    rnd = random.Random(seed)
    caps = {b["name"]: b["capabilities"] for b in core.team}
    squad = [b["name"] for b in core.team if b["name"] in caps]
    scen = SC.generate(generations, seed=seed)
    history, total_rounds = [], 0
    for gi, plants in enumerate(scen):
        rows = None
        for _ in range(rounds_each):
            rows = [round_for_bot(core.brain, name, caps[name], plants, rnd) for name in squad]
            total_rounds += 1
        if gi % 5 == 0:                                           # a snowball burst every few scenarios
            snowball(core, rounds=20, seed=seed + gi)
        tr = round(sum(x["reward"] for x in rows), 1) if rows else 0
        if gi % 10 == 0 or gi == len(scen) - 1:
            proven = core.db.execute("SELECT COUNT(*) FROM brain_pop WHERE proven=1").fetchone()[0]
            history.append({"generation": gi + 1, "rounds": total_rounds, "team_reward": tr, "proven": proven})
            on_gen and on_gen(gi + 1, len(scen), proven)
    return {"generations": len(scen), "rounds": total_rounds, "history": history}
