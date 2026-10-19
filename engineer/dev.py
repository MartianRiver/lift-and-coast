"""Dev and test bench over the archive: rebuild any session's state at any lap, without the game
and without touching the live server.

    uv run python -m engineer.dev sessions
    uv run python -m engineer.dev brief 4 --lap 21 [--into 40]
    uv run python -m engineer.dev ask 4 --lap 21 "where am I losing time to Hamilton?" [--model a,b] [--repeat 3]
    uv run python -m engineer.dev serve 4 --lap 13 [--play 1]   # dashboard + engineer on :8078
    uv run python -m engineer.dev calls 4 [--lap 20]            # every unprompted call the engineer would have made
    uv run python -m engineer.dev radio [--last 20]              # radio messages: transcript, reply (or why none), clip
    uv run python -m engineer.dev pits                           # what a stop costs at each track, from every archived race
    uv run python -m engineer.dev prep [--run]                   # the race plan before the race loads (fuel, start tyre, stops)
    uv run python -m engineer.dev triggers 8                     # when the pit wall would run over a race, and why (no models)
    uv run python -m engineer.dev wall 8 --lap 10 [--why "..."] [--ask "should I box?"]   # one pit wall run there

A session is an archive id (from `sessions`), `last`, `race` (latest race), or a capture file path.
--lap N stops when you start lap N (plus --into seconds); --at S is seconds into the session.
"""
import argparse
import threading
import time
from pathlib import Path

from . import archive, brief, driver, llm, log
from .calls import Caller
from .capture import read
from .engineer import DEFAULT_MODEL, prompt
from .hub import Hub
from .llm import stream
from .pitwall import MODELS
from .spec import MAX_CARS
from .state import RaceState

_log = log.get("dev")


def resolve(ref):
    """-> (label, [files in order])"""
    if Path(ref).exists():
        return Path(ref).name, [Path(ref)]
    db = archive.connect()
    where = {"last": "1 = 1", "race": "s.type_id between 15 and 17"}.get(ref, "s.id = ?")
    args = () if ref in ("last", "race") else (int(ref.lstrip("#")),)
    if ref.isdigit() and len(ref) > 9:  # a sessionUID: survives a reindex, ids don't
        where, args = "s.uid = ?", (ref,)
    row = db.execute(f"select s.* from sessions s where {where} order by s.started_at desc limit 1", args).fetchone()
    if not row:
        raise SystemExit(f"no session {ref!r} (see: uv run python -m engineer.dev sessions)")
    files = [archive.located(r["path"]) for r in db.execute("select path from files where session_uid = ? order by started_at", (row["uid"],))]
    return f"#{row['id']} {row['started_at']} {row['track']} {row['type']}", files


def load(files, lap=None, into=0.0, at=None, hub=None):
    """Feed a session into a fresh RaceState up to the moment -> (state, rest) where rest yields what's left."""
    st = RaceState(hub or Quiet())
    records = _records(files)
    for t, buf in records:
        st.ingest(buf, ("dev", 0))
        if _reached(st, t, lap, into, at):
            break
    return st, records


def _records(files):
    offset = 0.0
    for f in files:
        last = 0.0
        for t, buf in read(f):
            last = t
            yield offset + t, buf
        offset += last


def _reached(st, t, lap, into, at):
    if at is not None:
        return t >= at
    if lap is None or 2 not in st.latest:
        return False
    pkt = st.latest[2]
    me = pkt["header"]["playerCarIndex"]
    if me >= MAX_CARS:
        return False
    my = pkt["lapData"][me]
    return my["currentLapNum"] > lap or (my["currentLapNum"] == lap and my["currentLapTimeInMS"] >= into * 1000)


class Quiet:
    def publish(self, *_):
        pass


# --- commands ---------------------------------------------------------------------

def cmd_brief(args):
    label, files = resolve(args.session)
    st, _ = load(files, args.lap, args.into, args.at)
    print(f"# {label}\n" + (brief.build(st) or "not enough data yet"))


def cmd_ask(args):
    label, files = resolve(args.session)
    st, _ = load(files, args.lap, args.into, args.at)
    data = brief.build(st)
    if not data:
        raise SystemExit("not enough data at that point for a brief")
    print(f"# {label}, brief {len(data)} chars")
    for q in args.questions:
        print(f"\nQ: {q}")
        for model in args.model.split(","):
            for _ in range(args.repeat):
                out = []
                s = stream(model, prompt(data, q), out.append, role="dev")
                print(f"  [{model} via {s['provider']}, first word {s['firstMs']} ms, {s['totalMs']} ms] {''.join(out).strip()}")


def replay_calls(files, until_lap=None):
    """Every unprompted call the engineer would have made, stepping the caller as the live server does."""
    st = RaceState(Quiet())
    caller, last = Caller(st, Quiet()), -1.0
    for t, buf in _records(files):
        st.ingest(buf, ("dev", 0))
        pkt = st.latest.get(2)
        now = pkt["header"]["sessionTime"] if pkt else 0.0
        if abs(now - last) < 0.2:
            continue
        last = now
        yield from caller.step()
        if until_lap and _reached(st, t, until_lap, 0.0, None):
            return


