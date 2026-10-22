"""What a pit stop really costs at each track, measured from every car's stops in the archived races.

The game's own number (read off its rejoin estimate) can be badly off (≈11 s where the stops
cost 23–25). So every race the archive holds is a sample: in-lap + out-lap against the laps
before, the same rule as a stop seen live (`calc.stop_loss`). Stops under SC/VSC and stops between
slicks and wets, and between two wet sets, are kept apart: none of them is what a dry green-flag stop costs.

`pitloss.json` ships each track's figure from the races recorded so far, for a track with no stop
seen in your own races yet (`dev pits --write` rebuilds it, a release step).

    uv run python -m engineer.dev pits
"""
import json
import sqlite3
import statistics
from pathlib import Path

from . import archive, calc, log

_log = log.get("pitstops")

WET = {"Inter", "Wet"}
TABLE = Path(__file__).resolve().parent / "pitloss.json"
_cache = {}
_table = []


def measure(db, uid):
    """Every stop in one archived race: [{driver, lap (in-lap), loss, kind: green|sc|weather|wet, laps ms}]."""
    sc = _sc_periods(db, uid)
    out = []
    for r in db.execute("select car_idx, driver, stints from results where session_uid = ? and stops > 0", (uid,)):
        times = dict(db.execute("select lap, lap_ms from laps where session_uid = ? and car_idx = ? and lap_ms > 0",
                                (uid, r["car_idx"])).fetchall())
        ends = _ends(times)
        green = {n: ms for n, ms in times.items() if not _overlaps(ends, n, sc)}  # as live: SC laps left out
        stints = json.loads(r["stints"])
        for (end, was), (_, now) in zip(stints, stints[1:]):
            # endLap is the laps done on the set: the in-lap is the one after (endLap 12: in-lap 13, out-lap 14)
            around = (end, end + 1, end + 2)
            # as live: an SC lap among them makes it an SC stop, or the pair left is a lap before and the in-lap
            clean = all(n in green for n in around if n in times)
            kind = "weather" if (was in WET) != (now in WET) else "wet" if was in WET else "green"
            got = clean and calc.stop_loss(green, around)
            if not got:
                got, kind = calc.stop_loss(times, around), "sc"
            if not got:
                continue
            loss, lap = got
            out.append({"driver": r["driver"], "lap": lap, "loss": round(loss, 2), "kind": kind,
                        "key": (r["driver"], lap, times[lap], times[lap + 1])})
    return out


def _ends(times):
    """Lap -> session time at its end. Session time is 0 at lights out and every lap is in the history."""
    out, t = {}, 0.0
    for n in sorted(times):
        t += times[n] / 1000
        out[n] = t
    return out


def _overlaps(ends, n, periods):
    if n not in ends:
        return False
    start = ends.get(n - 1, 0.0)
    return any(a < ends[n] and b > start for a, b in periods)


def _sc_periods(db, uid):
    """[(from, to)] session seconds under SC/VSC, with any part a flashback rewound dropped."""
    periods, opened = [], None
    rows = db.execute("select session_time, code, details from events where session_uid = ? and code in ('SCAR', 'FLBK') "
                      "order by t", (uid,)).fetchall()
    for st, code, details in rows:
        d = json.loads(details or "null") or {}
        if code == "FLBK":
            to = d["flashbackSessionTime"]
            periods = [(a, min(b, to)) for a, b in periods if a < to]
            opened = opened if opened is not None and opened < to else None
        elif d.get("eventType") == 0 and opened is None:
            opened = st
        elif d.get("eventType") in (2, 3) and opened is not None:
            periods.append((opened, st))
            opened = None
    if opened is not None:
        periods.append((opened, float("inf")))
    return periods


def races(db, track_id=None, formula=None, before=None):
    """Archived races at this track (same formula: an F2 pit lane isn't an F1 one), oldest first,
    started before `before`. Not split by regs: the pit lane is the same either way."""
    sql, args = "select uid, track, track_id, started_at from sessions where type like 'Race%'", []
    for col, val in (("track_id", track_id), ("formula", formula)):
        if val is not None:
            sql += f" and {col} = ?"
            args.append(val)
    if before:
        sql += " and started_at < ?"
        args.append(before)
    return db.execute(sql + " order by started_at", args).fetchall()


def by_track(db, **where):
    """{track: {"id", "green": [s], "sc": [s], "weather": [s], "wet": [s], "races": n}}. A resumed save repeats the
    earlier laps under a new session, so the same stop is counted once."""
    out, seen = {}, set()
    for race in races(db, **where):
        stops = [s for s in measure(db, race["uid"]) if (race["track_id"], *s["key"]) not in seen]
        seen.update((race["track_id"], *s["key"]) for s in stops)
        t = out.setdefault(race["track"], {"id": race["track_id"], "green": [], "sc": [], "weather": [], "wet": [], "races": 0})
        t["races"] += any(s["kind"] == "green" for s in stops)
        for s in stops:
            t[s["kind"]].append(s["loss"])
    return out


def here(session):
    """(median green-flag loss, stops, races) at this session's track from earlier races, or None.
    Cached per session: the archive doesn't change mid-race."""
    uid = str(session["header"]["sessionUID"])
    key = (uid, session["trackId"])
    if key not in _cache:
        _cache[key] = _here(uid, session)
    return _cache[key]


def _here(uid, session):
    if not archive.DB.exists():
        return None
    try:
        db = archive.connect()
        row = db.execute("select started_at from sessions where uid = ?", (uid,)).fetchone()
        t = by_track(db, track_id=session["trackId"], formula=session["formula"], before=row and row["started_at"])
        db.close()
    except sqlite3.Error as e:
        _log.error("couldn't read pit losses from the archive", exc=False, error=str(e))
        return None
    green = next(iter(t.values()), {}).get("green")
    if not green:
        return None
    _log.info("pit loss from earlier races", track=session["trackId"], loss=round(statistics.median(green), 1), stops=len(green))
    return statistics.median(green), len(green), next(iter(t.values()))["races"]


def table(db):
    """What pitloss.json holds: each track's median green-flag loss in F1 races, and the median of those."""
    tracks = {str(t["id"]): {"track": name, "loss": round(statistics.median(t["green"]), 1), "stops": len(t["green"])}
              for name, t in by_track(db, formula=0).items() if t["green"]}
    usual = round(statistics.median(t["loss"] for t in tracks.values()), 1) if tracks else None
    return {"tracks": tracks, "usual": usual}


def usual(session):
    """(seconds, stops measured or None) from pitloss.json: this track's figure, else what a stop usually
    costs across tracks (stops None). F1 only: an F2 pit lane isn't timed the same."""
    if session.get("formula", 0) != 0:
        return None
    if not _table:
        try:
            _table.append(json.loads(TABLE.read_text()))
        except (OSError, ValueError) as e:
            _log.error("couldn't read the shipped pit losses", exc=False, error=str(e))
            _table.append({"tracks": {}, "usual": None})
    t = _table[0]
    here = t["tracks"].get(str(session["trackId"]))
    if here:
        return here["loss"], here["stops"]
    return t["usual"] and (t["usual"], None)
