"""A debug bundle: one session's recording, radio, model calls, logs and setup in a zip, to look through
or attach to an issue. Made only when asked for, saved under captures/bundles/, never uploaded.

The recording leaves out motion (every car's position: only the dashboard's car view reads it) and
lap-history and tyre-set packets that repeat the last one for that car, which the brief and the calls
come out the same without. A long race still won't fit one attachment, so the bundle is split into
parts of at most LIMIT bytes, side by side on an issue; `dev` opens part 1 and finds the rest.

    uv run python -m engineer.bundle last [--lap 12] [--note "said 43% when the brief had 39"] [--no-audio] [--no-telemetry]
    uv run python -m engineer.dev brief captures/bundles/<name>.zip --lap 12
"""
import argparse
import io
import json
import lzma
import platform
import re
import tempfile
import time
import zipfile
from datetime import datetime
from pathlib import Path

from . import archive, capture, log, prompts, radiolog
from .version import VERSION

_log = log.get("bundle")

FOLDER = archive.DATA / "bundles"
LIMIT = 24_000_000  # GitHub takes 25 MB per attached file
PIECE = 20_000_000  # compressed recording per part, leaving room for the rest
HEAD = 29  # packet header; lap history and tyre sets carry their car's index right after it
MOTION, REPEATS = 0, {11, 12}
SETUP = ("driver.json", "fixes.json", "pitwall-prep.json", "pitwall-brief.json", "settings.json")
AFTER = 120  # s past the recording's end that a reply, a spoken line or a log line still belongs to it


def slim(records):
    """The recording minus motion and repeated packets. -> generator of (seconds, datagram)."""
    last = {}
    for t, buf in records:
        pid = buf[6]
        if pid == MOTION:
            continue
        if pid in REPEATS:
            key = (pid, buf[HEAD])
            if last.get(key) == buf[HEAD:]:
                continue
            last[key] = buf[HEAD:]
        yield t, buf


def pieces(records, folder, size=PIECE):
    """Write records into consecutive .f1cap.xz files of at most ~size compressed bytes. -> [paths], packets."""
    paths, n, f, raw = [], 0, None, None
    for t, buf in records:
        if f is None or raw.tell() >= size:
            if f:
                f.close()
                raw.close()
            paths.append(Path(folder) / f"recording-{len(paths) + 1}.f1cap.xz")
            raw = open(paths[-1], "wb")
            f = lzma.open(raw, "wb", preset=6)  # stronger than the archive's: made once, sent once
            f.write(capture.MAGIC)
        f.write(capture._REC.pack(t, len(buf)))
        f.write(buf)
        n += 1
    if f:
        f.close()
        raw.close()
    return paths, n


def windows(uid, files):
    """[(wall-clock start, end)] of each recorded part: from its recording row on the radio log, else the
    catalogue's start time. `files` = [(path, started_at text, seconds)]."""
    rows = [r for r in _rows(radiolog.LOG) if r.get("kind") == "recording" and r.get("uid") == str(uid)]
    starts = {r["started"]: r["wall0"] for r in rows}
    out = []
    for _, started, secs in files:
        t0 = starts.get(started) or datetime.strptime(started, "%Y-%m-%d %H:%M:%S").timestamp()
        out.append((t0, t0 + (secs or 0)))
    return out


def within(t, spans, after=AFTER):
    return t is not None and any(a <= t <= b + after for a, b in spans)


def radio_rows(uid, spans):
    """The radio log's rows for this session: its recording rows, and every message, reply, call and
    spoken line while it was recording."""
    def at(r):
        return r.get("at") or r.get("start")
    return [r for r in _rows(radiolog.LOG)
            if (r.get("uid") == str(uid) if r.get("kind") == "recording" else within(at(r), spans))]


def model_calls(uid, spans, folder):
    """What was sent to the models for this session and what came back (captures/llm/)."""
    out = []
    for path in sorted(Path(folder).glob("*.jsonl")):
        out += [r for r in _rows(path) if r.get("session") == str(uid) or within(r.get("at"), spans)]
    return out


