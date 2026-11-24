# Teach a free model (Qwen2.5, Apache-2.0) to turn plain English into valid Lina Sigra rules. Paper research only.
# Owner's request, Nov 21 2026: "train my bot" on a free model instead of paying an API.
#
#   examples()  English request -> Lina rule pairs, built from the grammar; EVERY target is parsed by the real engine
#   grade()     a model's answer is right only if Lina parses it AND it means the same thing (same conditions, same
#               action, same days, same reason), so "2 sema" and "14 dia" both count, and a near-miss doesn't
#   evaluate()  valid % and right % on examples the model never trained on
#   finetune()  LoRA on Kaggle's free GPU (needs torch, transformers, peft); runs in lina_trainer_kernel.py
#
# The model never runs anything: its answers are only text that Lina checks. A trained model is used only if it
# beats the untrained one on the held-out test, and every rule it writes still goes through check, replay and exams.
import json, os, random, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lang

SUBJECTS = {"risk": ["risk", "the risk", "our risk"], "preza": ["price", "the price", "the stock price"],
            "regra": ["the rule", "our rule", "the rule's record"], "merka": ["the market", "the whole market"],
            "trema": ["fear", "the fear level", "market fear"], "novia": ["the news", "the news score", "tonight's news"],
            "fila": ["the losing streak", "losses in a row", "the streak"], "gania": ["profit", "our profit", "today's profit"],
            "perdia": ["the loss", "our loss", "today's loss"], "kosta": ["the cost", "trading costs", "fees"]}
# which labels make sense for which subject (Lina Tekna, Nov 21: rapa = wild/fast, lenta = slow, multe = much)
LABELS_FOR = {"merka": ["rapa", "parla", "alta", "basa"], "gania": ["alta", "basa", "lena", "mala"], "perdia": ["alta", "basa"],
              "kosta": ["alta", "basa"], "trema": ["multe", "alta", "basa"], "fila": ["alta", "basa", "mala"],
              "novia": ["lena", "mala", "multe"]}
LABEL_EN = {"alta": ["high"], "basa": ["low"], "lena": ["good", "doing well"], "mala": ["bad", "doing badly"],
            "vora": ["true"], "falsa": ["false"], "rapa": ["wild", "fast", "moving fast"], "parla": ["calm", "quiet", "smooth"],
            "multe": ["very high", "a lot"]}
ABOVE = ["is above {n}", "goes over {n}", "is higher than {n}", "rises past {n}"]
BELOW = ["is below {n}", "drops under {n}", "is lower than {n}", "falls below {n}"]
PAUSE = ["pause new trades for {d}", "stop opening trades for {d}", "don't open any trades for {d}", "sit out for {d}"]
WATCH = ["only watch", "just watch and record what we would have done", "observe only", "stay on the sidelines and watch"]
RUN = ["run the approved paper rule", "trade the approved paper rule as normal", "go ahead with the approved paper rule"]
HALF = ["run the approved paper rule at half size", "trade the paper rule at half size", "go ahead at half size"]
QUARTER = ["run the approved paper rule at quarter size", "trade at a quarter of the size", "go ahead at quarter size"]
HALT = ["stop trading until the owner restarts us", "halt everything until the owner says go", "shut down trading until the owner restarts it"]
COUNT_WORD = {2: "du", 3: "tri", 4: "kar", 5: "pen"}
TODAY = ["stop trading for today", "don't trade any more today", "take the rest of the day off"]
CLOSE = ["close all open paper trades", "close every open trade", "get out of all open paper trades"]
ASK = ["ask the owner", "check with the owner first", "wait for the owner to decide"]
VERIFY = ["double-check before trading", "verify everything before trading", "check again before any trade"]
HOLD = {"lorga": ["keep trades longer", "hold positions longer"], "kurta": ["keep trades shorter", "close positions sooner"]}
INPUT_EN = {"novia": "the news", "trema": "the fear level", "preza": "the price", "merka": "the market", "fila": "the streak"}
REASONS = {"na sinta risk": "we feel risk", "regra es mala": "the rule is bad", "preza es basa": "the price is low",
           "risk es alta": "risk is high", "merka es rapa": "the market is wild", "novia es mala": "the news is bad",
           "trema es multe": "fear is very high", "perdia es alta": "the loss is high"}
