"""What the Race tab shows: the few numbers worth a glance mid-race, from the same maths as the brief
(so the screen and the engineer never disagree)."""
from . import calc, incidents, strategy, trace
from . import lookups as L
from .brief import at_flag_words
from .fmt import FRONT_TO_BACK, WHEELS, faults, hurt, trend
from .race import Race, ready
from .spec import MAX_CARS
from .view import clean, colour


def glance(st):
    with st.lock:
        if not ready(st):
            return None
        b = Race(st)
        if b.me >= MAX_CARS:
            return None  # spectating
        out = {"session": _session(b), "me": _me(b), "log": _log_lines(b), "silentSecs": st.silent_for()}
        if b.race:
            out.update(ahead=_rival(b, -1), behind=_rival(b, +1))
        else:
            out["board"] = _board(b)
        out["timeLoss"] = _time_loss(b)
        return clean(out)


def _session(b):
    s = b.s
    return {"track": L.name(L.TRACKS, s["trackId"]), "type": L.name(L.SESSION_TYPES, s["sessionType"]),
            "race": b.race, "lap": b.my["currentLapNum"], "totalLaps": s["totalLaps"], "timeLeft": s["sessionTimeLeft"],
            "sc": L.name(L.SAFETY_CAR, s["safetyCarStatus"]) if s["safetyCarStatus"] else None,
            "weather": L.name(L.WEATHER, s["weather"]), "trackTemp": s["trackTemperature"],
            "cars": len(b.active())}


def _me(b):
    me, my = b.me, b.my
    hist = b.st.history.get(me)
    status, dmg = b.status(me), b.damage(me)
    out = {"position": b.pos(me), "name": b.name(me), "lastLapMs": my["lastLapTimeInMS"] or None,
           "bestLapMs": calc.best_ms(hist), "currentLapMs": my["currentLapTimeInMS"], "invalid": bool(my["currentLapInvalid"]),
           "pit": L.PIT_STATUS.get(my["pitStatus"]) if my["pitStatus"] else None, "stops": my["numPitStops"],
           "cornerCutting": my["cornerCuttingWarnings"], "penaltyAt": incidents.WARNINGS_FOR_PENALTY,
           "otherWarnings": my["totalWarnings"] - my["cornerCuttingWarnings"], "penaltiesSec": my["penalties"],
           "driveThroughs": my["numUnservedDriveThroughPens"], "stopGos": my["numUnservedStopGoPens"]}
    laps = calc.completed_laps(hist)
    if laps:
        out["lastValid"] = laps[-1][2]
    if status:
        out.update(fuelDelta=status["fuelRemainingLaps"], ersPct=round(100 * b.battery()),
                   ersMode=L.ERS_MODES.get(status["ersDeployMode"]),
                   tyre={"name": L.VISUAL_COMPOUNDS.get(status["visualTyreCompound"]), "age": status["tyresAgeLaps"]})
    if status and dmg:
        out["tyre"].update(_tyres(b, dmg))
    if dmg:
        out["damage"] = _damage(dmg)
        out["powerUnit"] = {"engine": dmg["engineDamage"], "gearbox": dmg["gearBoxDamage"]}
    return out


def _tyres(b, dmg):
    rates = strategy.stint_rates(b)
    worn = strategy.worn_in(b)
    return {"corners": [WHEELS[i] for i in FRONT_TO_BACK],
            "wear": [dmg["tyresWear"][i] for i in FRONT_TO_BACK],
            "rate": [rates[i] for i in FRONT_TO_BACK] if rates else None,
            "worn": worn and worn[1] is not None and {"corner": WHEELS[worn[0]], "laps": worn[1], "pct": strategy.WORN}}


def _damage(dmg):
    return [f"{k} {v}%" for k, v in hurt(dmg).items()] + faults(dmg)


def _rival(b, step):
    idx = b.neighbour(step)
    if idx is None:
        return None
    out = _who(b, idx)
    out["position"] = b.pos(idx)
    g = b.gaps.get(idx)
    if g:
        out["gap"] = abs(g["gap"])
        if g["last"] is not None:
            out["lastLap"] = trend(g["gap"], g["last"])
            out["closing"] = (g["last"] < 0) == (g["gap"] > 0) and abs(g["last"]) >= 0.05
        if g["trendLaps"] and g["trendLaps"] > 1:
            out["trend"] = trend(g["gap"], g["trend"])
            out["trendLaps"] = g["trendLaps"]
        if g["last"] is not None and g["trendLaps"] and g["trendLaps"] > 1:
            out["atFlag"] = at_flag_words(b.at_flag(g))
    c = b.lap_pkt["lapData"][idx]
    out["lastLapMs"] = c["lastLapTimeInMS"] or None
    out["pit"] = L.PIT_STATUS.get(c["pitStatus"]) if c["pitStatus"] else None
    out["stops"] = c["numPitStops"]
    return out


