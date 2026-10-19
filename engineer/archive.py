"""Long-term store: one capture file per session plus an SQLite catalogue of what's in them.

Raw captures stay the source of truth (they re-parse when the decoder improves); the database
holds what you'd want to query across sessions: sessions, results, every car's laps and sectors,
and events. Rebuildable at any time from the files with `reindex`.

    uv run python -m engineer.archive list
    uv run python -m engineer.archive reindex                   # rebuild the tables from every file
"""
import argparse
import json
import lzma
import os
import queue
import re
import shutil
import sqlite3
import struct
import threading
import time
from pathlib import Path

from . import log, profile
from . import lookups as L
from .capture import _is_buttons, read
from .decode import decode
from .spec import MAX_CARS

_log = log.get("archive")

DATA = Path(os.environ.get("RE_DATA_DIR") or Path(__file__).resolve().parent.parent / "captures")
SESSIONS = DATA / "sessions"
DB = DATA / "archive.db"
_UID = struct.Struct("<Q")  # sessionUID sits at byte 7 of every header
KEEP = {1, 2, 4, 8, 16}      # last packet of each kept per session
SKIP_EVENTS = {"BUTN", "SPTP"}

SCHEMA = """
create table if not exists sessions (
  id integer primary key, uid text unique not null, started_at text, track text, track_id int,
  type text, type_id int, formula int, regs2026 int, total_laps int, track_length int, weather text,
  track_temp int, air_temp int, game_version text, player_idx int, player text, team text,
  position int, best_lap_ms int, laps_done int, finished int, notes text);
create table if not exists files (
  path text primary key, session_uid text not null, started_at text, seconds real, packets int, bytes int);
create table if not exists results (
  session_uid text, car_idx int, driver text, team text, position int, grid int, laps int,
  best_lap_ms int, race_time_s real, penalties_s int, stops int, status text, stints text,
  primary key (session_uid, car_idx));
create table if not exists laps (
  session_uid text, car_idx int, lap int, lap_ms int, s1_ms int, s2_ms int, s3_ms int, valid int,
  primary key (session_uid, car_idx, lap));
create table if not exists events (
  session_uid text, file text, t real, session_time real, code text, details text);
create index if not exists events_session on events (session_uid);
create table if not exists usage (
  at real, session_uid text, session_type text, track text, role text, model text, provider text,
  in_tokens int, out_tokens int, cost real, first_ms int, total_ms int, why text, error text);
create index if not exists usage_session on usage (session_uid);
create table if not exists metrics (at real, session_uid text, kind text, value real, data text);
create index if not exists metrics_kind on metrics (kind, session_uid);
create table if not exists notes (session_uid text, at real, data text);
create table if not exists player_laps (
  session_uid text, lap int, fuel real, fuel_laps real, compound int, age int, wear text, life int,
  sc int, pit int, stops int, position int, primary key (session_uid, lap));
create table if not exists field_wear (session_uid text, lap int, rates text, primary key (session_uid, lap));
create table if not exists session_data (session_uid text primary key, forecast text, sets text, weekend text);
create index if not exists notes_session on notes (session_uid);
"""
# STEPS[n] takes the catalogue from user_version n to n + 1. Steps only ever add tables and columns, so an
# older version still opens a newer catalogue; anything that renames or drops is a 0.x.0 (docs/releasing.md).
STEPS = [SCHEMA]


def connect():
    DATA.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB, timeout=30)
    db.row_factory = sqlite3.Row
    _upgrade(db)
    _heal_paths(db)
    return db


def _upgrade(db):
    if db.execute("pragma user_version").fetchone()[0] >= len(STEPS):
        return
    db.execute("begin immediate")  # the server and a dev tool can open it at once: one of them upgrades
    have = db.execute("pragma user_version").fetchone()[0]
    try:
        for n in range(have, len(STEPS)):
            for statement in filter(str.strip, STEPS[n].split(";")):
                db.execute(statement)
            db.execute(f"pragma user_version = {n + 1}")
        db.commit()
    except sqlite3.Error:
        db.rollback()
        raise
    if have < len(STEPS):
        _log.info("catalogue upgraded", was=have, now=len(STEPS))


def stored(path):
    """A capture file as the catalogue keeps it: absolute, which every version can open (0.1 reads paths as they are)."""
    return str(Path(path).absolute())


def located(path):
    path = Path(path)
    return path if path.is_absolute() else DATA / path


