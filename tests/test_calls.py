"""Unprompted calls: what's worth a call, and that delivery waits for a straight."""
import unittest
from unittest.mock import patch

from engineer import brief, calls
from engineer.calls import Caller, common, events, gaps, tyres
from engineer.pitwall import triggers
from engineer.calls import caller as caller_mod
from engineer.calls.scan import SETTLE, scan
from engineer.race import Race
from engineer.spec import PACKETS
from tests import radio_rows
from tests.test_brief import Hub, raced
from tests.test_strategy import SOFT, brazil


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
        self.assertIn("Within a second next lap.", self.text(gap=1.3, trend=-0.4, last=-0.4)[1])

    def test_within_a_second_is_left_to_the_live_gap(self):
        self.assertIsNone(self.text(gap=0.8, trend=-0.4, last=-0.4))


class InRange(unittest.TestCase):
    """Said from the game's live gap the moment it drops under a second, not at the next line."""

    def setUp(self):
        self.r = raced(4)
        self.b, self.mem = Race(self.r.st), {}
        self.cars = self.b.lap_pkt["lapData"]
        self.ahead = next(i for i in self.b.active() if self.cars[i]["carPosition"] == self.b.my["carPosition"] - 1)

    def gap(self, ms, car=None):
        """Sets the live gap to the car ahead (or `car` behind) through both cars' time to the leader."""
        behind, ahead = (car, self.b.me) if car is not None else (self.b.me, self.ahead)
        self.cars[ahead].update(deltaToRaceLeaderMinutesPart=0, deltaToRaceLeaderMSPart=10000)
        self.cars[behind].update(deltaToRaceLeaderMinutesPart=0, deltaToRaceLeaderMSPart=10000 + ms)
        return gaps.in_range(self.b, self.mem)

    def test_once_until_he_drops_back(self):
        self.assertEqual(self.gap(1400), [])
        (c,) = self.gap(900)
        self.assertEqual(c["text"](self.b), f"You're within a second of {common.nice(self.b.name(self.ahead))}.")
        self.assertEqual(self.gap(700), [])
        self.gap(2600)
        self.assertEqual(len(self.gap(950)), 1)

    def test_armed_twice_in_a_lap_is_a_new_call(self):
        # #20: Hamilton re-armed on lap 2 under the same key, so the scan dropped it as said and he stayed silent
        (first,) = self.gap(900)
        self.gap(2600)
        self.b.lap_pkt["header"]["sessionTime"] += 10
        (again,) = self.gap(900)
        self.assertNotEqual(first["key"], again["key"])

    def test_level_on_timing_with_the_leader_does_not_re_arm(self):
        # Losail sprint, last lap: Verstappen 0.03 behind, then 16 ms ahead on timing while still P2,
        # which the game's unsigned ms part sends as 65520 (65.5 s) for 12 s
        leader = self.cars[self.ahead]
        self.assertEqual(leader["carPosition"], 1)
        self.assertEqual(len(self.gap(30)), 1)
        leader.update(deltaToRaceLeaderMinutesPart=0, deltaToRaceLeaderMSPart=0)
        self.cars[self.b.me].update(deltaToRaceLeaderMinutesPart=0, deltaToRaceLeaderMSPart=65520)
        self.assertEqual(gaps.in_range(self.b, self.mem), [])
        self.assertEqual(self.gap(300), [])

    def test_a_call_that_was_never_said_leaves_the_car_armed(self):
        (c,) = self.gap(900)
        c["unsaid"]()  # expired waiting for a straight
        self.assertEqual(len(self.gap(900)), 1)

    def test_not_said_once_he_is_past(self):
        (c,) = self.gap(900)
        me, them = self.cars[self.b.me], self.cars[self.ahead]
        me["carPosition"], them["carPosition"] = them["carPosition"], me["carPosition"]
        self.assertIsNone(c["text"](self.b))


    def test_not_from_the_game_gap_to_the_old_car_ahead_after_a_pass(self):
        me = self.cars[self.b.me]
        self.assertEqual(self.gap(-300), [])  # the times not yet in the new order
        self.gap(2900)
        me.update(deltaToCarInFrontMinutesPart=0, deltaToCarInFrontMSPart=50)  # still the car he just passed
        self.assertEqual(gaps.in_range(self.b, self.mem), [])

    def test_not_for_a_car_that_has_just_swapped_places_with_him(self):
        self.b.st.incidents.log.append({"t": self.b.now - 5, "lap": 3, "kind": "lost", "idx": self.ahead})
        self.assertEqual(self.gap(900), [])
        self.b.lap_pkt["header"]["sessionTime"] += gaps.JUST_PASSED  # still on him half a minute later: worth it now
        self.assertEqual(len(self.gap(900)), 1)

    def test_a_car_called_ahead_is_a_new_call_once_he_is_behind(self):
        # Losail sprint: "within a second of Verstappen" ahead, then he sat 0.5 s behind for six laps unsaid
        self.assertEqual(len(self.gap(900)), 1)
        me, them = self.cars[self.b.me], self.cars[self.ahead]
        me["carPosition"], them["carPosition"] = them["carPosition"], me["carPosition"]
        (c,) = self.gap(600, car=self.ahead)
        self.assertEqual(c["text"](self.b), f"{common.nice(self.b.name(self.ahead))} is within a second.")
        me["carPosition"], them["carPosition"] = them["carPosition"], me["carPosition"]  # and back: a battle
        self.assertEqual(self.gap(700), [])

    def test_drs_range_only_when_the_race_has_drs(self):
        behind = next(i for i in self.b.active() if self.cars[i]["carPosition"] == self.b.my["carPosition"] + 1)
        (c,) = [c for c in self.gap(800, car=behind) if c["key"][1] == behind]
        who = common.nice(self.b.name(behind))
        self.assertEqual(c["text"](self.b), f"{who} is within a second.")  # no DRSE yet: wet, or lap 1
        self.r.event(self.b.now + 1, "DRSE")
        self.assertEqual(c["text"](self.b), f"{who} is within a second, in DRS range.")
        self.r.event(self.b.now + 2, "DRSD", bytes([0]))
        self.assertEqual(c["text"](self.b), f"{who} is within a second.")


