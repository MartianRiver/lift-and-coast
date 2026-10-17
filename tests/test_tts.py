"""Speaking: written calls turned into speech text, replies spoken a sentence at a time, and
River keying the radio cutting the engineer off."""
import importlib.util
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from engineer import radiolog
from engineer.engineer import Engineer
from engineer.spoken import speakable
from engineer.tts import Speaker, parse_voice
from tests import radio_rows
from tests.test_brief import Hub


class Spoken(unittest.TestCase):
    def test_gaps_and_times_are_said_the_way_an_engineer_says_them(self):
        self.assertEqual(speakable("Norris is closing, 0.7 a lap and 6.7 back."),
                         "Norris is closing, seven tenths a lap and 6.7 back.")
        self.assertEqual(speakable("You've got a 3 s penalty."), "You've got a 3 second penalty.")
        self.assertEqual(speakable("Best 1:06.986, last 1:07.05"),
                         "Best one oh six point nine eight six, last one oh seven point zero five")
        self.assertEqual(speakable("Track limits at 1158 m, P13."), "Track limits at 1158 metres, P13.")

    def test_other_decimals_and_names_are_left_alone(self):
        self.assertEqual(speakable("0.0 and 0.71 and 10.7"), "0.0 and 0.71 and 10.7")
        self.assertEqual(speakable("Leclerc is out, VSC."), "Leclair is out, V S C.")

    def test_voice_spec(self):
        self.assertEqual(parse_voice("kokoro:bm_daniel"), ("kokoro", "bm_daniel"))
        self.assertEqual(parse_voice("soprano"), ("soprano", None))
        with self.assertRaises(ValueError):
            parse_voice("nope")


class Streaming(unittest.TestCase):
    def test_reply_is_handed_to_the_voice_sentence_by_sentence(self):
        said = []
        chunks = ["Norris is closing, 0.", "7 a lap. About 4.6", " at the flag. Cop", "y."]
        with patch("engineer.engineer.api_key", return_value="x"), \
                patch("engineer.engineer.brief.build", return_value="NORRIS +1.2 closing on you 0.68/lap ≈4.6s at the flag"), \
                patch("engineer.engineer.stream", lambda m, msgs, on_text, **kw: [on_text(c) for c in chunks] and {}):
            eng = Engineer(Hub(), SimpleNamespace(lock=threading.Lock(), session_uid=1, latest={}))
            eng.speak = lambda text, at=None: said.append(text)
            eng._answer({"id": 1, "text": "gap?"})
        self.assertEqual(said, ["Norris is closing, 0.7 a lap.", "About 4.6 at the flag.", "Copy."])

    def test_local_replies_are_spoken_too(self):
        said = []
        with patch("engineer.engineer.api_key", return_value="x"):
            eng = Engineer(Hub(), SimpleNamespace(lock=threading.Lock(), session_uid=1, latest={}))
        eng.commands.append(lambda text: "Copy, only the important stuff.")
        eng.speak = lambda text, at=None: said.append(text)
        eng._answer({"id": 1, "text": "less chat"})
        self.assertEqual(said, ["Copy, only the important stuff."])


class FakeVoice:
    name = "fake"
    def __init__(self, samples=2400):
        self.rendered, self.samples = [], samples
    def load(self):
        pass
    def render(self, text):
        self.rendered.append(text)
        import numpy as np

        yield np.zeros(self.samples, dtype=np.float32), 24000


@unittest.skipUnless(importlib.util.find_spec("sounddevice") and importlib.util.find_spec("numpy"), "voice group")
class Playing(unittest.TestCase):
    def setUp(self):
        self.played = []
        out = SimpleNamespace(write=lambda a: (self.played.append(len(a)), time.sleep(0.01)))

        class Stream:
            def __init__(s, **kw): pass
            def __enter__(s): return out
            def __exit__(s, *a): pass
        patcher = patch("sounddevice.OutputStream", Stream)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.rows = radio_rows(self)
        self.sp = Speaker(Hub())
        self.sp.voice = FakeVoice()
        self.sp.start()

    def wait(self, cond, secs=3):
        end = time.time() + secs
        while time.time() < end and not cond():
            time.sleep(0.01)
        return cond()

    def test_says_it_then_goes_idle(self):
        self.assertTrue(self.wait(lambda: self.sp.state == "ready"))
        self.sp.say("P1.")
        self.assertTrue(self.sp.busy())
        self.assertTrue(self.wait(lambda: self.played and not self.sp.busy()))
        self.assertEqual(self.sp.voice.rendered, ["P1."])
        self.assertEqual(self.rows("spoken"), [])  # only kept live

    def test_live_keeps_each_line_as_a_clip_with_when_it_played(self):
        self.sp.record = True
        self.assertTrue(self.wait(lambda: self.sp.state == "ready"))
        asked = time.time()
        self.sp.say("P1.")
        self.assertTrue(self.wait(lambda: self.rows("spoken")))
        row = self.rows("spoken")[0]
        self.assertEqual({k: row[k] for k in ("text", "part", "secs", "played", "cut")},
                         {"text": "P1.", "part": 0, "secs": 0.1, "played": 0.1, "cut": False})
        self.assertGreaterEqual(row["start"], round(asked, 3))
        self.assertTrue((radiolog.CLIPS / "spoken" / row["clip"]).exists())

    def test_a_clip_that_cant_be_saved_is_still_said(self):
        self.sp.record = True
        self.assertTrue(self.wait(lambda: self.sp.state == "ready"))
        with patch("soundfile.write", side_effect=OSError("disk full")):
            self.sp.say("P1.")
            self.assertTrue(self.wait(lambda: self.played and not self.sp.busy()))
        self.assertEqual(self.rows("spoken"), [])

    def test_a_line_cut_off_says_how_much_was_heard(self):
        self.sp.record = True
        self.sp.voice = FakeVoice(samples=24000)  # a second, 20 writes
        self.assertTrue(self.wait(lambda: self.sp.state == "ready"))
        self.sp.say("A long one.")
        self.assertTrue(self.wait(lambda: len(self.played) >= 3))
        self.sp.stop()
        self.assertTrue(self.wait(lambda: self.rows("spoken")))
        row = self.rows("spoken")[0]
        self.assertTrue(row["cut"])
        self.assertGreater(row["played"], 0)
        self.assertLess(row["played"], row["secs"])

    def test_keying_the_radio_drops_what_was_asked_before(self):
        self.assertTrue(self.wait(lambda: self.sp.state == "ready"))
        asked = time.time() - 1
        self.sp.stop()
        self.sp.say("stale answer", at=asked)
        self.assertFalse(self.sp.busy())
        self.sp.say("fresh", at=time.time())
        self.assertTrue(self.wait(lambda: self.sp.voice.rendered == ["fresh"]))


if __name__ == "__main__":
    unittest.main()
