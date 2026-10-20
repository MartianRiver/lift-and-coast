"""Stop plans worked out in code for the brief and the calls: the models are handed the sums, never
asked to do them (wrong calls came from models doing their own arithmetic).

Rain: stay out on this set and stop once for inters when it arrives, or stop now for fresh dries and
again for inters. The second costs one extra stop and buys back what new tyres are worth for the
laps until the rain. Safety car: what a stop costs while the field is slowed, and how long waiting
for one can pay.
"""
import math
from statistics import median

from . import calc, wear

RAIN_PCT = 50
SLICK_CALL = 1.0  # s/lap a slick must be worth over their inters before we say box: the out-lap on cold slicks on a
                  # damp track costs more than a normal one (the field's slick out-laps ran 135 s vs ~124 on inters)
LIFE_MARGIN = 1.15  # a set's life must cover the laps left by this much (the player's tyres can wear 1.6-2x the field's); 1.25 ruled out 12-lap mediums with 10 to go
WORN = 70        # % on the fastest-wearing tyre that's too far to stretch a set. A guess until the player's
                 # pace against wear says where the cliff is (a model read "≈73% at the flag" as "they'll make it")
SC_SHARE = {1: 0.5, 2: 0.65}  # share of the green-flag loss a stop costs under SC / VSC: a rule of thumb
                              # until a race gives us cars that stayed out (so far the whole field has stopped)


def rain(b):
    """(first forecast sample with rain likely, the lap it lands on at your pace or None if after the flag)."""
    samples = [w for w in b.s["weatherForecastSamples"][:b.s["numWeatherForecastSamples"]]
               if w["sessionType"] == b.s["sessionType"]][:6]
    w = next((w for w in samples if w["weather"] >= 3 or w["rainPercentage"] >= RAIN_PCT), None)
    if not w or not b.race or not b.ref_ms:
        return None
    lap = calc.lap_at(b.my, b.s, w["timeOffset"], b.ref_ms)
    return w, (lap if lap <= b.s["totalLaps"] else None)


def easing(b):
    """Raining now: (first forecast sample that isn't, its lap or None after the flag, rain again later?), or None."""
    samples = [w for w in b.s["weatherForecastSamples"][:b.s["numWeatherForecastSamples"]]
               if w["sessionType"] == b.s["sessionType"]][:6]
    wet = [w["weather"] >= 3 or w["rainPercentage"] >= RAIN_PCT for w in samples]
    if not samples or not wet[0] or all(wet) or not b.ref_ms:
        return None
    i = wet.index(False)
    lap = calc.lap_at(b.my, b.s, samples[i]["timeOffset"], b.ref_ms)
    return samples[i], (lap if lap <= b.s["totalLaps"] else None), any(wet[i:])


def slicks(b, measured=True):
    """On inters or wets: each slick compound's estimated gain over the fitted set and laps of life, the
    quickest one that reaches the flag with a margin, and what the cars already on slicks are really doing.
    Or None. The sets' gain has called the crossover right, though it undersold mediums over hards
    (0.9 s/lap estimated, ~2 s measured)."""
    status, sets = b.status(), b.st.tyre_sets.get(b.me)
    if not b.race or not status or status["visualTyreCompound"] in calc.DRY or not sets:
        return None
    left = b.s["totalLaps"] - b.my["currentLapNum"]  # laps after this one, if you box at the end of it
    best = {}
    for s in sets["tyreSetData"]:
        c = s["visualTyreCompound"]
        if s["available"] and c in calc.DRY and (c not in best or s["lapDeltaTime"] < best[c]["lapDeltaTime"]):
            best[c] = s
    options = sorted(((c, -s["lapDeltaTime"] / 1000, s["lifeSpan"]) for c, s in best.items()), key=lambda o: -o[1])
    pick = next((o for o in options if o[2] >= left * LIFE_MARGIN), None)
    seen = measured and calc.slicks_vs_wets(b.st.laps, b.active())
    return {"options": options, "pick": pick, "left": left, "seen": seen} if options else None


def slick_call(b):
    """(compound, s/lap, laps after this one, cars already on slicks) when it's time to say box for slicks."""
    p = slicks(b, measured=False)
    if not p or not p["pick"] or p["pick"][1] < SLICK_CALL or b.my["pitStatus"]:
        return None
    status = b.st.latest.get(7)
    on = sum(status["carStatusData"][i]["visualTyreCompound"] in calc.DRY for i in b.active() if i != b.me)
    return p["pick"][0], p["pick"][1], p["left"], on


