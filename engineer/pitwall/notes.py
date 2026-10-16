"""The team's notes: reading a strategist's reply, the PIT WALL section of the engineer's brief,
and keeping them in the archive so a server restart mid-race doesn't lose the plan."""
import json
import re
import time

from .. import archive, driver, log

_log = log.get("pitwall")

KEYS = ("CALL", "SAY", "WHY", "BOX", "A", "B", "C", "ACTIVE")
LINE = re.compile(r"^\W*(CALL|SAY|WHY|BOX|FUEL|START|A|B|C|ACTIVE|PLAN [ABC])\W*:\s*(.*)$", re.I)
SILENT = {"", "nothing", "none", "-", "n/a", "no"}
FRESH_LAPS = 3  # a call stays in the engineer's brief this long; old answers got repeated as current before


def parse(text):
    """'KEY: value' lines (markdown and stray bold stripped) -> {key: value}; untagged lines join the one above."""
    out, key = {}, None
    for raw in text.splitlines():
        line = raw.strip().replace("**", "")
        m = LINE.match(line)
        if m:
            key = m.group(1).upper().replace("PLAN ", "")
            out[key] = m.group(2).strip()
        elif key and line:
            out[key] += " " + line
    return out


def lead(text):
    """What the lead strategist decided."""
    p = parse(text)
    say = p.get("SAY", "").strip().strip('"“”')
    box = re.search(r"\d+", p.get("BOX", ""))
    plans = {k: p[k] for k in "ABC" if p.get(k)}
    active = p.get("ACTIVE", "").strip()[:1].upper() or ("A" if plans else "")
    return {"fuel": p.get("FUEL"), "start": p.get("START"), "call": p.get("CALL", ""), "say": None if say.lower().rstrip(".") in SILENT else say,
            "why": p.get("WHY", ""), "box": int(box.group()) if box else None,
            "plans": plans, "active": active if active in ("A", "B", "C") else None}


def review(text):
    """The second strategist: (agrees?, why)."""
    line = next((ln.strip().replace("**", "") for ln in text.splitlines() if ln.strip()), "")
    m = re.match(r"^\W*(AGREE|DISAGREE)\W*:?\s*(.*)$", line, re.I)
    if not m:
        return None, line
    return m.group(1).upper() == "AGREE", m.group(2).strip()


def section(wall, lap, tyres=None):
    """PIT WALL lines for the engineer's brief: the plans, whether their tyres reach the stop, and the team's
    latest call while it's fresh."""
    out = ["PIT WALL (your strategy team: their call is the plan; relay it, don't make your own)"]
    for k in "ABC":
        if k in wall.plans:
            out.append(f"  plan {k}{' (active)' if k == wall.active else ''}: {wall.plans[k]}")
    if wall.box:
        out.append(f"  planned stop: end of lap {wall.box}")
    if tyres:
        out.append(f"  tyre target: {tyres}")
    last = next((n for n in reversed(wall.notes) if n["who"] == "lead" and n.get("call")), None)
    if last and lap - last["lap"] <= FRESH_LAPS:
        ago = "this lap" if last["lap"] == lap else f"{lap - last['lap']} lap{'s' * (lap - last['lap'] != 1)} ago"
        out.append(f"  team's call ({ago}): {last['call']}. Why: {last['why']}")
        rev = next((n for n in reversed(wall.notes) if n["who"] == "review" and n.get("of") == last["id"]), None)
        if rev and rev.get("agree") is False:
            out.append(f"  (the second strategist disagrees: {rev['text']})")
    if len(out) == 1:
        out.append("  no plan or call from the team yet")
    return out


def history(wall, n=4):
    """The team's own recent notes, for the next run to build on."""
    out = []
    for note in [x for x in wall.notes if x["who"] in ("lead", "review")][-n:]:
        if note["who"] == "lead":
            out.append(f"  L{note['lap']} you: {note['call']}. {note['why']}" + (f' Told {driver.name()}: "{note["say"]}"' if note.get("say") else ""))
        else:
            out.append(f"  L{note['lap']} second strategist: {'agrees' if note['agree'] else 'disagrees'}: {note['text']}")
    return out


BRIEF = archive.DATA / "pitwall-brief.json"


def read_brief():
    """What the driver told the team about the race ahead ("damage control, few rewinds"): kept until changed."""
    try:
        return json.loads(BRIEF.read_text())
    except (FileNotFoundError, ValueError):
        return None


def write_brief(text):
    text = text.strip()
    if not text:
        BRIEF.unlink(missing_ok=True)
        return None
    brief = {"text": text, "at": time.time()}
    BRIEF.parent.mkdir(parents=True, exist_ok=True)
    BRIEF.write_text(json.dumps(brief))
    return brief


def save(uid, note):
    try:
        db = archive.connect()
        with db:
            db.execute("insert into notes values (?, ?, ?)", (uid, note["at"], json.dumps(note)))
        db.close()
    except Exception as e:
        _log.error("couldn't save note", error=str(e))


def load(uid):
    try:
        db = archive.connect()
        rows = db.execute("select data from notes where session_uid = ? order by at", (uid,)).fetchall()
        db.close()
        return [json.loads(r[0]) for r in rows]
    except Exception as e:
        _log.error("couldn't load notes", error=str(e))
        return []
