# The AI coach (owner's request, Nov 22 2026): a free local model that sits ON TOP of the learning brains and
# suggests changes to their settings, written in Lina Sigra. Paper research only. No API, no key, no cost.
#
#   1. read last night's best brains for a market (brain type, neurons, holding days, inputs, levels passed, exam)
#   2. ask the model for a few one-line Lina suggestions, e.g.  se regra es mala: na va fora neta 64
#   3. Lina checks every line; only SUGGESTIONS whose condition is true tonight are kept (orders, money words and
#      anything Lina rejects are dropped)
#   4. each suggestion becomes a changed copy of the best genome, which joins tonight's population
#   5. those copies face the same 8 levels, the locked exam and the rising luck bar as every other brain:
#      the coach never changes a bot directly, it only adds contestants
#
# Model: COACH_MODEL, else the same free Qwen the news test uses. Swap in the trained Lina writer once the
# trainer (lina_trainer_kernel.py) names a winner. A time budget (COACH_BUDGET_S, default 5 minutes a night) caps it.
import os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "lina"))
import lang

BUDGET_S = float(os.environ.get("COACH_BUDGET_S", "300"))
ASKS = 4                                              # suggestions asked per market and band
CONTEXT = {"novia", "trema", "merka", "fila", "gania", "perdia", "kosta", "risk"}   # inputs that live in the "context" group

_model = {"gen": None, "why": None, "tried": False, "spent": 0.0}


def describe(saved):
    """Last night's best brains, in plain English, for the model."""
    last = (saved or {}).get("last") or []
    if not last: return "No results yet for this market."
    rows = []
    for x in last[:3]:
        g = x["genome"]
        rows.append(f"- {g['brain']} brain, {g['hidden']} neurons, holds {g['hold']} days, sees {g['inputs']}: passed "
                    f"{x['levels_passed']} of 8 levels, exam {'passed' if x.get('passed') else 'failed'}")
    return "Last night's best brains:\n" + "\n".join(rows)


def state(saved):
    """What a suggestion's condition can test tonight: regra (is the best brain good?) and fila (nights stuck)."""
    last = (saved or {}).get("last") or []
    best = last[0] if last else None
    return {"regra": "lena" if best and best.get("passed") else "mala",
            "fila": int((saved or {}).get("stuck", 0)),
            "gania": float(best["levels_passed"]) if best else 0.0}


def request(saved, i):
    asks = ["Suggest ONE change to the network size that could help.", "Suggest ONE change to how long trades are kept.",
            "Suggest ONE input the brains should use or ignore.", "Suggest ONE change you think matters most."]
    return describe(saved) + "\n" + asks[i % len(asks)] + " Answer with one Lina suggestion rule (na va fora neta / tena / suma / rimae)."


def apply(g, action, genes):
    """A Lina suggestion -> a changed copy of genome g (None when it changes nothing or can't apply)."""
    if action.get("do") != "suggest": return None
    c = dict(g); what, to = action["set"], action["to"]
    if what == "neurons": c["brain"] = c["brain"] if c["brain"] in ("rocket", "experts") else "rocket"; c["hidden"] = to
    elif what == "hold":
        holds = sorted(genes["hold"]); i = holds.index(c["hold"]) if c["hold"] in holds else 0
        c["hold"] = holds[min(i + 1, len(holds) - 1)] if to == "longer" else holds[max(i - 1, 0)]
    elif what in ("use_input", "ignore_input"):
        if to not in CONTEXT: return None                 # price/chart is always seen; nothing to change
        has = c["inputs"] in ("chart+context", "all")
        if what == "use_input" and not has: c["inputs"] = "all" if c["inputs"] in ("chart+reasons", "chart+indicators") else "chart+context"
        elif what == "ignore_input" and has: c["inputs"] = "chart+indicators" if c["inputs"] == "all" else "chart"
    else: return None
    return c if c != g and all(c[k] in genes[k] for k in genes) else None


def suggestions(generate, saved, genes, asks=ASKS):
    """Ask, let Lina check, keep only suggestions whose condition holds tonight. Returns (genomes, log)."""
    base = ((saved or {}).get("genomes") or [None])[0]
    if not base or set(base) != set(genes): return [], ["no saved brain to coach yet"]
    out, log, st = [], [], state(saved)
    for i in range(asks):
        try: text = (generate(request(saved, i)) or "").strip()
        except Exception as e: log.append(f"model error: {type(e).__name__}"); continue
        line = next((l.strip().strip("`").strip() for l in text.splitlines() if l.strip()), "")
        try: r = lang.run(line, st)
        except lang.LinaError as e: log.append(f"rejected `{line[:60]}`: {str(e)[:70]}"); continue
        d = r["decision"]
        if d is None: log.append(f"`{line}`: condition not true tonight"); continue
        c = apply(base, d, genes)
        if c is None: log.append(f"`{line}`: changes nothing"); continue
        if c not in out: out.append(c); log.append(f"`{line}` -> try {c['brain']} {c['hidden']}n hold {c['hold']}d sees {c['inputs']}")
    return out, log


def load():
    """The coach model once per night: a function request -> answer, or None (with the reason in _model['why'])."""
    if not _model["tried"]:
        _model["tried"] = True
        try:
            import local_llm, train
            gen, why = local_llm.load(os.environ.get("COACH_MODEL"), max_new_tokens=40)
            if gen is None: _model["why"] = why
            else:
                def ask(req, _g=gen): return _g(train.messages(req, shots=True))
                ask.model_name = gen.model_name; _model["gen"] = ask
        except Exception as e: _model["why"] = f"{type(e).__name__}: {str(e)[:80]}"
    return _model["gen"]


def coach(saved, genes, loader=load, clock=time.monotonic):
    """Tonight's coach genomes for one market/band, plus report lines. Never raises."""
    if _model["spent"] > BUDGET_S: return [], ["- AI coach: time budget used up for tonight"]
    gen = loader()
    if gen is None: return [], [f"- AI coach: off ({_model['why'] or 'no model'})"]
    t0 = clock()
    try: seeds, log = suggestions(gen, saved, genes)
    except Exception as e: seeds, log = [], [f"problem: {e}"]
    _model["spent"] += clock() - t0
    return seeds, [f"- AI coach ({getattr(gen, 'model_name', '?')}, $0): {len(seeds)} ideas sent to the exams"] + [f"    {l}" for l in log[:6]]
