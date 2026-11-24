# Free local AI model (owner's request, Nov 21 2026): run an open model ON THE KAGGLE MACHINE itself, with no API, no
# key and no cost per question. Paper research only.
#
# First job: a FAIR TEST against Claude. Each night the free model scores the SAME news items Claude scored, and both
# sets are saved side by side (news/local_scores.json). The free model replaces Claude only after it holds up on many
# nights; until then it only records. Nothing here can stop the nightly run: every failure becomes a report line.
#
# Model: Qwen2.5-1.5B-Instruct (Apache-2.0), downloaded from Hugging Face during the run; runs on GPU or plain CPU.
# Override with LOCAL_MODEL. A time budget stops it (LOCAL_BUDGET_S, default 15 minutes).
# First check (Nov 21, 5 sample headlines, CPU): direction right on clear good/bad news, but routine news (a
# conference, a new marketing chief) scored +/-1 instead of ~0. Small models overreact; the nightly test measures it.
import json, math, os, re, time

GPU_MODEL = CPU_MODEL = "Qwen/Qwen2.5-1.5B-Instruct"     # ~1.5 s per stock on a plain CPU, ~250 stocks fit the budget
BUDGET_S = float(os.environ.get("LOCAL_BUDGET_S", "900"))
NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def prompt(ticker, item):
    """The same question Claude gets, for one stock at a time (small models do better one at a time)."""
    return ("You score overnight news for a US stock. Give ONE number from -1 to 1: how this news is likely to move the "
            "stock price over the next few days compared with the overall market (-1 clearly bad, +1 clearly good, 0 nothing "
            "that matters, routine, or old news). Most stocks most days are near 0. Use only the text below. "
            "Answer with the number only.\n\nTicker: " + ticker + "\n" + json.dumps(item)[:3000])


def parse(text):
    """The first number in the answer, clipped to -1..1. None if the model didn't give one."""
    m = NUMBER.search(text or "")
    if not m: return None
    v = float(m.group())
    return max(-1.0, min(1.0, v)) if math.isfinite(v) else None


def load(model_id=None, max_new_tokens=8):
    """A function prompt (text, or a list of chat messages) -> answer text using a free local model, or (None, why)."""
    try:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
    except Exception as e:
        return None, f"transformers/torch not installed ({type(e).__name__})"
    gpu = torch.cuda.is_available()
    name = model_id or os.environ.get("LOCAL_MODEL") or (GPU_MODEL if gpu else CPU_MODEL)
    try:
        tok = AutoTokenizer.from_pretrained(name)
        model = AutoModelForCausalLM.from_pretrained(name, torch_dtype=torch.float16 if gpu else torch.float32)
        model.to("cuda" if gpu else "cpu").eval()
    except Exception as e:
        return None, f"could not load {name} ({type(e).__name__}: {str(e)[:80]})"

    def generate(text):
        msgs = text if isinstance(text, list) else [{"role": "user", "content": text}]
        enc = tok.apply_chat_template(msgs, add_generation_prompt=True, return_tensors="pt", return_dict=True)
        enc = {k: v.to(model.device) for k, v in enc.items()}          # a dict in old and new transformers alike
        with torch.no_grad():
            out = model.generate(**enc, max_new_tokens=max_new_tokens, do_sample=False, pad_token_id=tok.eos_token_id)
        return tok.decode(out[0][enc["input_ids"].shape[1]:], skip_special_tokens=True)
    generate.model_name = name; generate.device = "gpu" if gpu else "cpu"
    return generate, None


def score(items, generate, budget_s=BUDGET_S, clock=time.monotonic):
    """{ticker: score} for as many items as fit in the time budget (tickers in a fixed order, so nights compare)."""
    out, t0 = {}, clock()
    for t in sorted(items):
        if clock() - t0 > budget_s: break
        try: v = parse(generate(prompt(t, items[t])))
        except Exception: v = None
        if v is not None: out[t] = v
    return out


def agreement(claude, local):
    """How closely the free model matches Claude on the stocks both scored: count, same direction, correlation."""
    both = sorted(set(claude) & set(local))
    if not both: return {"n": 0, "same_sign": None, "corr": None}
    a = [claude[t] for t in both]; b = [local[t] for t in both]
    sign = lambda x: (x > 0.05) - (x < -0.05)
    same = sum(sign(x) == sign(y) for x, y in zip(a, b)) / len(both)
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    va, vb = sum((x - ma) ** 2 for x in a), sum((y - mb) ** 2 for y in b)
    corr = sum((x - ma) * (y - mb) for x, y in zip(a, b)) / math.sqrt(va * vb) if va > 0 and vb > 0 else None
    return {"n": len(both), "same_sign": round(same, 3), "corr": None if corr is None else round(corr, 3)}


def nightly(supa, today, items, claude_scores, loader=load):
    """Score tonight's items with the free model, save them next to Claude's, and say how close they were."""
    hist = supa.get_json("news/local_scores.json") or {}
    if today in hist: return f"- free model news test: already done for {today}"
    if not items: return "- free model news test: no news tonight"
    generate, why = loader()
    if generate is None: return f"- free model news test: skipped ({why})"
    t0 = time.monotonic(); local = score(items, generate); took = time.monotonic() - t0
    agree = agreement(claude_scores, local)
    hist[today] = {"model": getattr(generate, "model_name", "?"), "scores": {t: round(v, 2) for t, v in local.items()}, "vs_claude": agree}
    supa.put_json("news/local_scores.json", hist)
    sa = "-" if agree["same_sign"] is None else f"{agree['same_sign']:.0%}"
    return (f"- free model news test ({getattr(generate, 'model_name', '?')} on {getattr(generate, 'device', '?')}, $0): scored "
            f"{len(local)} of {len(items)} stocks in {took:.0f}s; vs Claude on {agree['n']}: same direction {sa}, "
            f"correlation {agree['corr'] if agree['corr'] is not None else '-'} (records only; Claude stays in charge)")
