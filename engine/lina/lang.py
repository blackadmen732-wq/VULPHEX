#!/usr/bin/env python3
"""Lina Sigra, the programming language for bots (owner's language, Nov 21 2026). Paper research only.

Lina Eldoria is the vocabulary. Lina Sigra is the machine layer (every word is a 4-digit code). This file makes it a
language a bot can RUN: you write a desk rule in Lina, the bot follows it, and anyone can read why it did.

    se risk es alta: na no va menda 10 dia            if risk is high: we will not trade for 10 days

Built for agents, not people:
  - EVERY WORD IS EXACT. A word is only legal if it is in the dictionary, with the meaning the dictionary gives it.
    `si` (yes) where `se` (if) belongs is an error with a suggestion, never a guess.
  - IT ALWAYS FINISHES. No loops, no variables, no jumps: rules are checked top to bottom, the first one that
    matches decides. A program can't hang, and it costs at most one check per rule.
  - IT CAN ONLY SEE WHAT THE DESK HANDS IT. The runner reads a frozen copy of the desk's state (numbers, and the
    words alta/basa/lena/mala/vora/falsa). Nothing else exists for it: no internet, no files, no money.
    The word `moni` (money) is refused outright.
  - IT CAN ONLY BE MORE CAREFUL. The actions are: pause new trades (or stop for today), watch (record what it would
    have done), close open paper trades, ask the owner, double-check, or run the desk's approved paper rule at full,
    half or quarter size. Nothing can raise a size, add a market or go live.
  - LOCKED WORDS ARE REFUSED. moni (money), paga (pay), vori (buy), sori (sell), dela (give), toma (take) and
    valida (approve) can't appear in a program at all, so no bot can order them or approve itself (owner, Nov 21).
  - SUGGESTIONS ARE NOT ORDERS. `fora neta`, `tena`, `suma`, `rimae` only PROPOSE a change to the bot's settings;
    the desk sends it to the exams and the luck filter, and only a change that passes is ever used.
  - EVERY DECISION EXPLAINS ITSELF. The result names the exact sentence, the line, the values that triggered it,
    the optional `kava` (because) reason, and the program's fingerprint (sha256 of its Lina Sigra codes).
  - IT CHECKS ITSELF FIRST. `check` warns about a subject used as both a label and a number, and about rules
    that can never be reached.
  - IT TRANSLATES BACK. `gloss` turns any program into plain English sentences, from what the reader understood.

Grammar (one rule per line, or the action indented on the next line):
    rule      := "se" cond ":" action ["kava" word+]
    cond      := test (("e" | "o") test)*                   e = and (checked first), o = or
    test      := subject "es" ["no"] value
    value     := alta | basa | lena | mala | vora | falsa          the desk's label for that subject
               | (alta | basa) number                              above / below a number
    test      := ... | "fila" "de" count "mala"                    count losses in a row or more (tri, 3, ...)
    action    := "na" "va" "pausa" number (dia | sema)             pause new trades (long form: na no va menda ...)
               | "na" "va" "halta"                                 stop until the owner restarts the bot
               | "na" "no" "va" "menda" number (dia | sema)        pause new trades
               | "na" "no" "va" "menda" "esta" "dia"               stop trading for today
               | "na" "va" "mira"                                  watch only (shadow results keep coming)
               | "na" "va" "menda" ["pika" | "un" "karta"]         run the approved paper rule (half / quarter size)
               | "na" "va" "sera" "ala"                            close all open paper trades
               | "na" "va" "pesa" "la" "tenor"                     ask the owner (the bot waits for a human)
               | "na" "va" "vera"                                  double-check before trading
               | "na" "va" "fora" "neta" number                    SUGGEST a Rocket network of 8/16/32/64 neurons
               | "na" "va" "tena" ("lorga" | "kurta")              SUGGEST keeping trades longer / shorter
               | "na" "va" ("suma" | "rimae") input                SUGGEST using / ignoring an input
    subject   := any dictionary word the desk provides (e.g. risk, preza, regra, merka, trema, novia, fila)
    labels    := alta basa lena mala vora falsa, plus rapa (fast, wild) parla (calm) multe (much)
                 (lenta, slow, is refused: one letter from lena, good, so a typo would change the meaning silently)
"""
import datetime, difflib, hashlib, json, math, os, re, sys
from collections.abc import Mapping
from functools import cache
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lina_sigra as sigra

