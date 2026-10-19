"""The Diagnostics tab's model errors: what failed while driving, not the dev tools' own runs."""
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from engineer import archive, diagnostics


class Errors(unittest.TestCase):
    def test_dev_and_eval_failures_stay_off_the_list(self):
        tmp = Path(tempfile.mkdtemp())
        for p in [mock.patch.object(archive, "DATA", tmp), mock.patch.object(archive, "DB", tmp / "a.db")]:
            p.start()
            self.addCleanup(p.stop)
        db = archive.connect()
        now = time.time()
        with db:
            for role, uid, error in [("engineer", "7", "no answer in 5 s"), ("dev", "", "no answer in 0.3 s"),
                                     ("eval", "", "HTTP 500"), ("judge", "", "bad JSON"), ("pitwall", "6", "HTTP 429")]:
                db.execute("insert into usage (at, session_uid, role, model, error) values (?, ?, ?, 'm', ?)", (now, uid, role, error))
        out = diagnostics._errors(db, "7")
        self.assertEqual(sorted(e["role"] for e in out["recent"]), ["engineer", "pitwall"])
        self.assertEqual(out["session"], 1)


if __name__ == "__main__":
    unittest.main()
