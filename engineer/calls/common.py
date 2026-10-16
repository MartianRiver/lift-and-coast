"""What every kind of call shares: priorities, the call record, names said aloud."""
from ..fmt import WHEELS

URGENT, NORMAL, LOW = 0, 1, 2
CORNERS = {"RL": "rear-left", "RR": "rear-right", "FL": "front-left", "FR": "front-right"}


def call(key, topic, prio, text, ttl=40):
    """`text(race)` runs again when the call is delivered and returns None if it's stopped being true."""
    return {"key": key, "topic": topic, "prio": prio, "text": text, "ttl": ttl}


def nice(name):
    return " ".join(w.capitalize() for w in name.split())


def corner(i):
    return CORNERS[WHEELS[i]].capitalize()


def stopping(b):
    """In the pit lane, or the last lap line was crossed in it or just after."""
    xs = b.st.laps.cars.get(b.me, [])[-2:]
    return bool(b.my["pitStatus"]) or any(x["pit"] for x in xs) or (len(xs) == 2 and xs[0]["stops"] != xs[1]["stops"])
