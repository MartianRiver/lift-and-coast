"""Unprompted calls: what's worth a call, and that delivery waits for a straight."""
import unittest
from unittest.mock import patch

from engineer import brief, calls
from engineer.calls import Caller, common, events, gaps
from engineer.pitwall import triggers
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

    def test_a_team_call_from_the_last_session_isnt_said_in_this_one(self):
        # the team answered after the game went quiet, and the next race started hours later
        self.caller.push([{"key": ("team", "box"), "topic": "team", "prio": calls.URGENT, "ttl": 60,
                           "text": lambda b: "Box, box, new front wing."}])
        self.caller._uid = "the session before"
        self.assertEqual(self.step(dt=0.2) + self.step(dt=1.2), [])

    def test_calls_are_spaced(self):
        self.push(text="one")
        self.push(text="two")
        self.step(dt=0.2)
        self.assertEqual([c["text"] for c in self.step(dt=1.2)], ["one"])
        self.assertEqual(self.step(dt=1.0), [])
        self.assertEqual([c["text"] for c in self.step(dt=5.5)], ["two"])


class RedFlag(unittest.TestCase):
    # as the game sent it at Monza: SC out, a red flag 15 s later, the SC phases run out, then a standing restart
    def setUp(self):
        self.r, self.mem = raced(3), {}
        self.t = Race(self.r.st).now

    def send(self, code, details=b""):
        self.t += 1
        self.r.event(self.t, code, details)
        b = Race(self.r.st)
        return b, events.safety_car(b, self.mem)

    def test_called_as_a_red_flag_not_a_safety_car_restart(self):
        b, (sc,) = self.send("SCAR", bytes([1, 0]))
        self.assertEqual(sc["text"](b), "Safety car, safety car.")
        b, (red,) = self.send("RDFL")
        self.assertEqual(red["text"](b), "Red flag, red flag.")
        self.assertIsNone(sc["text"](b))  # one still waiting for a straight is dropped
        for details in (bytes([1, 1]), bytes([1, 2]), bytes([0, 3])):
            self.assertEqual(self.send("SCAR", details)[1], [])
        self.assertIsNotNone(b.red_flag())
        b, _ = self.send("LGOT")
        self.assertIsNone(b.red_flag())

    def test_the_brief_and_the_team_hear_of_it(self):
        self.send("SCAR", bytes([1, 0]))
        self.send("RDFL")
        self.assertIn("SITUATION RED FLAG: race suspended · everyone gets a free tyre change", brief.build(self.r.st))
        self.assertIn("red flag: free tyre change before the standing restart, which set for the laps left?",
                      [r["text"] for r in triggers.scan(Race(self.r.st), {"t0": 0.0})])
        self.send("LGOT")
        self.assertNotIn("RED FLAG", brief.build(self.r.st))


class Damage(unittest.TestCase):
    def test_two_hits_said_once_when_they_read_the_same(self):
        # Brazil: front wing, then the rear wing a moment later; both calls were rebuilt as "front wing right 80%, rear wing 66%"
        b, mem = Race(raced(3).st), {}
        dmg = b.damage()
        dmg["frontRightWingDamage"] = 80
        (first,) = [c for c in events.conditions(b, mem) if c["topic"] == "damage"]
        dmg["rearWingDamage"] = 66
        (second,) = [c for c in events.conditions(b, mem) if c["topic"] == "damage"]
        self.assertEqual(first["text"](b), "Damage: front wing right 80%, rear wing 66%.")
        self.assertIsNone(second["text"](b))
        dmg["frontRightWingDamage"] = 100
        (third,) = [c for c in events.conditions(b, mem) if c["topic"] == "damage"]
        self.assertEqual(third["text"](b), "Damage: front wing right 100%, rear wing 66%.")

    def test_after_a_flashback_the_same_damage_is_said_again(self):
        b, mem = Race(raced(3).st), {}
        dmg = b.damage()
        dmg["frontRightWingDamage"] = 80
        (c,) = [c for c in events.conditions(b, mem) if c["topic"] == "damage"]
        self.assertIsNotNone(c["text"](b))
        dmg["frontRightWingDamage"] = 0
        events.conditions(b, mem)
        dmg["frontRightWingDamage"] = 80
        (again,) = [c for c in events.conditions(b, mem) if c["topic"] == "damage"]
        self.assertEqual(again["text"](b), "Damage: front wing right 80%.")


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
