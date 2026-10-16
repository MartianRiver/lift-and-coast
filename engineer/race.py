"""One consistent look at the race state: who I am, where everyone is, what a stop costs.

The brief, strategy, the proactive calls and the Race tab all read the same snapshot, so they
can't disagree. Build it under `state.lock` and don't keep it past that.
"""
from . import calc, pitstops
from . import lookups as L

RACES = {15, 16, 17}


def ready(st):
    """Enough packets to build a snapshot (session, lap data, participants)."""
    return {1, 2, 4} <= st.latest.keys()


class Race:
    def __init__(self, st):
        self.st = st
        self.s = st.latest[1]
        self.lap_pkt = st.latest[2]
        self.me = self.lap_pkt["header"]["playerCarIndex"]
        self.race = self.s["sessionType"] in RACES
        self.my = self.lap_pkt["lapData"][self.me] if self.me < len(self.lap_pkt["lapData"]) else None
        self.sc_laps = st.laps.sc_laps(self.me)
        self.ref_ms = calc.ref_lap_ms(st.history.get(self.me), self.sc_laps)
        self.gaps = calc.gaps(st.laps, self.me, self.active()) if self.race and self.my else {}

    @property
    def now(self):
        return self.lap_pkt["header"]["sessionTime"]

    def active(self):
        return [i for i, c in enumerate(self.lap_pkt["lapData"]) if c["resultStatus"] in (2, 3)]

    def retired(self):
        return [i for i, c in enumerate(self.lap_pkt["lapData"]) if c["resultStatus"] >= 4]

    def car(self, pid, key, idx=None):
        pkt = self.st.latest.get(pid)
        return pkt[key][self.me if idx is None else idx] if pkt else None

    def status(self, idx=None):
        return self.car(7, "carStatusData", idx)

    def damage(self, idx=None):
        return self.car(10, "carDamageData", idx)

    def telemetry(self, idx=None):
        return self.car(6, "carTelemetryData", idx)

    def pos(self, idx):
        # when a session ends the game finishes AI laps off-screen: history and the final
        # classification get the result, lap data stops with stale positions
        final = self.st.latest.get(8)
        if final and idx < final["numCars"] and final["classificationData"][idx]["position"]:
            return final["classificationData"][idx]["position"]
        return self.lap_pkt["lapData"][idx]["carPosition"]

    def name(self, idx):
        p = self.st.latest[4]["participants"][idx]
        return p["name"] or L.DRIVERS.get(p["driverId"], f"Car {idx}")

    def team(self, idx):
        return L.name(L.TEAMS, self.st.latest[4]["participants"][idx]["teamId"])

    def neighbour(self, step):
        """The car `step` places from me (-1 ahead, +1 behind), or None."""
        pos = self.pos(self.me) + step
        return next((i for i in self.active() if self.pos(i) == pos), None)

    def laps_left(self):
        """Laps still to start after this one."""
        return self.s["totalLaps"] - self.my["currentLapNum"]

    def battery(self):
        status = self.status()
        return status and status["ersStoreEnergy"] / calc.ERS_STORE

    def loss(self):
        """(seconds a green-flag stop costs, where that comes from): this race's stops once there are
        two, else earlier races at this track, else this race's one stop."""
        live, past = calc.pit_loss(self.st.laps, self.st.history), pitstops.here(self.s)
        before = past and f"over {plural(past[1], 'stop')} in {plural(past[2], 'earlier race')} here"
        if live and (live[1] >= 2 or not past):
            return live[0], f"from {plural(live[1], 'stop')} this race" + (f"; {past[0]:.1f}s {before}" if past else "")
        if past:
            return past[0], before + (f"; the 1 stop this race said {live[0]:.1f}s" if live else ", none this race yet")
        return None

    def at_flag(self, g):
        """Where a gap goes at last lap's rate: ("closes", laps until it does, laps left) or ("gap", s at the flag, laps left)."""
        left = self.laps_left() + 1
        end = g["gap"] + g["last"] * left
        if (g["gap"] > 0) != (end > 0):
            return "closes", abs(g["gap"] / g["last"]), left
        return "gap", abs(end), left


def plural(count, thing):
    return f"{count} {thing}{'s' * (count != 1)}"
