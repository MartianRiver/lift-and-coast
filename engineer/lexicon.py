"""Fix speech-to-text mishearings before anything acts on a transcript.

Three passes, all reversible because the raw text is kept alongside:
1. spelled-out acronyms collapse ("D R S" -> "DRS")
2. fixes the driver has taught it (fixes.json in the data folder, editable from the Radio tab)
3. sound-alike matching against this session's names + team/track names + radio jargon
"""
import json
import re
import threading
import unicodedata

import jellyfish
from wordfreq import zipf_frequency

from . import archive, log
from .lookups import TEAMS, TRACKS

_log = log.get("lexicon")

FIXES_FILE = archive.DATA / "fixes.json"

JARGON = [
    "box", "pit", "soft", "medium", "hard", "inter", "wet", "inters", "intermediates", "wets", "softs", "mediums", "hards", "slicks",
    "DRS", "ERS", "VSC", "safety car", "undercut", "overcut", "deg", "graining", "blistering",
    "delta", "sector", "apex", "understeer", "oversteer", "lift and coast", "brake bias",
    "diff", "front wing", "rear wing", "pit window", "stint", "tow", "dirty air", "pole",
]
EXTRA_TEAMS = ["Red Bull", "Racing Bulls", "Merc", "Aston"]
COMMON_ZIPF = 3.0   # words at least this common are left alone ("nurse" sounds like Norris)
WORD = re.compile(r"[^\W\d_][\w'’-]*")
SPELLED = re.compile(r"\b(?:[A-Z]\.? ){1,3}[A-Z]\b\.?")


def _plain(s):
    s = unicodedata.normalize("NFKD", re.sub(r"['’]s$", "", s))
    return "".join(c for c in s if c.isalpha()).lower()


class Term:
    def __init__(self, text, name=False):
        self.text = text
        self.name = name
        self.plain = _plain(text)
        self.key = jellyfish.metaphone(self.plain)


def base_terms():
    # "Alpine '26", "Silverstone (Reverse)" -> what people actually say
    places = {re.sub(r"\s*\(.*\)|\s*'\d+", "", t) for t in [*TEAMS.values(), *TRACKS.values(), *EXTRA_TEAMS]}
    return [Term(t, name=True) for t in places if not t.startswith("F1 ")] + [Term(t) for t in JARGON]


def name_terms(names):
    """Participant names as the game sends them ('TSUNODA', 'River JAMES') plus first names."""
    out = []
    for name in names:
        for part in name.split():
            part = part.title() if part.isupper() else part
            if len(_plain(part)) >= 3:
                out.append(Term(part, name=True))
    return out


class Lexicon:
    def __init__(self, path=FIXES_FILE):
        self.path = path
        self._lock = threading.Lock()
        self._base = base_terms()
        self.fixes = self._load()

    # --- taught fixes --------------------------------------------------------

    def _load(self):
        try:
            return json.loads(self.path.read_text())
        except FileNotFoundError:
            return []
        except Exception as e:
            _log.error("couldn't read fixes", error=str(e), path=str(self.path))
            return []

    def teach(self, heard, meant):
        heard, meant = heard.strip(), meant.strip()
        if not heard or not meant:
            raise ValueError("both heard and meant are needed")
        with self._lock:
            self.fixes = [f for f in self.fixes if f["heard"].lower() != heard.lower()]
            self.fixes.append({"heard": heard, "meant": meant})
            self._save()
        _log.info("fix taught", heard=heard, meant=meant)

    def forget(self, heard):
        with self._lock:
            self.fixes = [f for f in self.fixes if f["heard"].lower() != heard.lower()]
            self._save()
        _log.info("fix forgotten", heard=heard)

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.fixes, indent=1, ensure_ascii=False) + "\n")

    # --- correction ----------------------------------------------------------

    def correct(self, text, names=()):
        """-> (fixed text, [{heard, meant, how}])"""
        changes = []
        text = SPELLED.sub(lambda m: _note(changes, m.group(), m.group().replace(".", "").replace(" ", ""), "spelled"), text)
        for f in list(self.fixes):
            pat = re.compile(rf"\b{re.escape(f['heard'])}\b", re.IGNORECASE)
            text = pat.sub(lambda m, f=f: _note(changes, m.group(), f["meant"], "taught"), text)
        text = _sound_alike(text, self._base + name_terms(names), changes)
        return text, changes


def _note(changes, heard, meant, how):
    if heard != meant:
        changes.append({"heard": heard, "meant": meant, "how": how})
    return meant


def _sound_alike(text, terms, changes):
    words = list(WORD.finditer(text))
    known = {t.plain: t for t in terms}
    out, last, i = [], 0, 0
    while i < len(words):
        step = 1
        for n in (3, 2, 1):
            span = words[i:i + n]
            if len(span) < n or not _joined_by_spaces(text, span):
                continue
            heard = text[span[0].start():span[-1].end()]
            if _plain(heard) in known:
                # right sounds, maybe split or cased oddly ("under cut") - normalise to the term
                term = known[_plain(heard)]
                if len(term.text.split()) != n:
                    out += [text[last:span[0].start()], _note(changes, heard, term.text, "spacing")]
                    last = span[-1].end()
                step = n
                break
            if n > 1 and any(_plain(w.group()) in known for w in span):
                continue  # don't let a window swallow a name that was heard right
            term = _match(heard, n, terms)
            if term:
                out += [text[last:span[0].start()], _note(changes, heard, term.text, "sounds like")]
                last, step = span[-1].end(), n
                break
        i += step
    out.append(text[last:])
    return "".join(out)


def _joined_by_spaces(text, span):
    return all(text[a.end():b.start()] == " " for a, b in zip(span, span[1:]))


def _match(heard, n, terms):
    plain = _plain(heard)
    if n == 1 and zipf_frequency(plain, "en") >= COMMON_ZIPF:
        return None
    key = jellyfish.metaphone(plain)
    scored = []
    for t in terms:
        d = jellyfish.levenshtein_distance(key, t.key)
        jw = jellyfish.jaro_winkler_similarity(plain, t.plain)
        if n > 1:
            # ordinary words strung together only count when they sound (nearly) exactly like the
            # term and start the same way - "a safety car" isn't a mishearing of "safety car"
            ok = t.name and plain[0] == t.plain[0] and ((d == 0 and jw >= 0.85 and (len(t.key) >= 4 or jw >= 0.88)) or (d == 1 and jw >= 0.9 and len(t.key) >= 5))
        elif t.name:
            ok = (d == 0 and jw >= 0.75) or (d == 1 and jw >= 0.84 and len(t.key) >= 3)
        else:
            ok = d == 0 and jw >= 0.75  # jargon is mostly real English; near-misses are too risky
        if ok:
            scored.append((d, -jw, t))
    if not scored:
        return None
    scored.sort(key=lambda s: (s[0], s[1]))
    if len(scored) > 1 and scored[1][:2] == scored[0][:2] and scored[1][2].plain != scored[0][2].plain:
        return None  # two terms fit equally well; leave it for the LLM
    return scored[0][2]
