import threading
import time
import unittest
from types import SimpleNamespace
from unittest import mock

from engineer import engineer as eng_module
from engineer import radio
from engineer.engineer import LOST, Engineer
from engineer.hub import Hub
from engineer.llm import LLMError

from . import radio_rows

from engineer.capture import _is_buttons
from engineer.engineer import ACKS, _plain, _question
from engineer.spec import EVENT_DETAILS_SIZE, PACKETS


class Replies(unittest.TestCase):
    def test_acknowledgements_get_no_reply(self):
        for said in ["Mm-hmm.", "Copy that!", "OK", "Roger."]:
            self.assertIn(_plain(said), ACKS, said)
        for said in ["How are my tyres?", "Copy, what's the gap?", "Yes"]:
            self.assertNotIn(_plain(said), ACKS, said)

    def test_a_bare_yeah_needs_a_question_to_answer(self):
        eng = Engineer(Hub(), SimpleNamespace(lock=threading.Lock(), session_uid=1))
        eng._work = lambda: None
        eng.ask({"id": "1", "text": "Yeah."})
        self.assertTrue(eng._queue.empty())
        eng._history.append((time.time(), None, "Norris half a second back, keep pushing."))
        eng.ask({"id": "2", "text": "Yeah."})
        self.assertTrue(eng._queue.empty())
        eng._history.append((time.time(), None, "Box this lap?"))
        eng.ask({"id": "3", "text": "Yeah."})
        self.assertEqual(eng._queue.get_nowait()["id"], "3")
        eng.ask({"id": "4", "text": "Yeah, what's the gap?"})
        self.assertEqual(eng._queue.get_nowait()["id"], "4")

    def test_silence_is_not_speech(self):
        try:
            import numpy as np
        except ImportError:
            self.skipTest("the voice group isn't installed")
        rate = radio.SAMPLE_RATE
        rng = np.random.default_rng(1)
        hiss = rng.normal(0, 0.0015, rate).astype(np.float32)  # the room with nobody talking (Spa: 0.0016)
        word = hiss.copy()
        word[8000:12000] += 0.03 * np.sin(np.arange(4000) / 5).astype(np.float32)  # a quiet word
        self.assertLess(radio.loudest(hiss), radio.SILENT_RMS)
        self.assertGreater(radio.loudest(word), radio.SILENT_RMS)

    def test_question_notes_what_was_heard(self):
        msg = {"text": "How far back is Tsunoda?", "heard": "How far back is Sonoda?",
               "changes": [{"heard": "Sonoda", "meant": "Tsunoda", "how": "sounds like"}]}
        self.assertIn('heard: "How far back is Sonoda?"', _question(msg))


class NoAnswer(unittest.TestCase):
    """The engineer model saying nothing for FIRST_WORD seconds, or failing outright."""
    def setUp(self):
        self.rows = radio_rows(self)
        for target, value in [("api_key", lambda: "key"), ("brief", SimpleNamespace(build=lambda st: "BRIEF"))]:
            patcher = mock.patch.object(eng_module, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def answer(self, replies, fallback="second/model"):
        """replies: model -> its answer, or an exception to raise after saying the text before it."""
        asked = []

        def stream(model, messages, on_text, why=None, first_by=None, **kw):
            asked.append((model, why, first_by))
            got = replies[model]
            text, fails = (got, None) if isinstance(got, str) else got
            for word in text.split():
                on_text(word + " ")
            if fails:
                raise fails
            return {"model": model, "firstMs": 1}
        eng = Engineer(Hub(), SimpleNamespace(lock=threading.Lock(), session_uid=1), model="first/model",
                       at=lambda: ("s", 0), fallback=fallback)
        heard = []
        eng.speak = lambda text, at=None: heard.append(text)
        with mock.patch.object(eng_module, "stream", stream):
            eng._answer({"id": "1", "text": "gap?"})
        [row] = self.rows("reply")
        return asked, heard, row

    def test_the_second_model_answers_when_the_first_says_nothing(self):
        asked, heard, row = self.answer({"first/model": ("", LLMError("no answer in 5 s")), "second/model": "Holding it."})
        self.assertEqual(asked, [("first/model", "question", eng_module.FIRST_WORD), ("second/model", "fallback", eng_module.FIRST_WORD)])
        self.assertEqual(heard, ["Holding it."])
        self.assertEqual((row["status"], row["model"]), ("done", "second/model"))

    def test_when_neither_answers_it_says_so(self):
        down = ("", LLMError("network: down"))
        asked, heard, row = self.answer({"first/model": down, "second/model": down})
        self.assertEqual(len(asked), 2)
        self.assertEqual(heard, [LOST])
        self.assertEqual((row["status"], row["text"], row["error"]), ("error", LOST, "network: down"))

    def test_an_answer_cut_off_halfway_isnt_started_again(self):
        asked, heard, row = self.answer({"first/model": ("Holding the gap. And he's", LLMError("no answer in 5 s")),
                                         "second/model": "Holding it."})
        self.assertEqual([m for m, _, _ in asked], ["first/model"])
        self.assertEqual(heard, ["Holding the gap."])
        self.assertEqual(row["status"], "error")

    def test_a_cut_off_answer_with_nothing_said_still_says_so(self):
        _, heard, _ = self.answer({"first/model": ("Rear-left at 43%. And", LLMError("no answer in 5 s"))})
        self.assertEqual(heard, [LOST])  # the one sentence was held back: they heard nothing

    def test_without_a_fallback_one_model_is_tried(self):
        asked, heard, _ = self.answer({"first/model": ("", LLMError("HTTP 500: oops"))}, fallback=None)
        self.assertEqual((len(asked), heard), (1, [LOST]))


class Replay(unittest.TestCase):
    def test_button_events_are_recognised(self):
        def event(code):
            d = PACKETS[3].blank()
            d["header"].update(packetFormat=2026, packetId=3)
            d.update(eventStringCode=code, eventDetails=b"\0" * EVENT_DETAILS_SIZE)
            return PACKETS[3].pack(d)
        self.assertTrue(_is_buttons(event("BUTN")))
        self.assertFalse(_is_buttons(event("SCAR")))


if __name__ == "__main__":
    unittest.main()
