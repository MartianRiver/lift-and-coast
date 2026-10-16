"""Every radio message and what the engineer did with it, kept next to the clips for review.

One JSON line per message and per reply in captures/radio/messages.jsonl (gitignored with the clips),
so a mishearing or a pointless answer can be traced back to the audio after a restart. Live, it also
gets every unprompted call as made, every stretch of the engineer's voice as played, and the start of
each session recording on the wall clock, which together put the whole radio on the race's timeline.

    uv run python -m engineer.dev radio [--last 20]
"""
import json
import threading
from pathlib import Path

from . import log

_log = log.get("radiolog")

CLIPS = Path(__file__).resolve().parent.parent / "captures" / "radio"
LOG = CLIPS / "messages.jsonl"
_lock = threading.Lock()


def record(kind, data):
    try:
        with _lock:
            CLIPS.mkdir(parents=True, exist_ok=True)
            with LOG.open("a") as f:
                f.write(json.dumps({"kind": kind, **data}) + "\n")
    except OSError as e:
        _log.error("couldn't record radio log", error=str(e))


def history(path=LOG):
    """Messages oldest first, each with the engineer's `reply` (or None) attached."""
    if not path.exists():
        return []
    msgs, by_id = [], {}
    for line in path.read_text().splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue  # a line cut short by a crash
        if row["kind"] == "message":
            row["reply"] = None
            msgs.append(row)
            by_id[row["id"]] = row
        elif row["kind"] == "reply" and row.get("to") in by_id:
            by_id[row["to"]]["reply"] = row
    return msgs