def run_logs(spans, folder):
    """Every server run's log that overlaps the session: names are the run's start, YYYYMMDD-HHMMSS."""
    runs = []
    for path in sorted(Path(folder).glob("*.log")):
        try:
            runs.append((datetime.strptime(path.stem, "%Y%m%d-%H%M%S").timestamp(), path))
        except ValueError:
            continue
    first, last = min(a for a, _ in spans), max(b for _, b in spans) + AFTER
    keep = []
    for i, (began, path) in enumerate(runs):
        ended = runs[i + 1][0] if i + 1 < len(runs) else float("inf")
        if began <= last and ended >= first:
            keep.append(path)
    return keep


def starts(logs):
    """The server's `starting` lines: version, options and models of each run."""
    out = []
    for path in logs:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            m = re.search(r"\[server\] starting (\{.*\})$", line)
            if m:
                out.append(json.loads(m.group(1)))
            m = re.search(r"\[radio\] mic open (\{.*\})$", line)
            if m and out:
                out[-1]["mic"] = json.loads(m.group(1)).get("device")
    return out


def make(uid, lap=None, note="", audio=True, telemetry=True, live=None, out=None):
    """Bundle session `uid` -> [zip paths]. live: (path, started on the wall clock) of the file still being
    recorded for it, if any."""
    db = archive.connect()
    try:
        row = db.execute("select * from sessions where uid = ?", (str(uid),)).fetchone()
        parts = [(archive.located(r["path"]), r["started_at"], r["seconds"]) for r in db.execute(
            "select path, started_at, seconds from files where session_uid = ? order by started_at", (str(uid),))]
    finally:
        db.close()
    if live:
        path, began = live
        parts.append((Path(path), time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(began)), time.time() - began))
    if not parts:
        raise ValueError(f"no recording for session {uid}")
    spans = windows(uid, parts)
    info = dict(row) if row else {"uid": str(uid)}
    # the recording's own name: date, time, track and session type, even before the catalogue has them
    name = "lift-and-coast-" + parts[-1][0].name.split(".")[0]
    folder = Path(out or FOLDER)
    folder.mkdir(parents=True, exist_ok=True)
    _log.info("making debug bundle", uid=str(uid), parts=len(parts), audio=audio, telemetry=telemetry)

    with tempfile.TemporaryDirectory() as tmp:
        items, left_out = [], []  # (name in the zip, bytes or a path)
        rows = radio_rows(uid, spans)
        items.append(("radio/messages.jsonl", _jsonl(rows)))
        clips = [("radio/" + r["clip"], radiolog.CLIPS / r["clip"]) for r in rows if r.get("kind") == "message" and r.get("clip")]
        clips += [("radio/spoken/" + r["clip"], radiolog.CLIPS / "spoken" / r["clip"]) for r in rows
                  if r.get("kind") == "spoken" and r.get("clip")]
        if audio:
            items += [c for c in clips if c[1].exists()]
        else:
            left_out.append(f"audio: {len(clips)} radio clips")
        items.append(("models.jsonl", _jsonl(model_calls(uid, spans, archive.DATA / "llm"))))
        logs = run_logs(spans, archive.DATA / "logs")
        items += [(f"logs/{p.name}", p) for p in logs]
        items += [(f"setup/{s}", archive.DATA / s) for s in SETUP if (archive.DATA / s).exists()]
        items += [(f"setup/prompts/{p.parent.name}/{p.name}", p) for p in sorted(prompts.CUSTOM.glob("*/custom-*.md"))]
        recording = {}
        if telemetry:
            paths, kept = pieces(slim(_records(p for p, _, _ in parts)), tmp)
            items += [(p.name, p) for p in paths]
            recording = {"files": [p.name for p in paths], "packets": kept,
                         "left out": "motion (packet 0) and lap-history and tyre-set packets repeating the last one for their car"}
        else:
            left_out.append("telemetry: the session's recording")
        manifest = {"made": time.strftime("%Y-%m-%d %H:%M:%S"), "version": VERSION, "platform": platform.platform(),
                    "python": platform.python_version(), "session": info, "moment": {"lap": lap} if lap else None,
                    "note": note, "recording": recording, "left out": left_out, "runs": starts(logs),
                    "radio rows": len(rows)}
        return _pack(folder, name, items, manifest)


