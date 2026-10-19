"""The quick brief on the second button: what it says in each kind of session."""
import unittest
from unittest import mock

from engineer import calc, quick
from engineer.state import RaceState
from tests.test_brief import Hub, raced


class Quick(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = raced(8)

    def setUp(self):
        self.s = self.r.st.latest[1]
        kind, sc, laps = self.s["sessionType"], self.s["safetyCarStatus"], self.r.st.latest[2]["lapData"]
        order = {i: laps[i]["carPosition"] for i in range(4)}

        def restore():
            self.s["sessionType"], self.s["safetyCarStatus"] = kind, sc
            for i, pos in order.items():
                laps[i]["carPosition"] = pos
        self.addCleanup(restore)

    def test_race_gaps_either_side_and_the_worst_tyre(self):
        said = quick.brief(self.r.st)
        self.assertEqual((said["topic"], said["lap"]), ("quick", 8))
        self.assertEqual(said["text"], "P2. Alonso ahead, 0.9, you're catching 0.2 a lap. "
                                       "Tsunoda behind, 0.1, closing 0.2 a lap. Front-right 22%.")

    def test_practice_last_lap_against_best(self):
        self.s["sessionType"] = 3
        self.assertEqual(quick.brief(self.r.st)["text"], "Last lap 1:30.000, 0.300 off your best. Front-right 22%.")
        me = self.r.st.latest[2]["lapData"][0]
        last, me["lastLapTimeInMS"] = me["lastLapTimeInMS"], me["lastLapTimeInMS"] - 300
        self.addCleanup(me.update, lastLapTimeInMS=last)
        self.assertEqual(quick.brief(self.r.st)["text"], "Last lap 1:29.700, your best. Front-right 22%.")

    def test_quali_where_you_stand(self):
        self.s["sessionType"] = 12
        laps = self.r.st.latest[2]["lapData"]
        mine, top = laps[0]["carPosition"], next(i for i in range(4) if laps[i]["carPosition"] == 1)
        laps[0]["carPosition"], laps[top]["carPosition"] = 1, mine  # the game orders quali by best lap
        self.assertRegex(quick.brief(self.r.st)["text"], r"^P1, 0\.\d{3} clear of \w+\. Last lap 1:30\.000, 0\.300 off your best\.$")

    def test_nothing_before_the_game_sends_anything(self):
        self.assertIsNone(quick.brief(RaceState(Hub())))

    def test_flags_come_first(self):
        self.s["safetyCarStatus"] = 1
        self.assertTrue(quick.brief(self.r.st)["text"].startswith("P2. Safety car. Alonso ahead"))
        r = raced(3)
        r.event(r.st.latest[2]["header"]["sessionTime"] + 1, "RDFL")
        self.assertEqual(quick.brief(r.st)["text"], "Red flag.")

    def test_a_gap_going_the_other_way(self):
        self.assertEqual(quick._moving({"gap": 1.2, "last": 0.3}), ", dropping back")
        self.assertEqual(quick._moving({"gap": -1.2, "last": -0.3}), ", pulling away")
        self.assertEqual(quick._moving({"gap": 1.2, "last": 0.05}), "")

    def test_little_to_go_on(self):
        with mock.patch.object(quick.Race, "damage", lambda b, idx=None: None):
            self.assertNotIn("%", quick.brief(self.r.st)["text"])
        self.s["sessionType"] = 12
        with mock.patch.object(calc, "best_ms", lambda hist: None):
            self.assertEqual(quick.brief(self.r.st)["text"], "P2, no time yet. Last lap 1:30.000.")
            self.r.st.latest[2]["lapData"][0]["lastLapTimeInMS"], last = 0, self.r.st.latest[2]["lapData"][0]["lastLapTimeInMS"]
            self.assertEqual(quick.brief(self.r.st)["text"], "P2, no time yet.")  # quali, still on the out-lap
            self.s["sessionType"] = 3
            self.assertTrue(quick.brief(self.r.st)["text"].startswith("No lap time yet. "))  # practice, then the worst tyre
            self.r.st.latest[2]["lapData"][0]["lastLapTimeInMS"] = last
        mine = calc.best_ms(self.r.st.history.get(0))
        with mock.patch.object(calc, "best_ms", lambda hist: mine if hist is self.r.st.history.get(0) else None):
            self.s["sessionType"] = 12
            self.assertTrue(quick.brief(self.r.st)["text"].startswith("P2. Last lap"))  # nobody else has a time

    def test_nothing_while_spectating(self):
        header = self.r.st.latest[2]["header"]
        header["playerCarIndex"] = 255
        self.addCleanup(header.update, playerCarIndex=0)
        self.assertIsNone(quick.brief(self.r.st))
