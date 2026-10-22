"""What every kind of call shares: priorities, the call record, names said aloud."""
from ..fmt import WHEELS

URGENT, NORMAL, LOW = 0, 1, 2
CORNERS = {"RL": "rear-left", "RR": "rear-right", "FL": "front-left", "FR": "front-right"}
# the switches in Settings: each call's topic is under one. The code's own strategy calls are what the team says when it's on
GROUPS = {"gaps": ("gap", "last", "lap", "pass", "out", "pit"), "tyres": ("tyres",), "damage": ("damage", "contact"),
          "flags": ("sc", "flag", "weather", "limits", "penalty"), "fuel": ("fuel",), "team": ("team", "strategy")}
GROUP = {topic: g for g, topics in GROUPS.items() for topic in topics}


def call(key, topic, prio, text, ttl=40, unsaid=None):
    """`text(race)` runs again when the call is delivered and returns None if it's stopped being true.
    `unsaid()` runs if it's never said: it expired waiting for a straight, or wasn't true any more."""
    return {"key": key, "topic": topic, "prio": prio, "text": text, "ttl": ttl, "unsaid": unsaid}


def nice(name):
    return " ".join(w.capitalize() for w in name.split())


def corner(i):
    return CORNERS[WHEELS[i]].capitalize()


def stopping(b):
    """In the pit lane, or the last lap line was crossed in it or just after."""
    xs = b.st.laps.cars.get(b.me, [])[-2:]
    return bool(b.my["pitStatus"]) or any(x["pit"] for x in xs) or (len(xs) == 2 and xs[0]["stops"] != xs[1]["stops"])
