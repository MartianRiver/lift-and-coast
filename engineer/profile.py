"""The player's own numbers across sessions: fuel, tyres and wear at every lap line, kept in the archive,
and what they say about the next race (fuel burn per km, how long their tyres really last against the
game's estimate, race length at their usual distance).

`Tracker` follows the player through a capture as it's catalogued; the rest reads the archive.
"""
import json
import math
from statistics import median

from . import lookups as L
from .decode import decode

SAMPLE = 0.5      # s between lap-data reads: a lap line is never closer than that
WORN = 70         # % on the worst tyre that counts as used up (strategy.WORN)
RACES = (15, 16, 17)
WET = (7, 8)      # visual compounds: inter, wet
FULL_KM = {"race": 305.0, "sprint": 100.0}  # F1 distances; Monaco's race is 260 km
DRY_MIN_LAPS = 4  # a stint shorter than this says nothing about tyre life
FIELD_AGE = 3     # laps on a set before its wear over age says anything


class Tracker:
    """Fed every packet of one session in order; rows = {lap: what the player had crossing into it}."""

    def __init__(self):
        self.rows, self.raw = {}, {}
        self.lap, self.next, self.sc, self.pit = None, 0.0, False, False

    def feed(self, t, pid, buf):
        if pid in (1, 7, 10):
            self.raw[pid] = buf
        elif pid == 12 and buf[29] == buf[27]:  # carIdx == playerCarIndex: their own sets
            self.raw[12] = buf
        elif pid == 2 and t >= self.next:
            self.next = t + SAMPLE
            self._look(decode(buf)[1])

    def _look(self, lap_pkt):
        me = lap_pkt["header"]["playerCarIndex"]
        if me >= len(lap_pkt["lapData"]):
            return
        c = lap_pkt["lapData"][me]
        s = self.raw.get(1) and decode(self.raw[1])[1]
        self.sc |= bool(s and s["safetyCarStatus"])
        self.pit |= c["pitStatus"] > 0
        lap = c["currentLapNum"]
        if lap == self.lap and lap in self.rows and self.rows[lap]["fuel"] is None and 7 in self.raw:
            self.rows[lap].update(self._row(me, c))  # the session loaded before car status did (the grid)
        if lap == self.lap or not lap:
            return
        if self.lap is not None and lap < self.lap:  # flashback over a lap line
            self.rows = {n: r for n, r in self.rows.items() if n <= lap}
            if lap in self.rows:  # keep what they crossed the line with, not this mid-lap state
                self.lap = lap
                return
        elif self.lap in self.rows:
            self.rows[self.lap].update(sc=self.sc, pit=self.pit)  # what happened during the lap just finished
        self.rows[lap] = self._row(me, c)
        self.rows[lap]["field"] = self._field(lap_pkt, me, self.rows[lap]["compound"])
        self.lap, self.sc, self.pit = lap, False, c["pitStatus"] > 0

    def _row(self, me, c):
        status = self.raw.get(7) and decode(self.raw[7])[1]["carStatusData"][me]
        dmg = self.raw.get(10) and decode(self.raw[10])[1]["carDamageData"][me]
        sets = self.raw.get(12) and decode(self.raw[12])[1]
        fitted = sets and sets["tyreSetData"][sets["fittedIdx"]] if sets and sets["fittedIdx"] < 20 else None
        return {"fuel": status and status["fuelInTank"], "fuelLaps": status and status["fuelRemainingLaps"],
                "compound": status and status["visualTyreCompound"], "age": status and status["tyresAgeLaps"],
                "wear": dmg and [round(w, 2) for w in dmg["tyresWear"]], "life": fitted and fitted["lifeSpan"],
                "stops": c["numPitStops"], "position": c["carPosition"], "sc": False, "pit": False}

    def _field(self, lap_pkt, me, compound):
        """The other cars' wear per lap on their compound (wear over the set's age), median per wheel."""
        if 7 not in self.raw or 10 not in self.raw or compound is None:
            return None
        status, dmg = decode(self.raw[7])[1]["carStatusData"], decode(self.raw[10])[1]["carDamageData"]
        rates = [[w / s["tyresAgeLaps"] for w in d["tyresWear"]]
                 for i, (c, s, d) in enumerate(zip(lap_pkt["lapData"], status, dmg))
                 if i != me and c["resultStatus"] == 2 and not c["pitStatus"] and s["visualTyreCompound"] == compound
                 and s["tyresAgeLaps"] >= FIELD_AGE]
        if len(rates) < 3:
            return None
        return [round(median(r[i] for r in rates), 3) for i in range(4)]

    def extras(self):
        """The forecast and their tyre sets as the session ended."""
        s = self.raw.get(1) and decode(self.raw[1])[1]
        sets = self.raw.get(12) and decode(self.raw[12])[1]
        forecast = s and [{"session": w["sessionType"], "offset": w["timeOffset"], "weather": w["weather"],
                           "rain": w["rainPercentage"], "track": w["trackTemperature"]}
                          for w in s["weatherForecastSamples"][:s["numWeatherForecastSamples"]]]
        mine = sets and [{"compound": x["visualTyreCompound"], "wear": x["wear"], "life": x["lifeSpan"],
                          "usable": x["usableLife"], "delta": x["lapDeltaTime"], "fitted": bool(x["fitted"])}
                         for x in sets["tyreSetData"] if x["available"]]
        weekend = s and s["weekendStructure"][:s["numSessionsInWeekend"]]
        return forecast, mine, weekend


