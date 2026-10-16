"""Per-car lap-line records, the history the brief's trends and projections are built from.

Each time a car starts a new lap we note when it crossed the line plus its position, tyre,
wear, fuel and pit count at that moment. Gaps come from crossing times (same point on track)
rather than the live delta fields, so they're consistent and survive flashbacks: anything
after the rewind point is dropped.
"""
from . import log
from .spec import MAX_CARS

_log = log.get("laps")


class Laps:
    def __init__(self):
        self.cars = {}    # idx -> [crossing], oldest first; crossing["lap"] is the lap just started
        self._seen = {}   # idx -> lap number last seen
        self._peak = {}   # idx -> max surface temp per wheel this lap (player only)
        self._sc = {}     # idx -> SC/VSC was out at some point this lap

    def on_lap_data(self, data, latest):
        t = data["header"]["sessionTime"]
        status, damage = latest.get(7), latest.get(10)
        sc = bool(latest.get(1)) and latest[1]["safetyCarStatus"] in (1, 2)
        for idx, c in enumerate(data["lapData"]):
            if c["resultStatus"] < 2:
                continue
            lap, seen = c["currentLapNum"], self._seen.get(idx)
            self._seen[idx] = lap
            was_sc = self._sc.get(idx, False) or sc
            self._sc[idx] = was_sc
            if seen is None or lap == seen:
                continue
            if lap < seen:  # rewound past a line without (or before) the FLBK event
                self.cars[idx] = [x for x in self.cars.get(idx, []) if x["lap"] <= lap]
                continue
            x = _crossing(t, c, idx, status, damage, self._peak.pop(idx, None))
            x["scLap"] = was_sc  # the lap just finished ran under SC/VSC for at least part of it
            self._sc[idx] = sc
            self.cars.setdefault(idx, []).append(x)

    def on_telemetry(self, data):
        idx = data["header"]["playerCarIndex"]
        if idx >= MAX_CARS:
            return
        temps = data["carTelemetryData"][idx]["tyresSurfaceTemperature"]
        peak = self._peak.get(idx)
        self._peak[idx] = list(temps) if peak is None else [max(a, b) for a, b in zip(peak, temps)]

    def flashback(self, session_time):
        dropped = 0
        for idx, xs in self.cars.items():
            keep = [x for x in xs if x["t"] <= session_time]
            dropped += len(xs) - len(keep)
            self.cars[idx] = keep
            self._seen[idx] = keep[-1]["lap"] if keep else None
        self._peak.clear()  # the rewound part of the lap is gone; restart the peaks
        self._sc.clear()
        _log.info("flashback pruned laps", to=round(session_time, 2), dropped=dropped)

    def sc_laps(self, idx):
        """Lap numbers this car ran at least partly under SC/VSC."""
        return {x["lap"] - 1 for x in self.cars.get(idx, []) if x.get("scLap")}

    def at(self, idx, lap):
        return next((x for x in reversed(self.cars.get(idx, [])) if x["lap"] == lap), None)


def _crossing(t, c, idx, status, damage, peak):
    x = {
        "lap": c["currentLapNum"],
        # the packet arrives a little after the line; back-date by the time into the new lap
        "t": t - c["currentLapTimeInMS"] / 1000,
        "pos": c["carPosition"],
        "stops": c["numPitStops"],
        "pit": c["pitStatus"] > 0,
        "lastMs": c["lastLapTimeInMS"],
        "peakTemps": peak,
    }
    if status:
        s = status["carStatusData"][idx]
        x.update(tyre=s["visualTyreCompound"], age=s["tyresAgeLaps"], fuelLaps=s["fuelRemainingLaps"])
    if damage:
        d = damage["carDamageData"][idx]
        x["wear"] = list(d["tyresWear"])
        x["pu"] = (d["engineDamage"], d["gearBoxDamage"])
    return x
