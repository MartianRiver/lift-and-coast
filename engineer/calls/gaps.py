"""Calls about the cars either side: within a second, closing or being caught, the last lap."""
import math

from .. import calc
from .common import NORMAL, LOW, call, nice, stopping

CLOSING = 0.25   # s/lap worth a call
IN_RANGE = 1.0   # DRS distance, s
REARM = 2.5      # s apart before the same car is worth another within-a-second call
JUST_PASSED = 30  # s after a pass either way: of course he's within a second
FLAG_CLOSING, FLAG_LAPS = 0.4, 8  # a closing car is worth a flag projection this near the end


def in_range(b, mem):
    """Within a second of the car ahead or behind, from the game's live gap, which moves every few
    hundred metres. The gap at the line is a lap late for this: the move has often happened by then."""
    if b.s["safetyCarStatus"] or b.my["currentLapNum"] < 2 or stopping(b):
        return []
    said, out = mem.setdefault("range", set()), []  # (car, -1 ahead / +1 behind): once each side
    swapped = {e["idx"] for e in b.st.incidents.log if e["kind"] in ("passed", "lost") and b.now - e["t"] < JUST_PASSED}
    for step in (-1, +1):
        idx = _live_neighbour(b, step)
        gap = idx is not None and _live_gap(b, idx, step)
        if not gap:
            continue
        if gap > REARM:
            said.discard((idx, step))
        elif gap <= IN_RANGE and (idx, step) not in said and idx not in swapped:
            said.add((idx, step))
            out.append(call(("range", idx, round(b.now, 1)), "gap", NORMAL,  # a key per arming: twice a lap is fine
                            lambda b, i=idx, s=step: _range_words(b, i, s), ttl=20,
                            unsaid=lambda k=(idx, step): said.discard(k)))  # not said: the next time counts
    return out


def _live_neighbour(b, step):
    pos = b.my["carPosition"] + step
    return next((i for i in b.active() if b.lap_pkt["lapData"][i]["carPosition"] == pos), None)


def _live_gap(b, idx, step):
    """Seconds between me and the car `step` places away, from both cars' live time to the leader;
    None in the pit lane. Not the game's gap to the car in front: after a pass it keeps the old car's
    gap until the next timing point, while the positions have already changed."""
    cars = b.lap_pkt["lapData"]
    theirs, mine = calc.to_leader(cars, idx), calc.to_leader(cars, b.me)
    gap = theirs is not None and mine is not None and (theirs - mine) * step
    return gap if gap and gap > 0 else None


def _range_words(b, idx, step):
    if _live_neighbour(b, step) != idx or (_live_gap(b, idx, step) or 99) > IN_RANGE + 0.2:
        return None  # passed, or dropped back, while the call waited for a straight
    who = nice(b.name(idx))
    if step < 0:
        return f"You're within a second of {who}."
    return f"{who} is within a second, in DRS range." if b.st.drs else f"{who} is within a second."


def at_the_line(b, mem, lap):
    """Once a lap: a car either side closing in or being caught, the lap-2 position, the last lap."""
    out, left = [], b.s["totalLaps"] - lap + 1
    if lap == b.s["totalLaps"]:
        out.append(call(("last",), "last", NORMAL, _last_lap, ttl=60))
    elif lap == 2:
        out.append(call(("p1",), "lap", LOW, _first_lap, ttl=30))
    said = mem.setdefault("rival", {})
    for step in (+1, -1):
        idx = b.neighbour(step)
        text = idx is not None and rival(b, idx, left)
        if not text or lap - said.get((idx, text[0]), -9) < 3:
            continue
        said[(idx, text[0])] = lap
        out.append(call(("rival", idx, text[0], lap), "gap", NORMAL, lambda b, i=idx, s=step: _rival_words(b, i, left, s), ttl=45))
    return out


def _gap(b, idx):
    g = b.gaps.get(idx)
    return g and abs(g["gap"])


def rival(b, idx, left):
    """(kind, words) if this neighbour deserves a call now, else None."""
    g = b.gaps.get(idx)
    if not g or g["last"] is None:
        return None
    gap, behind = abs(g["gap"]), g["gap"] > 0
    sign = -1 if behind else 1
    closing = sign * g["last"]
    if g["trendLaps"] and g["trendLaps"] > 1:
        closing = min(closing, sign * g["trend"])  # one quick lap isn't a trend
    elif closing >= CLOSING:
        closing = 0.0
    if gap <= IN_RANGE or closing < CLOSING:
        return None  # within a second is in_range's job, from the live gap
    who = nice(b.name(idx))
    eta = math.ceil((gap - IN_RANGE) / closing)
    if eta <= left:
        kind, tail = "catch", "Within a second next lap." if eta == 1 else f"Within a second in about {eta} laps."
    elif closing >= FLAG_CLOSING and left <= FLAG_LAPS:
        kind, tail = "flag", f"About {gap - closing * left:.1f} at the flag."
    else:
        return None
    if behind:
        return kind, f"{who} is closing, {closing:.1f} a lap and {gap:.1f} back. {tail}"
    return kind, f"You're taking {closing:.1f} a lap out of {who}, {gap:.1f} ahead. {tail}"


def _rival_words(b, idx, left, step):
    if b.neighbour(step) != idx:
        return None  # a pass since the line
    r = rival(b, idx, left)
    return r and r[1]


def _last_lap(b):
    for step, word in ((+1, "behind"), (-1, "ahead")):
        idx = b.neighbour(step)
        if idx is not None and _gap(b, idx) is not None:
            return f"Last lap. {nice(b.name(idx))} is {_gap(b, idx):.1f} {word}. Bring it home."
    return "Last lap. Bring it home."


def _first_lap(b):
    behind = b.neighbour(+1)
    gap = behind is not None and _gap(b, behind)
    return f"P{b.pos(b.me)}." + (f" {nice(b.name(behind))} {gap:.1f} behind." if gap else "")