def cmd_calls(args):
    label, files = resolve(args.session)
    print(f"# {label}: unprompted calls")
    for c in replay_calls(files, args.lap):
        print(f"  L{c['lap']:<2} {c['dist']:>5} m  t={c['sessionTime']:>7}  [{c['topic']}] {c['text']}")


def replay_triggers(files, run=False):
    """Every pit wall run over a session, stepping the wall as the live server does; run=True calls the
    models at each one (the replay waits for them), else it's free. Yields (job, wall)."""
    from .pitwall import PitWall

    st = RaceState(Quiet())
    wall, last = PitWall(st, Quiet(), persist=False), -1.0
    for _, buf in _records(files):
        st.ingest(buf, ("dev", 0))
        pkt = st.latest.get(2)
        now = pkt["header"]["sessionTime"] if pkt else 0.0
        if abs(now - last) < 1.0:
            continue
        last = now
        job = wall.step()
        if job:
            if run:
                wall.run(*job, wait=True)
            elif any(r["key"] == ("plans",) for r in job[0]):
                wall.plans = {"A": "(dry run)"}
            yield job, wall


def cmd_triggers(args):
    label, files = resolve(args.session)
    print(f"# {label}: pit wall runs" + (" (with the models)" if args.run else ""))
    n, wall = 0, None
    for (reasons, lap, now, _), wall in replay_triggers(files, args.run):
        n += 1
        urgent = "!" if any(r["urgent"] for r in reasons) else " "
        print(f"  L{lap:<2} t={now:>7.1f} {urgent} " + " · ".join(r["text"] for r in reasons))
        for note in [x for x in wall.notes if x["lap"] == lap and not x.get("shown")]:
            note["shown"] = True
            if note["who"] == "lead":
                print(f"        CALL {note.get('call') or note.get('error')}\n        SAY  {note.get('say')}\n        WHY  {note.get('why')}"
                      + (f"\n        PLANS {note['plans']} active {note['active']}" if note.get("plans") else ""))
            else:
                print(f"        2nd  {'agrees' if note['agree'] else 'DISAGREES'}: {note['text']}")
    print(f"{n} runs" + (f", ${wall.spent:.3f}" if args.run and wall else ""))


def cmd_wall(args):
    from .pitwall import PitWall
    from .pitwall.triggers import reason

    label, files = resolve(args.session)
    st, _ = load(files, args.lap, args.into, args.at)
    wall = PitWall(st, Quiet(), args.models.split(","), persist=False)
    with st.lock:
        pkt = st.latest[2]
        me = pkt["lapData"][pkt["header"]["playerCarIndex"]]
        lap, now, stops = me["currentLapNum"], pkt["header"]["sessionTime"], me["numPitStops"]
    reasons = [reason(("plans",), "no plans yet: write plans A, B and C from here")]
    reasons += [reason(("why",), args.why)] if args.why else []
    reasons += [reason(("question",), f'{driver.name()} asked: "{args.ask}"', urgent=True, question=args.ask)] if args.ask else []
    print(f"# {label}, L{lap}: " + " · ".join(r["text"] for r in reasons))
    note = wall.run(reasons, lap, now, stops, wait=True)
    for n in wall.notes:
        if n["who"] == "lead":
            print(f"\n[{n['model']}, {n.get('ms')} ms, ${n.get('cost') or 0:.4f}]\n{n.get('text') or n.get('error')}")
        else:
            print(f"\n[{n['model']}, {n.get('ms')} ms, ${n.get('cost') or 0:.4f}] review: "
                  f"{'agree' if n['agree'] else 'DISAGREE' if n['agree'] is False else '?'}: {n['text']}")
    if note and note.get("plans"):
        print("\n" + wall.section())


def cmd_prep(args):
    """The race prep: what the team reads before the race loads, and with --run its plan (saved for the race)."""
    from .pitwall import PitWall, prep

    text, info = prep.facts()
    print(text or info)
    if not (text and args.run):
        return
    llm.TRACE = archive.DATA / "llm"  # the race uses this plan, so it's kept like the live calls
    wall = PitWall(RaceState(Quiet()), Quiet(), args.models.split(","), persist=False)
    wall._prepare()
    p = wall.prep
    if p.get("error"):
        raise SystemExit(p["error"])
    print(f"\n[{p['note']['model']}, {p['note'].get('ms')} ms]\n{p['note']['text']}")
    if p.get("review"):
        print(f"\n[{p['review']['model']}] {'agree' if p['review']['agree'] else 'DISAGREE'}: {p['review']['text']}")