SHAPES = ["If {c}, {a}{w}.", "When {c}, {a}{w}.", "{A} when {c}{w}.", "{A} if {c}{w}."]
SYSTEM = ("Translate the request into ONE Lina Sigra bot rule. Grammar: se <test> [e|o <test>]: <action> [kava <reason>]. "
          "test: <subject> es [no] alta|basa|lena|mala|vora|falsa|rapa|parla|multe, or <subject> es alta|basa <number> "
          "(above/below), or fila de <count> mala (that many losses in a row). subjects: risk, preza (price), regra (the "
          "rule), merka (market), trema (fear), novia (news), fila (losing streak), gania (profit), perdia (loss), kosta "
          "(cost). e = and, o = or. actions: na va pausa <n> dia|sema (pause n days or weeks); na va pausa esta dia "
          "(stop for today); na va halta (stop until the owner restarts); na va mira (watch only); na va menda (run the approved paper rule); "
          "na va menda pika (half size); na va menda un karta (quarter size); na va sera ala (close all trades); "
          "na va pesa la tenor (ask the owner); na va vera (double-check); suggestions: na va fora neta 8|16|32|64 "
          "(network size), na va tena lorga|kurta (keep trades longer/shorter), na va suma|rimae <subject> (use/ignore "
          "an input). Answer with the rule only.")
SHOTS = [("If risk is above 0.8, pause new trades for 10 days because we feel risk.",
          "se risk es alta 0.8: na va pausa 10 dia kava na sinta risk"),
         ("Only watch when the rule is bad and the price is below -0.05.", "se regra es mala e preza es basa -0.05: na va mira"),
         ("If risk is not high, run the approved paper rule.", "se risk es no alta: na va menda"),
         ("When the market is wild, close all open paper trades.", "se merka es rapa: na va sera ala")]


def _test(r):
    subj = r.choice(list(SUBJECTS))
    if subj == "fila" and r.random() < 0.5:                 # fila de tri mala: three losses in a row (or more)
        n = r.choice(list(COUNT_WORD)); w = COUNT_WORD[n] if r.random() < 0.6 else str(n)
        return f"fila de {w} mala", r.choice([f"we lost {n} in a row", f"we have {n} losses in a row", f"there are {n} losing trades in a row"])
    if r.random() < 0.5:
        n = r.choice([round(r.uniform(0.05, 0.95), 2), round(r.uniform(-0.2, 0.2), 2), r.randint(1, 100)])
        up = r.random() < 0.5
        lina = f"{subj} es {'alta' if up else 'basa'} {n:g}"
        en = f"{r.choice(SUBJECTS[subj])} " + r.choice(ABOVE if up else BELOW).format(n=f"{n:g}")
    else:
        label = r.choice(LABELS_FOR[subj] if subj in LABELS_FOR else
                         ["alta", "basa", "lena", "mala"] if r.random() < 0.9 else ["vora", "falsa"])
        neg = r.random() < 0.2
        lina = f"{subj} es {'no ' if neg else ''}{label}"
        en = f"{r.choice(SUBJECTS[subj])} is {'not ' if neg else ''}{r.choice(LABEL_EN[label])}"
    return lina, en


def _action(r):
    k = r.random()
    if k < 0.4:
        if r.random() < 0.7:
            d = r.randint(1, 30); lina = f"na va pausa {d} dia"; dur = f"{d} day{'s' if d != 1 else ''}"
        else:
            w = r.randint(1, 8); lina = f"na va pausa {w} sema"; dur = f"{w} week{'s' if w != 1 else ''}"
        return lina, r.choice(PAUSE).format(d=dur)
    if k < 0.5: return "na va mira", r.choice(WATCH)
    if k < 0.6: return "na va menda", r.choice(RUN)
    if k < 0.67: return "na va menda pika", r.choice(HALF)
    if k < 0.72: return "na va menda un karta", r.choice(QUARTER)
    if k < 0.75: return "na va pausa esta dia", r.choice(TODAY)
    if k < 0.77: return "na va halta", r.choice(HALT)
    if k < 0.82: return "na va sera ala", r.choice(CLOSE)
    if k < 0.86: return "na va pesa la tenor", r.choice(ASK)
    if k < 0.90: return "na va vera", r.choice(VERIFY)
    if k < 0.94:
        n = r.choice([8, 16, 32, 64]); return f"na va fora neta {n}", r.choice([f"suggest a network of {n} neurons", f"try {n} neurons"])
    if k < 0.97:
        h = r.choice(["lorga", "kurta"]); return f"na va tena {h}", "suggest we " + r.choice(HOLD[h])
    w = r.choice(list(INPUT_EN)); v = r.choice(["suma", "rimae"])
    return f"na va {v} {w}", ("suggest using " if v == "suma" else "suggest ignoring ") + INPUT_EN[w]


def example(r):
    """One (English request, Lina rule) pair. The Lina side always parses."""
    tests = [_test(r) for _ in range(r.choice([1, 1, 1, 2, 2, 3]))]
    joins = [r.choice(["e", "e", "o"]) for _ in tests[1:]]
    lina_c = tests[0][0] + "".join(f" {j} {t[0]}" for j, t in zip(joins, tests[1:]))
    en_c = tests[0][1] + "".join(f" {'and' if j == 'e' else 'or'} {t[1]}" for j, t in zip(joins, tests[1:]))
    act_lina, act_en = _action(r)
    reason = r.choice(list(REASONS)) if r.random() < 0.3 else None
    lina = f"se {lina_c}: {act_lina}" + (f" kava {reason}" if reason else "")
    w = f", because {REASONS[reason]}" if reason else ""
    en = r.choice(SHAPES).format(c=en_c, a=act_en, A=act_en[0].upper() + act_en[1:], w=w)
    lang.parse(lina)                                      # never emit a target the engine rejects
    return en, lina


