"""Debug bundles: what goes in for one session, what's left out of the recording, parts that fit an
issue, and the dev tools reading one back."""
import json
import random
import tempfile
import time
import unittest
import zipfile
from datetime import datetime
from pathlib import Path
from unittest import mock

from engineer import archive, bundle, capture, radiolog
from engineer.spec import PACKETS


def packet(pid, t, car=0, **fields):
    data = PACKETS[pid].blank()
    data["header"].update(packetFormat=2026, gameYear=25, packetId=pid, sessionUID=7, sessionTime=t)
    if pid in (11, 12):
        data["carIdx"] = car
    data.update(fields)
    return PACKETS[pid].pack(data)


WALL0 = datetime(2026, 10, 18, 16, 5, 30).timestamp()


class Bundle(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        for p in [mock.patch.object(archive, "DATA", self.tmp), mock.patch.object(archive, "DB", self.tmp / "a.db"),
                  mock.patch.object(radiolog, "CLIPS", self.tmp / "radio"),
                  mock.patch.object(radiolog, "LOG", self.tmp / "radio" / "messages.jsonl"),
                  mock.patch.object(bundle, "FOLDER", self.tmp / "bundles")]:
            p.start()
            self.addCleanup(p.stop)
        for d in ("radio/spoken", "llm", "logs", "sessions"):
            (self.tmp / d).mkdir(parents=True)

    def session(self, seconds=600.0):
        """A recorded race: 20 Hz motion and lap data, lap history that only changes once, and its catalogue rows."""
        recs = []
        for i in range(200):
            t = i * 0.05
            recs += [(t, packet(0, t)), (t, packet(2, t)), (t, packet(11, t, car=1, numLaps=1 + (i >= 100)))]
        capture.write(self.tmp / "sessions" / "2026-10-18_160530_Brazil_Race-2.f1cap.xz", recs)
        db = archive.connect()
        with db:
            db.execute("insert into sessions (uid, started_at, track, type) values ('7', '2026-10-18 16:05:30', 'Brazil', 'Race 2')")
            db.execute("insert into files (path, session_uid, started_at, seconds) values ('sessions/2026-10-18_160530_Brazil_Race-2.f1cap.xz', '7', '2026-10-18 16:05:30', ?)",
                       (seconds,))
        db.close()
        return recs

    def radio(self, *rows):
        with radiolog.LOG.open("a") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")

    def test_the_recording_keeps_everything_but_motion_and_repeats(self):
        recs = self.session()
        kept = list(bundle.slim(recs))
        self.assertEqual(sum(b[6] == 0 for _, b in kept), 0)
        self.assertEqual(sum(b[6] == 2 for _, b in kept), 200)
        self.assertEqual([t for t, b in kept if b[6] == 11], [0.0, 5.0])  # the history packet only when it changed
        # each car's history arrives in turn: a repeat is against that car's last one, not the last packet
        turns = [(0.0, packet(11, 0.0, car=1, numLaps=1)), (0.1, packet(11, 0.1, car=2, numLaps=3)), (0.2, packet(11, 0.2, car=1, numLaps=1))]
        self.assertEqual([t for t, _ in bundle.slim(turns)], [0.0, 0.1])

    def test_a_long_recording_goes_into_pieces(self):
        rng = random.Random(1)  # doesn't compress, so the pieces fill up
        noise = [(i * 0.05, bytes([0, 0, 0, 0, 0, 0, 2]) + rng.randbytes(1600)) for i in range(3000)]
        paths, n = bundle.pieces(noise, self.tmp, size=200_000)
        self.assertGreater(len(paths), 1)
        self.assertEqual(n, 3000)
        back = [r for p in paths for r in capture.read(p)]
        self.assertEqual(back, noise)

    def test_whats_in_it_for_one_session(self):
        self.session()
        clip, spoken, other = "20261018-160600.wav", "20261018-160602-1.wav", "20261018-120000.wav"
        for name in (clip, other):
            (self.tmp / "radio" / name).write_bytes(b"RIFF" + b"\0" * 1000)
        (self.tmp / "radio" / "spoken" / spoken).write_bytes(b"RIFF" + b"\0" * 500)
        self.radio({"kind": "recording", "uid": "7", "started": "2026-10-18 16:05:30", "wall0": WALL0},
                   {"kind": "message", "at": WALL0 + 30, "text": "gap?", "clip": clip},
                   {"kind": "reply", "at": WALL0 + 30, "text": "1.2 to Leclerc."},
                   {"kind": "spoken", "start": WALL0 + 32, "clip": spoken},
                   {"kind": "message", "at": WALL0 - 4000, "text": "earlier session", "clip": other},
                   {"kind": "recording", "uid": "6", "started": "2026-10-18 15:00:00", "wall0": WALL0 - 4000})
        (self.tmp / "llm" / "20261018.jsonl").write_text(
            json.dumps({"at": WALL0 + 31, "session": "7", "reply": "1.2 to Leclerc."}) + "\n"
            + json.dumps({"at": WALL0 - 4000, "session": "6", "reply": "other"}) + "\n" + "not json\n")
        run = time.strftime("%Y%m%d-%H%M%S", time.localtime(WALL0 - 60))
        (self.tmp / "logs" / f"{run}.log").write_text(
            '2026-10-18 16:04:30 [INFO] [server] starting {"version": "0.2.0", "engineer_model": "moonshotai/kimi-k3"}\n'
            '2026-10-18 16:04:30 [INFO] [radio] mic open {"device": "MacBook Air Microphone"}\n')
        (self.tmp / "logs" / "20261017-090000.log").write_text("a run the day before\n")
        (self.tmp / "logs" / "notes.log").write_text("not a run\n")
        (self.tmp / "driver.json").write_text('{"name": "River"}')

        [z] = bundle.make("7", lap=13, note="said 43%")
        with zipfile.ZipFile(z) as zf:
            names = set(zf.namelist())
            manifest = json.loads(zf.read("manifest.json"))
            radio = [json.loads(line) for line in zf.read("radio/messages.jsonl").decode().splitlines()]
            calls = zf.read("models.jsonl").decode()
        self.assertEqual(names, {"manifest.json", "radio/messages.jsonl", f"radio/{clip}", f"radio/spoken/{spoken}",
                                 "models.jsonl", f"logs/{run}.log", "setup/driver.json", "recording-1.f1cap.xz"})
        self.assertEqual([r.get("text") for r in radio], [None, "gap?", "1.2 to Leclerc.", None])
        self.assertIn("1.2 to Leclerc.", calls)
        self.assertNotIn("other", calls)
        self.assertEqual((manifest["note"], manifest["moment"], manifest["parts"], manifest["left out"]),
                         ("said 43%", {"lap": 13}, 1, []))
        self.assertEqual(manifest["runs"], [{"version": "0.2.0", "engineer_model": "moonshotai/kimi-k3", "mic": "MacBook Air Microphone"}])
        self.assertEqual(manifest["session"]["track"], "Brazil")
        self.assertEqual(z.name, "lift-and-coast-2026-10-18_160530_Brazil_Race-2.zip")

    def test_audio_and_telemetry_can_be_left_out(self):
        self.session()
        (self.tmp / "radio" / "a.wav").write_bytes(b"RIFF")
        self.radio({"kind": "message", "at": WALL0 + 30, "text": "gap?", "clip": "a.wav"})
        [z] = bundle.make("7", audio=False, telemetry=False)
        with zipfile.ZipFile(z) as zf:
            names = zf.namelist()
            manifest = json.loads(zf.read("manifest.json"))
        self.assertNotIn("radio/a.wav", names)
        self.assertFalse([n for n in names if n.endswith(".xz")])
        self.assertEqual(manifest["left out"], ["audio: 1 radio clips", "telemetry: the session's recording"])
        with self.assertRaises(SystemExit):
            bundle.open_bundle(z)

    def test_without_a_recording_row_the_catalogue_time_places_it(self):
        self.session(seconds=60)
        self.radio({"kind": "message", "at": WALL0 + 50, "text": "in it"},
                   {"kind": "message", "at": WALL0 + 60 + bundle.AFTER + 5, "text": "after it"})
        rows = bundle.radio_rows("7", bundle.windows("7", [(None, "2026-10-18 16:05:30", 60)]))
        self.assertEqual([r["text"] for r in rows], ["in it"])

    def test_the_recording_row_beats_the_catalogue_time(self):
        self.session(seconds=600)
        late = WALL0 + 500  # the catalogue's start is to the second, this is when the file's clock started
        self.radio({"kind": "recording", "uid": "7", "started": "2026-10-18 16:05:30", "wall0": late},
                   {"kind": "message", "at": late + 590, "text": "near the end"})
        rows = bundle.radio_rows("7", bundle.windows("7", [(None, "2026-10-18 16:05:30", 600)]))
        self.assertEqual([r.get("text") for r in rows], [None, "near the end"])

    def test_the_file_still_being_recorded_is_included(self):
        recs = self.session()
        live = self.tmp / "sessions" / "2026-10-18_163000_Brazil_Race-2.f1cap"
        capture.write(live, [(0.0, packet(2, 0.0))])
        began = time.time() - 300  # the second part, five minutes in
        self.radio({"kind": "message", "at": began + 100, "text": "on the second part"})
        [z] = bundle.make("7", live=(live, began))
        self.assertEqual(z.name, "lift-and-coast-2026-10-18_163000_Brazil_Race-2.zip")  # named after the newest part
        label, files = bundle.open_bundle(z)
        self.assertEqual(sum(1 for f in files for _ in capture.read(f)), len(list(bundle.slim(recs))) + 1)
        with zipfile.ZipFile(z) as zf:
            self.assertIn("on the second part", zf.read("radio/messages.jsonl").decode())

    def test_too_big_for_one_attachment_goes_in_parts_the_dev_tools_join_again(self):
        recs = self.session()
        rng = random.Random(2)
        for i in range(3):
            (self.tmp / "radio" / f"{i}.wav").write_bytes(rng.randbytes(120_000))
            self.radio({"kind": "message", "at": WALL0 + 10 * i, "text": "gap?", "clip": f"{i}.wav"})
        with mock.patch.object(bundle, "LIMIT", 450_000):
            parts = bundle.make("7")
        self.assertGreater(len(parts), 1)
        self.assertTrue(all(p.stat().st_size <= 450_000 for p in parts))
        self.assertEqual([p.name for p in parts], [f"lift-and-coast-2026-10-18_160530_Brazil_Race-2-part{i}of{len(parts)}.zip"
                                                   for i in range(1, len(parts) + 1)])
        with zipfile.ZipFile(parts[-1]) as zf:
            files = json.loads(zf.read("manifest.json"))["files"]
        self.assertEqual({f["part"] for f in files}, set(range(1, len(parts) + 1)))
        label, files = bundle.open_bundle(parts[-1])  # any part opens the whole
        self.assertEqual([r for f in files for r in capture.read(f)], list(bundle.slim(recs)))
        self.assertIn("Brazil", label)
        parts[0].unlink()
        with self.assertRaises(SystemExit):
            bundle.open_bundle(parts[-1])

    def test_a_server_that_never_used_the_radio_still_bundles(self):
        self.session()
        [z] = bundle.make("7", telemetry=False)  # no radio log at all
        with zipfile.ZipFile(z) as zf:
            self.assertEqual(zf.read("radio/messages.jsonl"), b"")

    def test_a_session_with_no_recording_is_an_error(self):
        with self.assertRaisesRegex(ValueError, "no recording for session 12345"):
            bundle.make("12345")


if __name__ == "__main__":
    unittest.main()
