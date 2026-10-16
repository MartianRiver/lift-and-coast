"""What's worth saying right now (races only). `scan(race, mem)` returns new calls; `mem` holds
what's been said this session. When each call is actually said is the caller's job."""
from ..spec import MAX_CARS
from . import events, gaps, plans, tyres

SETTLE = 20.0  # s of session time after first seeing a session that only baselines: a resumed save loads in stages


def scan(b, mem, team=False):
    """team: the pit wall owns the box-for-slicks and rain-plan calls (its run says them, or falls back to ours)."""
    if not b.race or b.me >= MAX_CARS:
        return []
    now = b.now
    # joined mid-race or resumed a save: note what's already happened, say nothing about it. Weather,
    # damage and positions can still be loading in the first seconds
    first = now - mem.setdefault("t0", now) < SETTLE or "lap" not in mem
    out = (events.from_log(b, mem) + events.safety_car(b, mem) + events.conditions(b, mem)
           + gaps.in_range(b, mem) + ([] if team else plans.slicks(b)))
    lap = b.my["currentLapNum"]
    if lap != mem.get("lap"):
        if not first and lap > mem["lap"] and not b.s["safetyCarStatus"]:  # gaps and pace mean nothing behind the SC
            left = b.s["totalLaps"] - lap + 1
            out += gaps.at_the_line(b, mem, lap) + tyres.at_the_line(b, left) + plans.fuel(b) + ([] if team else plans.rain(b, mem))
        mem["lap"] = lap
    said, fresh = mem.setdefault("said", set()), []
    for c in out:
        if c["key"] not in said:
            said.add(c["key"])
            fresh.append(c)
    return [] if first else fresh
