"""Written call text -> what the engineer should say aloud ("0.7 a lap" -> "seven tenths a lap")."""
import json
import re
from pathlib import Path

PRONOUNCE = Path(__file__).resolve().parent / "pronounce.json"
DIGITS = "zero one two three four five six seven eight nine".split()
SPELT = {"VSC": "V S C", "ERS": "E R S"}


def _words(n):
    """0-99 in words; enough for seconds on a lap time."""
    teens = "ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
    tens = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()
    if n < 10:
        return DIGITS[n]
    if n < 20:
        return teens[n - 10]
    return tens[n // 10] + (f" {DIGITS[n % 10]}" if n % 10 else "")


def _lap_time(m):
    """1:06.986 -> "one oh six point nine eight six", the way it's said on the radio."""
    mins, secs, frac = int(m[1]), int(m[2]), m[3]
    s = f"oh {DIGITS[secs]}" if secs < 10 else _words(secs)
    return f"{DIGITS[mins]} {s} point " + " ".join(DIGITS[int(d)] for d in frac)


def _tenths(m):
    n = int(m[1])
    return f"{DIGITS[n]} tenth" + ("" if n == 1 else "s")


def _respell():
    try:
        return json.loads(PRONOUNCE.read_text())
    except (OSError, ValueError):
        return {}


def speakable(text):
    text = re.sub(r"[*_#`]", "", text)
    text = re.sub(r"\b(\d):(\d\d)\.(\d{2,3})\b", _lap_time, text)
    text = re.sub(r"\b0\.([1-9])(?!\d)", _tenths, text)
    text = re.sub(r"\b(\d+(?:\.\d+)?) ?s\b", lambda m: f"{m[1]} second" + ("" if m[1] == "1" else "s"), text)
    text = re.sub(r"\b(\d+) ?m\b", lambda m: f"{m[1]} metre" + ("" if m[1] == "1" else "s"), text)
    text = text.replace("seconds penalty", "second penalty")
    for word, said in {**SPELT, **_respell()}.items():
        text = re.sub(rf"\b{re.escape(word)}\b", said, text, flags=re.I)
    return text
