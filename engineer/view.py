"""Turns RaceState into JSON-ready dicts for the dashboard.

Values stay in game units (ms, kph, celsius, joules); formatting is the UI's job.
"""
import math
import time

from . import calc
from . import lookups as L
from .spec import MAX_CARS, PACKETS

STALE_AFTER = 2.0


def _ms(minutes, ms):
    return minutes * 60000 + ms


def colour(c):
    return f'#{c["red"]:02x}{c["green"]:02x}{c["blue"]:02x}'


def _strip_header(d):
    return {k: v for k, v in d.items() if k != "header"}


def clean(v):
    """Make values safe for JSON.parse: no NaN/inf, no ints JS can't hold."""
    if isinstance(v, float):
        return v if math.isfinite(v) else None
    if isinstance(v, int) and v > 2**53:
        return str(v)  # sessionUID etc. would lose precision in JS
    if isinstance(v, dict):
        return {k: clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [clean(x) for x in v]
    return v


def _active_indices(st):
    lap = st.latest.get(2)
    if lap:
        return [i for i, c in enumerate(lap["lapData"]) if c["resultStatus"] >= 2]
    parts = st.latest.get(4)
    return list(range(parts["numActiveCars"])) if parts else []


def _car(st, pid, key, idx):
    pkt = st.latest.get(pid)
    return pkt[key][idx] if pkt else None


def _identity(st, idx):
    p = _car(st, 4, "participants", idx)
    if not p:
        return {"name": f"Car {idx}", "team": None, "number": None}
    name = p["name"] or L.DRIVERS.get(p["driverId"], f"Car {idx}")
    return {
        "name": name,
        "driver": L.DRIVERS.get(p["driverId"]),
        "team": L.name(L.TEAMS, p["teamId"]),
        "number": p["raceNumber"],
        "ai": bool(p["aiControlled"]),
        "myTeam": bool(p["myTeam"]),
        "nationality": L.NATIONALITIES.get(p["nationality"]),
        "telemetryPublic": bool(p["yourTelemetry"]),
        "colour": colour(p["liveryColours"][0]) if p["numColours"] else None,
    }


def player_identity(st):
    with st.lock:
        if not st.latest:
            return None
        idx = st.latest[next(iter(st.latest))]["header"]["playerCarIndex"]
        return _identity(st, idx) if idx < MAX_CARS else None


def session_names(st):
    """Every name a driver in this session goes by: the game's ('TSUNODA') plus the full one."""
    with st.lock:
        pkt = st.latest.get(4)
        if not pkt:
            return []
        names = []
        # not [:numActiveCars]: retired cars keep their slot, so the count drops below the last index
        for p in pkt["participants"]:
            if p["name"]:  # padded empty slots from 22-car formats read as driver 0
                names += [p["name"], L.DRIVERS.get(p["driverId"], "")]
        return [n for n in names if n]


def _tower_row(st, idx, player_idx):
    lap = _car(st, 2, "lapData", idx)
    status = _car(st, 7, "carStatusData", idx)
    dmg = _car(st, 10, "carDamageData", idx)
    tel = _car(st, 6, "carTelemetryData", idx)
    tel2 = _car(st, 16, "carTelemetry2Data", idx)
    row = {"idx": idx, "isPlayer": idx == player_idx, **_identity(st, idx)}

    if lap:
        row.update(
            position=lap["carPosition"],
            lap=lap["currentLapNum"],
            lastLapMs=lap["lastLapTimeInMS"],
            currentLapMs=lap["currentLapTimeInMS"],
            s1Ms=_ms(lap["sector1TimeMinutesPart"], lap["sector1TimeMSPart"]),
            s2Ms=_ms(lap["sector2TimeMinutesPart"], lap["sector2TimeMSPart"]),
            sector=lap["sector"] + 1,
            gapLeaderMs=_ms(lap["deltaToRaceLeaderMinutesPart"], lap["deltaToRaceLeaderMSPart"]),
            gapAheadMs=_ms(lap["deltaToCarInFrontMinutesPart"], lap["deltaToCarInFrontMSPart"]),
            lapDistance=lap["lapDistance"],
            pit=L.PIT_STATUS.get(lap["pitStatus"], ""),
            pitStops=lap["numPitStops"],
            penaltiesSec=lap["penalties"],
            warnings=lap["totalWarnings"],
            cornerCutting=lap["cornerCuttingWarnings"],
            unservedDT=lap["numUnservedDriveThroughPens"],
            unservedSG=lap["numUnservedStopGoPens"],
            invalid=bool(lap["currentLapInvalid"]),
            grid=lap["gridPosition"],
            driverStatus=L.DRIVER_STATUS.get(lap["driverStatus"]),
            result=L.RESULT_STATUS.get(lap["resultStatus"]),
        )
    if status:
        row.update(
            tyre=L.VISUAL_COMPOUNDS.get(status["visualTyreCompound"]),
            compound=L.ACTUAL_COMPOUNDS.get(status["actualTyreCompound"]),
            tyreAge=status["tyresAgeLaps"],
            fuelLaps=status["fuelRemainingLaps"],
            ersJ=status["ersStoreEnergy"],
            ersMode=L.ERS_MODES.get(status["ersDeployMode"]),
            flag=L.FIA_FLAGS.get(status["vehicleFiaFlags"]),
            drsAllowed=bool(status["drsAllowed"]),
        )
    if dmg:
        row.update(
            wearMax=max(dmg["tyresWear"]),
            wingDamage=max(dmg["frontLeftWingDamage"], dmg["frontRightWingDamage"], dmg["rearWingDamage"]),
        )
    if tel:
        row.update(speed=tel["speed"], gear=tel["gear"], drs=bool(tel["drs"]))
    if tel2:
        row.update(overtakeActive=bool(tel2["overtakeActive"]), aeroStraight=bool(tel2["activeAeroMode"]))
    row["bestLapMs"] = calc.best_ms(st.history.get(idx))
    return row


def _session(st):
    s = st.latest.get(1)
    if not s:
        return None
    out = _strip_header(s)
    out["marshalZones"] = s["marshalZones"][: s["numMarshalZones"]]
    out["weatherForecastSamples"] = [
        {**w, "sessionTypeName": L.name(L.SESSION_TYPES, w["sessionType"]),
         "weatherName": L.name(L.WEATHER, w["weather"])}
        for w in s["weatherForecastSamples"][: s["numWeatherForecastSamples"]]
    ]
    out["activeAeroZonesFull"] = s["activeAeroZonesFull"][: s["numActiveAeroZonesFull"]]
    out["activeAeroZonesPartial"] = s["activeAeroZonesPartial"][: s["numActiveAeroZonesPartial"]]
    out["drsZones"] = s["drsZones"][: s["numDRSZones"]]
    out["weekendStructure"] = [L.name(L.SESSION_TYPES, t) for t in s["weekendStructure"][: s["numSessionsInWeekend"]]]
    out["names"] = {
        "track": L.name(L.TRACKS, s["trackId"]),
        "sessionType": L.name(L.SESSION_TYPES, s["sessionType"]),
        "weather": L.name(L.WEATHER, s["weather"]),
        "formula": L.name(L.FORMULAS, s["formula"]),
        "gameMode": L.name(L.GAME_MODES, s["gameMode"]),
        "ruleSet": L.name(L.RULESETS, s["ruleSet"]),
        "safetyCar": L.name(L.SAFETY_CAR, s["safetyCarStatus"]),
    }
    return out


def _event_view(st, ev):
    d = ev["details"] or {}
    names = {}
    for key in ("vehicleIdx", "otherVehicleIdx", "overtakingVehicleIdx", "beingOvertakenVehicleIdx",
                "vehicle1Idx", "vehicle2Idx", "fastestVehicleIdxInSession"):
        if key in d and d[key] < MAX_CARS:
            names[key] = _identity(st, d[key])["name"]
    if ev["code"] == "PENA":
        names["penaltyType"] = L.name(L.PENALTY_TYPES, d["penaltyType"])
        names["infringementType"] = L.name(L.INFRINGEMENTS, d["infringementType"])
    return {**ev, "names": names}


def _packet_stats(st, now):
    return [
        {
            "id": pid,
            "name": PACKETS[pid].name,
            "count": s.count,
            "rate": s.rate(now),
            "size": s.size,
            "specSize": PACKETS[pid].size,
            "ageSec": now - s.last_at if s.last_at else None,
        }
        for pid, s in st.stats.items()
    ]


def snapshot(st, listen):
    now = time.time()
    with st.lock:
        player = st.latest[next(iter(st.latest))]["header"]["playerCarIndex"] if st.latest else None
        cars = [_tower_row(st, i, player) for i in _active_indices(st)]
        cars.sort(key=lambda c: c.get("position") or 99)
        tel = st.latest.get(6)
        return clean({
            "meta": {
                "listen": listen,
                "now": now,
                "receiving": bool(st.last_packet_at) and now - st.last_packet_at < STALE_AFTER,
                "lastPacketAgeSec": now - st.last_packet_at if st.last_packet_at else None,
                "totalPackets": st.total,
                "sources": dict(st.sources),
                "wrongFormats": {str(k): v for k, v in st.wrong_formats.items()},
                "errorCount": st.error_count,
                "recentErrors": [{"at": t, "msg": m} for t, m in list(st.errors)[-10:]],
                "gameVersion": st.version,
                "format": st.format,
                "sessionUID": str(st.session_uid) if st.session_uid else None,
            },
            "playerIdx": player,
            "session": _session(st),
            "cars": cars,
            "mfdPanel": tel["mfdPanelIndex"] if tel else None,
            "suggestedGear": tel["suggestedGear"] if tel else None,
            "buttons": L.pressed_buttons(st.buttons),
            "events": [_event_view(st, e) for e in list(st.events)[-150:]],
            "packets": _packet_stats(st, now),
        })


def car_detail(st, idx):
    with st.lock:
        player = st.latest[next(iter(st.latest))]["header"]["playerCarIndex"] if st.latest else None
        hist = st.history.get(idx)
        if hist:
            hist = _strip_header(hist)
            hist["lapHistoryData"] = hist["lapHistoryData"][: hist["numLaps"]]
            hist["tyreStintsHistoryData"] = [
                {**s, "visual": L.VISUAL_COMPOUNDS.get(s["tyreVisualCompound"]),
                 "actual": L.ACTUAL_COMPOUNDS.get(s["tyreActualCompound"])}
                for s in hist["tyreStintsHistoryData"][: hist["numTyreStints"]]
            ]
        sets = st.tyre_sets.get(idx)
        if sets:
            sets = _strip_header(sets)
            sets["tyreSetData"] = [
                {**s, "visual": L.VISUAL_COMPOUNDS.get(s["visualTyreCompound"]),
                 "actual": L.ACTUAL_COMPOUNDS.get(s["actualTyreCompound"])}
                for s in sets["tyreSetData"]
            ]
        status = _car(st, 7, "carStatusData", idx)
        tel = _car(st, 6, "carTelemetryData", idx)
        is_player = idx == player
        setups = st.latest.get(5)
        return clean({
            "idx": idx,
            "isPlayer": is_player,
            "identity": _identity(st, idx),
            "participant": _car(st, 4, "participants", idx),
            "lap": _car(st, 2, "lapData", idx),
            "telemetry": tel and {**tel, "surfaceNames": [L.name(L.SURFACES, s) for s in tel["surfaceType"]]},
            "telemetry2": _car(st, 16, "carTelemetry2Data", idx),
            "status": status and {
                **status,
                "names": {
                    "tyre": L.VISUAL_COMPOUNDS.get(status["visualTyreCompound"]),
                    "compound": L.ACTUAL_COMPOUNDS.get(status["actualTyreCompound"]),
                    "fuelMix": L.FUEL_MIX.get(status["fuelMix"]),
                    "ersMode": L.ERS_MODES.get(status["ersDeployMode"]),
                    "flag": L.FIA_FLAGS.get(status["vehicleFiaFlags"]),
                },
            },
            "damage": _car(st, 10, "carDamageData", idx),
            "setup": _car(st, 5, "carSetups", idx),
            "nextFrontWing": setups["nextFrontWingValue"] if setups and is_player else None,
            "motion": _car(st, 0, "carMotionData", idx),
            "motionEx": _strip_header(st.latest[13]) if is_player and 13 in st.latest else None,
            "history": hist,
            "tyreSets": sets,
        })


def raw(st, pid):
    with st.lock:
        if pid == 11:
            return clean({str(k): v for k, v in st.history.items()})
        if pid == 12:
            return clean({str(k): v for k, v in st.tyre_sets.items()})
        if pid == 15:
            return clean({str(k): v for k, v in st.lap_positions.items()})
        return clean(st.latest.get(pid))
