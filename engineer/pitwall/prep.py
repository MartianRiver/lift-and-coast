"""Race prep: the plan for a race before it loads. The game only starts sending the race once the player's
past the strategy screen, so fuel, the starting tyre and the stop plan come from the last session at
this track (qualifying: their grid slot, the race forecast, the sets they have left) and their own numbers
from earlier races (fuel burn, how long their tyres really last). The team writes the plan; it carries
into the race when it loads and gets revised from there.
"""
import json
import math
import re
import time
from statistics import median

from .. import archive, log, pitstops, profile
from .. import lookups as L
from ..fmt import WHEELS

_log = log.get("pitwall")

FILE = archive.DATA / "pitwall-prep.json"
KEEP_HOURS = 12      # a prep older than this belongs to another weekend
RACES = (15, 16, 17)
QUALI = range(5, 15)  # every kind of qualifying and shootout


def facts(db=None):
    """The PRE-RACE section the team reads -> (text, info) or (None, why not)."""
    own = db is None
    db = db or archive.connect()
    try:
        last = profile.latest_here(db)
        if not last:
            return None, "no practice or qualifying session in the archive yet"
        lines, info = _event(db, last)
        lines += _fuel(db, info) + _tyres(db, last, info) + _field(db, info) + _pit(db, last)
        return "\n".join(lines), info
    finally:
        if own:
            db.close()


def _event(db, last):
    track, length = last["track"], last["track_length"]
    weekend = last["weekend"] or []
    later = [t for t in weekend[weekend.index(last["type_id"]) + 1:] if t in RACES] if last["type_id"] in weekend else []
    kind = later[0] if later else 15
    sprint = len([t for t in weekend if t in RACES]) > 1 and kind == min(t for t in weekend if t in RACES)
    share = profile.distance(db)
    laps = round(profile.full_laps(track, length, sprint) * share) if share else None
    info = {"track": track, "trackId": last["track_id"], "length": length, "laps": laps, "session": kind, "grid": None,
            "sprint": sprint}
    lines = ["PRE-RACE (the race hasn't loaded: this is from his last session here and his earlier races)",
             f"EVENT  {track} ({length / 1000:.3f} km) · next: {L.name(L.SESSION_TYPES, kind)}{' (the sprint)' if sprint else ''}"
             + (f" · ≈{laps} laps ({share:.0%} race distance, like his other races; the exact count comes when it loads)" if laps else "")]
    grid = last["position"]
    if last["type_id"] in QUALI and grid:
        info["grid"] = grid
        lines.append(f"GRID   P{grid} (his {last['type']} result{'; outside the top 10 he picks his starting tyre' if grid > 10 else ''})")
    samples = [w for w in last["forecast"] or [] if w["session"] == kind]
    if samples:
        lines.append("FORECAST (race) " + " · ".join(f"{'now' if not w['offset'] else '+' + str(w['offset']) + 'm'} "
                                                     f"{L.name(L.WEATHER, w['weather']).lower()} {w['rain']}% rain" for w in samples)
                     + f" · track {samples[0]['track']}°C")
        info["rainChance"] = max(w["rain"] for w in samples)
        if last["best_lap_ms"]:
            info["wetLaps"] = _wet_laps(samples, last["best_lap_ms"], laps)
            span = max(w["offset"] for w in samples) * 60000 / last["best_lap_ms"]
            lines.append(f"       the forecast reaches +{max(w['offset'] for w in samples)}m ≈ {span:.0f} laps at his "
                         f"{last['type']} pace (race laps are a little slower)")
    return lines, info


def _wet_laps(samples, lap_ms, laps):
    """Laps the forecast has raining (light rain or worse), at their qualifying pace."""
    at = lambda m: m * 60000 / lap_ms
    ends = [w["offset"] for w in samples[1:]] + [None]
    wet = sum((min(at(end), laps or 99) if end is not None else (laps or at(w["offset"]))) - at(w["offset"])
              for w, end in zip(samples, ends) if w["weather"] >= 3)
    return round(max(0, wet))


