"""A small synthetic race pushed through the real decoder and RaceState, then briefed.

Cars (lap 90 s for River):
  0 River JAMES  player, FR wears 3%/lap
  1 TSUNODA      starts 1.5 s behind, 0.2 s/lap quicker -> closing
  2 ALONSO       starts 2.0 s ahead, 0.15 s/lap slower -> River catching
  3 STROLL       starts 30 s behind, stops on lap 4 losing 22 s
"""
import struct
import time
import unittest
from unittest import mock

from engineer import brief, calc, pitstops, race, strategy
from engineer.glance import glance
from engineer.spec import EVENT_DETAILS_SIZE, PACKETS
from engineer.state import RaceState

PACE = {0: 90.0, 1: 89.8, 2: 90.15, 3: 90.0}
START = {0: 0.0, 1: 1.5, 2: -2.0, 3: 30.0}
NAMES = {0: "River JAMES", 1: "TSUNODA", 2: "ALONSO", 3: "STROLL"}
STOP_LAP, STOP_EXTRA = 4, (10.0, 12.0)  # in-lap and out-lap each lose this much


class Hub:
    def publish(self, *_):
        pass


def lap_time(idx, lap):
    t = PACE[idx]
    if idx == 3 and lap in (STOP_LAP, STOP_LAP + 1):
        t += STOP_EXTRA[lap - STOP_LAP]
    return t


def line_time(idx, lap):
    """When car idx starts `lap` (session seconds)."""
    return 10 + START[idx] + sum(lap_time(idx, n) for n in range(1, lap))


