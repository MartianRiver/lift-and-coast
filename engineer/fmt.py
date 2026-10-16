"""Text formatting shared by the brief sections."""
from . import lookups as L

WHEELS = ("RL", "RR", "FL", "FR")  # game order
FRONT_TO_BACK = (2, 3, 0, 1)  # FL FR RL RR, how the MFD reads
BODYWORK = {"front wing left": "frontLeftWingDamage", "front wing right": "frontRightWingDamage",
            "rear wing": "rearWingDamage", "floor": "floorDamage", "diffuser": "diffuserDamage", "sidepod": "sidepodDamage"}


def tyre(visual):
    return L.VISUAL_COMPOUNDS.get(visual, f"#{visual}")


def wheels(values, fmt):
    return " ".join(f"{WHEELS[i]} {fmt.format(values[i])}" for i in FRONT_TO_BACK)


def laptime(ms):
    m, s = divmod(ms / 1000, 60)
    return f"{int(m)}:{s:06.3f}"


def offset(minutes):
    return f"+{minutes}m" if minutes else "now"


def clock(secs):
    return f"{secs // 60}:{secs % 60:02d}"


def gap(secs, ref_ms):
    if ref_ms and abs(secs) * 1000 > ref_ms:
        laps = int(abs(secs) * 1000 // ref_ms)
        return f"{'+' if secs > 0 else '−'}{laps}L"
    return f"{secs:+.1f}".replace("-", "−")


def trend(gap, per_lap):
    """Spelled out: models misread the sign of a gap trend."""
    if abs(per_lap) < 0.05:
        return "gap steady"
    behind = gap > 0
    shrinking = (per_lap < 0) if behind else (per_lap > 0)
    if behind:
        return f"{'closing on you' if shrinking else 'dropping back'} {abs(per_lap):.2f}/lap"
    return f"{'you are catching' if shrinking else 'pulling away'} {abs(per_lap):.2f}/lap"


def damage(dmg, start=None):
    """start: (engine, gearbox) at the first lap line seen this session."""
    parts = [f"{k} {v}%" for k, v in hurt(dmg).items()] + faults(dmg)
    out = ["  damage " + ", ".join(parts)] if parts else []
    engine, gearbox = dmg["engineDamage"], dmg["gearBoxDamage"]
    if engine or gearbox:
        # career mode: wear on the fitted parts, carried across the season and rotated between sessions
        line = (f"  power unit engine {engine}%, gearbox {gearbox}%: season-long wear on the fitted parts, "
                "rotated by the driver; not race damage, so don't raise it unprompted, but give the numbers if asked")
        if start:
            gained = [f"{k} +{now - was}%" for k, now, was in (("engine", engine, start[0]), ("gearbox", gearbox, start[1]))
                      if now - was >= 1]
            line += f" · this race: {', '.join(gained) if gained else 'no change'}"
        out.append(line)
    return out


def hurt(dmg):
    """{part: %} for the bodywork that's damaged."""
    return {k: dmg[v] for k, v in BODYWORK.items() if dmg[v]}


def faults(dmg):
    return [f"{k[:3].upper()} fault" for k in ("drsFault", "ersFault") if dmg[k]]