def dry_stop(b):
    """On slicks with a stop still to make (a second compound owed, or the fitted set won't reach the flag
    under WORN): each set you could fit this lap, best of each compound, with its pace against the fitted
    set and the wear it reaches by the flag; the quickest that stays under WORN. Or None.

    The wear is your fastest-wearing tyre's rate this stint, scaled by each compound's life against the
    fitted one's. The sets' own lifeSpan runs on well past WORN at the player's wear; it's the fallback."""
    status, sets, hist = b.status(), b.st.tyre_sets.get(b.me), b.st.history.get(b.me)
    if not b.race or not status or status["visualTyreCompound"] not in calc.DRY or not sets or b.my["pitStatus"]:
        return None
    left = b.s["totalLaps"] - b.my["currentLapNum"]
    run = {t["tyreVisualCompound"] for t in hist["tyreStintsHistoryData"][:hist["numTyreStints"]]} if hist else set()
    run.add(status["visualTyreCompound"])
    owed = not b.sprint() and len(run) < 2  # a stint on inters or wets counts too
    flag = wear_at(b, b.s["totalLaps"])
    if left < 1 or not (owed or flag and flag[1] > WORN):
        return None
    fitted = sets["tyreSetData"][sets["fittedIdx"]]
    rate = flag and stint_rates(b)[flag[0]]
    best = {}
    for i, s in enumerate(sets["tyreSetData"]):
        c = s["visualTyreCompound"]
        if (s["available"] and i != sets["fittedIdx"] and c in calc.DRY and not (owed and c in run)
                and (c not in best or s["lapDeltaTime"] < best[c]["lapDeltaTime"])):
            best[c] = s
    options = []
    for c, s in best.items():
        at = s["wear"] + rate * fitted["usableLife"] / s["usableLife"] * left if rate and s["usableLife"] and fitted["usableLife"] else None
        options.append({"compound": c, "wear": s["wear"], "gain": -s["lapDeltaTime"] / 1000, "at_flag": at,
                        "lasts": at <= WORN if at is not None else s["lifeSpan"] >= left * LIFE_MARGIN})
    options.sort(key=lambda o: -o["gain"])
    pick = next((o for o in options if o["lasts"]), None)
    return {"options": options, "pick": pick, "left": left, "owed": owed, "run": run,
            "wheel": flag and flag[0]} if options else None


def stint_rates(b):
    """Your %/lap per wheel on the set you're on now (None until it has two laps)."""
    status = b.status()
    fitted = status and (status["visualTyreCompound"], status["tyresAgeLaps"])
    return calc.wear_rates(b.st.laps.cars.get(b.me, []), stops=b.my["numPitStops"], fitted=fitted)


def fresh_gain(b):
    """(s/lap new tyres are worth, where that comes from): measured from this race's stops onto the
    same kind of tyre as yours (dry or wet) once there are two, else the tyre sets' own estimate."""
    status = b.status()
    dry = bool(status) and status["visualTyreCompound"] in calc.DRY
    same = [g for old, new, g in calc.fresh_gains(b.st.laps, b.st.history) if (old in calc.DRY) == (new in calc.DRY) == dry]
    if len(same) >= 2:
        return median(same), f"measured from {len(same)} stops"
    gain = calc.fresh_gain(b.st.tyre_sets.get(b.me))
    return (gain, "best fresh set's estimate") if gain and gain > 0 else None


def wear_at(b, lap):
    """(wheel index, % on your fastest-wearing tyre by `lap`) at this stint's rate, or None."""
    dmg = b.damage()
    rates = stint_rates(b)
    if not dmg or not rates:
        return None
    w = max(range(4), key=lambda i: rates[i])
    return w, dmg["tyresWear"][w] + rates[w] * (lap - b.my["currentLapNum"])


def worn_in(b):
    """(wheel, laps until your fastest-wearing tyre reaches WORN at this stint's rate) or None. Ours, not
    the set's lifeSpan: that has said "~17 laps left" with the RL heading for 75% in 8."""
    dmg = b.damage()
    rates = stint_rates(b)
    if not dmg or not rates:
        return None
    w = max(range(4), key=lambda i: rates[i])
    return w, max(0, int((WORN - dmg["tyresWear"][w]) / rates[w])) if rates[w] > 0 else None