class Race:
    def __init__(self):
        self.st = RaceState(Hub())
        self.frame = 0

    def send(self, pid, t, **fields):
        layout = PACKETS[pid]
        data = layout.blank()
        self.frame += 1
        data["header"].update(packetFormat=2026, gameYear=25, packetId=pid, sessionUID=99,
                              sessionTime=t, overallFrameIdentifier=self.frame, playerCarIndex=0)
        for k, v in fields.items():
            data[k] = v
        self.st.ingest(layout.pack(data), ("test", 0))
        return data

    def where(self, idx, t):
        lap = 1
        while line_time(idx, lap + 1) <= t:
            lap += 1
        return lap, max(t - line_time(idx, lap), 0)  # sat on the grid until its start

    def progress(self, idx, t):
        lap, into = self.where(idx, t)
        return lap - 1 + into / lap_time(idx, lap)

    def setup(self):
        s = PACKETS[1].blank()
        s.update(sessionType=15, totalLaps=20, trackLength=5000, trackId=7, numWeatherForecastSamples=2,
                 trackTemperature=31, airTemperature=22)
        s["weatherForecastSamples"][0].update(sessionType=15, timeOffset=0, weather=1, rainPercentage=10)
        s["weatherForecastSamples"][1].update(sessionType=15, timeOffset=15, weather=3, rainPercentage=60)
        self.send(1, 0, **{k: v for k, v in s.items() if k != "header"})
        p = PACKETS[4].blank()
        p["numActiveCars"] = 4
        for idx, name in NAMES.items():
            p["participants"][idx].update(name=name, teamId=idx, driverId=200 + idx)
        self.send(4, 0, **{k: v for k, v in p.items() if k != "header"})
        sets = PACKETS[12].blank()
        sets["carIdx"], sets["fittedIdx"] = 0, 0
        sets["tyreSetData"][0].update(visualTyreCompound=17, actualTyreCompound=18, available=1, fitted=1, lifeSpan=9,
                                      usableLife=21)
        sets["tyreSetData"][1].update(visualTyreCompound=18, actualTyreCompound=19, available=1, lapDeltaTime=-700,
                                      lifeSpan=26, usableLife=26)
        self.send(12, 0, **{k: v for k, v in sets.items() if k != "header"})

    def tick(self, t):
        lap_pkt = PACKETS[2].blank()
        status = PACKETS[7].blank()
        dmg = PACKETS[10].blank()
        order = sorted(PACE, key=lambda i: -self.progress(i, t))
        for idx in PACE:
            lap, into = self.where(idx, t)
            pitted = idx == 3 and lap > STOP_LAP
            lap_pkt["lapData"][idx].update(
                currentLapNum=lap, currentLapTimeInMS=int(into * 1000), resultStatus=2,
                carPosition=order.index(idx) + 1, numPitStops=int(pitted),
                lastLapTimeInMS=int(lap_time(idx, lap - 1) * 1000) if lap > 1 else 0,
                lapDistance=into / PACE[idx] * 5000)
            age = lap - (STOP_LAP + 1) if pitted else lap - 1
            status["carStatusData"][idx].update(visualTyreCompound=18 if pitted else 17,
                                                actualTyreCompound=19 if pitted else 18,
                                                tyresAgeLaps=age, fuelRemainingLaps=30.0, ersStoreEnergy=2e6)
            done = age + into / PACE[idx]
            dmg["carDamageData"][idx]["tyresWear"] = [1.0 * done, 1.0 * done, 2.0 * done, 3.0 * done]
        for pid, pkt in ((7, status), (10, dmg), (2, lap_pkt)):
            self.send(pid, t, **{k: v for k, v in pkt.items() if k != "header"})

    def history(self, t):
        for idx in PACE:
            lap, _ = self.where(idx, t)
            h = PACKETS[11].blank()
            h.update(carIdx=idx, numLaps=lap, bestLapTimeLapNum=1 if lap > 1 else 0)
            for n in range(1, lap):
                ms = int(lap_time(idx, n) * 1000) + (n == 2 and idx == 0) * -300  # River's best is lap 2
                third = ms // 3
                h["lapHistoryData"][n - 1].update(
                    lapTimeInMS=ms, lapValidBitFlags=0xF,
                    sector1TimeMSPart=third, sector2TimeMSPart=third, sector3TimeMSPart=ms - 2 * third)
            if lap > 2:
                h["bestLapTimeLapNum"] = 2
            self.send(11, t, **{k: v for k, v in h.items() if k != "header"})

    def run(self, start, end, step=0.5):
        t = start
        while t <= end:
            self.tick(t)
            if int(t * 2) % 10 == 0:
                self.history(t)
            t += step

    def event(self, t, code, details=b""):
        self.send(3, t, eventStringCode=code, eventDetails=details.ljust(EVENT_DETAILS_SIZE, b"\0"))

    def flashback(self, to):
        details = struct.pack("<If", 0, to).ljust(EVENT_DETAILS_SIZE, b"\0")
        self.send(3, to, eventStringCode="FLBK", eventDetails=details)


def raced(until_lap=8):
    r = Race()
    r.setup()
    r.run(12, line_time(0, until_lap) + 20)
    return r