def cmd_radio(args):
    """Radio messages with their clip and what the engineer did, newest last."""
    from . import radiolog

    msgs = radiolog.history()
    if not msgs:
        return print(f"no radio messages recorded yet ({radiolog.LOG})")
    for m in msgs[-args.last:]:
        when = time.strftime("%m-%d %H:%M:%S", time.localtime(m["at"]))
        said = m["text"] or f"({m['note']})"
        if m.get("heard") and m["heard"] != m["text"]:
            said += f'  [heard "{m["heard"]}"]'
        print(f"{when}  {m['source']:<5} {m['audioSec']:>5.2f}s loud {m.get('loud') or 0:.4f}  {said}")
        r = m["reply"]
        if r:
            print(f"{'':16}-> {r['text'] if r['status'] == 'done' else r['status'] + ': ' + (r.get('why') or r.get('error') or '')}")
        if m.get("clip"):
            print(f"{'':16}   {radiolog.CLIPS / m['clip']}")


def cmd_pits(_args):
    from statistics import median

    from . import pitstops

    tracks = pitstops.by_track(archive.connect())
    if not tracks:
        return print("no races in the archive yet")
    for track, t in tracks.items():
        g = t["green"]
        parts = [f"green-flag stop {median(g):.1f}s ({len(g)} stop{"s" * (len(g) != 1)}, {min(g):.1f}–{max(g):.1f})"] if g else []
        # an SC stop measured against green laps isn't what it costs under the SC: count them only
        parts += [f"{len(t[k])} {k} stop{'s' * (len(t[k]) != 1)} kept apart" for k in ("sc", "weather") if t[k]]
        print(f"{track:<14} {' · '.join(parts) or 'no stops measured'}  [{t['races']} race{'s' * (t['races'] != 1)} with green-flag stops]")


def cmd_serve(args):
    from .crew import assemble
    from .server import Server, make_handler

    label, files = resolve(args.session)
    hub = Hub()
    st, rest = load(files, args.lap, args.into, args.at, hub)
    st.check_feed = False  # frozen on purpose
    crew = assemble(hub, st, args.model, mic=False, live=False,  # typed questions only; spend logged as dev
                    team=None if args.no_pitwall else MODELS)
    if args.play:
        threading.Thread(target=_play, args=(st, rest, args.play), daemon=True).start()
    listen = {"ip": "dev", "udpPort": None, "recording": None, "dev": True}
    httpd = Server(("127.0.0.1", args.port), make_handler(st, listen, hub, crew))
    print(f"{label}: http://localhost:{args.port}  ({'playing at ' + str(args.play) + 'x' if args.play else 'frozen'}; Ctrl+C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


def _play(st, rest, speed):
    began, first = time.monotonic(), None
    for t, buf in rest:
        first = t if first is None else first
        wait = (t - first) / speed - (time.monotonic() - began)
        if wait > 0:
            time.sleep(wait)
        st.ingest(buf, ("dev", 0))
    _log.info("dev replay finished")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sessions")
    sub.add_parser("radio").add_argument("--last", type=int, default=20)
    sub.add_parser("pits")
    p = sub.add_parser("prep")
    p.add_argument("--run", action="store_true", help="ask the team for the plan (saved: the live race picks it up)")
    p.add_argument("--models", default=",".join(MODELS))
    for name in ("brief", "ask", "serve", "calls", "triggers", "wall"):
        p = sub.add_parser(name)
        p.add_argument("session")
        p.add_argument("--lap", type=int)
        p.add_argument("--into", type=float, default=0.0, help="seconds into --lap")
        p.add_argument("--at", type=float, help="seconds into the session")
        if name == "triggers":
            p.add_argument("--run", action="store_true", help="call the models at each run (costs ~$0.01-0.02 a run)")
        if name in ("calls", "triggers"):
            continue
        if name == "wall":
            p.add_argument("--why", help="what changed, as a trigger would say it")
            p.add_argument("--ask", help="a strategy question from the driver")
            p.add_argument("--models", default=",".join(MODELS))
            continue
        if name in ("ask", "serve"):
            p.add_argument("--model", default=DEFAULT_MODEL)
        if name == "ask":
            p.add_argument("questions", nargs="+")
            p.add_argument("--repeat", type=int, default=1)
        if name == "serve":
            p.add_argument("--port", type=int, default=8078)
            p.add_argument("--play", type=float, help="keep replaying from the moment at this speed")
            p.add_argument("--no-pitwall", action="store_true", help="no strategy team (it costs a model run per trigger)")
    args = ap.parse_args()
    if args.cmd == "sessions":
        return archive.print_sessions(archive.connect())
    if args.cmd == "radio":
        return cmd_radio(args)
    if args.cmd == "pits":
        return cmd_pits(args)
    if args.cmd == "prep":
        return cmd_prep(args)
    {"brief": cmd_brief, "ask": cmd_ask, "serve": cmd_serve, "calls": cmd_calls, "triggers": cmd_triggers,
     "wall": cmd_wall}[args.cmd](args)


if __name__ == "__main__":
    main()