WORDS = sigra.BY_WORD                                   # word -> {"code", "english", ...}
LABELS = {"alta", "basa", "lena", "mala", "vora", "falsa", "rapa", "parla", "multe"}   # not lenta: one letter from lena
FORBIDDEN = {"moni": "money is not something a Lina program can touch (paper research only)",
             **{w: f"`{w}` ({why}) is a locked word: no bot can order it (paper research only)" for w, why in
                {"paga": "pay", "vori": "buy", "sori": "sell", "dela": "give", "toma": "take", "valida": "approve"}.items()}}
INPUTS = {"risk", "preza", "regra", "merka", "trema", "novia", "fila", "gania", "perdia", "kosta", "dato", "sensa"}   # what suma/rimae may name
NEURONS = {8, 16, 32, 64}
COUNT = {"un": 1, "du": 2, "tri": 3, "kar": 4, "pen": 5, "ses": 6, "set": 7, "ot": 8, "nov": 9, "des": 10}
GRAMMAR = {"se", "es", "no", "e", "o", "na", "va", "menda", "mira", "pika", "un", "karta", "dia", "sema", "esta", "sera",
           "ala", "pesa", "la", "tenor", "vera", "fora", "neta", "tena", "lorga", "kurta", "suma", "rimae", "kava",
           "pausa", "halta", "de", "fila"} | LABELS | set(COUNT)
CONFUSED = {"si": "se", "kon": "se", "ke": "se"}        # common slips: si = yes, kon = with
MAX_RULES, MAX_LINE = 64, 200
VERSION = "lina-sigra 0.4"                             # the interpreter version, saved with every logged decision
UNITS = {"dia": 1, "sema": 7}
RECEIPT_FORMAT = 1


class LinaError(Exception):
    def __init__(self, line, msg):
        super().__init__(f"{'line ' + str(line) if line else 'input'}: {msg}"); self.line = line


def _hint(w):
    if w in CONFUSED:
        return f"`{w}` means {WORDS[w]['english']!r}; did you mean `{CONFUSED[w]}` ({WORDS[CONFUSED[w]]['english']})?"
    near = difflib.get_close_matches(w, list(WORDS), n=3, cutoff=0.7)   # on a tie, suggest a word the grammar uses
    near.sort(key=lambda c: (-difflib.SequenceMatcher(None, w, c).ratio(), c not in GRAMMAR))
    return f"`{w}` is not in the dictionary" + (f"; did you mean `{near[0]}` ({WORDS[near[0]]['english']})?" if near else "")


def _num(t):
    return re.fullmatch(r"-?\d+(\.\d+)?", t) is not None


def tokens(text, line):
    out = []
    for t in re.findall(r"-?\d+(?:\.\d+)?|[A-Za-z][A-Za-z\-']*|:|\S", text):
        if t == ":" or _num(t): out.append(t); continue
        w = t.lower()
        if not w.isalpha() and w not in WORDS: raise LinaError(line, f"`{t}` is not part of Lina")
        if w in FORBIDDEN: raise LinaError(line, FORBIDDEN[w])
        if w not in WORDS: raise LinaError(line, _hint(w))
        out.append(w)
    return out


class _P:
    """A tiny recursive-descent reader over one rule's tokens."""
    def __init__(self, toks, line): self.t, self.i, self.line = toks, 0, line
    def peek(self): return self.t[self.i] if self.i < len(self.t) else None
    def take(self, *want):
        tok = self.peek()
        if want and tok not in want:
            got = "the end of the line" if tok is None else f"`{tok}`"
            exp = " or ".join(f"`{w}`" for w in want)
            raise LinaError(self.line, f"expected {exp}, found {got}" + (f" ({_hint(tok)})" if tok in CONFUSED else ""))
        if tok is None: raise LinaError(self.line, "the line ends too early")
        self.i += 1; return tok
    def number(self):
        tok = self.peek()
        if tok is None or not _num(tok): raise LinaError(self.line, f"expected a number, found {tok and '`' + tok + '`' or 'the end of the line'}")
        self.i += 1; return float(tok)


