"""The pit wall: reading the strategists' replies, when a run happens, what triggers one, and
which radio questions go to the team."""
import threading
import unittest
from types import SimpleNamespace
from unittest import mock

from engineer.calls import Caller, URGENT
from engineer.calls.common import call
from engineer.engineer import CHECKING, Engineer
from engineer.pitwall import notes, triggers, wall as wall_mod
from engineer.pitwall.wall import GATHER, PitWall
from engineer.race import Race
from tests.test_brief import Hub, raced

LEAD = """**CALL:** Stay out, box end of L14 for hards (plan A)
SAY: nothing
WHY: RL reaches worn at L17.
Pit loss 19.5s.
BOX: L14
A: Medium to L14, hards to the flag
B: SC before L12 → box under it for hards
C: rain ≥ 50% within 5 laps → inters when it lands
ACTIVE: A"""


class Notes(unittest.TestCase):
    def test_lead_reply(self):
        n = notes.lead(LEAD)
        self.assertEqual(n["call"], "Stay out, box end of L14 for hards (plan A)")
        self.assertIsNone(n["say"])
        self.assertEqual(n["why"], "RL reaches worn at L17. Pit loss 19.5s.")
        self.assertEqual(n["box"], 14)
        self.assertEqual(set(n["plans"]), {"A", "B", "C"})
        self.assertEqual(n["active"], "A")

    def test_say_and_no_plans(self):
        n = notes.lead('CALL: Box this lap for mediums\nSAY: "Box, box, mediums."\nWHY: x\nBOX: none')
        self.assertEqual(n["say"], "Box, box, mediums.")
        self.assertIsNone(n["box"])
        self.assertEqual(n["plans"], {})
        self.assertIsNone(n["active"])

    def test_review(self):
        self.assertEqual(notes.review("AGREE: window opens L11"), (True, "window opens L11"))
        self.assertEqual(notes.review("**DISAGREE:** box now, 0.9 s/lap"), (False, "box now, 0.9 s/lap"))
        self.assertEqual(notes.review("Looks fine"), (None, "Looks fine"))


def _wall(st=None):
    st = st or SimpleNamespace(lock=threading.Lock(), latest={}, session_uid=None)
    w = PitWall(st, Hub(), persist=False)
    w.error = None
    return w


class When(unittest.TestCase):
    def setUp(self):
        self.w = _wall()

    def r(self, key, urgent=False, question=None):
        return triggers.reason((key,), key, urgent=urgent, question=question)

    def test_reasons_gather_then_run_together(self):
        self.w._add([self.r("pit")])
        self.assertIsNone(self.w._due(5, 100.0))
        self.w._add([self.r("worn")])
        self.assertIsNone(self.w._due(5, 100.0 + GATHER - 1))
        self.assertEqual([r["text"] for r in self.w._due(5, 100.0 + GATHER)], ["pit", "worn"])

    def test_urgent_goes_at_once_and_takes_what_was_waiting(self):
        self.w._add([self.r("pit")])
        self.w._due(5, 100.0)
        self.w._add([self.r("sc", urgent=True)])
        self.assertEqual(len(self.w._due(5, 101.0)), 2)

    def test_one_routine_run_a_lap(self):
        self.w._add([self.r("pit")])
        self.w._due(5, 100.0)
        self.assertTrue(self.w._due(5, 100.0 + GATHER))
        self.w._add([self.r("worn")])
        self.w._due(5, 120.0)
        self.assertIsNone(self.w._due(5, 140.0))
        self.assertTrue(self.w._due(6, 160.0))

    def test_over_budget_only_urgent_and_questions(self):
        self.w.spent = self.w.budget
        self.w._add([self.r("pit")])
        self.assertIsNone(self.w._due(5, 100.0))
        self.assertEqual(self.w.pending, [])
        self.w._add([self.r("q", question="box?")])
        self.assertTrue(self.w._due(5, 100.0))


class Triggers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.st = raced(8).st

    def test_a_stop_around_you_once(self):
        self.st.incidents.log.append({"t": 300.0, "lap": 4, "kind": "pit", "idx": 3, "before": 3, "after": None})
        b = Race(self.st)
        mem = {"t0": b.now - 100}
        got = [r["text"] for r in triggers.scan(b, mem)]
        self.assertTrue(any("Stroll" in t and "has stopped" in t for t in got), got)
        self.assertFalse(any("Stroll" in r["text"] for r in triggers.scan(b, mem)))

    def test_nothing_while_settling(self):
        b = Race(self.st)
        self.assertEqual(triggers.scan(b, {}), [])

    def test_past_the_planned_stop(self):
        b = Race(self.st)
        lap = b.my["currentLapNum"]
        got = triggers.scan(b, {"t0": b.now - 100}, box=lap - 3)
        self.assertTrue(any(r["key"][0] == "late" for r in got))
        self.assertFalse(any(r["key"][0] == "late" for r in triggers.scan(b, {"t0": b.now - 100}, box=lap)))

    def test_race_start_asks_for_plans(self):
        w = _wall(self.st)
        w.step()
        self.assertTrue(any(r["key"] == ("plans",) for r in w.pending))


