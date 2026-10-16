"""Rear grip by sector on the player's own laps: sliding, wheelspin on the throttle, rear surface temps.

The AI's tyre temps aren't simulated (every medium reads one fixed number all race, every hard another),
so there's no field to hold the player against. The yardstick is the same set on its first clean laps.
Sliding = the rears' slip angle at speed; wheelspin = the share of full-throttle running with a rear's
slip ratio over SPIN. Inters spin far more than slicks (30–45 % all race), another reason it's never a
fixed number.

"The back is slipping out" with normal wear looked like this: the rears sliding 1.6x and spinning
4x as much in one sector as on the first laps of the set, back to normal a few laps later.
"""
from .spec import MAX_CARS

BIN = 25         # m
SPIN = 0.10      # rear slip ratio that counts as wheelspin
EARLY = 3        # first clean laps on a set: the baseline
NOW = 2          # latest clean laps: grip comes and goes within a few laps
SLIDE_UP = 1.4   # rear slip angle against the baseline before a sector counts as sliding
SPIN_UP = 2.0    # times the baseline, and
SPIN_PTS = 7.0   # points of full-throttle time more, before wheelspin counts
HOT = 12         # °C over the baseline on a rear before the temps are worth naming

THR, SPUN, RL, RR, TEMPS, SLIDE, MOVING = range(7)


