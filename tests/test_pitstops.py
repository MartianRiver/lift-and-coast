"""Pit loss per track from the archive: which laps are the stop, and which stops count as green-flag."""
import json
import sqlite3
import unittest

from engineer import archive, calc, pitstops

PACE = 90_000


def times(extra, n=20, pace=PACE):
    """{lap: ms} at `pace`, plus `extra` {lap: ms}."""
    return {lap: pace + extra.get(lap, 0) for lap in range(1, n + 1)}


class StopLoss(unittest.TestCase):
    def test_in_and_out_lap_wherever_the_box_is(self):
        t = times({8: 3000, 9: 16000})
        self.assertEqual(calc.stop_loss(t, (7, 8, 9)), (19.0, 8))
        self.assertEqual(calc.stop_loss(t, (8, 9, 10)), (19.0, 8))

    def test_measured_against_the_laps_either_side(self):
        # dying tyres before (+1.5 s), fresh after (-0.5 s): the old pace alone would hide 2 s of it
        t = times({6: 1500, 7: 1500, 8: 3000 + 1500, 9: 16000 - 500, 10: -500, 11: -500})
        loss, _ = calc.stop_loss(t, (7, 8, 9))
        self.assertAlmostEqual(loss, 200 - 2 * 90.5, places=3)  # 94.5 + 105.5 against 91.5/91.5/89.5/89.5
        del t[10], t[11]  # not run yet: the laps before stand in
        loss, _ = calc.stop_loss(t, (7, 8, 9))
        self.assertAlmostEqual(loss, 200 - 2 * 91.5, places=3)

    def test_nothing_that_looks_like_a_stop(self):
        self.assertIsNone(calc.stop_loss(times({}), (7, 8, 9)))


class Archive(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.executescript(archive.SCHEMA)

    def race(self, uid, started, cars, events=(), track_id=10):
        self.db.execute("insert into sessions (uid, started_at, track, track_id, type, formula, regs2026) "
                        "values (?, ?, 'Spa', ?, 'Race', 0, 0)", (uid, started, track_id))
        for idx, (laps, stints) in enumerate(cars):
            self.db.execute("insert into results (session_uid, car_idx, driver, stops, stints) values (?, ?, ?, ?, ?)",
                            (uid, idx, f"CAR{idx}", len(stints) - 1, json.dumps(stints)))
            self.db.executemany("insert into laps (session_uid, car_idx, lap, lap_ms) values (?, ?, ?, ?)",
                                [(uid, idx, n, ms) for n, ms in laps.items()])
        self.db.executemany("insert into events (session_uid, t, session_time, code, details) values (?, ?, ?, ?, ?)",
                            [(uid, t, st, code, json.dumps(d)) for t, st, code, d in events])

    def test_stint_end_lap_is_the_lap_before_the_in_lap(self):
        self.race("1", "2026-10-14 10:00", [(times({9: 2000, 10: 17000}), [[8, "Medium"], [255, "Hard"]])])
        (s,) = pitstops.measure(self.db, "1")
        self.assertEqual((s["lap"], s["loss"], s["kind"]), (9, 19.0, "green"))

    def test_stops_under_the_safety_car_are_kept_apart(self):
        sc = [(0, 9 * 90 - 30, "SCAR", {"safetyCarType": 1, "eventType": 0}),
              (1, 12 * 90, "SCAR", {"safetyCarType": 1, "eventType": 2})]
        stop = (times({9: 2000, 10: 17000}), [[8, "Medium"], [255, "Hard"]])
        self.race("1", "2026-10-14 10:00", [stop], sc)
        self.assertEqual(pitstops.measure(self.db, "1")[0]["kind"], "sc")

    def test_an_out_lap_under_the_safety_car_is_not_a_green_flag_sample(self):
        # Monza: in-lap 9 green, out-lap 10 under the red flag's SC; laps 8 + 9 alone said ≈7 s
        sc = [(0, 9 * 90 + 10, "SCAR", {"safetyCarType": 1, "eventType": 0}),
              (1, 9 * 90 + 40, "SCAR", {"safetyCarType": 1, "eventType": 2})]
        self.race("1", "2026-10-14 10:00", [(times({8: 500, 9: 7000, 10: 90000}), [[8, "Medium"], [255, "Hard"]])], sc)
        self.assertEqual([s["kind"] for s in pitstops.measure(self.db, "1")], [])  # 180 s out-lap: no sample at all

    def test_a_safety_car_a_flashback_took_back_does_not_count(self):
        events = [(0, 9 * 90 - 30, "SCAR", {"safetyCarType": 1, "eventType": 0}),
                  (1, 9 * 90 - 20, "FLBK", {"flashbackSessionTime": 9 * 90 - 40})]
        self.race("1", "2026-10-14 10:00", [(times({9: 2000, 10: 17000}), [[8, "Medium"], [255, "Hard"]])], events)
        self.assertEqual(pitstops.measure(self.db, "1")[0]["kind"], "green")

    def test_slicks_to_inters_is_not_a_green_flag_sample(self):
        self.race("1", "2026-10-14 10:00", [(times({9: 2000, 10: 17000}), [[8, "Medium"], [255, "Inter"]])])
        self.assertEqual(pitstops.measure(self.db, "1")[0]["kind"], "weather")

    def test_a_resumed_save_counts_each_stop_once_and_only_earlier_races(self):
        stop = (times({9: 2000, 10: 17000}), [[8, "Medium"], [255, "Hard"]])
        self.race("1", "2026-10-14 10:00", [stop])
        self.race("2", "2026-10-14 10:30", [stop])  # the same race resumed: history repeats its laps
        self.race("3", "2026-10-14 11:00", [(times({9: 2000, 10: 21000}), [[8, "Medium"], [255, "Hard"]])])
        t = pitstops.by_track(self.db, track_id=10)["Spa"]
        self.assertEqual((sorted(t["green"]), t["races"]), ([19.0, 23.0], 2))
        t = pitstops.by_track(self.db, track_id=10, before="2026-10-14 11:00")["Spa"]
        self.assertEqual(t["green"], [19.0])


if __name__ == "__main__":
    unittest.main()
