"""Drying track: when the rain eases, which slick to box for, and what slicks are really doing."""
import unittest
from types import SimpleNamespace
from unittest import mock

from engineer import calc, race, strategy

INTER, SOFT, MEDIUM, HARD = 7, 16, 17, 18


def brief(forecast, sets, lap=5, total=15, fitted=INTER):
    s = {"sessionType": 15, "totalLaps": total, "trackLength": 7000, "numWeatherForecastSamples": len(forecast),
         "weatherForecastSamples": [{"sessionType": 15, "timeOffset": m, "weather": w, "rainPercentage": p}
                                    for m, w, p in forecast]}
    tyre_sets = {"tyreSetData": [{"visualTyreCompound": c, "available": 1, "lapDeltaTime": d, "lifeSpan": life}
                                 for c, d, life in sets], "fittedIdx": 0}
    st = SimpleNamespace(tyre_sets={0: tyre_sets}, latest={7: {"carStatusData": [{"visualTyreCompound": fitted}]}},
                         laps=SimpleNamespace(cars={}, sc_laps=lambda idx: set()))
    return SimpleNamespace(s=s, st=st, me=0, race=True, ref_ms=124_000, active=lambda: [0],
                           my={"currentLapNum": lap, "lapDistance": 3500, "pitStatus": 0},
                           status=lambda idx=0: st.latest[7]["carStatusData"][idx])


SPA_L5 = [(0, 3, 61), (5, 2, 28), (10, 2, 14), (15, 1, 9), (30, 1, 13)]  # Spa race 2, mid-lap 5


class Drying(unittest.TestCase):
    def test_rain_easing_with_none_after(self):
        sample, lap, again = strategy.easing(brief(SPA_L5, []))
        self.assertEqual((sample["timeOffset"], lap, again), (5, 7, False))
        self.assertIsNone(strategy.easing(brief([(0, 3, 80), (5, 3, 70)], [])))  # raining all through

    def test_quickest_slick_that_lasts(self):
        # Spa L6: softs quickest but ~8 laps of life for 9 left; mediums it is
        b = brief(SPA_L5, [(INTER, 0, 14), (SOFT, -2700, 8), (MEDIUM, -2300, 12), (HARD, -1400, 18)], lap=6)
        p = strategy.slicks(b)
        self.assertEqual((p["pick"][0], p["left"]), (MEDIUM, 9))
        self.assertEqual(strategy.slick_call(b), (MEDIUM, 2.3, 9, 0))

    def test_no_call_while_slicks_are_still_slower_or_marginal(self):
        b = brief(SPA_L5, [(INTER, 0, 14), (MEDIUM, 400, 12), (HARD, 1300, 18)])
        self.assertIsNone(strategy.slick_call(b))
        b = brief(SPA_L5, [(INTER, 0, 14), (MEDIUM, -700, 12)])
        self.assertIsNone(strategy.slick_call(b))  # quicker, but not by enough to pay for a cold out-lap
        self.assertIsNone(strategy.slicks(brief(SPA_L5, [(MEDIUM, -700, 12)], fitted=MEDIUM)))  # already on slicks


class Measured(unittest.TestCase):
    def test_slick_laps_against_inter_laps_on_the_same_lap(self):
        laps = SimpleNamespace(cars={}, sc_laps=lambda idx: set())
        laps.at = lambda idx, n: next((x for x in laps.cars.get(idx, []) if x["lap"] == n), None)

        def car(idx, tyres, times, stop_after=None):
            laps.cars[idx] = [{"lap": n, "tyre": tyres[n - 1], "stops": int(stop_after is not None and n > stop_after),
                               "pit": n == (stop_after or 0) + 1, "lastMs": times.get(n - 1, 0)} for n in range(1, 9)]

        for idx in (1, 2):  # boxed for hards at the end of L4: out-lap 5, clean from L6
            car(idx, [INTER] * 4 + [HARD] * 4, {n: 117_000 if n >= 6 else 124_000 for n in range(1, 8)}, stop_after=4)
        car(0, [INTER] * 8, {n: 123_000 for n in range(1, 8)})
        n, slick, wet, nd, nw = calc.slicks_vs_wets(laps, [0, 1, 2])
        self.assertEqual((n, slick, wet, nd, nw), (7, 117.0, 123.0, 2, 1))


def stop_at(sets, rate=4.5, **kw):
    with mock.patch.object(calc, "wear_rates", return_value=rate and [1.0, rate, 1.0, 1.0]):
        return strategy.dry_stop(brazil(sets, **kw))


def brazil(sets=(), lap=13, total=25, run=(), weekend=(15,), kind=15, rr=50.0, pit=0, fitted=MEDIUM):
    """Brazil L13: 11 laps on a Medium (usable life 21), RR 50%, no stop yet."""
    data = [{"visualTyreCompound": MEDIUM, "available": 1, "lapDeltaTime": 0, "lifeSpan": 8, "usableLife": 21, "wear": 42}]
    data += [{"visualTyreCompound": c, "available": 1, "lapDeltaTime": d, "lifeSpan": life, "usableLife": usable, "wear": w}
             for c, d, life, usable, w in sets]
    hist = {"numTyreStints": len(run) + 1, "tyreStintsHistoryData": [{"tyreVisualCompound": c} for c in (*run, fitted)]}
    st = SimpleNamespace(tyre_sets={0: {"tyreSetData": data, "fittedIdx": 0}}, history={0: hist},
                         laps=SimpleNamespace(cars={0: []}))
    s = {"totalLaps": total, "sessionType": kind, "weekendStructure": list(weekend), "numSessionsInWeekend": len(weekend)}
    b = SimpleNamespace(st=st, s=s, me=0, race=True, my={"currentLapNum": lap, "pitStatus": pit, "numPitStops": 0},
                        status=lambda idx=0: {"visualTyreCompound": fitted, "tyresAgeLaps": 3},
                        damage=lambda: {"tyresWear": [20, rr, 20, 20]})
    b.sprint = lambda: race.Race.sprint(b)
    b.laps_left = lambda: total - lap
    return b