class Questions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.st = raced(6).st

    def test_strategy_questions_go_to_the_team(self):
        w = _wall(self.st)
        with mock.patch.object(wall_mod, "PIT_ENTRY", 2.0):
            for q in ["Should I box this lap?", "When do I stop?", "Is the undercut on?", "Are inters worth it?"]:
                self.assertEqual(w.routes(q), "team", q)
            for q in ["How are my tyres?", "Gap to Alonso?", "Where am I losing time?"]:
                self.assertIsNone(w.routes(q), q)

    def test_no_time_to_ask_near_the_box(self):
        w = _wall(self.st)
        with mock.patch.object(wall_mod, "PIT_ENTRY", 0.0):
            self.assertEqual(w.routes("Box or stay out?"), "now")

    def test_engineer_says_checking_and_hands_it_over(self):
        w = _wall(self.st)
        eng = Engineer(Hub(), self.st)
        eng.wall, eng.speak = w, lambda *a: None
        with mock.patch.object(wall_mod, "PIT_ENTRY", 2.0):
            eng._answer({"id": "1", "text": "Should I box?"})
        self.assertEqual(eng.replies[-1]["text"], CHECKING)
        self.assertEqual(w.pending[0]["question"], "Should I box?")

    def test_tell_the_team(self):
        import tempfile
        from pathlib import Path
        w = _wall(self.st)
        with tempfile.TemporaryDirectory() as d, mock.patch.object(notes, "BRIEF", Path(d) / "brief.json"):
            self.assertEqual(w.command("Tell the team this one's damage control, few rewinds"), "Copy, I'll pass it on.")
            self.assertEqual(notes.read_brief()["text"], "this one's damage control, few rewinds")
            self.assertTrue(any(r["key"][0] == "brief" for r in w.pending))
            self.assertIn("damage control", w._input("BRIEF", [], 5))
            self.assertIsNone(w.command("what did you tell the team?"))

    def test_go_plan_b(self):
        w = _wall(self.st)
        self.assertIsNone(w.command("go plan B"))  # no plans yet: nothing to switch to
        w.plans, w.active = {"A": "one stop", "B": "SC: box"}, "A"
        self.assertIsNone(w.command("what's plan B?"))
        self.assertEqual(w.command("Go plan B."), "Copy, plan B.")
        self.assertEqual(w.active, "B")


class Prep(unittest.TestCase):
    def test_two_compounds(self):
        from engineer.pitwall import prep
        info = {"compounds": ["Medium", "Soft"]}
        same = {"start": "Soft, the 7% used set", "call": "Used Soft start, box L11-15 for the new Soft, Medium if a safety car comes early"}
        self.assertIn("two different", prep.check(same, info))
        self.assertIsNone(prep.check({"start": "Medium new", "call": "Medium start, box L15-18 for the new Soft"}, info))
        self.assertIn("which set", prep.check({"start": "Soft", "call": "Soft start, one stop"}, info))

    def test_fuel_from_conditions_not_whole_races(self):
        from engineer.pitwall import prep
        races = [{"lap1": -0.06, "dry": 0.0, "dryLow": -0.02, "wet": None, "sc": 0.27},   # dry, with a safety car
                 {"lap1": 0.02, "dry": None, "dryLow": None, "wet": -0.10, "sc": None}]  # all wet
        dry = prep._suggest(races, {"laps": 25, "rainChance": 16, "wetLaps": 0}, 1.43)
        self.assertIn("SUGGESTED FUEL +0.9 laps", dry[0])  # -0.06 + 23 × -0.02 = -0.52, + 0.3 at the flag
        self.assertIn("3-lap one leaves ≈+1.2", dry[1])
        wet = prep._suggest(races, {"laps": 25, "rainChance": 60, "wetLaps": 10}, 1.43)
        self.assertIn("+1.7 covers it", wet[-1])  # 10 laps at -0.10 instead of -0.02


class Section(unittest.TestCase):
    def test_fresh_call_and_a_disagreement(self):
        w = _wall()
        w._apply({"id": "n1", "who": "lead", "lap": 10, "stops": 0, **notes.lead(LEAD)}, publish=False)
        w._apply({"id": "n1r", "who": "review", "of": "n1", "lap": 10, "agree": False, "text": "box now"}, publish=False)
        text = "\n".join(notes.section(w, 11))
        self.assertIn("plan A (active): Medium to L14", text)
        self.assertIn("planned stop: end of lap 14", text)
        self.assertIn("team's call (1 lap ago): Stay out", text)
        self.assertIn("second strategist disagrees: box now", text)
        self.assertNotIn("team's call", "\n".join(notes.section(w, 10 + notes.FRESH_LAPS + 1)))


class Relay(unittest.TestCase):
    def test_a_new_team_call_replaces_one_still_waiting(self):
        st = raced(4).st
        caller = Caller(st, Hub(), scan=False)
        caller.busy = lambda: True  # hold everything in the queue
        caller.push([call(("team", "a"), "team", URGENT, lambda b: "Box this lap.")])
        caller.step()
        caller.push([call(("team", "b"), "team", URGENT, lambda b: "Stay out.")])
        caller.step()
        self.assertEqual([c["key"] for c in caller.queue], [("team", "b")])


if __name__ == "__main__":
    unittest.main()
