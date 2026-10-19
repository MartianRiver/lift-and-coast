"""The quick brief: one press of the second button, no talking, no model. What a glance at the
dashboard would tell you, said in a few seconds: gaps and tyres in a race, where you stand in
qualifying, last lap against best in practice."""
from . import calc
from .calls.common import corner, nice
from .fmt import laptime
from .race import Race, ready
from .spec import MAX_CARS

STEADY = 0.1         # s/lap a gap has to move by to be worth a word
QUALI = range(5, 15)  # session types: every kind of qualifying and shootout


def brief(st):
    """The quick brief as a call row, or None when there's nothing to go on (menus, spectating, no lap yet)."""
    with st.lock:
        if not ready(st):
            return None
        b = Race(st)
        if b.me >= MAX_CARS:
            return None
        parts = _race(b) if b.race else _lap(b)
        if not parts:
            return None
        return {"topic": "quick", "text": " ".join(parts), "lap": b.my["currentLapNum"], "dist": round(b.my["lapDistance"]),
                "sessionTime": round(b.now, 1)}


def _race(b):
    if b.red_flag():
        return ["Red flag."]
    out = [f"P{b.pos(b.me)}."]
    if b.s["safetyCarStatus"]:
        out.append("Safety car." if b.s["safetyCarStatus"] == 1 else "Virtual safety car.")
    for step, where in ((-1, "ahead"), (+1, "behind")):
        idx = b.neighbour(step)
        g = idx is not None and b.gaps.get(idx)
        if g:
            out.append(f"{nice(b.name(idx))} {where}, {abs(g['gap']):.1f}{_moving(g)}.")
    return out + _tyre(b)


def _moving(g):
    if g["last"] is None or abs(g["last"]) < STEADY:
        return ""
    shrinking = (g["last"] < 0) == (g["gap"] > 0)
    if g["gap"] > 0:
        return f", closing {abs(g['last']):.1f} a lap" if shrinking else ", dropping back"
    return f", you're catching {abs(g['last']):.1f} a lap" if shrinking else ", pulling away"


def _tyre(b):
    dmg = b.damage()
    if not dmg:
        return []
    wear = dmg["tyresWear"]
    i = max(range(4), key=lambda i: wear[i])
    return [f"{corner(i)} {wear[i]:.0f}%."]


def _lap(b):
    hist = b.st.history.get(b.me)
    best, last = calc.best_ms(hist), b.my["lastLapTimeInMS"]
    out = []
    if b.s["sessionType"] in QUALI:
        out += _standing(b, best)
    if last:
        off = best and (last - best) / 1000
        out.append(f"Last lap {laptime(last)}" + (", your best." if off == 0 else f", {off:.3f} off your best." if off and off > 0 else "."))
    elif not best and not out:
        return []
    return out + ([] if b.s["sessionType"] in QUALI else _tyre(b))


def _standing(b, best):
    pos = b.pos(b.me)
    if not best:
        return [f"P{pos}, no time yet."]
    other = next((i for i in b.active() if b.pos(i) == (2 if pos == 1 else 1)), None)
    theirs = other is not None and calc.best_ms(b.st.history.get(other))
    margin = theirs and (theirs - best if pos == 1 else best - theirs) / 1000
    if not margin or margin < 0:  # no time to compare, or the game's order isn't by these laps
        return [f"P{pos}."]
    return [f"P{pos}, {margin:.3f} {'clear of' if pos == 1 else 'off'} {nice(b.name(other))}."]
