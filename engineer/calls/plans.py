"""Calls that change the plan: box for slicks, stay out for the rain, save fuel."""
import math

from .. import strategy
from ..lookups import VISUAL_COMPOUNDS
from .common import NORMAL, URGENT, call, corner

RAIN_SAVES, RAIN_WITHIN = 5, 10  # s a stay-out-for-the-rain plan must save, laps ahead the rain must be
FUEL_SHORT = -0.5


def slicks(b):
    """On inters with slicks now clearly quicker and one that lasts: box for it, once a stint."""
    if not b.race or b.s["safetyCarStatus"] or not strategy.slick_call(b):
        return []
    return [call(("slicks", b.my["numPitStops"]), "strategy", URGENT, _slick_words, ttl=90)]


def _slick_words(b):
    got = strategy.slick_call(b)
    if not got:
        return None
    compound, gain, left, on = got
    name = VISUAL_COMPOUNDS[compound].lower() + "s"
    gone = f" {on} cars have already gone." if on >= 3 else ""
    return f"Slicks are quicker now: {name} about {gain:.1f} a lap on these and they'll do the {left} laps. Box for {name}.{gone}"


def rain(b, mem):
    """Rain coming and staying out saves a stop: said once, and again if the forecast moves it 3+ laps."""
    p = strategy.rain_plan(b)
    if not _rain_worth(b, p):
        return []
    last = mem.get("rainplan")
    if last is not None and abs(p["lap"] - last) < 3:
        return []
    mem["rainplan"] = p["lap"]
    return [call(("rainplan", p["lap"]), "strategy", NORMAL, _rain_words, ttl=60)]


def _rain_worth(b, p):
    return (p and p["saves"] >= RAIN_SAVES and p["lap"] - b.my["currentLapNum"] <= RAIN_WITHIN
            and not (p["worn"] and p["worn"][1] > strategy.WORN))


def _rain_words(b):
    p = strategy.rain_plan(b)
    if not _rain_worth(b, p):
        return None
    text = f"Rain's due around lap {p['lap']}. Staying out to stop once for inters saves about {p['saves']:.0f} seconds."
    if p["worn"]:
        w, pct = p["worn"]
        text += f" {corner(w)} gets there at {pct:.0f}%."
    return text


def fuel(b):
    status = b.status()
    if not status or status["fuelRemainingLaps"] > FUEL_SHORT:
        return []
    return [call(("fuel", math.floor(status["fuelRemainingLaps"])), "fuel", NORMAL, _fuel_text, ttl=60)]


def _fuel_text(b):
    status = b.status()
    d = status["fuelRemainingLaps"] if status else 0
    return f"Fuel's {abs(d):.1f} laps short of target. Start saving." if d <= FUEL_SHORT else None
