"""Per-session recording and the archive catalogue, on synthetic packets in a temp folder."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from engineer import archive
from engineer.capture import read
from engineer.recorder import SessionRecorder
from engineer.spec import PACKETS
from tests import radio_rows


def packet(pid, uid, t=1.0, **fields):
    data = PACKETS[pid].blank()
    data["header"].update(packetFormat=2026, gameYear=25, packetId=pid, sessionUID=uid, sessionTime=t, playerCarIndex=0)
    data.update(fields)
    return PACKETS[pid].pack(data)


def session(uid, track=17, kind=3):
    s = {k: v for k, v in PACKETS[1].blank().items() if k != "header"}
    s.update(trackId=track, sessionType=kind, trackLength=4318, totalLaps=5)
    return packet(1, uid, **s)


def history(uid, laps):
    h = {k: v for k, v in PACKETS[11].blank().items() if k != "header"}
    h.update(carIdx=0, numLaps=len(laps), bestLapTimeLapNum=1 + laps.index(min(laps)))
    for i, ms in enumerate(laps):
        h["lapHistoryData"][i].update(lapTimeInMS=ms, sector1TimeMSPart=20000, sector2TimeMSPart=25000,
                                      sector3TimeMSPart=ms - 45000, lapValidBitFlags=1)
    return packet(11, uid, **h)


class Recording(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        patches = [mock.patch.object(archive, "DATA", self.tmp), mock.patch.object(archive, "DB", self.tmp / "a.db"),
                   mock.patch.object(archive, "SESSIONS", self.tmp / "sessions"),
                   mock.patch.object(archive, "finish_later", archive.finish)]  # no background worker in tests
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_each_session_gets_its_own_named_file_and_catalogue_row(self):
        rec = SessionRecorder(self.tmp / "sessions")
        rec.write(packet(2, 0))  # menus: no session yet, dropped
        rec.write(session(111))
        rec.write(history(111, [66000, 65500]))
        first = rec.path
        rec.write(session(222, track=6, kind=15))
        self.assertIn("_Austria_P3", first.name)
        self.assertIn("_Montreal_Race", rec.path.name)
        rec.close(wait=True)

        db = archive.connect()
        rows = {r["track"]: r for r in db.execute("select * from sessions")}
        self.assertEqual(set(rows), {"Austria", "Montreal"})
        self.assertEqual(rows["Austria"]["best_lap_ms"], 65500)
        laps = db.execute("select lap, lap_ms, s3_ms from laps order by lap").fetchall()
        self.assertEqual([tuple(r) for r in laps], [(1, 66000, 21000), (2, 65500, 20500)])

    def test_packets_that_arrive_while_the_server_stops_are_dropped(self):
        rec = SessionRecorder(self.tmp / "sessions")
        rec.write(session(444))
        finish = archive.finish

        def busy(path, started):  # the game keeps sending while the last file is archived
            rec.write(session(444))
            finish(path, started)
        with mock.patch.object(archive, "finish", busy):
            rec.close(wait=True)
        self.assertEqual(list((self.tmp / "sessions").glob("*.f1cap")), [])

    def test_finished_file_is_compressed_and_still_readable(self):
        rec = SessionRecorder(self.tmp / "sessions")
        rec.write(session(333))
        rec.write(history(333, [70000]))
        raw = rec.path
        rec.close(wait=True)
        xz = raw.with_name(raw.name + ".xz")
        self.assertFalse(raw.exists())
        self.assertEqual(len(list(read(xz))), 2)
        path = archive.connect().execute("select path from files").fetchone()["path"]
        self.assertEqual(path, f"sessions/{xz.name}")  # relative, so the data folder can move
        self.assertEqual(archive.located(path), xz)

    def test_reindexing_an_old_catalogue_doesnt_list_a_file_twice(self):
        rec = SessionRecorder(self.tmp / "sessions")
        rec.write(session(777))
        rec.write(history(777, [70000]))
        rec.close(wait=True)
        db = archive.connect()
        with db:
            db.execute("update files set path = ? || path, started_at = '2026-10-13 18:18:18'",  # as the old rows
                       (tempfile.mkdtemp() + "/",))
        db.close()
        db = archive.connect()
        archive.reindex(db)
        self.assertEqual([tuple(r) for r in db.execute("select started_at from files")], [("2026-10-13 18:18:18",)])

    def test_leftover_raw_file_is_finished_on_start(self):
        rec = SessionRecorder(self.tmp / "sessions")
        rec.write(session(444))
        rec.writer.close()  # crash: never archived
        leftover = rec.path
        SessionRecorder(self.tmp / "sessions")
        self.assertTrue(leftover.with_name(leftover.name + ".xz").exists())

    def test_a_quiet_game_closes_the_file_and_the_same_session_resuming_opens_a_second_part(self):
        rec = SessionRecorder(self.tmp / "sessions")
        rec.write(session(555))
        rec.write(history(555, [70000]))
        rec.idle()
        self.assertIsNotNone(rec.writer)  # not quiet for long enough yet
        rec.last_write -= 300
        rec.idle()
        self.assertIsNone(rec.writer)
        rec.write(history(555, [70000, 69000]))  # saved game resumed with the same uid
        self.assertIsNotNone(rec.writer)
        rec.close(wait=True)
        self.assertEqual(len(list(self.tmp.joinpath("sessions").glob("*.f1cap.xz"))), 2)

    def test_each_file_puts_its_start_on_the_radio_log(self):
        rows = radio_rows(self)
        rec = SessionRecorder(self.tmp / "sessions")
        rec.write(session(666))
        first = rec.writer.wall0
        rec.last_write -= 300
        rec.idle()
        rec.write(history(666, [70000]))  # a second part has its own t=0
        second = rec.writer.wall0
        rec.close(wait=True)
        self.assertEqual([(r["uid"], r["wall0"]) for r in rows("recording")], [("666", first), ("666", second)])
        self.assertLess(first, second)



class OldCatalogue(unittest.TestCase):
    """A catalogue from before paths were relative, copied over from another folder."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        for p in [mock.patch.object(archive, "DATA", self.tmp / "data"), mock.patch.object(archive, "DB", self.tmp / "data" / "a.db"),
                  mock.patch.object(archive, "SESSIONS", self.tmp / "data" / "sessions")]:
            p.start()
            self.addCleanup(p.stop)
        archive.SESSIONS.mkdir(parents=True)
        (archive.SESSIONS / "2026-10-13_181818_Austria_Race.f1cap.xz").write_bytes(b"")
        db = archive.connect()
        with db:
            for name in ("2026-10-13_181818_Austria_Race.f1cap.xz", "2026-10-12_090000_Spa_Race.f1cap.xz"):
                old = str(self.tmp / "elsewhere" / "sessions" / name)
                db.execute("insert into files (path, session_uid) values (?, '1')", (old,))
                db.execute("insert into events (session_uid, file, code) values ('1', ?, 'SSTA')", (old,))
        db.close()

    def rows(self):
        db = archive.connect()
        return sorted(r[0] for r in db.execute("select path from files")), sorted(r[0] for r in db.execute("select file from events"))

    def test_files_that_are_here_are_found_here(self):
        files, events = self.rows()
        self.assertEqual(files, sorted([str(self.tmp / "elsewhere" / "sessions" / "2026-10-12_090000_Spa_Race.f1cap.xz"),  # not here
                                        "sessions/2026-10-13_181818_Austria_Race.f1cap.xz"]))
        self.assertEqual(events, files)
        self.assertTrue(archive.located("sessions/2026-10-13_181818_Austria_Race.f1cap.xz").exists())

    def test_the_copy_here_wins_while_the_old_folder_still_exists(self):
        old = self.tmp / "elsewhere" / "sessions" / "2026-10-14_172555_Zandvoort_Race.f1cap.xz"
        old.parent.mkdir(parents=True)
        old.write_bytes(b"")
        (archive.SESSIONS / old.name).write_bytes(b"")
        db = archive.connect()
        with db:
            db.execute("insert into files (path, session_uid) values (?, '3')", (str(old),))
        db.close()
        self.assertIn(f"sessions/{old.name}", self.rows()[0])

    def test_rows_an_older_version_adds_later_are_moved_too(self):
        self.rows()
        db = archive.connect()
        with db:
            db.execute("insert into files (path, session_uid) values (?, '2')", (str(archive.SESSIONS / "2026-10-17_114731_Austria_Race.f1cap.xz"),))
        db.close()
        self.assertIn("sessions/2026-10-17_114731_Austria_Race.f1cap.xz", self.rows()[0])


if __name__ == "__main__":
    unittest.main()