def _heal_paths(db):
    """Point each row at the file where it is now: a catalogue copied from another folder, or with the
    relative paths a pre-release 0.2 wrote, gets the copy in sessions/ (or under DATA for a relative one)."""
    moved = []
    for (old,) in db.execute("select path from files").fetchall():
        here = SESSIONS / Path(old).name  # names carry the date and time, so this is the same recording
        new = str(here) if here.exists() else stored(located(old))
        if new != old:
            moved.append((new, old))
    if moved:
        with db:
            db.executemany("update or replace files set path = ? where path = ?", moved)
            db.executemany("update events set file = ? where file = ?", moved)
        _log.info("catalogue paths pointed here", files=len(moved))


# --- reading a capture ------------------------------------------------------------

def scan(path):
    """One pass over a capture -> {uid: summary}. Only the packets the catalogue needs get decoded."""
    out = {}
    for t, buf in read(path):
        if len(buf) < 29:
            continue
        uid = _UID.unpack_from(buf, 7)[0]
        if not uid:
            continue
        s = out.setdefault(uid, {"first": t, "last": t, "packets": 0, "bytes": 0, "latest": {}, "history": {}, "events": [],
                                 "player": profile.Tracker()})
        s["last"], s["packets"], s["bytes"] = t, s["packets"] + 1, s["bytes"] + len(buf)
        pid = buf[6]
        s["player"].feed(t, pid, buf)
        if pid in KEEP:
            s["latest"][pid] = buf
        elif pid == 11:
            s["history"][buf[29]] = buf  # carIdx is the first byte after the header
        elif pid == 3 and not _is_buttons(buf) and buf[29:33].decode(errors="replace") not in SKIP_EVENTS:
            _, ev = decode(buf)
            s["events"].append((t, ev["header"]["sessionTime"], ev["eventStringCode"], ev["eventDetails"]))
    return out


def index(path, started_at=None, db=None):
    """Catalogue one per-session capture file (re-running replaces what it wrote before)."""
    path = Path(path)
    own = db is None
    db = db or connect()
    for uid, s in scan(path).items():
        latest = {pid: decode(buf)[1] for pid, buf in s["latest"].items()}
        history = {idx: decode(buf)[1] for idx, buf in s["history"].items()}
        uid = str(uid)
        with db:
            _session(db, uid, started_at or _started(path), latest, history)
            _results(db, uid, latest, history)
            _laps(db, uid, history)
            profile.save(db, uid, s["player"])
            db.execute("delete from events where file = ?", (stored(path),))
            db.executemany("insert into events values (?, ?, ?, ?, ?, ?)",
                           [(uid, stored(path), t, st, code, json.dumps(d)) for t, st, code, d in s["events"]])
            db.execute("insert or replace into files values (?, ?, ?, ?, ?, ?)",
                       (stored(path), uid, started_at or _started(path), s["last"] - s["first"], s["packets"], s["bytes"]))
        _log.info("indexed", path=str(path), uid=uid, packets=s["packets"], laps=sum(h["numLaps"] for h in history.values()))
    if own:
        db.close()


def _session(db, uid, started_at, latest, history):
    s, lap, parts = latest.get(1), latest.get(2), latest.get(4)
    if not s:
        db.execute("insert or ignore into sessions (uid, started_at) values (?, ?)", (uid, started_at))
        return
    h = s["header"]
    me = h["playerCarIndex"] if h["playerCarIndex"] < MAX_CARS else None
    player = parts["participants"][me] if parts and me is not None else None
    hist = history.get(me) if me is not None else None
    best = hist and hist["bestLapTimeLapNum"] and hist["lapHistoryData"][hist["bestLapTimeLapNum"] - 1]["lapTimeInMS"]
    final, tel2 = latest.get(8), latest.get(16)
    regs = tel2["carTelemetry2Data"][me]["is2026Regulations"] if tel2 and me is not None else None  # not in the session packet
    pos = (final["classificationData"][me]["position"] if final and me is not None
           else lap["lapData"][me]["carPosition"] if lap and me is not None else None)
    row = dict(uid=uid, started_at=started_at, track=L.name(L.TRACKS, s["trackId"]), track_id=s["trackId"],
               type=L.name(L.SESSION_TYPES, s["sessionType"]), type_id=s["sessionType"], formula=s["formula"],
               regs2026=regs, total_laps=s["totalLaps"], track_length=s["trackLength"],
               weather=L.name(L.WEATHER, s["weather"]), track_temp=s["trackTemperature"], air_temp=s["airTemperature"],
               game_version=f'{h["gameMajorVersion"]}.{h["gameMinorVersion"]:02d}', player_idx=me,
               player=player and (player["name"] or L.DRIVERS.get(player["driverId"])),
               team=player and L.name(L.TEAMS, player["teamId"]), position=pos or None, best_lap_ms=best or None,
               laps_done=hist and hist["numLaps"], finished=int(bool(final)))
    cols = ", ".join(row)
    keep = {"uid", "started_at"}
    sets = ", ".join(f"{k} = excluded.{k}" for k in row if k not in keep)
    db.execute(f"insert into sessions ({cols}) values ({', '.join('?' * len(row))}) on conflict (uid) do update set "
               f"{sets}, started_at = min(coalesce(sessions.started_at, excluded.started_at), excluded.started_at)",
               list(row.values()))


