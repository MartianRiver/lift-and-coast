"""What every model call cost and how long things took, kept in the archive so it adds up across
sessions: cost per session, per race, per session type; latency of each step from radio to voice.

Rows go through one writer thread. Callers are often holding the state lock mid-race and an
SQLite write shouldn't sit on that.
"""
import json
import queue
import threading
import time

from . import archive, log
from . import lookups as L

_log = log.get("usage")

NOWHERE = (None, None, None)  # (session uid, session type, track) for calls outside a session: evals, dev

_rows = queue.Queue()
_spent = {}  # session uid -> $ so far, for the header and the budget without a query per poll
_lock = threading.Lock()
_writer = None


def where(st):
    """(uid, session type, track) the state is showing. Read without the lock: a stale field is harmless here."""
    s = st.latest.get(1)
    if not st.session_uid or not s:
        return NOWHERE
    return str(st.session_uid), L.name(L.SESSION_TYPES, s["sessionType"]), L.name(L.TRACKS, s["trackId"])


def llm(role, model, stats=None, at=NOWHERE, why=None, error=None):
    """One model call: stats as llm.stream returns them, or error when it failed."""
    stats = stats or {}
    cost = stats.get("cost")
    if cost and at[0]:
        with _lock:
            _spent[at[0]] = _cost(at[0]) + cost
    _put("insert into usage values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
         (time.time(), *at, role, model, stats.get("provider"), stats.get("inTokens"), stats.get("outTokens"),
          cost, stats.get("firstMs"), stats.get("totalMs"), why, error))


def metric(kind, value, at=NOWHERE, **data):
    """A timing or a count: stt_ms, release_ms, tts_ms, call_delay_s, call_expired, call_stale, cut_off."""
    _put("insert into metrics values (?, ?, ?, ?, ?)", (time.time(), at[0], kind, value, json.dumps(data) if data else None))


def session_cost(uid):
    """$ spent on models in this session so far."""
    with _lock:
        return _cost(uid)


def _cost(uid):
    if not uid:
        return 0.0
    if uid not in _spent:
        try:
            db = archive.connect()
            _spent[uid] = db.execute("select coalesce(sum(cost), 0) from usage where session_uid = ?", (uid,)).fetchone()[0]
            db.close()
        except Exception as e:
            _log.error("couldn't read session cost", error=str(e))
            return 0.0
    return _spent[uid]


def flush(timeout=5.0):
    """Wait for queued rows to land (tests, and the server on its way out)."""
    end = time.time() + timeout
    while _rows.unfinished_tasks and time.time() < end:
        time.sleep(0.02)


def _put(sql, args):
    global _writer
    with _lock:
        if _writer is None:
            _writer = threading.Thread(target=_write, name="usage", daemon=True)
            _writer.start()
    _rows.put((sql, args))


def _write():
    db = None
    while True:
        sql, args = _rows.get()
        try:
            db = db or archive.connect()
            with db:
                db.execute(sql, args)
        except Exception as e:
            _log.error("couldn't record usage", error=str(e))
            db = None
        finally:
            _rows.task_done()