def _test(p):
    subj = p.take()
    if _num(subj) or subj in LABELS or subj in ("se", "e", "o", "na", "es", ":"):
        raise LinaError(p.line, f"expected something the desk measures (like `risk`), found `{subj}`")
    if subj == "fila" and p.peek() == "de":              # fila de tri mala = three losses in a row (or more)
        p.take("de"); w = p.take()
        n = COUNT.get(w, float(w) if _num(w) else None)
        if n is None or n != int(n) or not 1 <= n <= 100: raise LinaError(p.line, f"`fila de` needs a count (tri, 3, ...), found `{w}`")
        p.take("mala")
        return {"subject": "fila", "not": False, "value": "alta", "number": float(n - 1)}   # same as `fila es alta n-1`
    p.take("es"); neg = False
    if p.peek() == "no": p.take(); neg = True
    if p.peek() == "lenta":
        raise LinaError(p.line, "`lenta` (slow) is one letter from `lena` (good), so Lina won't use it as a label; for a calm market write `parla`")
    val = p.take(*sorted(LABELS)); num = None
    if p.peek() is not None and _num(p.peek()):
        if val not in ("alta", "basa"): raise LinaError(p.line, f"only `alta` (above) or `basa` (below) take a number, not `{val}`")
        num = p.number()
    return {"subject": subj, "not": neg, "value": val, "number": num}


def _cond(p):
    ors, ands = [], [_test(p)]
    while p.peek() in ("e", "o"):
        if p.take() == "o": ors.append(ands); ands = []
        ands.append(_test(p))
    ors.append(ands); return ors                         # [[test and test] or [test]]


def _pause(p):
    n = p.number(); unit = p.take("dia", "sema")
    if n <= 0 or n != int(n) or n * UNITS[unit] > 365: raise LinaError(p.line, "a pause is a whole number of days, 1 to 365")
    return {"do": "pause", "days": int(n * UNITS[unit])}


def _action(p):
    p.take("na")
    if p.peek() == "no":
        p.take("no"); p.take("va"); p.take("menda")
        if p.peek() == "esta": p.take(); p.take("dia"); return {"do": "stop_today"}
        return _pause(p)
    p.take("va"); verb = p.take("menda", "mira", "pausa", "halta", "sera", "pesa", "vera", "fora", "tena", "suma", "rimae")
    if verb == "mira": return {"do": "watch"}
    if verb == "halta": return {"do": "halt"}
    if verb == "pausa":                                  # short form: na va pausa 10 dia = na no va menda 10 dia
        if p.peek() == "esta": p.take(); p.take("dia"); return {"do": "stop_today"}
        return _pause(p)
    if verb == "sera": p.take("ala"); return {"do": "close_all"}
    if verb == "pesa": p.take("la"); p.take("tenor"); return {"do": "ask_owner"}
    if verb == "vera": return {"do": "double_check"}
    if verb == "fora":
        p.take("neta"); n = p.number()
        if n not in NEURONS: raise LinaError(p.line, f"a Rocket network has {', '.join(map(str, sorted(NEURONS)))} neurons, not {n:g}")
        return {"do": "suggest", "set": "neurons", "to": int(n)}
    if verb == "tena": return {"do": "suggest", "set": "hold", "to": "longer" if p.take("lorga", "kurta") == "lorga" else "shorter"}
    if verb in ("suma", "rimae"):
        w = p.take()
        if w not in INPUTS: raise LinaError(p.line, f"`{w}` is not an input a bot can use; inputs: {', '.join(sorted(INPUTS))}")
        return {"do": "suggest", "set": "use_input" if verb == "suma" else "ignore_input", "to": w}
    if p.peek() == "pika": p.take(); return {"do": "run", "size": 0.5}
    if p.peek() == "un": p.take(); p.take("karta"); return {"do": "run", "size": 0.25}
    return {"do": "run", "size": 1.0}