class Gaps(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = raced()
        cls.st = cls.r.st

    def test_crossing_times_are_back_dated_to_the_line(self):
        x = self.st.laps.at(0, 5)
        self.assertAlmostEqual(x["t"], line_time(0, 5), places=2)

    def test_gap_and_trend_behind(self):
        g = calc.gaps(self.st.laps, 0, [1, 2, 3])
        self.assertAlmostEqual(g[1]["gap"], 1.5 - 0.2 * 7, places=2)
        self.assertAlmostEqual(g[1]["trend"], -0.2, places=2)

    def test_gap_and_trend_ahead(self):
        g = calc.gaps(self.st.laps, 0, [1, 2, 3])
        self.assertAlmostEqual(g[2]["gap"], -2.0 + 0.15 * 7, places=2)
        self.assertAlmostEqual(g[2]["trend"], 0.15, places=2)

    def live(self, *order, pitting=()):
        """Lap data as the game sends it now: (car, seconds behind the leader) in running order."""
        cars = PACKETS[2].blank()["lapData"]
        for pos, (idx, secs) in enumerate(order, 1):
            cars[idx].update(deltaToRaceLeaderMinutesPart=int(secs // 60), deltaToRaceLeaderMSPart=round(secs % 60 * 1000),
                             pitStatus=int(idx in pitting), resultStatus=2, carPosition=pos)
        return cars

    def test_the_gap_now_comes_from_the_live_timing(self):
        # Tsunoda has just got past: the line gap still says behind, the live timing says 0.4 ahead
        line = calc.gaps(self.st.laps, 0, [1, 2])
        g = calc.gaps(self.st.laps, 0, [1, 2], live=self.live((2, 0.0), (1, 0.6), (0, 1.0)))
        self.assertAlmostEqual(g[1]["gap"], -0.4, places=3)
        self.assertAlmostEqual(g[2]["gap"], -1.0, places=3)  # the leader's own 0 counts
        self.assertEqual((g[1]["trend"], g[1]["last"]), (line[1]["trend"], line[1]["last"]))

    def test_the_race_snapshot_reads_the_live_timing(self):
        latest = self.st.latest[2]
        saved = latest["lapData"]
        latest["lapData"] = [dict(c) for c in saved]
        try:
            for idx, c in enumerate(self.live((2, 0.0), (1, 0.6), (0, 1.0))[:3]):
                latest["lapData"][idx].update(c)
            self.assertAlmostEqual(race.Race(self.st).gaps[1]["gap"], -0.4, places=3)
        finally:
            latest["lapData"] = saved

    def test_a_car_ahead_on_timing_before_its_place_changes(self):
        cars = self.live((2, 0.0), (0, 1.0))
        cars[0].update(deltaToRaceLeaderMinutesPart=0, deltaToRaceLeaderMSPart=65520)  # 16 ms ahead, still P2
        self.assertAlmostEqual(calc.to_leader(cars, 0), -0.016, places=3)
        cars[0].update(deltaToCarInFrontMinutesPart=1, deltaToCarInFrontMSPart=5500)
        self.assertEqual(calc.delta_ms(cars[0], "deltaToCarInFront"), 65500)  # a real 1:05.5

    def test_no_live_time_falls_back_to_the_line(self):
        line = calc.gaps(self.st.laps, 0, [1, 2])
        g = calc.gaps(self.st.laps, 0, [1, 2], live=self.live((2, 0.0), (1, 0.6), (0, 1.0), pitting=[1]))
        self.assertEqual(g[1]["gap"], line[1]["gap"])  # in the pit lane the game sends 0
        g = calc.gaps(self.st.laps, 0, [1, 2], live=self.live((0, 0.0), (2, 0.0), (1, 2.0)))
        self.assertEqual(g[2]["gap"], line[2]["gap"])  # 0 but not leading: not timed
        self.assertAlmostEqual(g[1]["gap"], 2.0, places=3)

    def test_trend_ignores_laps_across_a_stop(self):
        g = calc.gaps(self.st.laps, 0, [3])[3]
        self.assertAlmostEqual(g["trend"], 0.0, places=2)  # same pace after the stop

    def test_no_gap_from_a_crossing_made_in_the_pit_lane(self):
        x = self.st.laps.at(1, self.st.laps.cars[1][-1]["lap"])
        x["pit"] = True  # a car crossing the line in the pit lane, mid-stop
        try:
            self.assertNotIn(1, calc.gaps(self.st.laps, 0, [1, 2]))
            self.assertIn(2, calc.gaps(self.st.laps, 0, [1, 2]))
        finally:
            x["pit"] = False

    def test_wear_rate(self):
        rates = calc.wear_rates(self.st.laps.cars[0])
        self.assertAlmostEqual(rates[3], 3.0, places=1)  # FR

    def test_no_wear_rate_until_the_new_set_has_laps(self):
        xs = self.st.laps.cars[0]
        stops = xs[-1]["stops"]
        self.assertIsNotNone(calc.wear_rates(xs, stops=stops))
        self.assertIsNone(calc.wear_rates(xs, stops=stops + 1))  # just stopped: the rate would be the old set's

    def test_no_wear_rate_from_a_set_changed_in_the_garage(self):
        xs = self.st.laps.cars[0]
        tyre, age = xs[-1]["tyre"], xs[-1]["age"]
        self.assertIsNotNone(calc.wear_rates(xs, fitted=(tyre, age)))
        self.assertIsNone(calc.wear_rates(xs, fitted=(tyre + 1, 0)))  # practice: no stop counted, another compound
        self.assertIsNone(calc.wear_rates(xs, fitted=(tyre, 0)))  # the same compound, a new set
        b = race.Race(self.st)
        self.assertIsNotNone(strategy.stint_rates(b))
        status = b.status()
        status["visualTyreCompound"] += 1
        try:
            self.assertIsNone(strategy.stint_rates(b))
        finally:
            status["visualTyreCompound"] -= 1

    def test_the_fastest_lap_of_the_race(self):
        r = raced()
        self.assertIn("fastest lap of the race 1:29.700 (yours, L2)", brief.build(r.st))
        r.st.history[1]["lapHistoryData"][1]["lapTimeInMS"] = 89_500
        self.assertIn("fastest lap of the race 1:29.500 (TSUNODA, L2)", brief.build(r.st))
        for h in r.st.history.values():
            h["bestLapTimeLapNum"] = 0  # no valid lap yet
        self.assertNotIn("fastest lap", brief.build(r.st))

    def test_where_he_started_and_that_the_race_is_over(self):
        r = raced()
        me = r.st.latest[2]["lapData"][0]
        me["gridPosition"] = 3
        text = brief.build(r.st)
        self.assertIn("(started P3)", text)
        self.assertNotIn("chequered flag", text)
        me["resultStatus"] = 3
        self.assertIn("you've taken the chequered flag", brief.build(r.st))

    def test_pit_loss_from_observed_stop(self):
        loss, n = calc.pit_loss(self.st.laps, self.st.history)
        self.assertEqual(n, 1)
        self.assertAlmostEqual(loss, 22.0, places=1)

    def test_earlier_races_here_stand_in_until_two_stops_this_race(self):
        with mock.patch.object(pitstops, "here", return_value=(19.5, 20, 1)):
            text = brief.build(self.st)
        self.assertIn("green-flag loss ≈19.5s (over 20 stops in 1 earlier race here; the 1 stop this race said 22.0s)", text)

    def test_the_shipped_figure_only_with_no_stop_of_his_own(self):
        with mock.patch.object(calc, "pit_loss", return_value=None), mock.patch.object(pitstops, "usual", return_value=(21.5, 20)):
            text = brief.build(self.st)
        self.assertIn("green-flag loss ≈21.5s (a rule of thumb: what a stop here usually costs in F1 25, 20 stops measured;", text)
        self.assertNotIn("rejoin estimate,", text)
        with mock.patch.object(calc, "pit_loss", return_value=None), mock.patch.object(pitstops, "usual", return_value=(20.3, None)):
            self.assertIn("≈20.3s (a rule of thumb: what a stop usually costs in F1 25; none measured at this track)", brief.build(self.st))
        with mock.patch.object(pitstops, "usual", return_value=(21.5, 20)):
            self.assertIn("loss ≈22.0s (from 1 stop this race)", brief.build(self.st))
        me = self.st.latest[7]["carStatusData"][0]
        self.addCleanup(me.update, visualTyreCompound=me["visualTyreCompound"])
        me["visualTyreCompound"] = 7  # inters: the shipped figure is a dry one
        with mock.patch.object(calc, "pit_loss", return_value=None), mock.patch.object(pitstops, "usual", return_value=(21.5, 20)):
            self.assertIn("loss not measured yet (no stops seen)", brief.build(self.st))

    def test_rejoin(self):
        pos, ahead, behind = calc.rejoin(calc.gaps(self.st.laps, 0, [1, 2, 3]), 22.0)
        self.assertEqual((pos, ahead[0], behind[0]), (3, 1, 3))

    def test_brief_spells_out_trends_and_projections(self):
        text = brief.build(self.st)
        self.assertIn("TSUNODA", text)
        self.assertIn("closing on you 0.20/lap", text)
        self.assertIn("you are catching 0.15/lap", text)
        self.assertIn("loss ≈22.0s (from 1 stop this race)", text)
        self.assertIn("rain likely from +15m ≈ lap", text)
        self.assertIn("rain plan: stay out and stop once for inters at L18", text)
        self.assertIn("staying out saves ≈16s · your FR ≈52% by L18 · only 60% likely", text)
        self.assertIn("fastest-wearing FR +3.0%/lap", text)
        self.assertIn("undercut range ≈1.4s", text)
        self.assertIn("could undercut you: TSUNODA · you could undercut: ALONSO", text)
        self.assertIn("FR reaches 70% (worn out) in ≈16 laps, L24 — after the flag", text)
        self.assertIn("fuel   +30.0 laps vs target", text)

    def test_the_stop_line_names_the_sets_he_can_fit_and_what_the_field_took(self):
        text = brief.build(self.st)
        self.assertIn("(12 laps after it; the second compound is still owed, so not Medium;", text)
        self.assertIn("Hard new 0.70 s/lap quicker, ≈29% at the flag", text)  # FR 3%/lap × 21/26 × 12
        self.assertIn("→ Hard new: the quickest that reaches the flag under 70% (worn out)", text)
        self.assertIn("cars that have stopped, now on: Hard ×1 · not stopped yet, within 3 places of you: Medium ×2", text)

    def test_the_stop_line_says_why_not_the_quicker_set(self):
        soft = {"compound": 16, "wear": 5, "gain": 2.17, "at_flag": 71.4, "lasts": False}
        hard = {"compound": 18, "wear": 0, "gain": 1.22, "at_flag": 43.0, "lasts": True}
        p = {"options": [soft, hard], "pick": hard, "left": 12, "owed": True, "run": {17}, "wheel": 3}
        with mock.patch.object(strategy, "dry_stop", return_value=p):
            self.assertIn("→ Hard new: the quickest that reaches the flag under 70% (worn out); "
                          "the Soft used 5% is 0.95 s/lap quicker but reaches ≈71%", brief.build(self.st))
        with mock.patch.object(strategy, "dry_stop", return_value={**p, "pick": soft}):
            self.assertIn("→ Soft used 5%: the quickest that reaches the flag under 70% (worn out), "
                          "0.95 s/lap quicker than the Hard new", brief.build(self.st))
        with mock.patch.object(strategy, "dry_stop", return_value=None):
            self.assertNotIn("\nSTOP", brief.build(self.st))
        with mock.patch.object(strategy, "dry_stop", return_value={**p, "pick": None}):
            self.assertIn("→ none of them reaches the flag under 70% (worn out) from this lap", brief.build(self.st))
        no_rate = [{**soft, "at_flag": None, "lasts": True}, {**hard, "at_flag": None, "lasts": False, "gain": -0.3}]
        with mock.patch.object(strategy, "dry_stop", return_value={**p, "options": no_rate, "pick": no_rate[0], "wheel": None, "owed": False}):
            self.assertIn("(12 laps after it; any set; pace = the set's estimate vs your fitted set; life = the set's own estimate): "
                          "Soft used 5% 2.17 s/lap quicker, lasts · Hard new 0.30 s/lap slower, short", brief.build(self.st))

    def test_feed_lost_is_flagged_only_after_a_long_silence(self):
        st = self.st
        was = st.last_packet_at
        try:
            st.last_packet_at = time.time() - 60  # a pause: the state is still right
            self.assertNotIn("FEED LOST", brief.build(st))
            st.last_packet_at = time.time() - 1800
            self.assertIn("FEED LOST  no data from the car for 30:00", brief.build(st))
            self.assertGreater(glance(st)["silentSecs"], 1700)
        finally:
            st.last_packet_at = was

    def test_race_tab_shows_the_same_numbers(self):
        g = glance(self.st)
        self.assertEqual((g["ahead"]["name"], g["behind"]["name"]), ("ALONSO", "TSUNODA"))
        self.assertEqual(g["behind"]["trend"], "closing on you 0.20/lap")
        self.assertTrue(g["behind"]["closing"] and g["ahead"]["closing"])
        self.assertEqual(g["me"]["tyre"]["corners"], ["FL", "FR", "RL", "RR"])
        self.assertAlmostEqual(g["me"]["tyre"]["rate"][1], 3.0, places=1)  # FR


class Stops(unittest.TestCase):
    def test_loss_read_off_the_rejoin_estimate_uses_sorted_gaps(self):
        gaps = {i: {"gap": g} for i, g in enumerate([8.4, 10.2, 21.7, 20.7, 21.1, -3.0])}
        # P2 now, rejoin P5: three cars behind get past -> between the 3rd and 4th smallest gap
        self.assertEqual(calc.loss_from_rejoin(gaps, 2, 5), (20.7, 21.1))
        self.assertEqual(calc.loss_from_rejoin(gaps, 2, 7), (21.7, None))
        self.assertIsNone(calc.loss_from_rejoin(gaps, 2, 2))

    def test_free_stop_lap(self):
        self.assertEqual(calc.free_stop_lap(8.4, 1.0, 22.0, 6, 20), 20)
        self.assertIsNone(calc.free_stop_lap(8.4, 0.7, 22.0, 6, 20))
        self.assertEqual(calc.free_stop_lap(23.0, -0.5, 22.0, 6, 20), 6)
        self.assertIsNone(calc.free_stop_lap(8.4, -0.2, 22.0, 6, 20))


class SafetyCar(unittest.TestCase):
    def test_stop_under_sc_is_not_a_pit_loss_sample(self):
        r = raced()
        stroll = r.st.laps.cars[3]
        for x in stroll:
            if x["lap"] in (STOP_LAP + 1, STOP_LAP + 2):  # laps 4 and 5 ran under SC
                x["scLap"] = True
        self.assertEqual(r.st.laps.sc_laps(3), {STOP_LAP, STOP_LAP + 1})
        self.assertIsNone(calc.pit_loss(r.st.laps, r.st.history))

    def test_an_out_lap_under_sc_is_not_measured_from_the_laps_before(self):
        # Monza's red flag: the in-lap green, the out-lap under SC; the lap before and the in-lap said ≈7 s
        r = raced()
        for x in r.st.laps.cars[3]:
            x["scLap"] = x["lap"] == STOP_LAP + 2
        self.assertEqual(r.st.laps.sc_laps(3), {STOP_LAP + 1})
        self.assertIsNone(calc.pit_loss(r.st.laps, r.st.history))


class Flashback(unittest.TestCase):
    def test_rewind_drops_later_laps_and_rerecords_them(self):
        r = raced(6)
        before = [x["lap"] for x in r.st.laps.cars[0]]
        to = line_time(0, 5) - 30  # back into lap 4
        r.flashback(to)
        self.assertEqual(r.st.laps.cars[0][-1]["lap"], 4)
        r.run(to, line_time(0, 6) + 20)
        self.assertEqual([x["lap"] for x in r.st.laps.cars[0]], before)
        g = calc.gaps(r.st.laps, 0, [1])[1]
        self.assertAlmostEqual(g["trend"], -0.2, places=2)

    def test_lap_regression_without_event_still_prunes(self):
        r = raced(6)
        r.run(line_time(0, 5) - 30, line_time(0, 5) - 29)
        self.assertEqual(r.st.laps.cars[0][-1]["lap"], 4)


if __name__ == "__main__":
    unittest.main()
