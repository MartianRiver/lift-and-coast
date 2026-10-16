"""When the pit wall should think again: something changed that could change the plan.

`scan(race, mem, box)` returns new reasons (each once per session); the wall gathers them into
runs. A reason can carry the code's own call as a fallback, said if the team can't answer.
"""
from .. import driver, strategy
from ..calls import plans
from ..calls.common import NORMAL, call, corner, nice
from ..fmt import hurt
from ..lookups import VISUAL_COMPOUNDS
from ..spec import MAX_CARS

SETTLE = 20.0   # s after first seeing a session that only baselines (a resumed save loads in stages)
NEAR = 3        # places either side whose stops matter
TYRE_LAPS = 5   # laps before the fastest-wearing tyre is worn
DAMAGE = 5      # % more on any bodywork part
RAIN_MOVE = 3   # laps the forecast rain lap has to move


def reason(key, text, urgent=False, fallback=(), question=None):
    return {"key": key, "text": text, "urgent": urgent, "fallback": list(fallback), "question": question}


def scan(b, mem, box=None):
    """box: the lap the team planned this stint's stop for, or None."""
    if not b.race or b.me >= MAX_CARS:
        return []
    now = b.now
    first = now - mem.setdefault("t0", now) < SETTLE
    out = (_safety_car(b, mem) + _weather(b, mem) + _slicks(b) + _stops(b, mem) + _mine(b, mem)
           + _tyres(b) + _target(b, box) + _damage(b, mem) + _late(b, box))
    said = mem.setdefault("said", set())
    fresh = [r for r in out if r["key"] not in said]
    said.update(r["key"] for r in fresh)
    return [] if first else fresh


def _safety_car(b, mem):
    seen, out = mem.setdefault("events", set()), []
    for ev in b.st.events:
        k = (ev["sessionTime"], ev["code"])
        if ev["code"] != "SCAR" or k in seen:
            continue
        seen.add(k)
        d = ev["details"]
        if d["eventType"] == 0:
            vsc = d["safetyCarType"] == 2
            n = b.s["numVirtualSafetyCarPeriods" if vsc else "numSafetyCarPeriods"]
            out.append(reason(("sc", d["safetyCarType"], n), "VSC deployed" if vsc else "safety car deployed", urgent=True))
    return out


def _weather(b, mem):
    out = []
    weather, was = b.s["weather"], mem.get("weather", b.s["weather"])
    mem["weather"] = weather
    if weather >= 3 > was:
        mem["wet"] = mem.get("wet", 0) + 1
        out.append(reason(("raining", mem["wet"]), "it's started to rain", urgent=True))
    r = strategy.rain(b)
    lap, last = (r[1] if r and r[0]["timeOffset"] else None), mem.get("rain")
    if lap and (last is None or abs(lap - last) >= RAIN_MOVE):
        mem["rain"] = lap
        out.append(reason(("rain", lap), f"rain now forecast to land around lap {lap} ({r[0]['rainPercentage']}%)",
                          fallback=plans.rain(b, {})))
    elif not lap and last:
        mem["rain"] = None
        out.append(reason(("dry", last, b.my["currentLapNum"]), f"the rain forecast for lap {last} has gone"))
    return out


def _slicks(b):
    got = strategy.slick_call(b)
    if not got:
        return []
    compound, gain, left, on = got
    return [reason(("slicks", b.my["numPitStops"]),
                   driver.words(f"slicks are quicker: {VISUAL_COMPOUNDS[compound].lower()}s about {gain:.1f}s/lap over his inters and "
                                f"they last the {left} laps left; {on} cars on slicks already"), urgent=True, fallback=plans.slicks(b))]


def _stops(b, mem):
    seen, out, mine = mem.setdefault("log", set()), [], b.pos(b.me)
    for e in b.st.incidents.log:
        k = (e["kind"], e.get("idx"), e["lap"])
        if e["kind"] != "pit" or k in seen or e["idx"] == b.me:
            continue
        seen.add(k)
        was = e.get("before") or b.pos(e["idx"])
        if abs(was - mine) <= NEAR and not b.s["safetyCarStatus"]:  # under the SC the SC reason covers it
            side = "ahead" if was < mine else "behind"
            out.append(reason(("pit", e["idx"], e["lap"]), f"{nice(b.name(e['idx']))} (P{was}, {side}) has stopped"))
    return out


def _mine(b, mem):
    n, was = b.my["numPitStops"], mem.get("stops", b.my["numPitStops"])
    mem["stops"] = n
    if n > was:
        return [reason(("stopped", n), driver.words("River has just stopped: confirm the plan from here"))]
    return []


def _tyres(b):
    w = strategy.worn_in(b)
    if not w or w[1] is None or w[1] > TYRE_LAPS or w[1] >= b.laps_left():
        return []
    return [reason(("worn", b.my["numPitStops"]), f"{corner(w[0]).lower()} reaches {strategy.WORN}% (worn) in ≈{w[1]} laps")]


def tyre_target(b, box):
    """(strategy.target, what it has to reach): the team's planned stop, else the flag once they've stopped."""
    if box and box >= b.my["currentLapNum"]:
        lap, what = box, "the planned stop"
    elif b.my["numPitStops"] and b.laps_left() >= 0:
        lap, what = b.s["totalLaps"], "the flag"
    else:
        return None
    t = strategy.target(b, lap)
    return t and (t, what)


def _target(b, box):
    got = tyre_target(b, box)
    if not got or got[0]["at"] <= strategy.WORN or b.s["safetyCarStatus"]:
        return []
    t, what = got
    tyre, lap, n = corner(t["wheel"]), t["lap"], t["manage"]
    where = "all round the lap" if t["spread"] else "in sector " + " and ".join(str(s) for s in t["sectors"])
    said = (f"{tyre} won't make lap {lap} at this rate. Save it {where} for about {n} laps." if n
            else f"{tyre} won't make lap {lap} at this rate, it's worn from lap {t['worn']}.")
    return [reason(("target", b.my["numPitStops"], lap), driver.words(f"his tyres won't reach {what}: ") + strategy.target_text(t, what),
                   fallback=[call(("target", b.my["numPitStops"], lap), "tyres", NORMAL, lambda _b: said, ttl=90)])]


def _damage(b, mem):
    dmg = b.damage()
    if not dmg:
        return []
    now, before = hurt(dmg), mem.get("hurt", {})
    mem["hurt"] = now
    if not any(v >= before.get(k, 0) + DAMAGE for k, v in now.items()):
        return []
    parts = ", ".join(f"{k} {v}%" for k, v in now.items())
    return [reason(("damage", tuple(sorted(now.items()))), f"new damage: {parts}", urgent=True)]


def _late(b, box):
    lap = b.my["currentLapNum"]
    if not box or lap <= box + 1 or b.my["pitStatus"]:
        return []
    return [reason(("late", box, b.my["numPitStops"]), f"past the planned stop (L{box}) and still out on lap {lap}")]
