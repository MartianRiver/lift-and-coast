"""Per-session recording and the archive catalogue, on synthetic packets in a temp folder."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from engineer import archive
from engineer.capture import read
from engineer.recorder import SessionRecorder
from engineer.spec import PACKETS


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
        self.assertEqual(path, str(xz))

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


if __name__ == "__main__":
    unittest.main()
