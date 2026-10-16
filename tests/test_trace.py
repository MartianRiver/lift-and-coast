"""Zone comparison on synthetic laps, and the lap bookkeeping that real data tripped over."""
import unittest

from engineer import trace

TRACK = 3000


def lap(n, slow_from=0, slow_to=0, extra=0.0, brake_at=(1000, 2000)):
    """A 60 s lap at 50 m/s, braking hard just after each of brake_at; `extra` seconds lost evenly over a span."""
    x = trace.Lap(n)
    t = 0.0
    for i in range(1, 1201):
        d = i * 2.5
        dt = 0.05
        if slow_from <= d < slow_to:
            dt += extra / ((slow_to - slow_from) / 2.5)
        t += dt
        braking = any(b <= d < b + 60 for b in brake_at)
        x.add(d, int(t * 1000), 150 if braking else 300, 1.0 if braking else 0.0)
    x.total = x.ms[-1]
    return x


class Compare(unittest.TestCase):
    def test_zones_follow_braking_points(self):
        self.assertEqual(trace.zones(lap(1), TRACK), [(0, 1000), (1000, 2000), (2000, TRACK)])

    def test_time_lost_lands_in_the_right_zone(self):
        mine, theirs = lap(1, 1200, 1800, 0.3), lap(1)
        rows = trace.compare([mine], [theirs], trace.zones(theirs, TRACK))
        lost = {(a, b): round(dt, 2) for a, b, dt, *_ in rows}
        self.assertEqual(lost, {(0, 1000): 0.0, (1000, 2000): 0.3, (2000, TRACK): 0.0})

    def test_later_braking_is_measured_for_the_zone_it_starts(self):
        mine, theirs = lap(1, brake_at=(1020, 2000)), lap(1)
        rows = trace.compare([mine], [theirs], trace.zones(theirs, TRACK))
        self.assertAlmostEqual(rows[1][5], 20, delta=3)


def lap_pkt(t, n, d, ms, pit=0, sc=0):
    car = dict(currentLapNum=n, lapDistance=d, currentLapTimeInMS=ms, resultStatus=2, pitStatus=pit,
               currentLapInvalid=0, lastLapTimeInMS=60000)
    return {"header": {"sessionTime": t}, "lapData": [car]}, {1: {"safetyCarStatus": sc, "trackLength": TRACK}}


class Bookkeeping(unittest.TestCase):
    def drive(self, tr, n, start=0, pit_from=None, sc_from=None):
        for i in range(start, 1200):
            d = i * 2.5
            pkt, latest = lap_pkt(i, n, d, i * 50, pit=int(pit_from is not None and d >= pit_from),
                                  sc=int(sc_from is not None and d >= sc_from))
            tr.on_lap_data(pkt, latest)

    def test_pit_lap_is_kept_but_not_clean(self):
        tr = trace.Traces()
        self.drive(tr, 1)
        self.drive(tr, 2, pit_from=2800)
        self.drive(tr, 3)
        self.assertEqual([x.n for x in tr.laps[0]], [1, 2])
        self.assertEqual([x.n for x in tr.clean(0)], [1])

    def test_restart_at_the_line_clears_the_garage_stint(self):
        tr = trace.Traces()
        self.drive(tr, 1)
        self.drive(tr, 2, pit_from=0)   # quali: back to the garage, same lap number
        self.drive(tr, 2)               # out of the garage, rewinds to the line, flying lap
        self.drive(tr, 3, start=0)
        self.assertFalse(tr.laps[0][-1].dirty)

    def test_sc_flag_lingering_at_the_restart_line_is_ignored(self):
        tr = trace.Traces()
        self.drive(tr, 1)
        self.drive(tr, 2, sc_from=2900)
        for i in range(0, 1200):  # restart lap: flag still set for the first 150 m
            pkt, latest = lap_pkt(i, 3, i * 2.5, i * 50, sc=int(i * 2.5 < 150))
            tr.on_lap_data(pkt, latest)
        self.drive(tr, 4)
        self.assertEqual([x.n for x in tr.clean(0)], [1, 3])

    def test_sparse_lap_is_dropped(self):
        tr = trace.Traces()
        self.drive(tr, 1)
        for i in range(0, 1200, 20):  # 1 Hz: driven off-screen
            pkt, latest = lap_pkt(i, 2, i * 2.5, i * 50)
            tr.on_lap_data(pkt, latest)
        self.drive(tr, 3)
        self.assertEqual([x.n for x in tr.laps[0]], [1])


if __name__ == "__main__":
    unittest.main()