def save(db, uid, tracker):
    """A session can span several files (a server restart mid-session): each adds its own laps."""
    db.executemany("insert or replace into player_laps values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", [
        (uid, lap, r["fuel"], r["fuelLaps"], r["compound"], r["age"], json.dumps(r["wear"]), r["life"],
         int(r["sc"]), int(r["pit"]), r["stops"], r["position"]) for lap, r in sorted(tracker.rows.items())])
    db.executemany("insert or replace into field_wear values (?, ?, ?)",
                   [(uid, lap, json.dumps(r["field"])) for lap, r in sorted(tracker.rows.items()) if r.get("field")])
    forecast, sets, weekend = tracker.extras()
    if forecast or sets:  # a stub file at the end of a session has neither: keep what the main part had
        db.execute("insert or replace into session_data values (?, ?, ?, ?)",
                   (uid, json.dumps(forecast), json.dumps(sets), json.dumps(weekend)))


# --- reading it back --------------------------------------------------------------------

def _laps(db, uid):
    rows = db.execute("""select p.*, f.rates field from player_laps p left join field_wear f
                         on f.session_uid = p.session_uid and f.lap = p.lap where p.session_uid = ? order by p.lap""",
                      (uid,)).fetchall()
    return [dict(r, wear=json.loads(r["wear"]) if r["wear"] else None, field=json.loads(r["field"]) if r["field"] else None)
            for r in rows]


def _races(db, before=None):
    return db.execute("""select uid, track, track_length, total_laps, type_id, started_at from sessions
                         where type_id in (15, 16, 17) and total_laps >= 5 and (? is null or started_at < ?)
                         order by started_at""", (before, before)).fetchall()


def fuel(db, before=None):
    """Per race: kg burnt per km on green laps, and how the fuel delta moved a lap by condition (+ = less
    than the game's target that lap). The game's target matches a dry burn to a few hundredths of a
    lap, so the starting delta is roughly what's left at the flag; a safety car adds to it, and the
    wet can go either way (−0.10 a lap in one race, −0.01 in another)."""
    out, seen = [], set()
    for race in _races(db, before):
        laps = [r for r in _laps(db, race["uid"]) if r["fuel_laps"] is not None and r["fuel"]]
        key = (race["track"], race["total_laps"], race["started_at"][:10])
        steps = [(a, b) for a, b in zip(laps, laps[1:]) if b["lap"] == a["lap"] + 1 and (key, a["lap"]) not in seen]
        seen.update((key, a["lap"]) for a, _ in steps)
        if len(steps) < 3 or not race["track_length"]:
            continue
        drift, stints = {"lap1": [], "dry": [], "wet": [], "sc": []}, {}
        for a, b in steps:
            kind = "lap1" if a["lap"] == 1 else "sc" if a["sc"] else None if a["pit"] else "wet" if a["compound"] in WET else "dry"
            if kind:
                drift[kind].append(b["fuel_laps"] - a["fuel_laps"])
            if kind == "dry":
                stints.setdefault((a["stops"], a["compound"]), []).append(b["fuel_laps"] - a["fuel_laps"])
        heavy = [median(v) for v in stints.values() if len(v) >= 3]
        burn = [a["fuel"] - b["fuel"] for a, b in steps if not a["sc"] and not a["pit"] and a["lap"] > 1]
        out.append({"track": race["track"], "laps": race["total_laps"], "fromLap": laps[0]["lap"], "toLap": laps[-1]["lap"],
                    "start": laps[0]["fuel_laps"], "end": laps[-1]["fuel_laps"], "leftKg": laps[-1]["fuel"],
                    "perKm": median(burn) / (race["track_length"] / 1000) if burn else None,
                    **{k: (median(v) if v else None) for k, v in drift.items()},
                    "dryLow": min(heavy) if heavy else None, "scLaps": len(drift["sc"]), "wetLaps": len(drift["wet"])})
    return out


