"""Rear grip by sector against the first laps of the set."""
import unittest

from engineer import grip

TRACK = 3000
SPANS = [(0, 1000), (1000, 2000), (2000, 3000)]


class Drive:
    def __init__(self):
        self.g = grip.Grip()
        self.car = {"currentLapNum": 1, "lapDistance": 0.0, "numPitStops": 0, "pitStatus": 0}
        self.latest = {1: {"safetyCarStatus": 0}, 2: {"header": {"playerCarIndex": 0}, "lapData": [self.car]},
                       7: {"carStatusData": [{"visualTyreCompound": 17}]}}

    def at(self, lap, d, slide=0.02, spin=0.0, temp=80):
        self.car.update(currentLapNum=lap, lapDistance=d)
        tel = {"tyresSurfaceTemperature": [temp, temp, 80, 80], "throttle": 1.0, "brake": 0.0, "speed": 200}
        self.g.on_telemetry({"header": {"playerCarIndex": 0}, "carTelemetryData": [tel]}, self.latest)
        self.g.on_motion({"wheelSlipAngle": [slide, slide, 0, 0], "wheelSlipRatio": [spin, spin, 0, 0]}, self.latest)

    def lap(self, n, **s1):
        for d in range(10, TRACK, 20):
            self.at(n, d, **(s1 if d < 1000 else {}))


class Grip(unittest.TestCase):
    def test_sliding_in_one_sector(self):
        dr = Drive()
        for n in range(1, 6):
            dr.lap(n)
        self.assertEqual(grip.losing(grip.by_sector(dr.g, SPANS, TRACK)), [])
        dr.lap(6, slide=0.04)
        dr.lap(7, slide=0.04)
        rows = grip.by_sector(dr.g, SPANS, TRACK)
        self.assertEqual([r[0] for r in grip.losing(rows)], [1])
        text = "\n".join(grip.summary(dr.g, SPANS, TRACK))
        self.assertIn("rear grip has gone in S1: the rears are sliding more", text)

    def test_wheelspin_and_heat(self):
        dr = Drive()
        for n in range(1, 5):
            dr.lap(n)
        dr.lap(5, spin=0.2, temp=95)
        dr.lap(6, spin=0.2, temp=95)
        rows = grip.by_sector(dr.g, SPANS, TRACK)
        self.assertEqual([r[0] for r in grip.spinning(rows)], [1])
        self.assertEqual([r[0] for r in grip.heating(rows)], [1])

    def test_a_sector_done_this_lap_counts(self):
        dr = Drive()
        for n in range(1, 7):
            dr.lap(n)
        for d in range(10, 1100, 20):
            dr.at(7, d, slide=0.06)
        self.assertEqual([r[0] for r in grip.losing(grip.by_sector(dr.g, SPANS, TRACK))], [1])

    def test_flashback_and_new_set(self):
        dr = Drive()
        for n in range(1, 6):
            dr.lap(n)
        for d in range(10, 900, 20):
            dr.at(6, d, slide=0.3)
        dr.at(5, 2990)  # rewound over the line: lap 6 never happened
        self.assertNotIn(6, dr.g.laps)
        dr.car["numPitStops"] = 1
        dr.lap(6)
        self.assertEqual(grip.by_sector(dr.g, SPANS, TRACK), [])  # one lap on the new set: no baseline yet


if __name__ == "__main__":
    unittest.main()