def parse(source):
    """Lina text -> list of rules. Raises LinaError with the line and a plain-words reason."""
    rules, lines = [], source.splitlines()
    i = 0
    while i < len(lines):
        raw = lines[i].split("#")[0].rstrip(); n = i + 1; i += 1
        if not raw.strip(): continue
        if len(raw) > MAX_LINE: raise LinaError(n, f"a line is at most {MAX_LINE} characters")
        if raw[0].isspace(): raise LinaError(n, "an indented action needs a `se ...:` line above it")
        toks = tokens(raw, n); text = raw.strip()
        if toks and toks[-1] == ":":                     # action on the next, indented, line
            while i < len(lines) and not lines[i].split("#")[0].strip(): i += 1
            if i >= len(lines) or not lines[i][:1].isspace(): raise LinaError(n, "after `:` the action goes on the next line, indented")
            action_line = lines[i].split("#")[0].rstrip()
            if len(action_line) > MAX_LINE:
                raise LinaError(i + 1, f"a line is at most {MAX_LINE} characters")
            toks += tokens(action_line, i + 1)
            text += " " + action_line.strip()
            i += 1
        p = _P(toks, n); p.take("se"); cond = _cond(p); p.take(":"); act = _action(p); why = []
        if p.peek() == "kava":
            p.take(); why = p.t[p.i:]; p.i = len(p.t)
            if not why: raise LinaError(n, "`kava` (because) needs a reason after it")
            if any(_num(w) or w == ":" for w in why): raise LinaError(n, "a `kava` reason is words only")
        if p.peek() is not None: raise LinaError(n, f"unexpected `{p.peek()}` after the action")
        rules.append({"line": n, "text": text, "cond": cond, "action": act, "because": why, "tokens": toks})
        if len(rules) > MAX_RULES: raise LinaError(n, f"a program has at most {MAX_RULES} rules")
    if not rules: raise LinaError(1, "the program has no rules")
    return rules


def lint(rules):
    """Mistakes found before anything runs: a subject compared as a label in one place and a number in another,
    and rules that can never be reached because an earlier rule has the exact same condition."""
    warn, kind, seen = [], {}, {}
    for r in rules:
        for g in r["cond"]:
            for t in g:
                k = "number" if t["number"] is not None else "label"
                if kind.setdefault(t["subject"], (k, r["line"]))[0] != k:
                    warn.append(f"line {r['line']}: `{t['subject']}` is compared as a {k} here but as a {kind[t['subject']][0]} on line {kind[t['subject']][1]}")
        key = json.dumps(r["cond"], sort_keys=True)
        if key in seen: warn.append(f"line {r['line']}: never reached, line {seen[key]} has the same condition and decides first")
        seen.setdefault(key, r["line"])
    return warn


def codes(rules):
    """The program as Lina Sigra codes (words -> 4-digit codes, numbers -> 0090 + digits, each rule ends 0098)."""
    out = []
    for r in rules:
        for t in r["tokens"]:
            if t == ":": out.append("0097")              # the colon is written as the comma mark
            elif _num(t): out += [sigra.NUM, t]
            else: out.append(WORDS[t]["code"])
        out.append(sigra.STOP)
    return out + [sigra.END]


def fingerprint(rules):
    return hashlib.sha256(" ".join(codes(rules)).encode()).hexdigest()


_PLAIN = {"alta": "high", "basa": "low", "lena": "good", "mala": "bad", "vora": "true", "falsa": "false",
          "rapa": "wild", "parla": "calm", "multe": "high", "trema": "fear", "novia": "the news", "fila": "the losing streak",
          "merka": "the market", "tenor": "the owner", "gania": "profit", "perdia": "the loss", "kosta": "the cost",
          "talia": "the size", "pozia": "the open trade", "vinsa": "the win"}


def _en(w):
    if w in _PLAIN: return _PLAIN[w]
    if w in ("es", "va", "ta"): return {"es": "is", "va": "will", "ta": "did"}[w]
    return WORDS[w]["english"].split(";")[0].split("(")[0].strip()


def english(r):
    """One rule as a plain English sentence, built from what the reader understood (not a word-by-word guess)."""
    def test(t):
        subj = _en(t["subject"])
        if t["number"] is not None:
            return f"{subj} is {'not ' if t['not'] else ''}{'above' if t['value'] == 'alta' else 'below'} {t['number']:g}"
        return f"{subj} is {'not ' if t['not'] else ''}{_PLAIN[t['value']]}"
    cond = " or ".join(" and ".join(test(t) for t in g) for g in r["cond"])
    a = r["action"]
    act = {"pause": lambda: f"we will not open new trades for {a['days']} day{'s' if a['days'] != 1 else ''}",
           "watch": lambda: "we will only watch (record what we would have done)",
           "stop_today": lambda: "we will not trade for the rest of today",
           "halt": lambda: "we will stop trading until the owner restarts us",
           "close_all": lambda: "we will close all open paper trades",
           "ask_owner": lambda: "we will ask the owner first",
           "double_check": lambda: "we will double-check before trading",
           "suggest": lambda: "we suggest " + {"neurons": lambda: f"a Rocket network of {a['to']} neurons",
                                               "hold": lambda: f"keeping trades {a['to']}",
                                               "use_input": lambda: f"using {_en(a['to'])} as an input",
                                               "ignore_input": lambda: f"ignoring {_en(a['to'])}"}[a["set"]]() + " (the exams decide)",
           "run": lambda: "we will run the approved paper rule" + {1.0: "", 0.5: " at half size", 0.25: " at quarter size"}[a.get("size", 1.0)]}[a["do"]]()
    why = f", because {' '.join(_en(w) for w in r['because'])}" if r["because"] else ""
    return f"If {cond}, {act}{why}."