class Lap:
    def __init__(self, n, tyres):
        self.n, self.tyres = n, tyres
        self.bins = {}  # bin -> sums, indexed as above
        self.lo = self.hi = None
        self.dirty = False

    def row(self, d):
        self.lo = d if self.lo is None else min(self.lo, d)
        self.hi = d if self.hi is None else max(self.hi, d)
        return self.bins.setdefault(int(d // BIN), [0.0] * 7)

    def cut(self, d):
        self.bins = {b: r for b, r in self.bins.items() if b < int(d // BIN)}
        self.hi = min(self.hi, d) if self.hi is not None else None

    def whole(self, track_len):
        return self.lo is not None and self.lo < 100 and self.hi > track_len - 150

    def between(self, a, b):
        rows = [r for k, r in self.bins.items() if a <= k * BIN < b]
        return [sum(r[i] for r in rows) for i in range(7)]


class Grip:
    def __init__(self):
        self.laps = {}   # lap number -> Lap, player only
        self.tel = None  # the player's latest telemetry: throttle, brake, speed for the motion samples
        self.tyres = None

    def _lap(self, latest):
        """The player's Lap and lap distance now; None before the data's in."""
        lap_pkt, session, status = latest.get(2), latest.get(1), latest.get(7)
        me = lap_pkt and lap_pkt["header"]["playerCarIndex"]
        if not session or not status or me is None or me >= MAX_CARS:
            return None, None
        c = lap_pkt["lapData"][me]
        n, d = c["currentLapNum"], c["lapDistance"]
        if d < 0 or not n:
            return None, None
        tyres = self.tyres = (c["numPitStops"], status["carStatusData"][me]["visualTyreCompound"])
        for k in [k for k in self.laps if k > n]:  # flashback over the line
            del self.laps[k]
        lap = self.laps.setdefault(n, Lap(n, tyres))
        if lap.hi is not None and d < lap.hi - 20:  # rewound within the lap
            lap.cut(d)
        lap.dirty |= lap.tyres != tyres or bool(c["pitStatus"]) or (session["safetyCarStatus"] in (1, 2) and d > 200)
        return lap, d

    def on_telemetry(self, data, latest):
        me = data["header"]["playerCarIndex"]
        if me >= MAX_CARS:
            return
        self.tel = data["carTelemetryData"][me]
        lap, d = self._lap(latest)
        if lap:
            r = lap.row(d)
            r[RL] += self.tel["tyresSurfaceTemperature"][0]
            r[RR] += self.tel["tyresSurfaceTemperature"][1]
            r[TEMPS] += 1

    def on_motion(self, data, latest):
        t = self.tel
        if not t or t["speed"] < 60:
            return
        lap, d = self._lap(latest)
        if not lap:
            return
        r = lap.row(d)
        r[SLIDE] += max(abs(data["wheelSlipAngle"][0]), abs(data["wheelSlipAngle"][1]))
        r[MOVING] += 1
        if t["throttle"] >= 0.6 and t["brake"] <= 0.05:
            r[THR] += 1
            r[SPUN] += max(data["wheelSlipRatio"][0], data["wheelSlipRatio"][1]) > SPIN

    def stint(self, track_len):
        """Clean whole laps on the set they're on now, oldest first (never the standing start)."""
        return [self.laps[n] for n in sorted(self.laps)
                if n > 1 and self.laps[n].tyres == self.tyres and not self.laps[n].dirty and self.laps[n].whole(track_len)]


def _sum(laps, a, b):
    tot = [0.0] * 7
    for lap in laps:
        tot = [x + y for x, y in zip(tot, lap.between(a, b))]
    return tot


def _sector(s):
    """Sums -> (slip angle, spin %, (RL, RR) °C), or None when a part wasn't sampled."""
    if not (s[THR] and s[TEMPS] and s[MOVING]):
        return None
    return s[SLIDE] / s[MOVING], 100 * s[SPUN] / s[THR], (s[RL] / s[TEMPS], s[RR] / s[TEMPS])


def by_sector(grip, spans, track_len):
    """Per sector: (n, early, now) with each (slip angle, spin %, (RL, RR) °C); [] until the set has
    EARLY + NOW clean laps. A sector already done on this lap counts as one of the NOW laps: drivers
    feel a slide and say so before the lap is out."""
    laps = grip.stint(track_len)
    if len(laps) < EARLY + NOW or not spans:
        return []
    cur = grip.laps.get(max(grip.laps))
    cur = cur if cur and cur not in laps and not cur.dirty and cur.tyres == grip.tyres and cur.lo is not None and cur.lo < 100 else None
    out = []
    for n, (a, b) in enumerate(spans, 1):
        recent = laps[-(NOW - 1):] + [cur] if cur and cur.hi >= b - BIN else laps[-NOW:]
        was, now = _sector(_sum(laps[:EARLY], a, b)), _sector(_sum(recent, a, b))
        if not was or not now:
            return []
        out.append((n, was, now))
    return out


def sliding(rows):
    return [r for r in rows if r[1][0] and r[2][0] >= SLIDE_UP * r[1][0]]


def spinning(rows):
    return [r for r in rows if r[2][1] - r[1][1] >= SPIN_PTS and r[2][1] >= SPIN_UP * r[1][1]]


def heating(rows):
    return [r for r in rows if max(r[2][2][i] - r[1][2][i] for i in range(2)) >= HOT]


def losing(rows):
    """Sectors where the rear grip has gone (sliding or spinning up), worst slide first."""
    hit = {r[0]: r for r in sliding(rows) + spinning(rows)}
    return sorted(hit.values(), key=lambda r: -(r[2][0] / r[1][0] if r[1][0] else 0))


def summary(grip, spans, track_len):
    rows = by_sector(grip, spans, track_len)
    if not rows:
        return []
    laps = grip.stint(track_len)
    parts = [f"S{n} slide {now[0] / was[0]:.1f}×, spin {now[1]:.0f}% (was {was[1]:.0f}%), "
             f"RL/RR {now[2][0]:.0f}/{now[2][1]:.0f}°C (was {was[2][0]:.0f}/{was[2][1]:.0f})"
             for n, was, now in rows if was[0]]
    out = [f"  rears, your last {NOW} green laps (this one too, for the sectors done) vs laps {laps[0].n}-{laps[EARLY - 1].n} on this set (slide = rear slip "
           "angle against then; spin = share of full-throttle time with a rear spinning): " + " · ".join(parts)]
    slide, spin, temp = {r[0] for r in sliding(rows)}, {r[0] for r in spinning(rows)}, heating(rows)
    for n in sorted(slide | spin):
        what = " and ".join(w for w, hit in (("sliding more", n in slide), ("spinning up more on the throttle", n in spin)) if hit)
        out.append(f"  rear grip has gone in S{n}: the rears are {what} than on the first laps of this set")
    if temp:
        up = max(r[2][2][i] - r[1][2][i] for r in temp for i in range(2))
        out.append(f"  rear temps up as much as {up:.0f}°C on the start of the set in " + ", ".join(f"S{r[0]}" for r in temp))
    if not slide and not spin and not temp:
        out.append("  rear grip about as it was at the start of the set")
    return out
