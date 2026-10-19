"""The log file: INFO and up for the run whatever the console shows, and crashes that would only reach stderr."""
import logging
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from engineer import log

ROOT = logging.getLogger("re")


class LogFile(unittest.TestCase):
    def start(self, console=logging.DEBUG):
        """to_file as the server calls it, with the console at `console` (WARNING is RE_ENV=prod)."""
        saved = ROOT.level, sys.excepthook, threading.excepthook
        ROOT.setLevel(console)
        self.folder = Path(tempfile.mkdtemp()) / "logs"
        with mock.patch.object(log, "LEVEL", console):
            self.handler = log.to_file(self.folder)

        def undo():
            ROOT.removeHandler(self.handler)
            self.handler.close()
            ROOT.level, sys.excepthook, threading.excepthook = saved
        self.addCleanup(undo)

    def text(self):
        self.handler.flush()
        [f] = self.folder.glob("*.log")
        return f.read_text(encoding="utf-8")

    def test_info_and_up_even_when_the_console_only_shows_warnings(self):
        self.start(logging.WARNING)
        log.get("radio").info("radio message", text="box this lap?")
        self.assertRegex(self.text(), r'^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d \[INFO\] \[radio\] radio message \{"text": "box this lap\?"\}\n$')

    def test_debug_stays_out_of_the_file_when_the_console_shows_it(self):
        self.start(logging.DEBUG)
        log.get("radio").debug("level", rms=0.1)
        self.assertEqual(self.text(), "")

    def test_the_console_keeps_its_own_level(self):
        self.start(logging.WARNING)
        for h in ROOT.handlers:
            if h is not self.handler:
                self.assertEqual(h.level, log.LEVEL)

    def test_each_line_carries_when_it_was_logged_not_when_it_was_written(self):
        self.start()
        then = time.mktime((2026, 10, 14, 14, 3, 0, 0, 0, -1))
        record = logging.makeLogRecord({"created": then, "levelname": "INFO", "msg": "gap?", "mod": "radio"})
        self.assertEqual(self.handler.format(record), "2026-10-14 14:03:00 [INFO] [radio] gap?")

    def test_a_thread_that_dies_is_in_the_file_with_its_traceback(self):
        self.start()

        def boom():
            raise ValueError("bad packet")
        t = threading.Thread(target=boom, name="udp")
        t.start()
        t.join()
        text = self.text()
        self.assertIn('[ERROR] [crash] thread died {"thread": "udp"}', text)
        self.assertIn("ValueError: bad packet", text)

    def test_a_thread_that_exits_isnt_a_crash(self):
        self.start()
        t = threading.Thread(target=sys.exit, name="tts")
        t.start()
        t.join()
        self.assertEqual(self.text(), "")

    def test_an_uncaught_error_is_logged_but_ctrl_c_is_left_alone(self):
        self.start()
        try:
            raise RuntimeError("no session")
        except RuntimeError as e:
            sys.excepthook(RuntimeError, e, e.__traceback__)
        with mock.patch.object(sys, "__excepthook__") as default:
            sys.excepthook(KeyboardInterrupt, KeyboardInterrupt(), None)
        default.assert_called_once()
        text = self.text()
        self.assertIn("[ERROR] [crash] uncaught", text)
        self.assertIn("RuntimeError: no session", text)
        self.assertNotIn("KeyboardInterrupt", text)


if __name__ == "__main__":
    unittest.main()
