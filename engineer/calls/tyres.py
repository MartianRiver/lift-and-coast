"""Calls about my tyres: nearly worn out, one corner well ahead of the others, wearing faster than the field,
rear grip gone in a sector."""
from .. import grip, strategy, wear
from .common import NORMAL, call, corner

LIFE_CALL = 3               # laps until the fastest-wearing tyre is worn out (strategy.WORN)
UNEVEN = 8                  # points one corner is worn beyond the mean of the others
OVERWEAR = (1.4, 1.8, 2.2)  # times the field's wear rate: each step is said once a stint
OVERWEAR_MIN = 0.5          # %/lap beyond the field, so a tiny rate early on doesn't count
FLAG_WEAR = (60, 75)        # % projected at the flag: said again as it crosses each


def at_the_line(b, left, box=None):
    """box: the lap the team plans to stop at the end of this stint, if it has one."""
    out, stops = [], b.my["numPitStops"]
    worn = strategy.worn_in(b)
    if worn and worn[1] is not None and worn[1] <= LIFE_CALL and worn[1] < left:
        out.append(call(("life", stops), "tyres", NORMAL, _life, ttl=60))
    dmg = b.damage()
    if dmg and max(dmg["tyresWear"]) >= 30:
        w = dmg["tyresWear"]
        worst = max(range(4), key=lambda i: w[i])
        if w[worst] - (sum(w) - w[worst]) / 3 >= UNEVEN:
            out.append(call(("limit", stops, worst), "tyres", NORMAL, lambda b, i=worst: _worn(b, i), ttl=60))
    level = _overwear_level(b, box)
    if level and left >= 3:
        out.append(call(("overwear", stops, level), "tyres", NORMAL, lambda b, box=box: _overwear(b, box), ttl=60))
    if left >= 3:
        for n in _grip_gone(b):
            out.append(call(("grip", stops, n), "tyres", NORMAL, lambda b, n=n: _grip(b, n), ttl=60))
    return out


def _grip_rows(b):
    spans = wear.sectors(b.s)
    return grip.by_sector(b.st.grip, spans, b.s["trackLength"]) if spans else []


def _grip_gone(b):
    return [r[0] for r in grip.losing(_grip_rows(b))]


def _grip(b, n):
    rows = _grip_rows(b)
    slide, spin = {r[0] for r in grip.sliding(rows)}, {r[0] for r in grip.spinning(rows)}
    if n not in slide | spin:
        return None
    what = "sliding and spinning up more" if n in slide and n in spin else "sliding more" if n in slide else "spinning up more"
    return f"Rears are {what} in sector {n} than at the start of the set. Look after them through there."


def _overwear_numbers(b):
    """(wheel, my %/lap, field %/lap, sectors it concentrates in or None) when I'm wearing a tyre well beyond the field."""
    track_len, w = b.s["trackLength"], b.st.wear
    mine_laps, field = w.recent(b.me, track_len), wear.field_rates(w, b.me, b.active(), track_len)
    if len(mine_laps) < 2 or not field:
        return None
    mine = wear.rates(mine_laps)
    i, ratio = wear.worst(mine, field)
    if ratio < OVERWEAR[0] or mine[i] - field[i] < OVERWEAR_MIN:
        return None
    spans = wear.sectors(b.s)
    if not spans:
        return i, mine[i], field[i], None
    hot = wear.standout(wear.by_sector(w, b.me, b.active(), spans, track_len, i), ratio)[:2]
    return i, mine[i], field[i], [n for n, _, _ in hot]


def _overwear_level(b, box=None):
    """Steps of how far over the field and how bad the flag looks; a new step is a new call."""
    got = _overwear_numbers(b)
    if not got:
        return None
    flag = _at_flag(b, got[0], got[1], box)
    return sum(got[1] >= t * got[2] for t in OVERWEAR), sum(flag >= t for t in FLAG_WEAR) if flag else 0


def _at_flag(b, i, rate, box=None):
    """None while a second compound is owed or the team plans a stop before the flag: this set won't see it."""
    dmg = b.damage()
    stopping = box is not None and b.my["currentLapNum"] <= box < b.s["totalLaps"]
    return dmg and not stopping and not strategy.stop_owed(b) and dmg["tyresWear"][i] + rate * (b.laps_left() + 1)


def _overwear(b, box=None):
    got = _overwear_numbers(b)
    if not got:
        return None
    i, mine, field, worst = got
    text = f"{corner(i)}'s wearing {mine / field:.1f} times the field's rate."
    flag = _at_flag(b, i, mine, box)
    if flag:
        text += f" About {flag:.0f}% by the flag."
    if worst:
        text += f" Mostly in sector{'s' * (len(worst) > 1)} " + " and ".join(str(n) for n in worst) + "."
    elif worst is not None:
        text += " It's all round the lap."
    return text


def _life(b):
    worn = strategy.worn_in(b)
    if not worn or worn[1] is None or worn[1] > LIFE_CALL:
        return None
    w, n = worn
    return f"{corner(w)} reaches {strategy.WORN}% in about {n} lap{'s' * (n != 1)}." if n else f"{corner(w)} is past {strategy.WORN}%."


def _worn(b, i):
    dmg = b.damage()
    return f"{corner(i)} is the limit, {dmg['tyresWear'][i]:.0f}% worn." if dmg else None
