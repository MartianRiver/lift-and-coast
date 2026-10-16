"""Where on the lap the tyres wear, for every car.

The game sends every car's wear ten times a second as a float, so each increment can be put at the
lap distance it happened. The AI cars all wear within a few percent of each other (1.75–1.98 %/lap
on the RL), so the field's median is a steady yardstick: the player's laps against it, sector by
sector, say where they're taking life out of a tyre, and next to the sector times, whether that buys
any lap time. Sectors rather than corners for now: the wear is binned finely enough to go corner by
corner once corners have names.

Only like with like: the player's laps on the set they're on now, against cars on the same compound
(otherwise fresh mediums read "3.2x the field" against old inters laps and everyone else's hards).
"""
from statistics import median

from .fmt import WHEELS

BIN = 25         # m
KEEP = 4         # complete laps kept per car
JUMP = 2.0       # % in one sample: a tyre change or a flashback, not wear
OVER = 1.3       # times the field's rate before a tyre or a sector is worth naming
STANDOUT = 1.15  # a sector named only this far above the lap's ratio; a badly worn set reads 1.9-2.0x in all three


class Lap:
    def __init__(self, n, tyres=None):
        self.n = n
        self.tyres = tyres    # (stops, visual compound) it started on
        self.bins = {}        # bin -> [RL, RR, FL, FR] % worn there
        self.lo = self.hi = None
        self.dirty = False    # pit lane or safety car: not how the tyres wear racing

    def add(self, d, dw):
        b = int(d // BIN)
        row = self.bins.setdefault(b, [0.0] * 4)
        for i in range(4):
            row[i] += dw[i]
        self.lo = d if self.lo is None else min(self.lo, d)
        self.hi = d if self.hi is None else max(self.hi, d)

    def cut(self, d):
        """Rewound within the lap: what was worn from d on will be worn again."""
        self.bins = {b: row for b, row in self.bins.items() if b < int(d // BIN)}
        self.hi = min(self.hi, d) if self.hi is not None else None

    def whole(self, track_len):
        return self.lo is not None and self.lo < 100 and self.hi > track_len - 150

    def between(self, a, b):
        rows = [row for k, row in self.bins.items() if a <= k * BIN < b]
        return [sum(r[i] for r in rows) for i in range(4)]

    def total(self):
        return [sum(r[i] for r in self.bins.values()) for i in range(4)]


class Wear:
    def __init__(self):
        self.laps = {}   # idx -> {lap number: Lap}
        self._prev = {}  # idx -> (wear, lap, distance)
        self.tyres = {}  # idx -> (stops, visual compound) now

    def on_damage(self, data, latest):
        lap_pkt, session = latest.get(2), latest.get(1)
        if not lap_pkt or not session:
            return
        sc = session["safetyCarStatus"] in (1, 2)
        status = latest.get(7)
        for idx, c in enumerate(data["carDamageData"]):
            car = lap_pkt["lapData"][idx]
            if car["resultStatus"] != 2:
                continue
            tyres = self.tyres[idx] = (car.get("numPitStops", 0),
                                       status and status["carStatusData"][idx]["visualTyreCompound"])
            n, d, w = car["currentLapNum"], car["lapDistance"], c["tyresWear"]
            prev, self._prev[idx] = self._prev.get(idx), (w, n, d)
            if prev is None or d < 0:
                continue
            laps = self.laps.setdefault(idx, {})
            if n < prev[1]:  # flashback over the line
                for k in [k for k in laps if k > n]:
                    del laps[k]
            lap = laps.setdefault(n, Lap(n, tyres))
            lap.dirty |= lap.tyres != tyres
            if lap.hi is not None and d < lap.hi - 20:  # rewound (or quali's garage restart)
                lap.cut(d)
            dw = [w[i] - prev[0][i] for i in range(4)]
            if not all(-0.01 < x < JUMP for x in dw):
                continue
            lap.add(d, dw)
            lap.dirty |= bool(car["pitStatus"]) or (sc and d > 200)  # the SC flag lingers past the restart line
            for k in [k for k in laps if k < n - KEEP]:
                del laps[k]

    def recent(self, idx, track_len, k=3, compound=None):
        """Last k clean laps on the set this car is on now; [] if that isn't `compound`."""
        now, laps = self.tyres.get(idx), self.laps.get(idx, {})
        if compound is not None and (not now or now[1] != compound):
            return []
        return [laps[n] for n in sorted(laps)
                if not laps[n].dirty and laps[n].whole(track_len) and laps[n].tyres == now][-k:]

    def compound(self, idx):
        return self.tyres.get(idx, (0, None))[1]


def rates(laps):
    """%/lap per wheel over these laps."""
    totals = [lap.total() for lap in laps]
    return [sum(t[i] for t in totals) / len(totals) for i in range(4)]


def field_rates(wear, me, idxs, track_len):
    """Median %/lap per wheel over the other cars' recent green laps."""
    per = [rates(laps) for laps in _others(wear, me, idxs, track_len) if laps]
    if len(per) < 3:
        return None
    return [median(r[i] for r in per) for i in range(4)]


def _others(wear, me, idxs, track_len):
    return (wear.recent(i, track_len, compound=wear.compound(me)) for i in idxs if i != me)


def worst(mine, field):
    """The wheel that limits the stint (fastest-wearing) and how far over the field's rate it is."""
    i = max(range(4), key=lambda i: mine[i])
    return i, (mine[i] / field[i] if field[i] else 0)


def sectors(session):
    """[(start, end)] in lap metres for S1–S3, from the game's sector start distances."""
    a, b, end = session["sector2LapDistanceStart"], session["sector3LapDistanceStart"], session["trackLength"]
    return [(0, round(a)), (round(a), round(b)), (round(b), end)] if 0 < a < b < end else []


def by_sector(wear, me, idxs, spans, track_len, wheel):
    """Per sector: (number, your %/lap, field %/lap) for one wheel, biggest excess first."""
    mine = wear.recent(me, track_len)
    others = [laps for laps in _others(wear, me, idxs, track_len) if laps]
    out = []
    for n, (a, b) in enumerate(spans, 1):
        you = sum(lap.between(a, b)[wheel] for lap in mine) / len(mine)
        them = median(sum(lap.between(a, b)[wheel] for lap in laps) / len(laps) for laps in others)
        out.append((n, you, them))
    return sorted(out, key=lambda z: z[2] - z[1])


def standout(rows, ratio):
    """Sectors where the extra wear concentrates, worst first; [] when it's spread round the lap."""
    hot = [r for r in rows if r[2] and r[1] - r[2] >= 0.1 and r[1] / r[2] >= max(OVER, STANDOUT * ratio)]
    return sorted(hot, key=lambda r: -r[1] / r[2])


def summary(wear, me, idxs, spans, track_len, time_in):
    """Brief lines. `time_in(n)` -> (rival label, seconds you lose (+) or gain (−) in sector n) or None."""
    mine_laps = wear.recent(me, track_len)
    field = field_rates(wear, me, idxs, track_len)
    if not mine_laps or not field or not spans:
        return []
    mine = rates(mine_laps)
    w, ratio = worst(mine, field)
    out = [f"  wear %/lap, your last {len(mine_laps)} green laps vs the field's median: "
           + " ".join(f"{WHEELS[i]} {mine[i]:.1f} ({field[i]:.1f})" for i in range(4))]
    if ratio < OVER:
        return out + [f"  your fastest-wearing tyre ({WHEELS[w]}) is wearing about like the field's"]
    rows = by_sector(wear, me, idxs, spans, track_len, w)
    parts = [_sector(n, you, them, time_in(n)) for n, you, them in sorted(rows)]
    out.append(f"  {WHEELS[w]} (your fastest-wearing) is going {ratio:.1f}× the field's rate. By sector: " + " · ".join(parts))
    hot = standout(rows, ratio)
    out.append("  the extra is concentrated in " + " then ".join(f"S{n}" for n, _, _ in hot[:2]) if hot
               else "  the extra is spread evenly round the lap, no one sector stands out")
    return out


def _sector(n, you, them, timed):
    line = f"S{n} {you:.2f} vs {them:.2f}" + (f" ({you / them:.1f}×)" if them else "")
    if timed:
        label, dt = timed
        line += f", level with {label}" if abs(dt) < 0.02 else f", you {'lose' if dt > 0 else 'gain'} {abs(dt):.2f} to {label}"
    return line