def examples(n, seed=0):
    r, seen, out = random.Random(seed), set(), []
    while len(out) < n:
        en, lina = example(r)
        if en not in seen: seen.add(en); out.append({"request": en, "rule": lina})
    return out


def split(n_train=4000, n_test=300, seed=0):
    """Train and test share no request and no rule, so the test measures what the model learned, not what it saw."""
    pool = examples(n_train + n_test * 3, seed)
    test, train, rules = [], [], set()
    for ex in pool[::-1]:
        if len(test) < n_test: test.append(ex); rules.add(ex["rule"])
        elif ex["rule"] not in rules and len(train) < n_train: train.append(ex)
    return train, test


def meaning(rule):
    r = lang.parse(rule)
    if len(r) != 1: raise lang.LinaError(1, "expected exactly one rule")
    r = r[0]
    return json.dumps({"cond": r["cond"], "action": r["action"], "because": r["because"]}, sort_keys=True)


def grade(answer, target):
    """'right' (parses, same meaning), 'wrong' (parses, different meaning) or 'invalid' (Lina rejects it)."""
    lines = [l.strip().strip("`").strip() for l in (answer or "").splitlines()]
    line = next((l for l in lines if l), "")                  # the first non-empty line, without code backticks
    try: got = meaning(line)
    except lang.LinaError: return "invalid"
    return "right" if got == meaning(target) else "wrong"


def evaluate(generate, test):
    counts = {"right": 0, "wrong": 0, "invalid": 0}; misses = []
    for ex in test:
        try: g = grade(generate(ex["request"]), ex["rule"])
        except Exception: g = "invalid"
        counts[g] += 1
        if g != "right" and len(misses) < 5: misses.append(ex["request"])
    n = max(len(test), 1)
    return {"n": len(test), "right": round(counts["right"] / n, 3), "valid": round((counts["right"] + counts["wrong"]) / n, 3),
            "counts": counts, "examples_missed": misses}


def messages(request, shots=True):
    m = [{"role": "system", "content": SYSTEM}]
    if shots:
        for q, a in SHOTS: m += [{"role": "user", "content": q}, {"role": "assistant", "content": a}]
    return m + [{"role": "user", "content": request}]


def generator(model, tok, shots=True, max_new_tokens=60):
    import torch
    def gen(request):
        enc = tok.apply_chat_template(messages(request, shots), add_generation_prompt=True, return_tensors="pt", return_dict=True)
        enc = {k: v.to(model.device) for k, v in enc.items()}
        with torch.no_grad():
            out = model.generate(**enc, max_new_tokens=max_new_tokens, do_sample=False, pad_token_id=tok.eos_token_id)
        return tok.decode(out[0][enc["input_ids"].shape[1]:], skip_special_tokens=True)
    return gen


def finetune(model, tok, train, epochs=1, lr=2e-4, batch=8, log=print):
    """LoRA: train a small add-on (a few MB) on top of the frozen model. Loss only on the answer tokens."""
    import torch
    from peft import LoraConfig, get_peft_model
    model = get_peft_model(model, LoraConfig(r=16, lora_alpha=32, lora_dropout=0.05, task_type="CAUSAL_LM",
                                             target_modules=["q_proj", "k_proj", "v_proj", "qkv_proj", "o_proj"]))   # qkv_proj: Phi
    rows = []
    for ex in train:
        prompt = tok.apply_chat_template(messages(ex["request"], shots=False), add_generation_prompt=True, tokenize=False)
        p_ids = tok(prompt, add_special_tokens=False)["input_ids"]
        a_ids = tok(ex["rule"] + tok.eos_token, add_special_tokens=False)["input_ids"]
        rows.append((p_ids + a_ids, [-100] * len(p_ids) + a_ids))
    opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=lr)
    model.train(); step = 0
    for _ in range(epochs):
        random.Random(1).shuffle(rows)
        for i in range(0, len(rows), batch):
            chunk = rows[i:i + batch]; width = max(len(x) for x, _ in chunk)
            ids = torch.tensor([x + [tok.eos_token_id] * (width - len(x)) for x, _ in chunk], device=model.device)
            lab = torch.tensor([y + [-100] * (width - len(y)) for _, y in chunk], device=model.device)
            att = torch.tensor([[1] * len(x) + [0] * (width - len(x)) for x, _ in chunk], device=model.device)
            loss = model(input_ids=ids, attention_mask=att, labels=lab).loss
            loss.backward(); opt.step(); opt.zero_grad(); step += 1
            if step % 50 == 0: log(f"step {step}: loss {loss.item():.3f}")
    model.eval()
    return model