def tyre_life(db, before=None):
    """Per race stint: the game's life estimate when fitted against laps until their worst tyre reaches WORN."""
    out = []
    for race in _races(db, before):
        laps = _laps(db, race["uid"])
        grid = laps[0]["position"] if laps else None
        stints = {}
        for r in laps:
            if r["wear"] and r["compound"] is not None:
                stints.setdefault((r["stops"], r["compound"]), []).append(r)
        for (_, compound), rows in stints.items():
            rows = [r for r in rows if not r["sc"]]
            fitted = next((r for r in rows if r["life"]), None)  # the grid row can come before the sets packet
            if len(rows) < DRY_MIN_LAPS or not fitted:
                continue
            a, b = rows[1], rows[-1]  # skip the out-lap
            rate = (max(b["wear"]) - max(a["wear"])) / max(b["lap"] - a["lap"], 1)
            if rate <= 0:
                continue
            life = fitted["life"] + fitted["age"]  # the estimate when the set went on
            to_worn = WORN / rate
            out.append({"track": race["track"], "compound": compound, "wet": compound in WET, "laps": len(rows), "grid": grid,
                        "rate": rate, "gameLife": life, "toWorn": to_worn, "ratio": to_worn / life,
                        "vsField": _vs_field(a, b, rows)})
    return out


def _vs_field(a, b, rows):
    """The player's %/lap per wheel over the stint against the median of the field's on the same compound, or None."""
    field = [r["field"] for r in rows if r["field"]]
    if len(field) < 2:
        return None
    mine = [(y - x) / (b["lap"] - a["lap"]) for x, y in zip(a["wear"], b["wear"])]
    theirs = [median(f[i] for f in field) for i in range(4)]
    return [m / t if t else None for m, t in zip(mine, theirs)]


def full_laps(track, length_m, sprint=False):
    km = 100.0 if sprint else (260.0 if track == "Monaco" else 305.0)
    return math.ceil(km * 1000 / length_m)


def distance(db, before=None):
    """The player's usual race distance as a share of the real one, from their feature races (sprints are shorter)."""
    shares = [r["total_laps"] / full_laps(r["track"], r["track_length"]) for r in _races(db, before) if r["track_length"]]
    shares = [s for s in shares if s >= 0.2]  # a sprint's laps against a full race's
    return median(shares) if shares else None


def latest_here(db, track_id=None):
    """The most recent non-race session (at a track, or anywhere) with its forecast, sets and their result."""
    row = db.execute("""select s.*, d.forecast, d.sets, d.weekend from sessions s join session_data d on d.session_uid = s.uid
                        where s.type_id not in (15, 16, 17) and s.track_id is not null and (? is null or s.track_id = ?)
                        order by s.started_at desc limit 1""", (track_id, track_id)).fetchone()
    if not row:
        return None
    return dict(row, forecast=json.loads(row["forecast"] or "null"), sets=json.loads(row["sets"] or "null"),
                weekend=json.loads(row["weekend"] or "null"))


def compound(c):
    return L.VISUAL_COMPOUNDS.get(c, f"compound {c}")