def _fuel(db, info):
    races = profile.fuel(db)
    if not races:
        return ["FUEL   no earlier races with fuel data"]
    per_km = [r["perKm"] for r in races if r["perKm"]]
    lap_kg = median(per_km) * info["length"] / 1000
    out = [f"FUEL   his burn ≈{lap_kg:.2f} kg a lap here ({min(per_km):.3f}–{max(per_km):.3f} kg/km in his races). The fuel delta is "
           "laps of fuel over the game's target; how it moved a lap in his races (+ = he used less than the target):"]
    for r in races:
        parts = [f"started {r['start']:+.2f}, last lap {r['end']:+.2f}"]
        for key, label, n in (("lap1", "lap 1", None), ("dry", "dry green", None), ("dryLow", "heaviest dry stint", None),
                              ("wet", "wet green", "wetLaps"), ("sc", "safety car", "scLaps")):
            if r[key] is not None:
                parts.append(f"{label} {r[key]:+.2f}" + (f" ×{r[n]}" if n else ""))
        out.append(f"       {r['track']} L{r['fromLap']}–{r['toLap']} of {r['laps']}: " + " · ".join(parts))
    return out + _suggest(races, info, lap_kg)


RACE_LIFE = 0.5    # a set's life in the race against what quali says for it, every compound and track
HARD = (1.3, 500)  # the new Hard a main race adds (a sprint doesn't): life × the new Medium's, ms/lap slower than it
FLOOR = 0.3  # laps of fuel over the target left at the flag: they've never needed to save fuel


def _suggest(races, info, lap_kg):
    """The fuel delta to start on: a full dry race at their heaviest dry burn with no safety car ends at FLOOR."""
    n = info["laps"]
    pick = lambda key, worst: worst([r[key] for r in races if r[key] is not None] or [0.0])
    lap1, dry, wet, sc = pick("lap1", min), min(pick("dryLow", min), pick("dry", min), 0.0), pick("wet", min), pick("sc", max)
    if not n:
        return []
    need = lambda drift: max(FLOOR, math.ceil(round((FLOOR - drift) * 10, 6)) / 10)
    dry_case = lap1 + (n - 2) * dry
    start = need(dry_case)
    out = [f"SUGGESTED FUEL {start:+.1f} laps (≈{start * lap_kg:.1f} kg over the target): a full dry race, no safety car, "
           f"lap 1 at {lap1:+.2f} and every lap at his heaviest dry stint's {dry:+.2f}, ends ≈{start + dry_case:+.1f}"]
    if sc:
        out.append(f"       a safety car adds ≈{sc:+.2f} a lap, so a 3-lap one leaves ≈{start + dry_case + 3 * sc:+.1f} at the flag")
    if info.get("wetLaps") or (info.get("rainChance") or 0) >= 25:
        wet_laps = info.get("wetLaps") or n // 2
        wet_case = dry_case + wet_laps * (wet - dry)
        out.append(f"       if ≈{wet_laps} laps are wet at his worst wet rate ({wet:+.2f} a lap, Silverstone): ends ≈{start + wet_case:+.1f}; "
                   f"{need(wet_case):+.1f} covers it")
    elif wet < dry:
        out.append(f"       the wet burnt more than the target in his races ({wet:+.2f} a lap at worst), not less; "
                   f"the forecast has no rain worth fuelling for (≤{info.get('rainChance') or 0}%)")
    return out


def _tyres(db, last, info):
    out = []
    stints = profile.tyre_life(db)
    dry = [s["ratio"] for s in stints if not s["wet"]]
    wet = [s["ratio"] for s in stints if s["wet"]]
    if stints:
        out.append("TYRE LIFE laps until his worst tyre reaches 70%, against the game's own life estimate for the set: "
                   + " · ".join(f"{s['track']} {profile.compound(s['compound'])} {s['toWorn']:.0f} vs {s['gameLife']}"
                                + (f" (from P{s['grid']})" if s["grid"] else "") for s in stints))
        if dry:
            out.append(f"       dry: {min(dry):.2f}–{max(dry):.2f}× the game's estimate (median {median(dry):.2f})"
                       + (f" · wet: {min(wet):.2f}–{max(wet):.2f}×" if wet else ""))
        out += _vs_field(stints)
        if info["grid"] and info["grid"] > 10 and all(s["grid"] and s["grid"] <= 10 for s in stints if not s["wet"]):
            out.append(f"       his dry numbers all come from the top 10; from P{info['grid']} the first stint is in traffic, "
                       "where dirty air wears tyres faster")
    if last["sets"]:
        sets = _sets(race_sets(last["sets"], last["type_id"], info.get("sprint")), stints)
        out.append("SETS   he has (life = the game's estimate for the race; s/lap against the set he ended the session on):")
        for x in sets:
            mine = f", ≈{x['mine']:.0f} laps at his rate" if x["mine"] else ""
            out.append(f"       {x['name']}{' ×' + str(x['n']) if x['n'] > 1 else ''}: {x['delta']:+.2f} s/lap, life {x['life']}{mine}")
        out += _options(sets, info)
    return out