def _pack(folder, name, items, manifest):
    """Items into as few zips of at most LIMIT as fit, in order; each part has the manifest with every file's part."""
    sized = [(n, src, len(src) if isinstance(src, bytes) else Path(src).stat().st_size) for n, src in items]
    groups, total = [[]], 0
    for item in sized:
        if groups[-1] and total + item[2] > LIMIT - 200_000:  # room for the manifest
            groups.append([])
            total = 0
        groups[-1].append(item)
        total += item[2]
    manifest["files"] = [{"name": n, "bytes": size, "part": i + 1} for i, g in enumerate(groups) for n, _, size in g]
    manifest["parts"] = len(groups)
    paths = []
    for i, group in enumerate(groups):
        path = folder / (f"{name}.zip" if len(groups) == 1 else f"{name}-part{i + 1}of{len(groups)}.zip")
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("manifest.json", json.dumps(manifest, indent=1, default=str), zipfile.ZIP_DEFLATED)
            for n, src, _ in group:
                kind = zipfile.ZIP_STORED if n.endswith(".xz") else zipfile.ZIP_DEFLATED
                if isinstance(src, bytes):
                    z.writestr(n, src, kind)
                else:
                    z.write(src, n, kind)
        paths.append(path)
    _log.info("debug bundle made", files=[str(p) for p in paths], bytes=sum(p.stat().st_size for p in paths))
    return paths


def open_bundle(path):
    """A bundle (any one of its parts) -> (label, [recording files in order]), unpacked to a temp folder."""
    path = Path(path)
    m = re.match(r"(.*)-part\d+of(\d+)$", path.stem)
    zips = [path.with_name(f"{m.group(1)}-part{i}of{m.group(2)}.zip") for i in range(1, int(m.group(2)) + 1)] if m else [path]
    missing = [z.name for z in zips if not z.exists()]
    if missing:
        raise SystemExit(f"bundle parts missing next to {path.name}: {', '.join(missing)}")
    tmp = Path(tempfile.mkdtemp(prefix="re-bundle-"))
    names = []
    for z in zips:
        with zipfile.ZipFile(z) as zf:
            for n in zf.namelist():
                if re.fullmatch(r"recording-\d+\.f1cap\.xz", n):
                    zf.extract(n, tmp)
                    names.append(n)
            manifest = json.loads(zf.read("manifest.json"))
    if not names:
        raise SystemExit(f"{path.name} was made without the telemetry")
    s = manifest.get("session") or {}
    label = " ".join(str(x) for x in (path.name, s.get("started_at"), s.get("track"), s.get("type")) if x)
    return label, [tmp / n for n in sorted(names, key=lambda n: int(re.search(r"\d+", n).group()))]


def _records(files):
    offset = 0.0
    for f in files:
        last = 0.0
        for t, buf in capture.read(f):
            last = t
            yield offset + t, buf
        offset += last


def _rows(path):
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def _jsonl(rows):
    buf = io.StringIO()
    for r in rows:
        buf.write(json.dumps(r) + "\n")
    return buf.getvalue().encode()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("session", help="an archive id, a session uid, `last` or `race`")
    ap.add_argument("--lap", type=int, help="the lap to look at")
    ap.add_argument("--note", default="", help="what went wrong, in a sentence")
    ap.add_argument("--no-audio", action="store_true", help="leave out the radio clips")
    ap.add_argument("--no-telemetry", action="store_true", help="leave out the recording")
    args = ap.parse_args()
    db = archive.connect()
    where = {"last": "1 = 1", "race": "type_id between 15 and 17"}.get(args.session)
    if where:
        row = db.execute(f"select uid from sessions where {where} order by started_at desc limit 1").fetchone()
    else:
        row = db.execute("select uid from sessions where id = ? or uid = ?", (args.session.lstrip("#"), args.session)).fetchone()
    db.close()
    if not row:
        raise SystemExit(f"no session {args.session!r} (see: uv run python -m engineer.dev sessions)")
    for p in make(row["uid"], args.lap, args.note, not args.no_audio, not args.no_telemetry):
        print(f"{p}  {p.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
