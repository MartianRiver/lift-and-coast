"""Figures in the engineer's answers against the brief it was given. Brief lines and answers are real
ones, from the engineer on recorded races."""
import threading
import unittest
from types import SimpleNamespace
from unittest import mock

from engineer import engineer as eng_module
from engineer.engineer import UNSURE, Engineer
from engineer.hub import Hub
from engineer.numbers import unsupported

from . import radio_rows

WEAR = ("  wear   FL 38% FR 38% RL 39% RR 36% · fastest-wearing RL +4.7%/lap · RL reaches 70% (worn out) in ≈6 laps, L16\n"
        "  temps  peak surface last lap FL 102°C FR 79°C RL 103°C RR 90°C\n"
        "  rear temps up as much as 22°C on the start of the set in S1, S2, S3")
FIELD = ("SESSION  Race · Montreal · lap 21 of 25\n"
         "  P2  HAMILTON    Ferrari            +6.2  H  8  1:16.695  RL 15%  closing on you 0.28/lap\n"
         "PIT     rejoin ≈P2, 20.5s behind HAMILTON · fuel +1.31 laps vs target (25.1 kg in tank)\n"
         "  vs HAMILTON: you lose 0.31 at 2947–3692 m (apex -12 km/h) · you lose 0.17 at 4877–6612 m · gap 0.9")


class Unsupported(unittest.TestCase):
    def test_a_wear_figure_worked_forward_is_caught(self):
        self.assertEqual(unsupported("Rear-left's the concern: 43%, gone in about five laps.", WEAR), ["43"])

    def test_figures_said_the_way_an_engineer_says_them_pass(self):
        for said in ["Rear-left's at 39%, worn out by lap 16.", "Hamilton's 6.2 behind, last lap a 16.7.",
                     "Fuel's fine, plus 1.3 laps.", "Box now and you're P2, 20.5 seconds behind Hamilton.",
                     "The loss is around the 3000–3700 metre corner.", "Mainly from the 4.9 km mark.",
                     "Gap's nine tenths.", "Rears up around 20° on the start of the set.", "Hamilton's 1:16.695.",
                     "His rear-left's in the high 30s.", "Apex speed's down 12 k's."]:
            self.assertEqual(unsupported(said, WEAR + "\n" + FIELD), [], said)

    def test_a_figure_has_to_match_one_with_the_same_unit(self):
        # 22 is in the brief as °C, 16 as a lap: neither backs a wear figure
        self.assertEqual(unsupported("Rear-left's at 22%.", WEAR), ["22"])
        self.assertEqual(unsupported("You're P16.", WEAR), ["16"])
        self.assertEqual(unsupported("Box on lap 22.", WEAR), ["22"])
        self.assertEqual(unsupported("Twenty-five kilos left, 26 kg.", FIELD), ["26"])

    def test_a_hedge_allows_a_round_number_not_a_different_one(self):
        self.assertEqual(unsupported("About 40% on the rear-left.", WEAR), [])
        self.assertEqual(unsupported("About 43% on the rear-left.", WEAR), ["43"])
        self.assertEqual(unsupported("Up 20° on the start of the set.", WEAR), ["20"])

    def test_rounding_goes_as_far_as_the_figure_said(self):
        self.assertEqual(unsupported("Plus 1.31 laps.", FIELD), [])
        self.assertEqual(unsupported("Plus 1.4 laps.", FIELD), ["1.4"])
        self.assertEqual(unsupported("He's 6.3 behind.", FIELD), ["6.3"])

    def test_a_spelled_out_count_is_checked_when_it_has_a_unit(self):
        self.assertEqual(unsupported("Worn out in six laps.", WEAR), [])
        self.assertEqual(unsupported("Worn out in eleven laps.", WEAR), ["eleven laps"])
        self.assertEqual(unsupported("Gap's seven tenths.", FIELD), ["seven tenths"])
        self.assertEqual(unsupported("One lap more on these.", WEAR), ["One lap"])
        self.assertEqual(unsupported("That's the one to watch, one stop.", FIELD), [])


class HeldBack(unittest.TestCase):
    def setUp(self):
        self.rows = radio_rows(self)
        for target, value in [("api_key", lambda: "key"), ("brief", SimpleNamespace(build=lambda st: WEAR))]:
            patcher = mock.patch.object(eng_module, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def answer(self, reply, wall=None):
        def stream(model, messages, on_text, **kw):
            for word in reply.split(" "):
                on_text(word + " ")
            return {"firstMs": 1}
        eng = Engineer(Hub(), SimpleNamespace(lock=threading.Lock(), session_uid=1, latest={}), at=lambda: ("s", 0))
        eng.wall = wall
        heard = []
        eng.speak = lambda text, at=None: heard.append(text)
        with mock.patch.object(eng_module, "stream", stream):
            eng._answer({"id": "1", "text": "how are my tyres looking?"})
        return eng, heard

    def test_a_sentence_with_a_figure_not_in_the_brief_isnt_said(self):
        eng, heard = self.answer("Rear-left's the concern: 43%, gone in six laps. Ease off everywhere.")
        self.assertEqual(heard, ["Ease off everywhere."])
        [row] = self.rows("reply")
        self.assertEqual(row["held"], [{"text": "Rear-left's the concern: 43%, gone in six laps.", "numbers": ["43"]}])
        self.assertIn("43%", row["text"])  # the log keeps what the model wrote
        self.assertEqual(eng._history[-1][2], "Ease off everywhere.")  # a follow-up builds on what was said

    def test_the_team_reviews_what_was_said(self):
        reviewed = []
        wall = SimpleNamespace(routes=lambda text: "now", section=lambda: "PIT WALL", answered=lambda q, a: reviewed.append(a))
        self.answer("Box this lap for 43% fresher tyres. Mediums.", wall)
        self.assertEqual(reviewed, ["Mediums."])

    def test_when_nothing_can_be_said_it_says_so(self):
        _, heard = self.answer("Rear-left's at 43%.")
        self.assertEqual(heard, [UNSURE])

    def test_a_reply_that_checks_out_is_said_whole(self):
        eng, heard = self.answer("Rear-left's at 39%. Worn out by lap 16.")
        self.assertEqual(heard, ["Rear-left's at 39%.", "Worn out by lap 16."])
        self.assertIsNone(self.rows("reply")[0]["held"])
        self.assertEqual(eng._history[-1][2], "Rear-left's at 39%. Worn out by lap 16.")