def _vs_field(stints):
    """The player's wear per wheel against the AI on the same compound, from the stints that have it."""
    known = [s for s in stints if s["vsField"]]
    if not known:
        return []
    out = ["WEAR VS THE AI his %/lap per wheel ÷ the AI's median on the same compound, worst first: " + " · ".join(
        f"{s['track']} {profile.compound(s['compound'])} " + " ".join(
            f"{w} {x:.1f}×" for x, w in sorted(zip(s["vsField"], WHEELS), reverse=True) if x) for s in known)]
    for wet in (False, True):
        group = [s["vsField"] for s in known if s["wet"] == wet]
        if group:
            out.append(f"       {'wet' if wet else 'dry'}: " + " · ".join(
                f"{w} {min(g[i] for g in group):.1f}–{max(g[i] for g in group):.1f}×" for i, w in enumerate(WHEELS)))
    return out


def race_sets(raw, kind, sprint=False):
    """The sets as the race will have them: quali's lives halved, plus the new Hard quali doesn't list.
    Practice and race lives are already the race's."""
    if kind not in QUALI:
        return raw
    out = [{**s, "life": round(s["life"] * RACE_LIFE)} for s in raw]
    medium = next((s for s in out if s["compound"] == 17 and not s["wear"]), None)
    if medium and not sprint and not any(s["compound"] == 18 for s in out):
        out.append({**medium, "compound": 18, "life": round(medium["life"] * HARD[0]), "delta": medium["delta"] + HARD[1],
                    "fitted": False})
    return out


def _sets(raw, stints):
    """The player's sets, ones with the same name grouped, each with its life at their rate (that compound's, else all
    dry or wet). The game's estimate can differ by 0.01 s/lap between two identical used sets: the group takes the best."""
    def ratio(c):
        mine = [s["ratio"] for s in stints if s["compound"] == c]
        kind = [s["ratio"] for s in stints if s["wet"] == (c in profile.WET)]
        return median(mine) if len(mine) >= 2 else median(kind) if kind else None

    same = {}
    for s in raw:
        same.setdefault((s["compound"], s["wear"]), []).append(s)
    out = []
    for (c, worn), group in same.items():
        best = min(group, key=lambda s: s["delta"])
        r, life, delta = ratio(c), best["life"], best["delta"]
        out.append({"compound": profile.compound(c), "wet": c in profile.WET, "name": f"{profile.compound(c)} "
                    + ("new" if not worn else f"{worn}% used"), "n": len(group), "life": life, "delta": delta / 1000,
                    "mine": life * r if r else None})
    return out


def _options(sets, info):
    """Every dry one-stop they can run with these sets: two different compounds, each stint within its life."""
    laps, dry = info["laps"], [s for s in sets if not s["wet"] and s["mine"]]
    if info.get("sprint"):
        info["compounds"] = []  # nothing for check() to enforce
        return _no_stop(dry, laps)
    info["compounds"] = sorted({s["compound"] for s in dry})
    if not laps or len(info["compounds"]) < 2:
        return [f"       dry compounds: {', '.join(info['compounds']) or 'none'}"]
    out = [f"ONE-STOP OPTIONS (a dry race needs two different dry compounds: every car in his dry races ran two, "
           f"so {' → '.join([max(info['compounds'], key=lambda c: sum(s['compound'] == c for s in dry))] * 2)} "
           "is not allowed; no stop isn't either)"]
    for a in dry:
        for b in dry:
            if a["compound"] == b["compound"]:
                continue
            first, last = max(1, math.ceil(laps - b["mine"])), min(laps - 1, math.floor(a["mine"]))
            if first > last:
                out.append(f"       {a['name']} → {b['name']}: doesn't reach the flag on one stop")
                continue
            quicker = b["delta"] - a["delta"]
            out.append(f"       {a['name']} → {b['name']}: box any lap L{first}–{last} (the {a['name']} lasts {a['mine']:.0f}, "
                       f"the {b['name']} {b['mine']:.0f}); the second set is {abs(quicker):.2f} s/lap "
                       f"{'slower' if quicker > 0 else 'quicker'} than the first (game's estimate)")
    return out


