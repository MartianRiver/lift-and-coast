"""Per-distance lap traces for every car, and where time goes between two drivers.

Every car sends lap distance, lap time and speed at 20 Hz, so each lap becomes a distance → time
curve. The lap is cut into zones at the player's own braking points (brake onset to the next brake
onset: the corner plus the straight after it), and comparing the curves zone by zone says where
they gain or lose time to someone and whether it's the apex (min speed) or the exit (top speed).
"""
from bisect import bisect_left

KEEP = 4           # recent laps kept per car
BRAKE_ON = 0.3     # brake input that counts as braking
MIN_ZONE = 150     # m: brake taps closer than this to the last onset are the same corner
MIN_HZ = 10        # samples a second for a lap to count (the game sends 20)


class Lap:
    def __init__(self, n):
        self.n = n
        self.dist, self.ms, self.speed, self.brake = [], [], [], []
        self.dirty_from = None  # first distance with a pit, SC/VSC or invalid flag: no use for comparing
        self.total = None

    @property
    def dirty(self):
        return self.dirty_from is not None

    def add(self, d, ms, speed, brake):
        self.dist.append(d)
        self.ms.append(ms)
        self.speed.append(speed)
        self.brake.append(brake)

    def cut(self, d):
        """Rewound within the lap: forget everything from d on. (Quali keeps one lap number through a
        return to the garage, the out lap and the next flying lap, so this also restarts a lap.)"""
        if d < 100:  # back at the line (a pit lane's distances can jump back too, so only here)
            self.dirty_from = None
        i = bisect_left(self.dist, d)
        for xs in (self.dist, self.ms, self.speed, self.brake):
            del xs[i:]

    def time_at(self, d):
        if d >= self.dist[-1]:
            return self.total if self.total else self.ms[-1]
        i = bisect_left(self.dist, d)
        if i == 0:
            return self.ms[0] * d / self.dist[0] if self.dist[0] else self.ms[0]
        d0, d1 = self.dist[i - 1], self.dist[i]
        return self.ms[i - 1] + (self.ms[i] - self.ms[i - 1]) * (d - d0) / (d1 - d0)

    def min_speed(self, a, b):
        i, j = bisect_left(self.dist, a), bisect_left(self.dist, b)
        return min(self.speed[i:j] or [0])

    def max_speed(self, a, b):
        i, j = bisect_left(self.dist, a), bisect_left(self.dist, b)
        return max(self.speed[i:j] or [0])

    def brake_point(self, d):
        """Where this lap starts braking for the corner whose onset (on the player's lap) is at d."""
        i = bisect_left(self.dist, d - 150)
        while i < len(self.dist) and self.dist[i] < d + 100:
            if self.brake[i] >= BRAKE_ON:
                return self.dist[i]
            i += 1
        return None


class Traces:
    def __init__(self):
        self.laps = {}   # idx -> [Lap] completed, oldest first
        self.best = {}   # idx -> fastest clean Lap this session
        self._cur = {}   # idx -> Lap being driven

    def on_lap_data(self, data, latest):
        session, tel = latest.get(1), latest.get(6)
        if not session:
            return
        sc = session["safetyCarStatus"] in (1, 2)
        for idx, c in enumerate(data["lapData"]):
            if c["resultStatus"] != 2:
                continue
            n, d = c["currentLapNum"], c["lapDistance"]
            cur = self._cur.get(idx)
            if cur is None or n != cur.n:
                if cur is not None and n == cur.n + 1:
                    self._finish(idx, cur, c["lastLapTimeInMS"], session["trackLength"])
                elif cur is not None and n < cur.n:  # flashback over the line
                    self.laps[idx] = [x for x in self.laps.get(idx, []) if x.n < n]
                cur = self._cur[idx] = Lap(n)
            elif cur.dist and d < cur.dist[-1] - 20:  # flashback within the lap
                cur.cut(d)
            if d < 0 or (cur.dist and d <= cur.dist[-1]):
                continue
            t = tel["carTelemetryData"][idx] if tel else None
            cur.add(d, c["currentLapTimeInMS"], t["speed"] if t else 0, t["brake"] if t else 0.0)
            # the SC flag lingers a moment after a restart at the line
            if cur.dirty_from is None and ((sc and d > 200) or c["pitStatus"] > 0 or c["currentLapInvalid"]):
                cur.dirty_from = d

    def _finish(self, idx, lap, ms, track_len):
        whole = lap.dist and lap.dist[0] < 100 and lap.dist[-1] > track_len - 150
        # AI cars driven off-screen (quali, while the player sits in the garage) come through in big jumps
        dense = len(lap.dist) >= ms / 1000 * MIN_HZ
        if not whole or not ms or not dense:
            return
        lap.total = ms
        laps = self.laps.setdefault(idx, [])
        laps.append(lap)
        del laps[:-KEEP]
        best = self.best.get(idx)
        if not lap.dirty and (best is None or ms < best.total):
            self.best[idx] = lap

    def clean(self, idx, k=3):
        return [x for x in self.laps.get(idx, []) if not x.dirty][-k:]


