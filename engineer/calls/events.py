"""Calls about things that just happened: track limits, penalties, contact, passes, stops and
retirements nearby, the safety car, rain starting, new damage and the flag."""
from .. import incidents, strategy
from ..fmt import hurt
from .common import LOW, NORMAL, URGENT, call, nice, stopping

COLD = 75        # inner tyre temp (°C) below which a restart needs care
SC_STOP_AGE = 5  # laps on the set before a stop under the SC is worth mentioning


def from_log(b, mem):
    seen, out = mem.setdefault("log", set()), []
    me, name = b.me, lambda i: nice(b.name(i))
    for e in b.st.incidents.log:
        k = (e["kind"], e["t"], e.get("idx"))
        if k in seen:
            continue
        seen.add(k)
        kind, idx = e["kind"], e.get("idx")
        k = (kind, idx, e["lap"])  # after a flashback the game replays the same moment: same call, new time
        if kind == "limits":
            out.append(call(("limits", e["lap"], b.my["cornerCuttingWarnings"]), "limits", NORMAL, lambda b, e=e: _limits(b, e)))
        elif kind == "penalty" and idx == me:
            out.append(call(k, "penalty", URGENT, lambda b, e=e: f"You've got a {incidents.penalty_text(e)}.", ttl=60))
        elif kind == "contact":
            # chatty only: the driver knows already, and the damage call says if it cost anything
            out.append(call(k, "contact", LOW, lambda b, i=idx: f"Contact with {name(i)}.", ttl=30))
        elif kind in ("passed", "lost") and stopping(b):
            continue  # places change around our own stop
        elif kind == "passed":
            out.append(call(k, "pass", LOW, lambda b, i=idx: f"Through on {name(i)}, you're P{b.pos(b.me)}.", ttl=12))
        elif kind == "lost":
            out.append(call(k, "pass", LOW, lambda b, i=idx: f"{name(i)} is through, you're P{b.pos(b.me)}.", ttl=12))
        elif kind == "out" and abs(b.pos(idx) - b.pos(me)) <= 3:
            out.append(call(k, "out", LOW, lambda b, i=idx: f"{name(i)} is out.", ttl=20))
        elif kind == "pit" and not b.s["safetyCarStatus"] and abs(b.pos(idx) - b.pos(me)) == 1:
            out.append(call(k, "pit", LOW, lambda b, i=idx: f"{name(i)} is in the pits.", ttl=20))
    return out


def _limits(b, e):
    n = b.my["cornerCuttingWarnings"]
    if n >= incidents.WARNINGS_FOR_PENALTY or not n:
        return None  # the penalty call covers it / a flashback took it away
    if n == incidents.WARNINGS_FOR_PENALTY - 1:
        return f"That's {n} track-limits warnings, the last at {e['dist']} m. One more is a penalty."
    return f"Track limits warning, that's {n}."


def safety_car(b, mem):
    seen, out = mem.setdefault("events", set()), []
    for ev in b.st.events:
        k = (ev["sessionTime"], ev["code"])
        if k in seen:
            continue
        seen.add(k)
        if ev["code"] == "RDFL":
            out.append(call(("red", ev["sessionTime"]), "sc", URGENT, lambda b: "Red flag, red flag.", ttl=20))
        elif ev["code"] == "SCAR" and not b.red_flag():  # the game runs the SC phases through a red flag too
            out += _phase(b, ev["details"])
    return out


def _phase(b, d):
    kind, phase = d["safetyCarType"], d["eventType"]
    vsc = kind == 2
    n = b.s["numVirtualSafetyCarPeriods" if vsc else "numSafetyCarPeriods"]
    if phase == 0:
        return [call(("sc", kind, n), "sc", URGENT, lambda b: None if b.red_flag() else ("Virtual safety car." if vsc else "Safety car, safety car.") + _sc_stop(b, kind), ttl=20)]
    if phase == 3 and not vsc:
        return [call(("green", n), "sc", URGENT, lambda b: "Green, green.", ttl=6)]
    if phase in (1, 2):
        return [call(("sc-in", kind, n), "sc", URGENT, lambda b: "VSC ending." if vsc else _restart(b), ttl=30)]
    return []


def _sc_stop(b, kind):
    """What a stop costs now, when one is worth thinking about: tyres not fresh, laps left to use them."""
    status, cost, loss = b.status(), strategy.sc_stop(b, kind), b.loss()
    if not status or not cost or status["tyresAgeLaps"] < SC_STOP_AGE or b.laps_left() < 3 or b.my["pitStatus"]:
        return ""
    return f" A stop now costs roughly {cost[0]:.0f} seconds instead of {loss[0]:.0f}."


def _restart(b):
    parts = ["Safety car in this lap."]
    battery, tel = b.battery(), b.telemetry()
    if battery is not None:
        parts.append(f"Battery {battery:.0%}.")
    if tel and min(tel["tyresInnerTemperature"]) < COLD:
        parts.append("Tyres are cold, careful on the restart.")
    return " ".join(parts)


def conditions(b, mem):
    out = []
    # our own finish, not CHQF: that fires as the leader gets the flag, a few hundred metres early
    if b.my["resultStatus"] == 3:
        out.append(call(("flag",), "flag", URGENT, lambda b: f"Chequered flag. P{b.pos(b.me)}.", ttl=120))
    weather = b.s["weather"]
    was = mem.get("weather", weather)
    mem["weather"] = weather
    if was >= 3 > weather:
        mem["dry_spells"] = mem.get("dry_spells", 0) + 1  # the next rain is news again
    if weather >= 3 > was:
        out.append(call(("rain", mem.get("dry_spells", 0)), "weather", URGENT, lambda b: "It's started to rain.", ttl=30))
    dmg = b.damage()
    if dmg:
        now, before = hurt(dmg), mem.get("hurt", {})
        mem["hurt"] = now
        if any(v >= before.get(k, 0) + 2 for k, v in now.items()):  # a flashback lowers it and re-arms
            out.append(call(("damage", tuple(sorted(now.items()))), "damage", NORMAL, _damage, ttl=40))
    return out


def _damage(b):
    dmg = b.damage()
    parts = hurt(dmg) if dmg else {}
    return "Damage: " + ", ".join(f"{k} {v}%" for k, v in parts.items()) + "." if parts else None