def _no_stop(dry, laps):
    """A sprint has no compulsory stop, and nobody has stopped in one of his: which sets go the distance."""
    out = ["NO-STOP OPTIONS (a sprint has no compulsory stop and no car has stopped in his sprints: one set to the flag)"]
    for s in dry:
        enough = laps and s["mine"] >= laps
        out.append(f"       {s['name']}: lasts {s['mine']:.0f}" + (f", enough for {laps}" if enough else
                                                                    f", short of {laps}" if laps else "")
                   + f", {s['delta']:+.2f} s/lap")
    return out


def _field(db, info):
    """When the AI made its first stop in their dry races: when the pack around them will be pitting."""
    if info.get("sprint"):
        return []
    rows = db.execute("""select s.track, s.total_laps, r.stints from results r join sessions s on s.uid = r.session_uid
                         where s.type_id in (15, 16, 17) and s.total_laps >= 10 and r.status = 'Finished'""").fetchall()
    races = {}
    for r in rows:
        stints = json.loads(r["stints"] or "[]")
        if len(stints) < 2 or any(c in ("Inter", "Wet") for _, c in stints):
            continue
        races.setdefault((r["track"], r["total_laps"]), []).append(stints[0][0])
    if not races:
        return []
    shares = [lap / total for (_, total), stops in races.items() for lap in stops]
    out = ["FIELD  the AI's first stop in his dry races: " + " · ".join(
        f"{t} L{min(s)}–{max(s)} of {n}" for (t, n), s in races.items())]
    if info["laps"]:
        lo, hi = sorted(shares)[len(shares) // 10], sorted(shares)[-1 - len(shares) // 10]
        out.append(f"       most stop at {lo:.0%}–{hi:.0%} of the race ≈ L{round(lo * info['laps'])}–{round(hi * info['laps'])} here")
    return out


def _pit(db, last):
    tracks = pitstops.by_track(db)
    here = tracks.get(last["track"], {}).get("green")
    if here:
        return [f"PIT    a green-flag stop costs {median(here):.1f}s here ({len(here)} stops measured)"]
    usual = pitstops.usual({"trackId": last["track_id"], "formula": last["formula"]})
    if usual and usual[1]:
        return [f"PIT    a green-flag stop costs ≈{usual[0]:.1f}s here: a rule of thumb, {usual[1]} stops measured in F1 25, none in his races"]
    rest = {t: median(v["green"]) for t, v in tracks.items() if v["green"]}
    if not rest:
        return ["PIT    no stop measured anywhere yet"]
    return ["PIT    no stop measured here yet; elsewhere: " + ", ".join(f"{t} {s:.1f}s" for t, s in rest.items())]


def check(note, info):
    """A plan that breaks the two-compound rule (the model once wrote "used Soft start, box for the new Soft")."""
    names = info.get("compounds") or []
    if len(names) < 2:
        return None
    pick = "|".join(names)
    start = re.search(pick, note.get("start") or "", re.I)
    box = re.search(rf"\bbox\b.*?\b({pick})", note.get("call") or "", re.I)
    if not start or not box:
        return "the CALL must say the start tyre and which set he boxes for (\"Soft start, box L14-17 for the new Medium\")"
    if start.group(0).lower() == box.group(1).lower():
        return (f"he starts on {start.group(0)} and boxes for {box.group(1)}: a dry race needs two different dry compounds, "
                "so plan A must be one of the ONE-STOP OPTIONS")
    return None


# --- keeping it for the race ------------------------------------------------------------

def save(prep):
    FILE.parent.mkdir(parents=True, exist_ok=True)
    FILE.write_text(json.dumps(prep))


def load(track_id=None):
    """The latest prep, if it's recent (and for this track)."""
    try:
        prep = json.loads(FILE.read_text())
    except (FileNotFoundError, ValueError):
        return None
    if time.time() - prep.get("at", 0) > KEEP_HOURS * 3600:
        return None
    if track_id is not None and prep.get("trackId") != track_id:
        return None
    return prep
