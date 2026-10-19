"""Numbers the engineer says that aren't in what it was given.

Checked a sentence at a time, before it's spoken. Allows what an engineer does with a figure on the
radio: rounding ("1.3" from +1.31), tenths in words ("nine tenths" from 0.9), a lap time by its
seconds ("a 16.7" for 1:16.695), metres rounded or said in km ("3000–3700", "4.9 km" from 2947–3692 m
and 4877 m), a hedged round number ("around 20°" from 22). A figure with a unit (%, °C, P, lap, kg, km/h) has to match one with the same unit, so a
wear figure moved on by a lap's rate isn't excused by some other 43 in the brief.
"""
import re

# lap times, then plain figures, which may be a lap or a position (an L or P straight before the digits)
TOKEN = re.compile(r"(?<![\w.])(\d+):(\d\d(?:\.\d+)?)(?![\d.])"
                   r"|(?:(?<=\bL)|(?<=\bP)|(?<![\w.:]))(\d+(?:\.\d+)?)(?![\d:])(s\b|\s*km\b(?!/h))?")
WORDS = {w: n for n, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen "
                                    "fourteen fifteen sixteen seventeen eighteen nineteen twenty".split())}
# a spelled-out count only claims a figure when a unit follows it ("five laps", not "the one")
SPELLED = re.compile(r"\b(" + "|".join(WORDS) + r")\s+(laps?|seconds?|tenths?|places?|positions?|percent|degrees?)\b", re.I)
HEDGED = re.compile(r"\b(around|about|roughly|nearly|almost|under|over|close to)\s+$", re.I)
UNITS = [("%", re.compile(r"\s*(%|percent\b)", re.I)), ("°C", re.compile(r"\s*(°|degrees?\b)", re.I)),
         ("kg", re.compile(r"\s*kg\b", re.I)), ("km/h", re.compile(r"\s*(km/h|kph\b|k's\b)", re.I))]


def unsupported(sentence, given):
    """The figures in `sentence` that `given` (the brief, the question) doesn't back."""
    pool = _pool(given)
    out = []
    for m in TOKEN.finditer(sentence):
        if _decade(m):
            continue  # "high 20s": a rough band, not a figure
        value, places, unit = _read(m, sentence)
        hedged = bool(HEDGED.search(sentence[max(0, m.start() - 12):m.start()]))
        if not _backed(value, places, pool[unit] if unit else pool[None], hedged):
            out.append(m.group(0).strip())
    for m in SPELLED.finditer(sentence):
        n, unit = WORDS[m.group(1).lower()], m.group(2).lower()
        value, places = (n / 10, 1) if unit.startswith("tenth") else (n, 0)
        kind = "%" if unit == "percent" else "°C" if unit.startswith("degree") else None
        if not _backed(value, places, pool[kind]):
            out.append(m.group(0))
    return out


def _read(m, text):
    """(value, decimal places, unit or None) for one TOKEN match."""
    if m.group(1):
        return int(m.group(1)) * 60 + float(m.group(2)), _places(m.group(2)), None
    value, places = float(m.group(3)), _places(m.group(3))
    if m.group(4) and m.group(4) != "s":  # km
        return value * 1000, places - 3, None
    before, after = text[max(0, m.start() - 4):m.start()], text[m.end():m.end() + 9]
    if before.endswith("P"):
        return value, places, "P"
    if before.endswith("L") or before.lower().endswith("lap "):
        return value, places, "lap"
    return value, places, next((u for u, pattern in UNITS if pattern.match(after)), None)


def _pool(text):
    """{unit: values} for the figures in `text`; None holds every figure, whatever its unit."""
    out = {None: set(), "P": set(), "lap": set(), **{u: set() for u, _ in UNITS}}
    for m in TOKEN.finditer(text):
        value, _, unit = _read(m, text)
        out[None].add(value)
        if unit:
            out[unit].add(value)
        if m.group(1):
            out[None].add(float(m.group(2)))  # "a 16.7"
    return out


def _decade(m):
    return m.group(4) == "s" and m.group(3).isdigit() and int(m.group(3)) % 10 == 0


def _places(token):
    return len(token.split(".")[1]) if "." in token else 0


def _backed(value, places, pool, hedged=False):
    if any(abs(b - value) <= 0.5 * 10 ** -places + 1e-9 for b in pool):
        return True
    if hedged and value >= 10 and places == 0 and any(value in (5 * round(b / 5), 10 * round(b / 10)) for b in pool):
        return True  # "around 20°" from 22
    # distances on the lap, rounded to one or two figures
    return value >= 1000 and any(b >= 1000 and value in (float(f"{b:.1g}"), float(f"{b:.2g}")) for b in pool)