BRAZIL = [(SOFT, -2169, 15, 17, 5), (SOFT, -1701, 14, 17, 11), (MEDIUM, -1794, 21, 21, 0), (HARD, -1224, 26, 26, 0)]


class DryStop(unittest.TestCase):
    def test_the_quickest_set_that_reaches_the_flag(self):
        p = stop_at(BRAZIL)
        self.assertEqual([o["compound"] for o in p["options"]], [SOFT, HARD])  # a second Medium wouldn't count
        soft, hard = p["options"]
        self.assertEqual(soft["wear"], 5)  # the less worn Soft
        self.assertAlmostEqual(soft["at_flag"], 5 + 4.5 * 21 / 17 * 12)  # ≈71.7: over WORN
        self.assertIs(p["pick"], hard)
        self.assertAlmostEqual(hard["at_flag"], 4.5 * 21 / 26 * 12)

    def test_fewer_laps_left_and_the_soft_makes_it(self):
        self.assertEqual(stop_at(BRAZIL, lap=15)["pick"]["compound"], SOFT)  # 5 + 5.56 × 10 ≈ 60.6

    def test_nothing_to_say_once_the_rule_is_met_and_the_set_lasts(self):
        self.assertIsNone(stop_at(BRAZIL, run=(SOFT,), rr=20.0, rate=2.0))
        self.assertIsNone(stop_at(BRAZIL, run=(INTER,), rr=20.0, rate=2.0))  # inters lift the rule
        self.assertIsNone(stop_at(BRAZIL, pit=1))  # in the pit lane: too late to choose
        p = stop_at(BRAZIL, run=(SOFT,))  # rule met, but the RR won't last: any set, a Medium too
        self.assertIn(MEDIUM, [o["compound"] for o in p["options"]])
        self.assertFalse(p["owed"])

    def test_a_sprint_owes_no_second_compound(self):
        weekend = (10, 15, 5, 16)  # the sprint is the weekend's first race
        self.assertIsNone(stop_at(BRAZIL, weekend=weekend, rr=20.0, rate=2.0))
        self.assertFalse(stop_at(BRAZIL, weekend=weekend)["owed"])
        self.assertTrue(stop_at(BRAZIL, weekend=weekend, kind=16)["owed"])  # the main race does

    def test_a_second_compound_owed_only_in_a_dry_main_race(self):
        self.assertTrue(strategy.stop_owed(brazil()))
        self.assertFalse(strategy.stop_owed(brazil(run=(SOFT,))))
        self.assertFalse(strategy.stop_owed(brazil(run=(INTER,))))
        self.assertFalse(strategy.stop_owed(brazil(fitted=INTER)))  # inters all race
        self.assertFalse(strategy.stop_owed(brazil(weekend=(10, 15, 5, 16))))  # the sprint

    def test_no_wear_rate_falls_back_on_the_sets_life(self):
        p = stop_at(BRAZIL, rate=None)
        self.assertIsNone(p["options"][0]["at_flag"])
        self.assertEqual(p["pick"]["compound"], SOFT)  # 15 laps ≥ 12 × LIFE_MARGIN


class Target(unittest.TestCase):
    """Silverstone L11: RL 37%, 4.5%/lap, the extra over the field in S3."""
    def target(self, lap, save):
        b = SimpleNamespace(damage=lambda: {"tyresWear": [37, 10, 10, 10]}, st=SimpleNamespace(laps=SimpleNamespace(cars={})),
                            me=0, my={"currentLapNum": 11, "numPitStops": 0}, status=lambda: None)
        with mock.patch.object(calc, "wear_rates", return_value=[4.5, 1, 1, 1]), \
                mock.patch.object(strategy, "_saving", return_value=([3], False, save)):
            return strategy.target(b, lap)

    def test_makes_it(self):
        t = self.target(16, 1.5)
        self.assertLess(t["at"], strategy.WORN)
        self.assertIn("it makes it", strategy.target_text(t, "the planned stop"))

    def test_laps_of_saving(self):
        t = self.target(19, 1.5)  # 37 + 9 × 4.5 = 77.5: 7.5 over, 1.5 a lap saved
        self.assertEqual((t["manage"], t["worn"]), (5, 18))
        self.assertIn("in S3 saves 1.5%/lap: about 5 laps", strategy.target_text(t, "the planned stop"))

    def test_saving_cant_get_there(self):
        t = self.target(19, 0.5)
        self.assertIsNone(t["manage"])
        self.assertIn("the stop has to come by L18", strategy.target_text(t, "the planned stop"))


if __name__ == "__main__":
    unittest.main()