class Overwear(unittest.TestCase):
    def test_no_flag_projection_while_the_second_compound_is_owed(self):
        self.assertFalse(tyres._at_flag(brazil(), 1, 4.5))  # this set comes off at the stop
        self.assertEqual(tyres._at_flag(brazil(run=(SOFT,)), 1, 4.5), 50 + 4.5 * 13)


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

    def drive(self, secs):
        """Steps the clock a second at a time, as the game does when it's not paused: the calls said."""
        out = []
        for _ in range(round(secs)):
            out += self.step(dt=1.0)
        return out

    def push(self, prio=calls.NORMAL, ttl=40, text="hello", topic="t", unsaid=None):
        self.caller.queue.append({"key": object(), "topic": topic, "prio": prio, "text": lambda b: text, "ttl": ttl,
                                  "at": self.t, "unsaid": unsaid})

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

    def test_no_tyre_call_about_the_corner_the_quick_brief_just_named(self):
        # Losail sprint: "…Front-left 31%." then 7 s later "Front-left is the limit, 31% worn."
        self.caller.quick_said("P1, Verstappen 0.4 behind. Front-left 31%.")
        self.push(text="Front-left is the limit, 31% worn.", topic="tyres")
        self.push(text="Rear-right's wearing 1.6 times the field's rate.", topic="tyres")
        self.step(dt=0.2)
        self.step(dt=0.6)
        self.assertEqual([c["text"] for c in self.step(dt=0.6)], ["Rear-right's wearing 1.6 times the field's rate."])
        self.assertEqual(self.caller.queue, [])
        self.drive(caller_mod.QUICK_REPEAT)
        self.push(text="Front-left is the limit, 40% worn.", topic="tyres")
        self.assertEqual(len(self.drive(2)), 1)  # long enough after it

    def test_the_quick_brief_holds_back_only_tyre_calls(self):
        self.caller.quick_said("P1. Front-left 31%.")
        self.push(prio=calls.URGENT, text="Puncture, front-left.", topic="damage")
        self.assertEqual(len(self.step(throttle=0.3, dt=0.2)), 1)

    def test_nothing_once_he_has_retired(self):
        # Melbourne: crashed out, the game paused, and the waiting "Safety car, safety car." went as he retired
        self.r.event(self.t, "RTMT", bytes([3, 3]))  # another car
        self.push(prio=calls.URGENT, text="Safety car, safety car.")
        self.assertEqual(len(self.step(dt=0.2)), 1)
        self.push(prio=calls.URGENT, text="Safety car, safety car.")
        self.assertEqual(self.step(dt=6.0), [])  # the clock moves on out of a pause: wait for that moment's events
        self.r.event(self.t, "RTMT", bytes([0, 3]))
        self.assertEqual(self.step(dt=0.2), [])
        self.assertEqual(self.caller.queue, [])

    def test_a_pause_holds_a_call_for_one_look(self):
        self.push(prio=calls.URGENT, text="Safety car, safety car.")
        self.assertEqual(self.step(dt=6.0), [])
        self.assertEqual(len(self.step(dt=0.2)), 1)

    def test_nothing_once_the_session_has_ended(self):
        self.push(prio=calls.URGENT, text="Safety car, safety car.")
        self.r.event(self.t, "SEND")
        self.assertEqual(self.step(dt=0.2), [])

    def test_old_calls_expire(self):
        unsaid = []
        self.push(ttl=5, unsaid=lambda: unsaid.append("expired"))
        self.step(throttle=0.2, dt=6)
        self.assertEqual(self.step(dt=2.0), [])
        self.assertEqual(self.caller.queue, [])
        self.assertEqual(unsaid, ["expired"])
        self.push(text=None, unsaid=lambda: unsaid.append("stale"))  # stopped being true while it waited
        for _ in range(3):
            self.step(dt=0.6)
        self.assertEqual(unsaid, ["expired", "stale"])

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
        self.drive(7)
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
        self.assertEqual([c["text"] for c in self.drive(6)], ["two"])


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
