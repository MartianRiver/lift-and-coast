"""Latest-known race state, fed one datagram at a time from the UDP thread."""
import threading
import time
from collections import Counter, deque

from . import log
from .decode import DecodeError, WrongFormat, decode
from .incidents import Incidents
from .laps import Laps
from .lookups import EVENT_NAMES
from .spec import PACKETS
from .trace import Traces
from .grip import Grip
from .wear import Wear

_log = log.get("state")

RATE_WINDOW = 2.0


class PacketStats:
    def __init__(self):
        self.count = 0
        self.size = 0
        self.last_at = 0.0
        self.arrivals = deque(maxlen=300)

    def hit(self, size, now):
        self.count += 1
        self.size = size
        self.last_at = now
        self.arrivals.append(now)

    def rate(self, now):
        recent = [t for t in self.arrivals if now - t <= RATE_WINDOW]
        return len(recent) / RATE_WINDOW


class RaceState:
    def __init__(self, hub):
        self.lock = threading.Lock()
        self.hub = hub
        self.button_listeners = []  # fn(prev_mask, new_mask), called under self.lock — keep them quick
        self.button_at = 0.0
        self.stats = {pid: PacketStats() for pid in PACKETS}
        self.total = 0
        self.last_packet_at = 0.0
        self.sources = Counter()
        self.wrong_formats = Counter()
        self.errors = deque(maxlen=50)
        self.error_count = 0
        self.version = None
        self.format = None
        self.check_feed = True  # dev replays that sit frozen turn this off
        self._reset_session(None)

    def silent_for(self):
        """Seconds since the game last sent anything (None before the first packet)."""
        return time.time() - self.last_packet_at if self.last_packet_at else None

    def _reset_session(self, uid):
        self.session_uid = uid
        self.latest = {}
        self.history = {}
        self.tyre_sets = {}
        self.lap_positions = {}
        self.laps = Laps()
        self.incidents = Incidents()
        self.traces = Traces()
        self.wear = Wear()
        self.grip = Grip()
        self.events = deque(maxlen=300)
        self.drs = False  # off until DRSE: a wet race may never enable it
        self.button_log = deque(maxlen=30)
        self.buttons = 0

    def ingest(self, buf, addr):
        now = time.time()
        with self.lock:
            self.total += 1
            self.last_packet_at = now
            if addr[0] not in self.sources:
                _log.info("receiving from new source", addr=addr[0], port=addr[1])
            self.sources[addr[0]] += 1

        try:
            pid, data = decode(buf)
        except WrongFormat as e:
            with self.lock:
                if e.fmt not in self.wrong_formats:
                    _log.warn("game is sending an unsupported UDP format", format=e.fmt)
                self.wrong_formats[e.fmt] += 1
            return
        except DecodeError as e:
            self._error(str(e), now, exc=False)
            return
        except Exception as e:
            self._error(f"{type(e).__name__}: {e}", now, exc=True)
            return

        with self.lock:
            self.stats[pid].hit(len(buf), now)
            self._store(pid, data, now)

    def _error(self, msg, now, exc):
        with self.lock:
            self.error_count += 1
            first = not any(m == msg for _, m in self.errors)
            self.errors.append((now, msg))
        if first:
            _log.error("decode failed", exc=exc, error=msg)

    def _store(self, pid, data, now):
        h = data["header"]
        uid = h["sessionUID"]
        if uid and uid != self.session_uid:
            _log.info("new session", uid=str(uid), previous=str(self.session_uid))
            self._reset_session(uid)
        self.version = f'{h["gameMajorVersion"]}.{h["gameMinorVersion"]:02d}'
        self.format = h["packetFormat"]

        self.latest[pid] = data
        if pid == 2:
            self.laps.on_lap_data(data, self.latest)
            self.incidents.on_lap_data(data)
            self.traces.on_lap_data(data, self.latest)
        elif pid == 6:
            self.laps.on_telemetry(data)
            self.grip.on_telemetry(data, self.latest)
        elif pid == 13:
            self.grip.on_motion(data, self.latest)
        elif pid == 10:
            self.wear.on_damage(data, self.latest)
        elif pid == 11:
            self.history[data["carIdx"]] = data
        elif pid == 12:
            self.tyre_sets[data["carIdx"]] = data
        elif pid == 15:
            self.lap_positions[data["lapStart"]] = data
        elif pid == 3:
            self._event(data, now)

    def _event(self, data, now):
        code = data["eventStringCode"]
        ev = {
            "at": now,
            "sessionTime": data["header"]["sessionTime"],
            "code": code,
            "name": EVENT_NAMES.get(code, code),
            "details": data["eventDetails"],
        }
        if code == "BUTN":
            prev, self.buttons = self.buttons, data["eventDetails"]["buttonStatus"]
            self.button_at = now
            self.button_log.append(ev)
            _log.trace("buttons", status=self.buttons)
            self.hub.publish("buttons", {"status": self.buttons, "at": now})
            for fn in self.button_listeners:
                fn(prev, self.buttons)
        else:
            if code == "FLBK":
                self.laps.flashback(data["eventDetails"]["flashbackSessionTime"])
            elif code in ("DRSE", "DRSD"):
                self.drs = code == "DRSE"
            self.incidents.on_event(ev, self.latest.get(2))
            self.events.append(ev)
            _log.debug("event", code=code, details=data["eventDetails"])
