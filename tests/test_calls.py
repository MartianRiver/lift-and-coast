"""Unprompted calls: what's worth a call, and that delivery waits for a straight."""
import unittest
from unittest.mock import patch

from engineer import calls
from engineer.calls import Caller, common, gaps
from engineer.calls.scan import SETTLE, scan
from engineer.race import Race
from engineer.spec import PACKETS
from tests import radio_rows
from tests.test_brief import Hub, raced


class Rival(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.b = Race(raced(4).st)

    def text(self, **g):
        self.b.gaps[1] = {"gap": 5.2, "trend": -0.4, "trendLaps": 3, "last": -0.7, **g}
        return gaps.rival(self.b, 1, 3)

    def test_closing_car_gets_a_flag_projection(self):
        kind, words = self.text()
        self.assertEqual(kind, "flag")
        self.assertIn("closing, 0.4 a lap and 5.2 back", words)
        self.assertIn("About 4.0 at the flag", words)

    def test_one_quick_lap_is_not_a_trend(self):
        self.assertIsNone(self.text(trend=None, trendLaps=1, last=-2.6))
        self.assertIsNone(self.text(trend=-0.05, last=-2.6))  # last lap alone would say 2.6

    def test_catch_before_the_flag_names_the_lap_count(self):
        kind, words = self.text(gap=3.3, trend=-1.8, last=-1.8)
        self.assertEqual(kind, "catch")
        self.assertIn("Within a second in about 2 laps", words)

    def test_within_a_second_is_left_to_the_live_gap(self):
        self.assertIsNone(self.text(gap=0.8, trend=-0.4, last=-0.4))


class InRange(unittest.TestCase):
    """Said from the game's live gap the moment it drops under a second, not at the next line."""

    def setUp(self):
        self.b, self.mem = Race(raced(4).st), {}
        self.cars = self.b.lap_pkt["lapData"]
        self.ahead = next(i for i in self.b.active() if self.cars[i]["carPosition"] == self.b.my["carPosition"] - 1)

    def gap(self, ms):
        self.cars[self.b.me].update(deltaToCarInFrontMinutesPart=0, deltaToCarInFrontMSPart=ms)
        return gaps.in_range(self.b, self.mem)

    def test_once_until_he_drops_back(self):
        self.assertEqual(self.gap(1400), [])
        (c,) = self.gap(900)
        self.assertEqual(c["text"](self.b), f"You're within a second of {common.nice(self.b.name(self.ahead))}.")
        self.assertEqual(self.gap(700), [])
        self.gap(2600)
        self.assertEqual(len(self.gap(950)), 1)

    def test_not_said_once_he_is_past(self):
        (c,) = self.gap(900)
        me, them = self.cars[self.b.me], self.cars[self.ahead]
        me["carPosition"], them["carPosition"] = them["carPosition"], me["carPosition"]
        self.assertIsNone(c["text"](self.b))


class Settling(unittest.TestCase):
    def test_weather_still_loading_on_a_resume_is_not_new_rain(self):
        b, mem = Race(raced(4).st), {}
        now = b.lap_pkt["header"]["sessionTime"]
        b.s["weather"] = 1
        scan(b, mem)
        b.s["weather"] = 3  # the save finishes loading: it was raining all along
        b.lap_pkt["header"]["sessionTime"] = now + 5
        self.assertEqual(scan(b, mem), [])
        b.s["weather"] = 1  # genuinely dry for a while, then rain starts
        b.lap_pkt["header"]["sessionTime"] = now + SETTLE + 1
        scan(b, mem)
        b.s["weather"] = 3
        self.assertEqual([c["topic"] for c in scan(b, mem)], ["weather"])


class Delivery(unittest.TestCase):
    def setUp(self):
        self.r = raced(3)
        self.t = 300.0
        self.caller = Caller(self.r.st, Hub())
        self.step(throttle=0.2)  # baseline
        self.queued = []

    def step(self, throttle=1.0, brake=0.0, steer=0.0, dt=0.0):
        self.t += dt
        self.r.tick(self.t)
        tel = PACKETS[6].blank()
        tel["carTelemetryData"][0].update(throttle=throttle, brake=brake, steer=steer)
        self.r.send(6, self.t, **{k: v for k, v in tel.items() if k != "header"})
        return self.caller.step()

    def push(self, prio=calls.NORMAL, ttl=40, text="hello"):
        self.caller.queue.append({"key": object(), "topic": "t", "prio": prio, "text": lambda b: text, "ttl": ttl, "at": self.t})

    def test_waits_for_a_second_of_straight(self):
        self.push()
        self.assertEqual(self.step(dt=0.2), [])
        self.assertEqual(self.step(dt=0.6), [])
        self.assertEqual([c["text"] for c in self.step(dt=0.6)], ["hello"])

    def test_a_corner_restarts_the_wait(self):
        self.push()
        self.step(dt=0.2)
        self.step(dt=0.9, steer=0.5)
        self.assertEqual(self.step(dt=0.6), [])

    def test_urgent_goes_without_a_straight(self):
        self.push(prio=calls.URGENT, text="Safety car, safety car.")
        self.assertEqual(len(self.step(throttle=0.3, brake=1.0, dt=0.2)), 1)

    def test_old_calls_expire(self):
        self.push(ttl=5)
        self.step(throttle=0.2, dt=6)
        self.assertEqual(self.step(dt=2.0), [])
        self.assertEqual(self.caller.queue, [])

    def test_never_talks_over_the_driver(self):
        self.caller.busy = lambda: True
        self.push()
        self.step(dt=0.2)
        self.assertEqual(self.step(dt=1.5), [])
        self.assertEqual(len(self.caller.queue), 1)

    def test_live_calls_go_in_the_radio_log_and_replayed_ones_dont(self):
        rows = radio_rows(self)
        self.push(text="replayed")
        self.step(dt=0.2)
        self.step(dt=1.2)
        self.caller.at = lambda: (1, 15, 17)
        self.push(text="live")
        self.step(dt=7.0)
        self.assertEqual(rows("call"), [{"kind": "call", **self.caller.sent[0]}])
        self.assertEqual(self.caller.sent[0]["text"], "live")

    def test_calls_are_spaced(self):
        self.push(text="one")
        self.push(text="two")
        self.step(dt=0.2)
        self.assertEqual([c["text"] for c in self.step(dt=1.2)], ["one"])
        self.assertEqual(self.step(dt=1.0), [])
        self.assertEqual([c["text"] for c in self.step(dt=5.5)], ["two"])


class Level(unittest.TestCase):
    def test_voice_commands_change_how_much_is_said(self):
        c = Caller(raced(3).st, Hub())
        self.assertEqual(c.command("less chat please"), "Copy, only the important stuff.")
        self.assertEqual(c.level, "quiet")
        c.command("more info")
        self.assertEqual(c.level, "chatty")
        c.command("back to normal chat")
        self.assertEqual(c.level, "normal")
        self.assertIsNone(c.command("how are my tyres looking"))
        self.assertEqual(c.level, "normal")

    def test_quiet_keeps_only_urgent_calls(self):
        c = Caller(raced(3).st, Hub())
        c.step()  # baseline
        found = [{"key": n, "topic": n, "prio": p, "text": lambda b: n, "ttl": 40}
                 for n, p in (("pass", calls.LOW), ("gap", calls.NORMAL), ("sc", calls.URGENT))]
        for level, kept in (("quiet", ["sc"]), ("normal", ["gap", "sc"]), ("chatty", ["pass", "gap", "sc"])):
            c.level, c.queue = level, []
            with patch("engineer.calls.caller.scan", return_value=found):
                sent = c.step()
            self.assertEqual(sorted(x["topic"] for x in c.queue + sent), sorted(kept))


if __name__ == "__main__":
    unittest.main()
