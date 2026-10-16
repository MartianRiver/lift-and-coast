"""Who's driving: the name the engineer and the team use, and their pronouns. Set on first run from
the dashboard (the game's player name is the default) and kept in the data folder.

The prompts and the team's fact lines are written about River, he/him; `words` rewrites our own text
for whoever is driving. Never run it over what the driver said ("he's closing" is about someone else).
"""
import functools
import json
import re

from . import archive, log

_log = log.get("driver")

FILE = archive.DATA / "driver.json"
PRONOUNS = ("he/him", "she/her", "they/them")
WRITTEN = "River"  # the name the prompts are written with

SWAP = {
    "she/her": {"he": "she", "him": "her", "his": "her", "himself": "herself", "he's": "she's", "he'd": "she'd", "he'll": "she'll"},
    "they/them": {"he": "they", "him": "them", "his": "their", "himself": "themselves", "he's": "they're", "he'd": "they'd",
                  "he'll": "they'll"},
}
# "he asks" -> "they ask"
VERBS = {"is": "are", "was": "were", "has": "have", "does": "do", "goes": "go", "isn't": "aren't", "wasn't": "weren't",
         "hasn't": "haven't", "doesn't": "don't"}
PRONOUN = re.compile(r"\b(he's|he'd|he'll|himself|he|him|his)\b", re.I)
HE_DOES = re.compile(r"\b([Hh]e\s+(?:always |never |also |just |still |only |already )?)([A-Za-z']+)")


def get():
    """{"name", "pronouns"}; name is None until the driver's been asked."""
    try:
        got = json.loads(FILE.read_text())
        return {"name": got.get("name") or None, "pronouns": got.get("pronouns") if got.get("pronouns") in PRONOUNS else "they/them"}
    except (FileNotFoundError, ValueError):
        return {"name": None, "pronouns": "they/them"}


def save(name, pronouns):
    name = " ".join(str(name or "").split())[:40]
    if not name or pronouns not in PRONOUNS:
        raise ValueError("a name and one of " + ", ".join(PRONOUNS))
    FILE.parent.mkdir(parents=True, exist_ok=True)
    FILE.write_text(json.dumps({"name": name, "pronouns": pronouns}))
    _log.info("driver set", pronouns=pronouns)
    return get()


def name():
    return get()["name"] or "the driver"


def from_game(identity):
    """The game's name for the player as a default: career sends the surname in capitals ("River JAMES")."""
    raw = (identity or {}).get("name") or ""
    if not raw or raw.startswith("Car ") or raw.lower() == "player":
        return None
    return " ".join(w.title() if w.isupper() and len(w) > 1 else w for w in raw.split())


def words(text):
    d = get()
    return _words(text, d["name"] or "the driver", d["pronouns"])


@functools.lru_cache(maxsize=64)
def _words(text, who, pronouns):
    text = re.sub(rf"\b{WRITTEN.upper()}'S\b", who.upper() + "'S", text)
    text = re.sub(rf"\b{WRITTEN}\b", who, text).replace("(he/him)", f"({pronouns})")
    swap = SWAP.get(pronouns)
    if not swap:
        return text

    if pronouns == "they/them":
        text = HE_DOES.sub(lambda m: m.group(1) + _plural(m.group(2)), text)

    def one(m):
        out = swap[m.group(1).lower()]
        return out[0].upper() + out[1:] if m.group(1)[0].isupper() else out

    return PRONOUN.sub(one, text)


def _plural(verb):
    """'asks' -> 'ask', for "they"; anything that isn't a third-person verb comes back as it was."""
    low = verb.lower()
    if low in VERBS:
        return VERBS[low]
    if len(low) > 4 and low.endswith("ies"):
        return verb[:-3] + "y"
    if low.endswith(("sses", "shes", "ches", "xes", "zes")):
        return verb[:-2]
    if len(low) > 2 and low.endswith("s") and not low.endswith(("ss", "us")):
        return verb[:-1]
    return verb