def _results(db, uid, latest, history):
    parts, final, lap = latest.get(4), latest.get(8), latest.get(2)
    if not parts:
        return
    for idx, p in enumerate(parts["participants"]):
        h = history.get(idx)
        if not p["name"] and not p["driverId"] and not h:
            continue
        c = final["classificationData"][idx] if final and idx < final["numCars"] else None
        live = lap["lapData"][idx] if lap else None
        if c is None and (not live or live["resultStatus"] < 2):
            continue
        best = h and h["bestLapTimeLapNum"] and h["lapHistoryData"][h["bestLapTimeLapNum"] - 1]["lapTimeInMS"]
        stints = [(x["endLap"], L.VISUAL_COMPOUNDS.get(x["tyreVisualCompound"])) for x in h["tyreStintsHistoryData"][:h["numTyreStints"]]] if h else []
        status = c["resultStatus"] if c else live["resultStatus"]
        db.execute("insert or replace into results values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (
            uid, idx, p["name"] or L.DRIVERS.get(p["driverId"], f"Car {idx}"), L.name(L.TEAMS, p["teamId"]),
            c["position"] if c else live["carPosition"], c["gridPosition"] if c else live["gridPosition"],
            c["numLaps"] if c else (h["numLaps"] if h else None), (c and c["bestLapTimeInMS"]) or best or None,
            c["totalRaceTime"] if c else None, c["penaltiesTime"] if c else live["penalties"],
            c["numPitStops"] if c else live["numPitStops"], L.name(L.RESULT_STATUS, status), json.dumps(stints)))


def _laps(db, uid, history):
    rows = []
    for idx, h in history.items():
        for n, r in enumerate(h["lapHistoryData"][:h["numLaps"]], 1):
            if r["lapTimeInMS"]:
                s = [r[f"sector{i}TimeMinutesPart"] * 60000 + r[f"sector{i}TimeMSPart"] for i in (1, 2, 3)]
                rows.append((uid, idx, n, r["lapTimeInMS"], *s, r["lapValidBitFlags"] & 1))
    db.executemany("insert or replace into laps values (?, ?, ?, ?, ?, ?, ?, ?)", rows)


def _started(path):
    """When recording began: from the file's own name (recorder and import both stamp it)."""
    m = re.match(r"(\d{4}-\d{2}-\d{2})_(\d{2})(\d{2})(\d{2})?", Path(path).name)
    return f"{m[1]} {m[2]}:{m[3]}:{m[4] or '00'}" if m else None


def label(started, session):
    """'2026-10-13_180121_Austria_P3': sortable, and says what it is at a glance."""
    stamp = time.strftime("%Y-%m-%d_%H%M%S", time.localtime(started))
    if not session:
        return stamp
    kind = L.name(L.SESSION_TYPES, session["sessionType"]).replace("Short ", "").replace("Qualifying", "Quali")
    return "_".join([stamp] + [re.sub(r"[^A-Za-z0-9]+", "-", x).strip("-") for x in (L.name(L.TRACKS, session["trackId"]), kind)])


def unique(path):
    path, n = Path(path), 2
    base = path
    while path.exists() or Path(f"{path}.xz").exists():
        path = base.with_name(f"{base.stem}-{n}{base.suffix}")
        n += 1
    return path


# --- finishing a session file: index, then compress -------------------------------

