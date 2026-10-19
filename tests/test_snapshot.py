"""The release check's snapshot: briefs every few laps and every call over a race, and the diff of two."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from engineer import archive, capture, snapshot

from .test_brief import Race, line_time


def packets(until_lap=12):
    r, got = Race(), []
    r.st = SimpleNamespace(ingest=lambda buf, src: got.append((0.0, buf)))
    r.setup()
    r.run(12, line_time(0, until_lap) + 20)
    return got


class Steps:
    """A caller that says one thing on lap 4, and counts how often it's stepped."""
    def __init__(self, st, hub):
        self.st, self.steps, self.said = st, 0, False

    def step(self):
        self.steps += 1
        me = self.st.latest[2]["lapData"][0]
        if me["currentLapNum"] == 4 and not self.said:
            self.said = True
            return [{"lap": 4, "dist": 1234, "topic": "gap", "text": "Tsunoda half a second back."}]
        return []


class Snapshot(unittest.TestCase):
    def test_a_brief_every_few_laps_and_the_calls_where_they_came(self):
        made = []
        with mock.patch.object(snapshot, "Caller", lambda st, hub: made.append(Steps(st, hub)) or made[-1]):
            text = snapshot.race(packets())
        heads = [line for line in text.splitlines() if line.startswith("==")]
        self.assertEqual(heads, ["== brief, start of L1", "== brief, start of L6", "== brief, start of L11"])
        self.assertIn("SESSION  Race", text.split("start of L6")[1])
        self.assertLess(text.index("start of L1"), text.index("L4 1234 m [gap] Tsunoda half a second back."),
                        text.index("start of L6"))
        # the test race sends lap data every 0.5 s of session time, so each one is a step at the live rate
        self.assertEqual(made[0].steps, int((line_time(0, 12) + 20 - 12) / 0.5) + 1)

    def test_the_same_race_gives_the_same_text(self):
        race = packets(7)
        self.assertEqual(snapshot.race(race), snapshot.race(race))

    def test_every_race_in_the_archive_gets_its_file(self):
        tmp = Path(tempfile.mkdtemp())
        for p in [mock.patch.object(archive, "DATA", tmp), mock.patch.object(archive, "DB", tmp / "a.db")]:
            p.start()
            self.addCleanup(p.stop)
        race = packets(7)
        capture.write(tmp / "race.f1cap.xz", race)
        capture.write(tmp / "quali.f1cap.xz", race[:50])
        db = archive.connect()
        with db:
            db.execute("insert into sessions (id, uid, started_at, track, type_id) values (1, '99', '2026-10-18 16:05:30', 'Brazil', 16)")
            db.execute("insert into sessions (id, uid, started_at, track, type_id) values (2, '98', '2026-10-18 15:56:21', 'Brazil', 13)")
            db.execute("insert into sessions (id, uid, started_at, track, type_id) values (3, '97', '2026-10-17 17:02:51', 'Zandvoort', 15)")
            db.execute("insert into files (path, session_uid, started_at) values ('race.f1cap.xz', '99', '2026-10-18 16:05:30')")
            db.execute("insert into files (path, session_uid, started_at) values ('gone.f1cap.xz', '97', '2026-10-17 17:02:51')")
            db.execute("insert into files (path, session_uid, started_at) values ('quali.f1cap.xz', '98', '2026-10-18 15:56:21')")
        db.close()
        out = tmp / "snap"
        self.assertEqual(snapshot.make(out, jobs=1), 1)  # quali isn't a race; the Zandvoort file is gone
        [made] = out.glob("*.txt")
        self.assertEqual(made.name, "2026-10-18_160530_Brazil_99.txt")
        self.assertEqual(made.read_text(encoding="utf-8"), snapshot.race(race))
        self.assertEqual(snapshot.make(tmp / "none", only={3}, jobs=1), 0)
        self.assertEqual(snapshot.make(tmp / "pool", jobs=2), 1)  # worker processes, reading this archive too
        self.assertEqual((tmp / "pool" / made.name).read_text(encoding="utf-8"), made.read_text(encoding="utf-8"))

    def test_diff_names_the_races_that_changed(self):
        a, b = Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp())
        (a / "monza.txt").write_text("L3 [gap] Norris 1.2 back\n")
        (b / "monza.txt").write_text("L3 [gap] Norris 1.2 back\n")
        (a / "spa.txt").write_text("== brief\nRL 39%\n")
        (b / "spa.txt").write_text("== brief\nRL 43%\n")
        (b / "brazil.txt").write_text("new race\n")
        text, changed = snapshot.diff(a, b)
        self.assertEqual(changed, 2)
        self.assertIn("-RL 39%\n+RL 43%", text)
        self.assertIn("+new race", text)
        self.assertNotIn("monza", text)


if __name__ == "__main__":
    unittest.main()
