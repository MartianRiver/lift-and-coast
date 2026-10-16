import threading
import time
import unittest
from types import SimpleNamespace


from engineer import radio
from engineer.engineer import Engineer
from engineer.hub import Hub

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