def compress(path):
    path = Path(path)
    out = path.with_name(path.name + ".xz")
    part = out.with_name(out.name + ".part")
    with open(path, "rb") as src, lzma.open(part, "wb", preset=1) as dst:
        shutil.copyfileobj(src, dst, 1 << 20)
    part.rename(out)
    path.unlink()
    return out


def finish(path, started_at=None, db=None):
    path = Path(path)
    t0 = time.perf_counter()
    if path.stat().st_size <= len(b"F1CAP1\n"):
        path.unlink()  # nothing was recorded
        return None
    index(path, started_at, db)
    path = _name_from_archive(path, db)
    out = compress(path)
    own = db is None
    db = db or connect()
    with db:
        db.execute("update files set path = ? where path = ?", (stored(out), stored(path)))
        db.execute("update events set file = ? where file = ?", (stored(out), stored(path)))
    if own:
        db.close()
    _log.info("session archived", path=str(out), mb=round(out.stat().st_size / 1e6, 1), secs=round(time.perf_counter() - t0, 1))
    return out


def _name_from_archive(path, db=None):
    """A part with no session packet (e.g. only the results screen after a server restart) takes
    its name from the session it belongs to, if the archive already knows it."""
    if re.match(r"\d{4}-\d{2}-\d{2}_\d{6}(-\d+)?\.f1cap$", path.name) is None:
        return path
    own = db is None
    db = db or connect()
    row = db.execute("select s.track_id, s.type_id from sessions s join files f on f.session_uid = s.uid "
                     "where f.path = ? and s.track_id is not null", (stored(path),)).fetchone()
    if row:
        stamp = time.mktime(time.strptime(path.name[:17], "%Y-%m-%d_%H%M%S"))
        new = unique(path.with_name(f"{label(stamp, {'trackId': row['track_id'], 'sessionType': row['type_id']})}.f1cap"))
        path.rename(new)
        with db:
            db.execute("update files set path = ? where path = ?", (stored(new), stored(path)))
            db.execute("update events set file = ? where file = ?", (stored(new), stored(path)))
        path = new
    if own:
        db.close()
    return path


_jobs = queue.Queue()
_worker_lock = threading.Lock()
_worker_started = False


def _worker():
    while True:
        path, started_at = _jobs.get()
        try:
            finish(path, started_at)
        except Exception as e:  # leave the raw file for the next sweep
            _log.error("archiving failed", path=str(path), error=str(e))


def finish_later(path, started_at=None):
    global _worker_started
    with _worker_lock:
        if not _worker_started:
            threading.Thread(target=_worker, name="archive", daemon=True).start()
            _worker_started = True
    _jobs.put((Path(path), started_at))


def sweep(folder=SESSIONS, skip=None):
    """Queue raw session files left behind (crash, killed server) for finishing."""
    for path in sorted(Path(folder).glob("*.f1cap")):
        if path != skip:
            _log.info("finishing leftover capture", path=str(path))
            finish_later(path)


def reindex(db):
    for path in sorted(SESSIONS.glob("*.f1cap*")):
        if not path.name.endswith(".part"):
            row = db.execute("select started_at from files where path = ?", (stored(path),)).fetchone()
            index(path, row["started_at"] if row else None, db)


def list_sessions(db, limit=50):
    return db.execute("""
        select s.id, s.started_at, s.track, s.type, s.player, s.position, s.best_lap_ms, s.laps_done,
               sum(f.seconds) as seconds, group_concat(f.path, ' ') as files
        from sessions s left join files f on f.session_uid = s.uid
        group by s.uid order by s.started_at desc limit ?""", (limit,)).fetchall()


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    sub.add_parser("reindex")
    args = ap.parse_args()
    db = connect()
    if args.cmd == "reindex":
        reindex(db)
    print_sessions(db)


def print_sessions(db):
    for r in list_sessions(db):
        best = f"{r['best_lap_ms'] // 60000}:{r['best_lap_ms'] % 60000 / 1000:06.3f}" if r["best_lap_ms"] else "—"
        mins = f"{(r['seconds'] or 0) / 60:.0f} min"
        print(f"#{r['id']:<3} {r['started_at'] or '?':19}  {r['track'] or '?':10} {r['type'] or '?':15} "
              f"P{r['position'] or '-':<3} best {best:9} laps {r['laps_done'] or 0:<3} {mins:>7}")


if __name__ == "__main__":
    main()