def target(b, lap):
    """Your fastest-wearing tyre at the end of `lap` (the planned stop, or the flag) at this stint's rate.
    Past WORN: what saving it takes, as the extra over the field in the sectors it comes from, and how
    many laps of matching the field there get it to `lap`. None without two laps of wear."""
    dmg, rates = b.damage(), stint_rates(b)
    if not dmg or not rates:
        return None
    i = max(range(4), key=lambda k: rates[k])
    now, rate, laps = dmg["tyresWear"][i], rates[i], lap - b.my["currentLapNum"] + 1
    if rate <= 0 or laps <= 0:
        return None
    t = {"wheel": i, "lap": lap, "now": now, "rate": rate, "at": now + rate * laps, "laps": laps,
         "worn": b.my["currentLapNum"] + max(0, int((WORN - now) / rate)), "sectors": [], "spread": False,
         "save": None, "manage": None}
    if t["at"] > WORN:
        t["sectors"], t["spread"], t["save"] = _saving(b, i)
        if t["save"]:
            n = math.ceil((t["at"] - WORN) / t["save"])
            t["manage"] = n if n <= laps else None
    return t


def _saving(b, i):
    """(sectors, spread round the lap?, %/lap saved) if wheel i matched the field wherever it wears more."""
    w, track_len, spans = b.st.wear, b.s["trackLength"], wear.sectors(b.s)
    mine, field = w.recent(b.me, track_len), wear.field_rates(w, b.me, b.active(), track_len)
    if len(mine) < 2 or not field or not field[i] or not spans:
        return [], False, None
    rows = wear.by_sector(w, b.me, b.active(), spans, track_len, i)
    hot = wear.standout(rows, wear.rates(mine)[i] / field[i])
    over = hot or [r for r in rows if r[1] > r[2]]
    save = sum(you - them for _, you, them in over)
    return sorted(n for n, _, _ in over), not hot, (save if save >= 0.05 else None)


def target_text(t, what):
    """One line for the brief: does it make `what` (the planned stop, the flag), and if not, what saves it."""
    tyre, lap = wear.WHEELS[t["wheel"]], t["lap"]
    head = f"{tyre} {t['now']:.0f}% now, {t['rate']:.1f}%/lap → ≈{t['at']:.0f}% by the end of L{lap} ({what})"
    if t["at"] <= WORN:
        return head + f": it makes it, ≈{(WORN - t['at']) / t['rate']:.0f} laps spare before {WORN}%"
    head += f", past {WORN}% (worn) from L{t['worn']}"
    where = "all round the lap" if t["spread"] else "in " + " and ".join(f"S{n}" for n in t["sectors"])
    if t["manage"]:
        return head + (f". Matching the field's wear {where} saves {t['save']:.1f}%/lap: about {t['manage']} "
                       f"lap{'s' * (t['manage'] != 1)} of that gets it to L{lap}")
    if t["save"]:
        return head + (f". Even matching the field {where} every lap saves only {t['save']:.1f}%/lap: "
                       f"not enough, so the stop has to come by L{t['worn']}")
    return head + f". It wears no faster than the field anywhere: the stop comes by L{t['worn']}, or slower laps all round"


def rain_plan(b):
    """Stay out for the rain vs stop now and again, or None when there's no choice to make."""
    r, status = rain(b), b.status()
    if not r or not r[1] or not status or status["visualTyreCompound"] not in calc.DRY or b.s["safetyCarStatus"]:
        return None
    sample, lap = r
    laps = lap - b.my["currentLapNum"] - 1  # on fresh dries between the out-lap and the rain
    loss, gain, worn = b.loss(), fresh_gain(b), wear_at(b, lap)
    if laps < 1 or not loss or not gain:
        return None
    back = gain[0] * laps
    return {"lap": lap, "pct": sample["rainPercentage"], "loss": loss[0], "gain": gain[0], "laps": laps,
            "back": back, "saves": loss[0] - back, "worn": worn}


def sc_stop(b, kind=None):
    """(seconds a stop costs under the SC (1) / VSC (2) that's out now, how we know) or None. The SCAR
    event comes a few seconds before the session packet's safetyCarStatus flips: pass its type then."""
    kind, loss = kind or b.s["safetyCarStatus"], b.loss()
    if kind not in SC_SHARE or not loss:
        return None
    return loss[0] * SC_SHARE[kind], f"about {SC_SHARE[kind]:.0%} of the green-flag loss: a rule of thumb, not measured here yet"


def sc_wait(b):
    """Staying out in case of a safety car: (s/lap it costs against new tyres, s an SC stop would save,
    laps it pays off within). No odds of an SC: the game doesn't send any and three races can't say."""
    status, loss, gain = b.status(), b.loss(), fresh_gain(b)
    if not status or not loss or not gain or b.s["safetyCarStatus"]:
        return None
    saved = loss[0] * (1 - SC_SHARE[1])
    return gain[0], saved, saved / gain[0]
