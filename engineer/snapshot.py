"""What the engineer would have seen and said over every recorded race, with no models: the brief at
the start of every EVERY-th lap and every unprompted call, one text file per race. Made on two
versions and diffed, it shows everything a change does to them (docs/releasing.md, step 4).

    uv run python -m engineer.dev snapshot out/next             # every race in the archive
    uv run python -m engineer.dev snapshot out/branch --only 35,40
    uv run python -m engineer.dev snapshot --diff out/next out/branch
"""
import difflib
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from . import archive, brief
from .calls import Caller
from .dev import Quiet, _records
from .spec import MAX_CARS
from .state import RaceState

EVERY = 5


def race(packets):
    """(seconds, datagram) pairs -> the text: the brief at the first lap and every EVERY-th after, and the calls,
    in the order they came."""
    st = RaceState(Quiet())
    caller, last, due, out = Caller(st, Quiet()), -1.0, 1, []
    for _, buf in packets:
        st.ingest(buf, ("dev", 0))
        pkt = st.latest.get(2)
        if not pkt:
            continue
        now = pkt["header"]["sessionTime"]
        if abs(now - last) < 0.2:  # the live server steps the caller 5 times a second
            continue
        last = now
        out += [f"L{c['lap']} {c['dist']} m [{c['topic']}] {c['text']}" for c in caller.step()]
        me = pkt["header"]["playerCarIndex"]
        lap = pkt["lapData"][me]["currentLapNum"] if me < MAX_CARS else 0
        if lap >= due:
            out.append(f"\n== brief, start of L{lap}\n{brief.build(st) or '(not enough data)'}\n")
            due = lap + EVERY
    return "\n".join(out) + "\n"


def _one(job):
    name, files, folder, paths = job
    # a worker is a new process: the brief's pit loss reads earlier races from the archive this one listed
    archive.DATA, archive.DB = paths
    (folder / f"{name}.txt").write_text(race(_records(files)))
    return name


def races(only=None):
    """[(file name, [capture files])] for every race in the archive, or the archive ids in `only`."""
    db = archive.connect()
    rows = db.execute("select * from sessions where type_id between 15 and 17 order by started_at").fetchall()
    out = []
    for r in rows:
        if only and r["id"] not in only:
            continue
        files = [archive.located(f["path"]) for f in db.execute(
            "select path from files where session_uid = ? order by started_at", (r["uid"],))]
        if files and all(f.exists() for f in files):
            out.append((f"{r['started_at'].replace(' ', '_').replace(':', '')}_{r['track']}_{r['uid']}", files))
    db.close()
    return out


def make(folder, only=None, jobs=None):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    todo = [(name, files, folder, (archive.DATA, archive.DB)) for name, files in races(only)]
    if jobs == 1:
        done = list(map(_one, todo))
    else:
        with ProcessPoolExecutor(jobs) as pool:
            done = list(pool.map(_one, todo))
    print("".join(f"  {name}\n" for name in done), end="")
    return len(done)


def diff(a, b):
    """Unified diff of two snapshot folders, race by race -> (text, races that differ)."""
    a, b = Path(a), Path(b)
    out, changed = [], 0
    for name in sorted({p.name for p in a.glob("*.txt")} | {p.name for p in b.glob("*.txt")}):
        left = (a / name).read_text().splitlines(keepends=True) if (a / name).exists() else []
        right = (b / name).read_text().splitlines(keepends=True) if (b / name).exists() else []
        d = list(difflib.unified_diff(left, right, str(a / name), str(b / name)))
        changed += bool(d)
        out += d
    return "".join(out), changed
