"""What has happened in the race: the player's warnings and penalties, other cars' stops, penalties,
retirements, contacts or passes involving the player, and passes between the cars just ahead and
behind ("Alonso just saved me" means Alonso got between the player and the car chasing them).

Warnings and penalty seconds come from the player's lap-data counters rather than PENA events:
the counters are what the game holds, and they drop back after a flashback (a 3rd warning and its
3 s penalty flashbacked away take the counters from 3 back to 2).
Every entry carries its session time, so a flashback drops whatever came after the rewind point.
"""
from . import log
from . import lookups as L
from .spec import MAX_CARS

_log = log.get("incidents")

# the 3rd corner-cutting warning brings a 3 s penalty
WARNINGS_FOR_PENALTY = 3
WAVE = 5  # more stops than this in the window get summarised
AROUND = 3  # positions either side of the player whose passes between each other are worth knowing
PENALTIES = {0, 1, 2, 4, 6}  # drive through, stop-go, grid, time, DSQ; warnings and lap invalidations are noise


class Incidents:
    def __init__(self):
        self.log = []      # {t, lap, kind, ...}, oldest first; lap = the player's lap at the time
        self._counts = None
        self._pit = {}     # idx -> pitStatus last seen

    def on_lap_data(self, data):
        me = data["header"]["playerCarIndex"]
        if me >= MAX_CARS:
            return
        t, cars = data["header"]["sessionTime"], data["lapData"]
        lap = cars[me]["currentLapNum"]
        self._player(t, lap, cars[me])
        for idx, c in enumerate(cars):
            if c["resultStatus"] != 2:
                continue
            now = c["pitStatus"]
            was = self._pit.get(idx, now)  # a car first seen in the pit lane started there
            self._pit[idx] = now
            if idx == me or was == now:
                continue
            if not was:
                self._add(t, lap, "pit", idx=idx, before=c["carPosition"], after=None)
            elif not now:  # out of the pit lane: where they came out
                stop = next((e for e in reversed(self.log) if e["kind"] == "pit" and e["idx"] == idx), None)
                if stop:
                    stop["after"] = c["carPosition"]

    def _player(self, t, lap, c):
        counts = {k: c[k] for k in ("cornerCuttingWarnings", "totalWarnings", "penalties")}
        prev, self._counts = self._counts, counts
        if prev is None:
            return
        if counts["cornerCuttingWarnings"] > prev["cornerCuttingWarnings"]:
            self._add(t, lap, "limits", dist=round(c["lapDistance"]))
        elif counts["totalWarnings"] > prev["totalWarnings"]:
            self._add(t, lap, "warning", dist=round(c["lapDistance"]))

    def on_event(self, ev, lap_pkt):
        code, d, t = ev["code"], ev["details"], ev["sessionTime"]
        if code == "FLBK":
            return self.flashback(d["flashbackSessionTime"])
        if not lap_pkt:
            return
        me = lap_pkt["header"]["playerCarIndex"]
        if me >= MAX_CARS:
            return
        my = lap_pkt["lapData"][me]
        lap = my["currentLapNum"]
        if code == "PENA" and d["penaltyType"] in PENALTIES:
            self._add(t, lap, "penalty", idx=d["vehicleIdx"], type=d["penaltyType"], why=d["infringementType"],
                      secs=d["time"] if d["time"] != 255 else None)
        elif code == "RTMT" and not any(e["kind"] == "out" and e["idx"] == d["vehicleIdx"] for e in self.log):
            self._add(t, lap, "out", idx=d["vehicleIdx"], why=d["reason"])  # re-sent after every flashback
        elif code == "COLL" and me in (d["vehicle1Idx"], d["vehicle2Idx"]):
            other = d["vehicle2Idx"] if d["vehicle1Idx"] == me else d["vehicle1Idx"]
            self._add(t, lap, "contact", idx=other, dist=round(my["lapDistance"]))
        elif code == "OVTK" and me in (d["overtakingVehicleIdx"], d["beingOvertakenVehicleIdx"]):
            passed = d["overtakingVehicleIdx"] == me
            other = d["beingOvertakenVehicleIdx"] if passed else d["overtakingVehicleIdx"]
            self._add(t, lap, "passed" if passed else "lost", idx=other, dist=round(my["lapDistance"]))
        elif code == "OVTK" and self._around(lap_pkt, me, d["overtakingVehicleIdx"], d["beingOvertakenVehicleIdx"]):
            self._add(t, lap, "move", idx=d["overtakingVehicleIdx"], other=d["beingOvertakenVehicleIdx"])
        elif code in ("DTSV", "SGSV"):
            self._add(t, lap, "served", idx=d["vehicleIdx"])

    @staticmethod
    def _around(lap_pkt, me, *idxs):
        mine = lap_pkt["lapData"][me]["carPosition"]
        return all(i < len(lap_pkt["lapData"]) and abs(lap_pkt["lapData"][i]["carPosition"] - mine) <= AROUND for i in idxs)

    def flashback(self, session_time):
        keep = [e for e in self.log if e["t"] <= session_time]
        if len(keep) < len(self.log):
            _log.info("flashback pruned incidents", to=round(session_time, 2), dropped=len(self.log) - len(keep))
        self.log = keep
        # counters revert on their own; the next packet re-baselines them without recording anything
        self._counts = None

    def _add(self, t, lap, kind, **fields):
        self.log.append({"t": t, "lap": lap, "kind": kind, **fields})
        _log.debug("incident", kind=kind, lap=lap, **fields)