def _who(b, idx):
    p = b.st.latest[4]["participants"][idx]
    status, dmg = b.status(idx), b.damage(idx)
    out = {"idx": idx, "name": b.name(idx), "team": b.team(idx),
           "colour": colour(p["liveryColours"][0]) if p["numColours"] else None}
    if status:
        out.update(tyre=L.VISUAL_COMPOUNDS.get(status["visualTyreCompound"]), tyreAge=status["tyresAgeLaps"])
    if dmg:
        out["wearMax"] = max(dmg["tyresWear"])
    return out


def _board(b):
    """Practice/quali: P1 and the cars either side of you on best lap."""
    mine = calc.best_ms(b.st.history.get(b.me))
    rows = sorted(b.active(), key=b.pos)
    at = rows.index(b.me) if b.me in rows else 0
    keep = sorted({0, at - 1, at, at + 1} & set(range(len(rows))))
    out = []
    for i in keep:
        idx = rows[i]
        best = calc.best_ms(b.st.history.get(idx))
        out.append({**_who(b, idx), "position": b.pos(idx), "bestMs": best, "me": idx == b.me,
                    "gapToMe": (best - mine) / 1000 if best and mine and idx != b.me else None})
    return out


def _log_lines(b, n=8):
    name, log = b.name, b.st.incidents.log
    waves = {}  # lap -> stops that lap; a safety-car pit wave becomes one line
    for e in log:
        if e["kind"] == "pit":
            waves.setdefault(e["lap"], []).append(e)
    out, seen = [], set()
    for e in log:
        k = e["kind"]
        if k == "pit" and len(waves[e["lap"]]) > incidents.WAVE:
            if e["lap"] in seen:
                continue
            seen.add(e["lap"])
            out.append({"lap": e["lap"], "text": f"{len(waves[e['lap']])} cars pitted", "kind": k, "mine": False})
            continue
        text = _incident(e, name)
        if text:
            mine = k in ("limits", "warning", "contact", "passed", "lost") or e.get("idx") == b.me
            out.append({"lap": e["lap"], "text": text, "kind": k, "mine": mine})
    return out[-n:][::-1]


def _incident(e, name):
    k = e["kind"]
    if k == "limits":
        return f"Track limits warning at {e['dist']} m"
    if k == "warning":
        return f"Warning at {e['dist']} m"
    if k == "penalty":
        return f"{name(e['idx'])}: {incidents.penalty_text(e)}"
    if k == "out":
        return f"{name(e['idx'])} {incidents.retired_text(e)}"
    if k == "contact":
        return f"Contact with {name(e['idx'])} at {e['dist']} m"
    if k in ("passed", "lost"):
        return f"You passed {name(e['idx'])}" if k == "passed" else f"Passed by {name(e['idx'])}"
    if k == "served":
        return f"{name(e['idx'])} served a penalty"
    if k == "pit":
        return f"{name(e['idx'])} pitted from P{e['before']}" + (f", out P{e['after']}" if e["after"] else "")
    return None


def _time_loss(b):
    """The biggest zone you lose and gain against each comparison, plus sectors where there's a zone."""
    tr, me, length = b.st.traces, b.me, b.s["trackLength"]
    if b.race:
        mine = tr.clean(me)
        rivals = [(i, lbl) for i, lbl in ((b.neighbour(-1), "ahead"), (b.neighbour(+1), "behind")) if i is not None]
        pairs = [(i, lbl, mine, tr.clean(i)) for i, lbl in rivals]
    else:
        mine = [tr.best[me]] if me in tr.best else []
        fastest = min((i for i in b.active() if i != me and i in tr.best), key=lambda i: tr.best[i].total, default=None)
        pairs = [(fastest, "fastest", mine, [tr.best[fastest]])] if fastest is not None else []
    spans = trace.zones(mine[-1], length) if mine else []
    out = []
    for idx, label, a, theirs in pairs if spans else []:
        if not theirs:
            continue
        rows = trace.compare(a, theirs, spans)
        lose = max(rows, key=lambda r: r[2])
        gain = min(rows, key=lambda r: r[2])
        out.append({"name": b.name(idx), "label": label, "net": sum(r[2] for r in rows),
                    "lose": _span(lose) if lose[2] >= 0.05 else None, "gain": _span(gain) if gain[2] <= -0.05 else None})
    return out


def _span(r):
    a, bb, dt, low, top, later = r
    return {"from": a, "to": bb, "secs": abs(dt), "apex": low, "top": top, "later": later}