def zones(lap, track_len):
    """[(start, end)] from one brake onset to the next, wrapping the line into the first zone's start."""
    points, braking = [], False
    for d, b in zip(lap.dist, lap.brake):
        if b >= BRAKE_ON and not braking and (not points or d - points[-1] >= MIN_ZONE):
            points.append(round(d))
        braking = b >= BRAKE_ON if not braking else b > 0.05
    if len(points) < 2:
        return []
    return [(0, points[0])] + list(zip(points, points[1:])) + [(points[-1], track_len)]


_HEAD = ("  corners: zones run from one of your braking points to the next, in lap metres; "
         "apex = min speed, top = top speed before the next braking, brake = how much later you brake into the zone")


def compare(mine, theirs, spans):
    """Per zone: (start, end, seconds you lose (+) or gain (−), apex (min) speed delta, top speed delta,
    metres you brake later (+) or earlier (−) for the corner the zone starts with, or None).

    Top speed is the max over the last 40% of the zone: over the whole zone a car that brakes earlier
    for the corner the zone starts with looks slow; right at the end, one braking earlier for the next.
    """
    out = []
    for a, b in spans:
        dt = _mean(x.time_at(b) - x.time_at(a) for x in mine) - _mean(x.time_at(b) - x.time_at(a) for x in theirs)
        low = _mean(x.min_speed(a, b) for x in mine) - _mean(x.min_speed(a, b) for x in theirs)
        tail = b - 0.4 * (b - a)
        top = _mean(x.max_speed(tail, b) for x in mine) - _mean(x.max_speed(tail, b) for x in theirs)
        out.append((a, b, dt / 1000, low, top, _later(mine, theirs, a) if a else None))
    return out


def _later(mine, theirs, d):
    a = [p for p in (x.brake_point(d) for x in mine) if p is not None]
    b = [p for p in (x.brake_point(d) for x in theirs) if p is not None]
    return _mean(a) - _mean(b) if a and b else None


def _mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs)


def summary(traces, me, rivals, name, track_len, race=True):
    """Brief lines: zone by zone against each rival (idx, label) and against the player's own best lap.
    Race: recent clean laps. Quali/practice: best lap against best lap."""
    if not race:
        return _best_vs_best(traces, me, rivals, name, track_len)
    mine = traces.clean(me)
    spans = zones(mine[-1], track_len) if mine else []
    if not spans:
        return []
    out = []
    for idx, label in rivals:
        theirs = traces.clean(idx)
        if theirs:
            rows = compare(mine, theirs, spans)
            net = sum(r[2] for r in rows)
            out.append(f"  vs {name(idx)} ({label}; your last {len(mine)} clean laps vs their last {len(theirs)};"
                       f" net {'you lose' if net > 0 else 'you gain'} {abs(net):.2f}/lap): {_where(rows)}")
    best = traces.best.get(me)
    if best and best is not mine[-1]:
        rows = compare(mine[-1:], [best], spans)
        out.append(f"  vs your best lap (L{best.n}), your last lap: {_where(rows)}")
    if not out:
        return []
    return [_HEAD] + out


def _best_vs_best(traces, me, rivals, name, track_len):
    mine = traces.best.get(me)
    spans = zones(mine, track_len) if mine else []
    out = []
    for idx, label in rivals if spans else []:
        theirs = traces.best.get(idx)
        if theirs:
            out.append(f"  vs {name(idx)} ({label}), best laps: {_where(compare([mine], [theirs], spans))}")
    return ([_HEAD] if out else []) + out


def _where(rows, n=2, floor=0.05):
    lose = sorted((r for r in rows if r[2] >= floor), key=lambda r: -r[2])[:n]
    gain = sorted((r for r in rows if r[2] <= -floor), key=lambda r: r[2])[:n]
    if not lose and not gain:
        return "level everywhere"
    parts = [f"you lose {_zone(r)}" for r in lose] + [f"you gain {_zone(r)}" for r in gain]
    return " · ".join(parts)


def _zone(r):
    a, b, dt, low, top, later = r
    bits = [f"apex {low:+.0f} km/h" if abs(low) >= 2 else "same apex speed",
            f"top {top:+.0f} km/h" if abs(top) >= 2 else "same top speed"]
    if later is not None and abs(later) >= 5:
        bits.append(f"brake {abs(later):.0f} m {'later' if later > 0 else 'earlier'}")
    if abs(low) < 2 and abs(top) < 2:
        bits = ["same apex and top speed, so it's in the braking or the exit"] + bits[2:]
    return f"{abs(dt):.2f} at {a}–{b} m ({', '.join(bits)})"
