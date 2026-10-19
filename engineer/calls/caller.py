"""Delivers the engineer's unprompted calls at a sensible moment.

`scan` says what's worth saying; this decides when. Calls wait for a straight (flat out,
no brake, wheel near centre for a second, not in the pit lane) unless they're urgent, never
talk over the driver or an answer in progress, keep a few seconds between calls, and expire if the
moment has passed. Times are session seconds, so a replay behaves like the live thing.
"""
import re
import threading
import time
from collections import deque

from .. import log, radiolog, usage
from ..race import Race, ready
from ..spec import MAX_CARS
from .common import LOW, NORMAL, URGENT
from .scan import scan

_log = log.get("calls")

# "less chat" / "more info": how low-priority a call may be and still be made
LEVELS = {"quiet": URGENT, "normal": NORMAL, "chatty": LOW}
WORDS = (("quiet", r"\b(less (chat|chatter|talk|info)|quiet|only the (important|essentials)|just the important|shush|shut up)\b"),
         ("chatty", r"\b(more (chat|chatter|talk|info)|talk to me|keep me (posted|updated|informed))\b"),
         ("normal", r"\b(normal|usual|default) (chat|chatter|talk|info|level)\b"))
REPLIES = {"quiet": "Copy, only the important stuff.", "normal": "Copy, back to normal.",
           "chatty": "Copy, I'll keep you posted on everything."}

QUIET = 5.0       # s without packets before the watcher stands down
STRAIGHT_SECS = 1.0
SPACING = 6.0     # between calls
TICK = 0.2


class Caller:
    def __init__(self, state, hub, busy=lambda: False, said=lambda text: None, at=None, scan=True):
        self.state, self.hub, self.busy, self.said = state, hub, busy, said
        self.scan = scan     # False: only say what's pushed (the team's calls), nothing of our own
        self.team = False    # the pit wall owns the strategy calls
        self.at = at  # fn -> usage.where(): record delivery timings (live only, not replays)
        self.sent = deque(maxlen=30)
        self._n = 0
        self.level = "normal"
        self._reset(None)

    def _reset(self, uid):
        self._uid, self.mem, self.queue, self._pushed = uid, {}, [], []
        self._flat_since, self._last_out = None, -1e9

    def push(self, calls):
        """Calls from outside the scan (the pit wall's), queued like ours at the next step."""
        self._pushed += calls

    def command(self, text):
        """"less chat" and the like: changes how much gets said and answers for the radio, else None."""
        for level, pattern in WORDS:
            if re.search(pattern, text.lower()):
                self.level = level
                _log.info("call verbosity", mode=level)
                return REPLIES[level]
        return None

    def start(self):
        threading.Thread(target=self._loop, name="calls", daemon=True).start()

    def _loop(self):
        while True:
            time.sleep(TICK)
            try:
                self.step()
            except Exception as e:  # keep the watcher alive whatever happens
                _log.error("calls step crashed", error=str(e))

    def step(self):
        """One look at the state; returns the calls delivered (usually none)."""
        st = self.state
        with st.lock:
            if not ready(st):
                return []
            if st.session_uid != self._uid:
                self._reset(st.session_uid)
            if (st.silent_for() or 0) > QUIET:
                return []  # paused or gone: nothing to call, and the clock isn't moving
            b = Race(st)
            if not b.race or b.me >= MAX_CARS:
                return []
            now = b.now
            if now < self._last_out:  # flashback: what was queued describes a moment that's gone
                self.queue.clear()
                self._last_out = now
            top = LEVELS[self.level]
            found = scan(b, self.mem, self.team) if self.scan else []
            pushed, self._pushed = self._pushed, []
            if any(c["topic"] == "team" for c in pushed):  # the team's newest call replaces one still waiting
                self.queue = [c for c in self.queue if c["topic"] != "team"]
            self.queue += [{**c, "at": now} for c in found if c["prio"] <= top] + [{**c, "at": now} for c in pushed]
            out = self._deliver(b, now)
        for c in out:
            self.said(c["text"])
        return out

    def _deliver(self, b, now):
        for c in self.queue:
            if now - c["at"] > c["ttl"]:
                self._metric("call_expired", 1, topic=c["topic"])  # never found a straight in time
        self.queue = [c for c in self.queue if 0 <= now - c["at"] <= c["ttl"]]
        if not self.queue or self.busy() or now - self._last_out < SPACING:
            return []
        flat = self._on_straight(b)
        for c in sorted(self.queue, key=lambda c: (c["prio"], c["at"])):
            if not (flat or c["prio"] == URGENT):
                continue
            self.queue.remove(c)
            text = c["text"](b)
            if text:
                self._metric("call_delay_s", round(now - c["at"], 1), topic=c["topic"])
                return [self._send(b, c, text, now)]
            self._metric("call_stale", 1, topic=c["topic"])
        return []

    def _metric(self, kind, value, **data):
        if self.at:
            usage.metric(kind, value, self.at(), **data)

    def _on_straight(self, b):
        tel = b.telemetry()
        if not tel or b.my["pitStatus"]:
            self._flat_since = None
            return False
        t = b.st.latest[6]["header"]["sessionTime"]
        if not (tel["throttle"] >= 0.95 and not tel["brake"] and abs(tel["steer"]) < 0.15):
            self._flat_since = None
        elif self._flat_since is None or t < self._flat_since:
            self._flat_since = t
        return self._flat_since is not None and t - self._flat_since >= STRAIGHT_SECS

    def _send(self, b, c, text, now):
        self._n += 1
        self._last_out = now
        out = {"id": f"c{self._n}", "at": time.time(), "lap": b.my["currentLapNum"], "dist": round(b.my["lapDistance"]),
               "sessionTime": round(now, 1), "topic": c["topic"], "prio": c["prio"], "text": text}
        self.sent.appendleft(out)
        self.hub.publish("call", out)
        if self.at:  # live only: what was really said, which a later `dev calls` replay can't tell you
            radiolog.record("call", out)
        _log.info("call", topic=c["topic"], lap=out["lap"], dist=out["dist"], text=text)
        return out
