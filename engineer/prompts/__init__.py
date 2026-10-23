"""What each model is told, as versions. Shipped ones are engineer/prompts/<role>/vN.md and never
change once released; the driver's edits are captures/prompts/<role>/custom-N.md. An edit is always a
new version, and which one each role uses is a setting (none set: the newest shipped one)."""
import difflib
import re
import threading
import time
from pathlib import Path

from .. import archive, log

_log = log.get("prompts")

SHIPPED = Path(__file__).resolve().parent
CUSTOM = archive.DATA / "prompts"
ROLES = {"engineer": "Engineer", "lead": "Team lead", "second": "Second opinion", "prep": "Race prep"}  # the editable ones
MAX_CHARS = 40_000
NAME = re.compile(r"^(v|custom-)(\d+)$")

_texts = {}  # (role, id) -> (header, body): a version never changes, so it's read once
_using = {}  # role -> id chosen in Settings
_lock = threading.Lock()


def _path(role, vid):
    m = NAME.match(vid or "")
    if not m:
        return None
    return (SHIPPED if m[1] == "v" else CUSTOM) / role / f"{vid}.md"


def _exists(role, vid):
    path = _path(role, vid)
    return bool(path and path.is_file())


def _n(vid):
    return int(NAME.match(vid)[2])


def _split(text):
    """-> ({key: value}, body) for a file that starts with a --- header."""
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    if not m:
        return {}, text
    head = dict(line.split(": ", 1) for line in m[1].splitlines() if ": " in line)
    return head, text[m.end():]


def _read(role, vid):
    with _lock:
        if (role, vid) in _texts:
            return _texts[role, vid]
    if not _exists(role, vid):
        raise KeyError(f"no {role} prompt {vid}")
    got = _split(_path(role, vid).read_text(encoding="utf-8"))
    with _lock:
        _texts[role, vid] = got
    return got


def _ids(role, where, prefix):
    found = [int(m[2]) for p in (where / role).glob(f"{prefix}*.md") if (m := NAME.match(p.stem)) and m[1] == prefix]
    return [f"{prefix}{n}" for n in sorted(found)]


def latest(role):
    """The newest shipped version."""
    return _ids(role, SHIPPED, "v")[-1]


def versions(role):
    """Shipped then custom, oldest first: [{id, custom, why, date, from}]."""
    out = []
    for vid in _ids(role, SHIPPED, "v") + _ids(role, CUSTOM, "custom-"):
        head, _ = _read(role, vid)
        out.append({"id": vid, "custom": vid.startswith("custom-"), "why": head.get("why"),
                    "date": head.get("date"), "from": head.get("from")})
    return out


def text(role, vid=None):
    """The prompt as sent: the version given, else the one in use."""
    return _read(role, vid or active(role))[1]


def active(role):
    with _lock:
        vid = _using.get(role)
    return vid if _exists(role, vid) else latest(role)


def pick(role):
    """The prompt in use -> (how the call records it, "engineer/v1"; its text)."""
    vid = active(role)
    return f"{role}/{vid}", text(role, vid)


def check(choice):
    """The Settings value {role: id} -> itself, or ValueError."""
    if not isinstance(choice, dict):
        raise ValueError("expected {role: version}")
    for role, vid in choice.items():
        if role not in ROLES:
            raise ValueError(f"no prompt role {role!r}")
        if not isinstance(vid, str) or not _exists(role, vid):
            raise ValueError(f"no {ROLES[role].lower()} prompt {vid!r}")
    return dict(choice)


def use(choice):
    with _lock:  # an answer starting now sees the old choice or the new one, never neither
        _using.clear()
        _using.update(choice or {})
    _log.info("prompts in use", **{r: active(r) for r in ROLES})


def base(role, vid):
    """The shipped version a custom one was made from (itself for a shipped one)."""
    if not vid.startswith("custom-"):
        return vid
    return _read(role, vid)[0].get("from") or latest(role)


def newer(role):
    """A shipped version newer than the one the prompt in use comes from, else None."""
    newest = latest(role)
    return newest if _n(base(role, active(role))) < _n(newest) else None


def diff(role, a, b):
    """Unified diff lines from version a to b."""
    return list(difflib.unified_diff(text(role, a).splitlines(), text(role, b).splitlines(), a, b, lineterm="", n=2))


def save(role, body, why, made_from):
    """A new custom version, never overwriting one. -> its id. Raises ValueError."""
    if role not in ROLES:
        raise ValueError(f"no prompt role {role!r}")
    if not isinstance(body, str) or not body.strip():
        raise ValueError("the prompt is empty")
    if len(body) > MAX_CHARS:
        raise ValueError(f"the prompt is over {MAX_CHARS} characters")
    why = " ".join(str(why or "").split())
    if not why:
        raise ValueError("say in a line why you changed it")
    try:
        if body.strip() == text(role, made_from).strip():
            raise ValueError(f"nothing changed from {made_from}")
    except KeyError:
        raise ValueError(f"no {ROLES[role].lower()} prompt {made_from!r}") from None
    folder = CUSTOM / role
    folder.mkdir(parents=True, exist_ok=True)
    body = body if body.endswith("\n") else body + "\n"
    head = f"---\nwhy: {why[:200]}\ndate: {time.strftime('%Y-%m-%d %H:%M')}\nfrom: {base(role, made_from)}\n---\n"
    made = _ids(role, CUSTOM, "custom-")
    n = _n(made[-1]) if made else 0
    while True:
        n += 1
        try:
            with (folder / f"custom-{n}.md").open("x", encoding="utf-8") as f:  # "x": a save never replaces one
                f.write(head + body)
            break
        except FileExistsError:
            continue
    _log.info("prompt saved", role=role, id=f"custom-{n}", why=why, made_from=made_from)
    return f"custom-{n}"


def view():
    """For the Prompts page: each editable role's versions, the one in use and a newer shipped one."""
    out = {}
    for role, name in ROLES.items():
        now, new = active(role), newer(role)
        out[role] = {"name": name, "versions": versions(role), "active": now, "latest": latest(role), "newer": new,
                     "changes": diff(role, base(role, now), new) if new else None}
    return out
