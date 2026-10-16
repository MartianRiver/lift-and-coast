"""Wear by lap distance: the bookkeeping that flashbacks and tyre changes would otherwise double-count."""
import unittest

from engineer import wear

TRACK = 1000
SECTORS = [(0, 300), (300, 650), (650, TRACK)]


class Feed:
    """Drives a Wear tracker with hand-built packets: n cars, each at (lap, distance, wear[4], pit)."""

    def __init__(self, n=4):
        self.w = wear.Wear()
        self.cars = [[1, 0.0, [0.0] * 4, 0] for _ in range(n)]
        self.tyres = [[0, 7] for _ in range(n)]  # stops, visual compound (inters)
        self.sc = 0

    def send(self):
        latest = {1: {"safetyCarStatus": self.sc},
                  2: {"lapData": [{"resultStatus": 2, "currentLapNum": c[0], "lapDistance": c[1], "pitStatus": c[3],
                                   "numPitStops": t[0]} for c, t in zip(self.cars, self.tyres)]},
                  7: {"carStatusData": [{"visualTyreCompound": t[1]} for t in self.tyres]}}
        self.w.on_damage({"carDamageData": [{"tyresWear": list(c[2])} for c in self.cars]}, latest)

    def drive(self, idx, to, rate, step=10.0):
        """Car idx drives on to distance `to` (past TRACK = next lap), wearing every tyre `rate` % per metre."""
        c = self.cars[idx]
        while c[1] + step <= to:
            c[1] += step
            if c[1] >= TRACK:
                c[0], c[1], to = c[0] + 1, c[1] - TRACK, to - TRACK
            c[2] = [x + rate * step for x in c[2]]
            self.send()

    def laps(self, idx, n, rate):
        for _ in range(n):
            self.drive(idx, self.cars[idx][1] + TRACK, rate)


class Bookkeeping(unittest.TestCase):
    def test_wear_lands_on_the_lap_it_happened(self):
        f = Feed(1)
        f.laps(0, 3, 0.002)
        done = f.w.recent(0, TRACK)
        self.assertEqual([x.n for x in done], [1, 2, 3])
        self.assertAlmostEqual(done[-1].total()[0], 2.0, delta=0.05)

    def test_flashback_within_a_lap_is_not_counted_twice(self):
        f = Feed(1)
        f.drive(0, 600, 0.002)
        c = f.cars[0]
        c[1], c[2] = 300.0, [0.6] * 4  # rewound: distance and wear both go back
        f.send()
        f.drive(0, TRACK + 5, 0.002)
        # a sample or two lost at the cut and the line; counting 300-600 twice would be 2.6
        self.assertAlmostEqual(f.w.laps[0][1].total()[0], 2.0, delta=0.1)

    def test_new_tyres_are_not_wear(self):
        f = Feed(1)
        f.laps(0, 1, 0.002)
        f.cars[0][2] = [0.0] * 4
        f.send()
        f.laps(0, 1, 0.002)
        self.assertAlmostEqual(f.w.laps[0][2].total()[0], 2.0, delta=0.05)

    def test_pit_and_safety_car_laps_are_left_out(self):
        f = Feed(1)
        f.laps(0, 1, 0.002)
        f.cars[0][3] = 1
        f.laps(0, 1, 0.002)
        f.cars[0][3], f.sc = 0, 1
        f.laps(0, 1, 0.002)
        f.sc = 0
        f.laps(0, 1, 0.002)
        self.assertEqual([x.n for x in f.w.recent(0, TRACK)], [1, 4])


class AgainstTheField(unittest.TestCase):
    def setUp(self):
        self.f = Feed(4)
        for i in range(1, 4):
            self.f.laps(i, 3, 0.002)
        # the player: like the field except 700-900 m, where they wear three times as much
        for _ in range(3):
            self.f.drive(0, 700, 0.002)
            self.f.drive(0, 900, 0.006)
            self.f.drive(0, TRACK + 0, 0.002)
            self.f.drive(0, self.f.cars[0][1] + 0.5, 0.002, step=0.5)

    def test_rates_and_the_worst_sector(self):
        w = self.f.w
        mine, field = wear.rates(w.recent(0, TRACK)), wear.field_rates(w, 0, range(4), TRACK)
        self.assertAlmostEqual(field[0], 2.0, delta=0.05)
        self.assertAlmostEqual(mine[0] / field[0], 1.4, delta=0.05)
        n, you, them = wear.by_sector(w, 0, range(4), SECTORS, TRACK, 0)[0]
        self.assertEqual(n, 3)
        self.assertAlmostEqual(you, 1.5, delta=0.05)  # 650-1000 m: 150 m at the field's rate, 200 m at three times it
        self.assertAlmostEqual(them, 0.7, delta=0.05)
        rows = wear.by_sector(w, 0, range(4), SECTORS, TRACK, 0)
        self.assertEqual([r[0] for r in wear.standout(rows, mine[0] / field[0])], [3])
        self.assertEqual(wear.standout([(1, 2.0, 1.0), (2, 2.1, 1.0), (3, 1.9, 1.0)], 2.0), [])  # even: nothing named

    def test_only_cars_on_his_compound_and_only_his_current_set(self):
        f, w = self.f, self.f.w
        f.tyres[0] = [1, 17]  # River boxes for mediums; the field stays on inters
        f.laps(0, 1, 0.006)
        self.assertEqual([x.n for x in w.recent(0, TRACK)], [3])  # laps 1-2 were on inters
        self.assertIsNone(wear.field_rates(w, 0, range(4), TRACK))  # nobody to compare a medium with
        self.assertEqual(wear.summary(w, 0, range(4), SECTORS, TRACK, lambda n: None), [])

    def test_summary_names_the_sector_and_the_time(self):
        lines = wear.summary(self.f.w, 0, range(4), SECTORS, TRACK,
                             lambda n: ("Gasly (ahead)", -0.12) if n == 3 else None)
        text = "\n".join(lines)
        self.assertIn("1.4× the field", text)
        self.assertIn("you gain 0.12 to Gasly (ahead)", text)
        self.assertIn("concentrated in S3", text)

    def test_sectors_from_the_session(self):
        session = {"sector2LapDistanceStart": 300.4, "sector3LapDistanceStart": 650.0, "trackLength": TRACK}
        self.assertEqual(wear.sectors(session), SECTORS)
        self.assertEqual(wear.sectors({**session, "sector3LapDistanceStart": 0.0}), [])


if __name__ == "__main__":
    unittest.main()