def penalty_text(e):
    kind = L.name(L.PENALTY_TYPES, e["type"]).lower()
    if e["secs"] and e["type"] == 4:
        kind = f"{e['secs']} s penalty"
    return f"{kind} ({L.name(L.INFRINGEMENTS, e['why']).lower()})"


def retired_text(e):
    # F1 24 doesn't say why
    return "retired" if e["why"] is None else f"retired ({L.name(L.RESULT_REASONS, e['why']).lower()})"


def summary(inc, my, name, track_len, recent=3):
    """Brief lines: the player's warnings/penalties for the whole race, other cars' news for the last few laps."""
    lap = my["currentLapNum"]
    out = []
    limits = [e for e in inc.log if e["kind"] == "limits"]
    if limits or my["penalties"] or my["totalWarnings"]:
        where = ", ".join(f"L{e['lap']} at {e['dist']} m" for e in limits)
        line = f"  track limits: {my['cornerCuttingWarnings']} warning{'s' * (my['cornerCuttingWarnings'] != 1)}"
        line += f" ({where} of {track_len} m)" if where else ""
        if my["cornerCuttingWarnings"] == WARNINGS_FOR_PENALTY - 1:
            line += " · one more is a time penalty"
        if my["totalWarnings"] > my["cornerCuttingWarnings"]:
            line += f" · other warnings {my['totalWarnings'] - my['cornerCuttingWarnings']}"
        out.append(line)
    owed = [f"{my['penalties']} s time penalty to come" if my["penalties"] else "",
            f"{my['numUnservedDriveThroughPens']} drive-through to serve" if my["numUnservedDriveThroughPens"] else "",
            f"{my['numUnservedStopGoPens']} stop-go to serve" if my["numUnservedStopGoPens"] else ""]
    if any(owed):
        out.append("  YOUR PENALTIES: " + ", ".join(p for p in owed if p))
    contacts = [f"L{e['lap']} {name(e['idx'])} at {e['dist']} m" for e in inc.log if e["kind"] == "contact"]
    if contacts:
        out.append("  contact with you: " + ", ".join(contacts))
    out += _others(inc, name, lap - recent + 1)
    return out


def _others(inc, name, since):
    out = []
    pens = [f"{name(e['idx'])} {penalty_text(e)} L{e['lap']}" for e in inc.log if e["kind"] == "penalty"]
    pens += [f"{name(e['idx'])} served it L{e['lap']}" for e in inc.log if e["kind"] == "served"]
    if pens:
        out.append("  penalties: " + " · ".join(pens))
    gone = [f"{name(e['idx'])} L{e['lap']} {retired_text(e)}" for e in inc.log if e["kind"] == "out"]
    if gone:
        out.append("  retired: " + ", ".join(gone))
    stops = [e for e in inc.log if e["kind"] == "pit" and e["lap"] >= since]
    if len(stops) > WAVE:  # a safety-car pit wave: count it, list only who moved
        laps = sorted({e["lap"] for e in stops})
        moved = [e for e in stops if e["after"] != e["before"]]
        out.append(f"  pitted recently: {len(stops)} cars, L{laps[0]}" + (f"–{laps[-1]}" if len(laps) > 1 else "")
                   + (", positions changed: " + _stops(moved, name) if moved else ", nobody changed position"))
    elif stops:
        out.append("  pitted recently: " + _stops(stops, name))
    moves = [e for e in inc.log if e["kind"] in ("passed", "lost") and e["lap"] >= since]
    if moves:
        out.append("  on track: " + ", ".join(
            f"{'you passed' if e['kind'] == 'passed' else 'passed by'} {name(e['idx'])} L{e['lap']} at {e['dist']} m"
            for e in moves))
    around = _around_you(inc, name, since)
    if around:
        out.append("  between the cars around you: " + " · ".join(around))
    return out


def _around_you(inc, name, since):
    """Passes between the cars near the player, a fight's back-and-forth collapsed to who came out ahead."""
    fights = {}
    for e in inc.log:
        if e["kind"] == "move" and e["lap"] >= since:
            fights.setdefault(frozenset((e["idx"], e["other"])), []).append(e)
    out = []
    for moves in sorted(fights.values(), key=lambda m: m[-1]["t"]):
        last = moves[-1]
        line = f"{name(last['idx'])} passed {name(last['other'])} L{last['lap']}"
        if len(moves) > 1:
            laps = f"L{moves[0]['lap']}" + (f"–{last['lap']}" if moves[0]["lap"] != last["lap"] else "")
            line += f" (after {len(moves)} changes of place, {laps})"
        out.append(line)
    return out


def _stops(stops, name):
    return ", ".join(f"{name(e['idx'])} L{e['lap']} P{e['before']}→" + (f"P{e['after']}" if e["after"] else "in the pit lane now")
                     for e in stops)
