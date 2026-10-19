"""`/api/diagnostics`: what the models cost (this session, today, per session type, recent sessions,
evals and dev on the side) and how long each step takes, from the usage tables."""
import time

from . import archive, formats, usage
from .version import VERSION

LATENCY = (("stt_ms", "speech to text", "ms"), ("release_ms", "release → text on screen", "ms"),
           ("tts_ms", "voice: text → first audio", "ms"), ("call_delay_s", "call queued → said", "s"))
COUNTS = (("radio_heard", "radio messages"), ("radio_empty", "radio presses with nothing said"),
          ("cut_off", "times you cut the engineer off"), ("call_expired", "calls dropped: no straight in time"),
          ("call_stale", "calls dropped: no longer true"))
WEEK = 7 * 86400


def report(st, wall=None):
    uid, kind, track = usage.where(st)
    db = archive.connect()
    try:
        return {"team": wall and {"spent": wall.spent, "budget": wall.budget, "models": wall.models,
                                  "runs": sum(n["who"] == "lead" for n in wall.notes)},"session": {"uid": uid, "type": kind, "track": track, **_spend(db, "session_uid = ?", (uid,))},
                "today": _spend(db, "at >= ?", (_midnight(),)),
                "allTime": _spend(db, "1 = 1", ()),
                "byType": _by_type(db), "recent": _recent(db), "offSession": _off_session(db),
                "latency": _latency(db, uid), "counts": _counts(db, uid), "errors": _errors(db, uid),
                "feed": _feed(st), "version": VERSION}
    finally:
        db.close()


def _midnight():
    t = time.localtime()
    return time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1))


def _spend(db, where, args):
    rows = db.execute(f"select role, count(*) n, coalesce(sum(cost), 0) cost from usage where {where} group by role", args)
    roles = {r["role"]: {"calls": r["n"], "cost": r["cost"]} for r in rows}
    return {"cost": sum(r["cost"] for r in roles.values()), "calls": sum(r["calls"] for r in roles.values()), "roles": roles}


def _by_type(db):
    rows = db.execute("""select session_type, count(distinct session_uid) sessions, count(*) calls, sum(cost) cost
                         from usage where session_uid is not null group by session_type order by cost desc""")
    return [{"type": r["session_type"], "sessions": r["sessions"], "calls": r["calls"], "cost": r["cost"] or 0,
             "perSession": (r["cost"] or 0) / r["sessions"]} for r in rows]


def _recent(db, n=12):
    rows = db.execute("""select session_uid, session_type, track, min(at) started, count(*) calls, sum(cost) cost,
                                sum(role = 'engineer') answers
                         from usage where session_uid is not null group by session_uid order by max(at) desc limit ?""", (n,))
    return [{"uid": r["session_uid"], "type": r["session_type"], "track": r["track"], "started": r["started"],
             "calls": r["calls"], "answers": r["answers"], "cost": r["cost"] or 0} for r in rows]


def _off_session(db):
    """Evals, dev questions and the like over the past week: real money, but not a race's."""
    rows = db.execute("""select role, count(*) n, sum(cost) cost from usage
                         where session_uid is null and at >= ? group by role order by cost desc""", (time.time() - WEEK,))
    return [{"role": r["role"], "calls": r["n"], "cost": r["cost"] or 0} for r in rows]


def _latency(db, uid):
    since = time.time() - WEEK
    out = []
    first = [r[0] for r in db.execute("select first_ms from usage where role = 'engineer' and first_ms is not null "
                                      "and session_uid = ?", (uid,))]
    week = [r[0] for r in db.execute("select first_ms from usage where role = 'engineer' and first_ms is not null "
                                     "and at >= ?", (since,))]
    out.append(_row("engineer: question → first word", "ms", first, week))
    team = [r[0] for r in db.execute("select total_ms from usage where role = 'pitwall' and total_ms is not null "
                                     "and session_uid = ?", (uid,))]
    team_week = [r[0] for r in db.execute("select total_ms from usage where role = 'pitwall' and total_ms is not null "
                                          "and at >= ?", (since,))]
    out.append(_row("pit wall: run → note", "ms", team, team_week))
    for kind, label, unit in LATENCY:
        mine = [r[0] for r in db.execute("select value from metrics where kind = ? and session_uid = ?", (kind, uid))]
        recent = [r[0] for r in db.execute("select value from metrics where kind = ? and at >= ?", (kind, since))]
        out.append(_row(label, unit, mine, recent))
    return out


def _row(label, unit, session, week):
    return {"label": label, "unit": unit, "session": _pcts(session), "week": _pcts(week)}


def _pcts(xs):
    if not xs:
        return None
    xs = sorted(xs)

    def pick(p):
        return xs[min(len(xs) - 1, int(p * len(xs)))]

    return {"n": len(xs), "p50": pick(0.5), "p90": pick(0.9)}


def _counts(db, uid):
    got = dict(db.execute("select kind, sum(value) from metrics where session_uid = ? group by kind", (uid,)).fetchall())
    return [{"label": label, "n": int(got.get(kind) or 0)} for kind, label in COUNTS]


def _errors(db, uid):
    # what went wrong while driving: the dev tools and evals have their own failures on purpose
    rows = db.execute("select at, role, model, error from usage where error is not null and at >= ? "
                      "and role not in ('dev', 'eval', 'judge') order by at desc limit 5", (time.time() - WEEK,)).fetchall()
    n = db.execute("select count(*) from usage where error is not null and session_uid = ?", (uid,)).fetchone()[0]
    return {"session": n, "recent": [dict(r) for r in rows]}


def _feed(st):
    with st.lock:
        quiet = st.silent_for()
        return {"packets": st.total, "decodeErrors": st.error_count, "silentSecs": quiet, "gameVersion": st.version,
                "format": formats.GAMES.get(st.format),
                "wrongFormats": {str(k): v for k, v in st.wrong_formats.items()}}
