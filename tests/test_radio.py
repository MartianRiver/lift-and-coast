import threading
import time
import unittest

from engineer import radiolog

try:
    import numpy as np
except ImportError:  # the voice extra isn't installed
    raise unittest.SkipTest("numpy")

from engineer.radio import BLOCK, MAX_OPEN_S, POST_ROLL_S, SAMPLE_RATE, Radio, button
from tests import radio_rows

TRIGGER = 1 << button("UDP Action 1")


class FakeHub:
    def __init__(self):
        self.events = []

    def publish(self, kind, data):
        self.events.append((kind, data))


def make(mode):
    r = Radio(FakeHub(), mode=mode)
    r.status = "ready"  # skip mic + model
    return r


def feed(r, blocks=3):
    for _ in range(blocks):
        r._on_audio(np.full((BLOCK, 1), 0.1, dtype=np.float32), BLOCK, None, None)


def finish(r):
    """Run the post-roll out and take the finished clip, as the tick thread would."""
    return r._poll(time.time() + POST_ROLL_S + 0.01)


class Hold(unittest.TestCase):
    def test_press_release_produces_one_clip(self):
        r = make("hold")
        feed(r)  # pre-roll
        r.on_buttons(0, TRIGGER)
        self.assertEqual(r.status, "open")
        feed(r, 5)
        r.on_buttons(TRIGGER, 0)
        audio, _ = finish(r)
        self.assertEqual(len(audio), 8 * BLOCK)  # 3 pre-roll + 5 live
        self.assertIsNone(r._frames)

    def test_reopens_after_a_finished_message(self):
        # regression: _close_at was never cleared, so the radio only ever worked once
        r = make("hold")
        for _ in range(3):
            r.on_buttons(0, TRIGGER)
            feed(r)
            r.on_buttons(TRIGGER, 0)
            self.assertIsNotNone(finish(r))
            r.status = "ready"

    def test_other_buttons_ignored(self):
        r = make("hold")
        r.on_buttons(0, 1)  # A
        self.assertIsNone(r._frames)

    def test_quick_publishes_without_opening(self):
        r = make("hold")
        pressed = threading.Event()
        r.on_quick.append(lambda: pressed.set() if threading.current_thread() is not threading.main_thread() else None)
        r.on_buttons(0, 1 << button(2))
        self.assertTrue(pressed.wait(2))  # off the packet thread, which holds the state lock
        self.assertIsNone(r._frames)
        self.assertIn("quick", [k for k, _ in r.hub.events])

    def test_any_button_can_be_the_radio(self):
        r = Radio(FakeHub(), mode="hold", trigger="left stick click")
        r.status = "ready"
        r.on_buttons(0, TRIGGER)
        self.assertIsNone(r._frames)
        r.on_buttons(0, 1 << button("Left Stick Click"))
        self.assertEqual(r.status, "open")
        with self.assertRaises(ValueError):
            button("Turbo")


class Toggle(unittest.TestCase):
    def test_tap_opens_second_tap_closes(self):
        r = make("toggle")
        r.on_buttons(0, TRIGGER)
        r.on_buttons(TRIGGER, 0)
        self.assertIsNone(r._close_at)  # still open after release
        r.on_buttons(0, TRIGGER)
        self.assertIsNotNone(r._close_at)

    def test_retap_during_post_roll_keeps_message(self):
        r = make("toggle")
        r.on_buttons(0, TRIGGER)
        feed(r)
        r.on_buttons(TRIGGER, 0)
        r.on_buttons(0, TRIGGER)  # close
        r.on_buttons(TRIGGER, 0)
        r.on_buttons(0, TRIGGER)  # re-tap inside post-roll: ignored
        self.assertIsNotNone(finish(r))


class Logged(unittest.TestCase):
    def test_message_says_when_its_clip_started(self):
        rows = radio_rows(self)
        r = make("hold")
        r._finish(np.full(SAMPLE_RATE // 5, 0.1, dtype=np.float32), time.time())  # too short to transcribe
        msg = rows("message")[0]
        self.assertEqual(msg["note"], "too short")
        self.assertAlmostEqual(msg["clipStart"], time.time() - 0.2, delta=0.1)
        self.assertTrue((radiolog.CLIPS / msg["clip"]).exists())


class Safety(unittest.TestCase):
    def test_auto_close_after_max_open(self):
        r = make("hold")
        r.on_buttons(0, TRIGGER)
        feed(r)
        late = time.time() + MAX_OPEN_S + 1
        self.assertIsNone(r._poll(late))  # starts post-roll
        self.assertIsNotNone(r._poll(late + POST_ROLL_S + 0.01))

    def test_not_ready_does_not_open(self):
        r = make("hold")
        r.status = "loading"
        r.on_buttons(0, TRIGGER)
        self.assertIsNone(r._frames)


if __name__ == "__main__":
    unittest.main()