def gloss(rules):
    """Plain English for every rule."""
    return [f"line {r['line']}: {english(r)}" for r in rules]


def _check(t, state, line):
    s = t["subject"]
    if s not in state: raise LinaError(line, f"the desk doesn't provide `{s}` ({WORDS[s]['english']}); it provides: {', '.join(sorted(state)) or 'nothing'}")
    v = state[s]
    if t["number"] is not None:
        if isinstance(v, bool) or not isinstance(v, (int, float)): raise LinaError(line, f"`{s}` is `{v}`, not a number")
        hit = v > t["number"] if t["value"] == "alta" else v < t["number"]
    else:
        if v not in LABELS: raise LinaError(line, f"`{s}` is {v!r}; compare it with a number (`alta 0.5`) or give the desk a label")
        hit = v == t["value"]
    return hit != t["not"], v


def _desk_state(state):
    if not isinstance(state, Mapping):
        raise LinaError(0, "the desk state must be an object")
    seen = {}
    for key, value in state.items():
        if key not in WORDS or key in FORBIDDEN:
            continue
        if isinstance(value, float) and not math.isfinite(value):
            raise LinaError(0, f"`{key}` is {value}, not a valid number; the desk must fix its input before Lina decides anything")
        if type(value) is int or type(value) is float or (isinstance(value, str) and value in LABELS):
            seen[key] = value
    return seen


def run(program, state):
    """Follow the program against the desk's state. A None decision means no rule matched."""
    rules = parse(program) if isinstance(program, str) else program
    return _evaluate(rules, _desk_state(state))


def _evaluate(rules, seen):
    fp = fingerprint(rules)
    for r in rules:
        used, any_ok = {}, False
        for group in r["cond"]:
            ok = True
            for t in group:
                hit, v = _check(t, seen, r["line"]); used[t["subject"]] = v; ok = ok and hit
                if not ok: break
            if ok: any_ok = True; break
        if any_ok:
            return {"decision": dict(r["action"]), "line": r["line"], "sentence": r["text"], "evidence": used,
                    "because": " ".join(r["because"]), "english": english(r), "program": fp, "inputs": seen, "version": VERSION}
    return {"decision": None, "line": None, "sentence": None, "evidence": {}, "because": "", "english": "no rule matched",
            "program": fp, "inputs": seen, "version": VERSION}


def log(path, desk, result, clock=None):
    """Append one decision to an append-only JSON-lines log (never rewritten): when, which desk, the interpreter
    version, the program fingerprint, the full rule, every input the program could see, and what it decided.
    The fingerprint names the program; this log is what lets anyone replay and audit the decision later."""
    rec = {"at": (clock or (lambda: datetime.datetime.now(datetime.timezone.utc)))().isoformat(), "desk": desk,
           **{k: result[k] for k in ("version", "program", "line", "sentence", "inputs", "evidence", "decision", "because", "english")}}
    with open(path, "a", encoding="utf-8") as f: f.write(json.dumps(rec, sort_keys=True) + "\n")
    return rec


