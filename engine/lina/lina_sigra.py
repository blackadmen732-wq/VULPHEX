#!/usr/bin/env python3
"""Lina Sigra - turns Lina Eldoria (Eldorian) text into number codes and back.

Usage:
  python3 lina_sigra.py encode "Ke vi sava Eldorian?"
  python3 lina_sigra.py decode "0006 0000 ..."
  python3 lina_sigra.py binary "Mi ama Eldoria."      (14-bit lit/dark signal for crystals)
  python3 lina_sigra.py gloss  "Mi ta fora un doma nova."  (word-by-word English)
"""
import json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = json.load(open(os.path.join(HERE, "lina_eldoria_lexicon.json"), encoding="utf-8"))
ENTRIES = DATA["entries"]
BY_WORD = {e["eldorian"].lower(): e for e in ENTRIES if e["class"] != 9 and not e.get("tag_only") and e["eldorian"] not in "#@*,."}
BY_CODE = {e["code"]: e for e in ENTRIES}
NAMES = sorted((e for e in ENTRIES if e["class"] == 9), key=lambda e: -len(e["eldorian"]))
ALIASES = {"eldorian": "Lina Eldoria", "orion": "Orion Mark Voss"}  # short forms -> registry
ALIASES = dict(sorted(ALIASES.items(), key=lambda kv: -len(kv[0])))

NUM, NAME, NEW, COMMA, STOP, END = "0090", "0091", "0092", "0097", "0098", "0099"
NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


class WireError(ValueError):
    """A malformed Lina Sigra message. Never guessed at, never partly obeyed."""


def check(codes):
    """CRC-16/CCITT over the whole message, unknown words included. Unlike a sum, it changes when codes are
    reordered (`Mi ama.` vs `Ama mi.`). It catches damage, not forgery: who sent a message is checked separately."""
    crc = 0xFFFF
    for b in " ".join(codes if isinstance(codes, list) else codes.split()).encode("utf-8"):
        crc ^= b << 8
        for _ in range(8): crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def strict_decode(codes):
    """decode(), but every problem is a WireError with its position: a missing end marker, an unknown code, a
    marker with nothing after it, a bad number, a name that isn't registered, or anything after the end."""
    codes = codes if isinstance(codes, list) else codes.split()
    if not codes or codes[-1] != END: raise WireError("message has no end marker (0099)")
    i = 0; open_sentence = False
    while i < len(codes) - 1:
        c = codes[i]
        if c in (NUM, NEW, NAME):
            if i + 1 >= len(codes) - 1: raise WireError(f"position {i}: {c} has nothing after it")
            v = codes[i + 1]
            if c == NUM and not NUMBER.fullmatch(v): raise WireError(f"position {i + 1}: `{v}` is not a number")
            if c == NAME and (v not in BY_CODE or BY_CODE[v]["class"] != 9): raise WireError(f"position {i + 1}: `{v}` is not a registered name")
            if c == NEW and not re.fullmatch(r"[^\W\d_][\w\-']*", v): raise WireError(f"position {i + 1}: `{v}` is not a word")
            open_sentence = True; i += 2; continue
        if c == END: raise WireError(f"position {i}: end marker before the end")
        if c not in BY_CODE: raise WireError(f"position {i}: `{c}` is not a Lina Sigra code")
        if BY_CODE[c]["class"] == 9: raise WireError(f"position {i}: a name needs its marker 0091 first")
        open_sentence = c != STOP; i += 1
    if open_sentence: raise WireError("the last sentence has no end marker (0098); it would be silently lost")
    return decode(codes)


def encode(text):
    out = []
    for sentence in re.split(r"(?<=[.!?])\s+", text.strip()):
        if not sentence:
            continue
        s = sentence
        for n in NAMES:  # full names first, longest first, whole words only
            s = re.sub(r"\b" + re.escape(n["eldorian"]) + r"\b", "\x00" + n["code"] + "\x00", s, flags=re.I)
        for alias, target in ALIASES.items():  # then short forms
            code = next(e["code"] for e in NAMES if e["eldorian"] == target)
            s = re.sub(r"\b" + re.escape(alias) + r"\b", "\x00" + code + "\x00", s, flags=re.I)
        # Nov 21 fix: whole signed decimals (-12.5 stayed apart as 12 and 5) and any-alphabet words (Crème lost its
        # letters and the stray `e` became 1015 = "and")
        tokens = re.findall(r"\x00\d{4}\x00|(?<![\w.])-?\d+(?:\.\d+)?|[^\W\d_](?:[^\W\d_]|[-'](?=[^\W\d_]))*|,", s)
        for t in tokens:
            if t.startswith("\x00"):
                out += [NAME, t.strip("\x00")]
            elif NUMBER.fullmatch(t):
                out += [NUM, t]
            elif t == ",":
                out.append(COMMA)
            elif t.lower() in BY_WORD:
                out.append(BY_WORD[t.lower()]["code"])
            else:
                out += [NEW, t.lower()]
        out.append(STOP)
    out.append(END)
    return out


def decode(codes):
    words, sentence, i = [], [], 0
    codes = codes if isinstance(codes, list) else codes.split()
    while i < len(codes):
        c = codes[i]
        if c in (NUM, NEW):
            sentence.append(codes[i + 1]); i += 2; continue
        if c == NAME:
            sentence.append(BY_CODE[codes[i + 1]]["eldorian"]); i += 2; continue
        if c == COMMA:
            if sentence: sentence[-1] += ","
        elif c == STOP:
            if sentence:
                line = " ".join(sentence)
                q = BY_CODE["0006"]["eldorian"]
                words.append(line[0].upper() + line[1:] + ("?" if sentence[0] == q else "."))
            sentence = []
        elif c == END:
            break
        else:
            sentence.append(BY_CODE[c]["eldorian"])
        i += 1
    return " ".join(words)


def gloss(text):
    rows = []
    codes = encode(text)
    i = 0
    while i < len(codes):
        c = codes[i]
        if c in (NUM, NEW, NAME):
            v = codes[i + 1]
            label = {NUM: "number", NEW: "NEW WORD (not in lexicon)", NAME: "name"}[c]
            rows.append(f"{c} {v:<6} {BY_CODE[v]['eldorian'] if c == NAME else v:<16} {label}")
            i += 2; continue
        e = BY_CODE[c]
        rows.append(f"{c}        {e['eldorian']:<16} {e['english']}")
        i += 1
    return "\n".join(rows)


def binary(text):
    """Each code as 14 bits (codes run 0000-9999): 1 = lit crystal, 0 = dark."""
    out = []
    for c in encode(text):
        out.append(format(int(c), "014b") if c.isdigit() else "".join(format(ord(ch), "08b") for ch in c))
    return " ".join(out)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__); sys.exit(1)
    cmd, arg = sys.argv[1], " ".join(sys.argv[2:])
    print({"encode": lambda a: " ".join(encode(a)), "decode": decode, "gloss": gloss, "binary": binary}[cmd](arg))