def _digest(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()


@cache
def evaluator_fingerprint():
    return _digest({
        "interpreter": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "codec": hashlib.sha256(Path(sigra.__file__).read_bytes()).hexdigest(),
        "words": WORDS,
    })


def record(source, state):
    """Capture the exact rule source, visible inputs, evaluator identity, and result."""
    if not isinstance(source, str):
        raise LinaError(1, "a receipt needs Lina source text")
    state = _desk_state(state)
    receipt = {
        "format": RECEIPT_FORMAT,
        "engine": evaluator_fingerprint(),
        "source": source,
        "state": state,
        "result": _evaluate(parse(source), state),
    }
    return {**receipt, "id": _digest(receipt)}


def replay(receipt):
    """Verify a receipt and reproduce its decision with the recorded interpreter and inputs."""
    if not isinstance(receipt, dict) or receipt.get("format") != RECEIPT_FORMAT:
        raise LinaError(1, "unsupported decision receipt")
    payload = {key: value for key, value in receipt.items() if key != "id"}
    try:
        expected = _digest(payload)
    except (TypeError, ValueError) as error:
        raise LinaError(1, "receipt contains invalid data") from error
    if receipt.get("id") != expected:
        raise LinaError(1, "decision receipt fingerprint does not match its contents")
    if payload.get("engine") != evaluator_fingerprint():
        raise LinaError(1, "replay needs the interpreter and lexicon that created this receipt")
    current = record(payload.get("source"), payload.get("state"))
    if current != receipt:
        raise LinaError(1, "the recorded decision could not be reproduced")
    return current["result"]


STAND_DOWNS = ("pause", "stop_today", "halt", "watch", "close_all", "ask_owner", "double_check")


def compare(source, receipts):
    """Try a candidate policy against the same inputs captured in one or more verified receipts."""
    rules = parse(source)
    if isinstance(receipts, dict):
        receipts = [receipts]
    if not isinstance(receipts, list) or not receipts:
        raise LinaError(1, "compare needs a decision receipt or a nonempty list of receipts")
    outcomes = []
    for receipt in receipts:
        before = replay(receipt)
        case = {"receipt": receipt["id"], "before": before}
        try:
            after = _evaluate(rules, receipt["state"])
        except LinaError as error:
            outcomes.append({**case, "status": "input_error", "error": str(error)})
            continue
        old_action, new_action = before["decision"], after["decision"]
        old_size = old_action.get("size", 0) if old_action and old_action["do"] == "run" else 0
        new_size = new_action.get("size", 0) if new_action and new_action["do"] == "run" else 0
        outcomes.append({
            **case, "after": after,
            "status": "changed" if old_action != new_action else "unchanged",
            "new_or_larger_paper_run": new_size > old_size,
            "stand_down_removed": bool(old_action and old_action["do"] in STAND_DOWNS and (new_action is None or new_action["do"] == "run")),
        })
    return {
        "candidate": fingerprint(rules),
        "checked": len(outcomes),
        "changed": sum(case["status"] == "changed" for case in outcomes),
        "input_errors": sum(case["status"] == "input_error" for case in outcomes),
        "new_or_larger_paper_runs": sum(case.get("new_or_larger_paper_run", False) for case in outcomes),
        "stand_downs_removed": sum(case.get("stand_down_removed", False) for case in outcomes),
        "outcomes": outcomes,
    }


def main(argv):
    commands = ("check", "gloss", "codes", "run", "record", "replay", "compare")
    if len(argv) < 3 or argv[1] not in commands or (argv[1] == "compare" and len(argv) != 4):
        print("""Usage: lang.py check|gloss|codes FILE.lina
       lang.py run|record FILE.lina '{"risk": "alta"}'
       lang.py replay RECEIPT.json
       lang.py compare CANDIDATE.lina RECEIPTS.json""")
        return 2
    cmd = argv[1]
    try:
        src = Path(argv[2]).read_text(encoding="utf-8")
        if cmd == "replay":
            print(json.dumps(replay(json.loads(src)), indent=2))
            return 0
        if cmd == "compare":
            receipts = json.loads(Path(argv[3]).read_text(encoding="utf-8"))
            print(json.dumps(compare(src, receipts), indent=2))
            return 0
        if cmd in ("run", "record"):
            state = json.loads(argv[3] if len(argv) > 3 else "{}")
            decision = record(src, state) if cmd == "record" else run(src, state)
            print(json.dumps(decision, indent=2))
            return 0

        rules = parse(src)
        if cmd == "check":
            w = lint(rules); print("\n".join("warning, " + x for x in w)) if w else None
            print(f"{'ok' if not w else 'parsed with warnings'}: {len(rules)} rules, fingerprint {fingerprint(rules)[:16]}")
            return 1 if w else 0
        if cmd == "gloss":
            print("\n".join(gloss(rules)))
        else:
            print(" ".join(codes(rules)))
    except (LinaError, ValueError, OSError) as e:
        print(f"Lina error, {e}"); return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
