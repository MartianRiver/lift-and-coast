"""The arithmetic behind the brief: plain functions over lap records, history and packets."""
import math
import statistics

DRY = {16, 17, 18}  # visual soft/medium/hard
ERS_STORE = 4e6  # J, a full battery


def completed_laps(hist):
    """-> [(lap number, ms, valid)] for laps with a time."""
    if not hist:
        return []
    rows = hist["lapHistoryData"][:hist["numLaps"]]
    return [(i + 1, r["lapTimeInMS"], bool(r["lapValidBitFlags"] & 1)) for i, r in enumerate(rows) if r["lapTimeInMS"]]


def best_ms(hist):
    if not hist or not hist["bestLapTimeLapNum"]:
        return None
    return hist["lapHistoryData"][hist["bestLapTimeLapNum"] - 1]["lapTimeInMS"] or None


def ref_lap_ms(hist, sc_laps=()):
    """Typical current lap: median of the last 3 valid green laps, else the best."""
    valid = [ms for n, ms, ok in completed_laps(hist) if ok and n not in sc_laps][-3:]
    return statistics.median(valid) if valid else best_ms(hist)


def lap_at(my, session, minutes, ref_ms):
    """Which lap you'll be on `minutes` from now at `ref_ms` a lap."""
    done = my["currentLapNum"] - 1 + max(my["lapDistance"], 0) / session["trackLength"]
    return int(done + minutes * 60000 / ref_ms) + 1


def stint(crossings):
    """Trailing crossings on the current set: same stop count and compound, with wear recorded."""
    out = []
    for x in reversed(crossings):
        if "wear" not in x or (out and (x["stops"] != out[0]["stops"] or x.get("tyre") != out[0].get("tyre"))):
            break
        out.insert(0, x)
    return out


def wear_rates(crossings, window=5):
    """%/lap per wheel over the last `window` laps of this stint, or None with < 2 laps of data."""
    xs = stint(crossings)[-(window + 1):]
    if len(xs) < 2 or xs[-1]["lap"] == xs[0]["lap"]:
        return None
    n = xs[-1]["lap"] - xs[0]["lap"]
    return [(b - a) / n for a, b in zip(xs[0]["wear"], xs[-1]["wear"])]


def deg(laps, current_lap, status, sc_laps=(), window=6):
    """Lap-time slope (s/lap) over this stint's valid green laps, out-lap excluded. Needs 3 laps."""
    if not status:
        return None
    start = current_lap - status["tyresAgeLaps"]
    pts = [(n, ms / 1000) for n, ms, ok in laps if n > start and ok][1:]
    pts = [p for p in pts if p[0] not in sc_laps][-window:]
    if len(pts) < 3:
        return None
    return _slope(pts)


def _slope(pts):
    mx = statistics.fmean(x for x, _ in pts)
    my = statistics.fmean(y for _, y in pts)
    den = sum((x - mx) ** 2 for x, _ in pts)
    return sum((x - mx) * (y - my) for x, y in pts) / den if den else None


def sector_deltas(hist):
    """Last completed lap's sectors minus the best lap's, in seconds."""
    laps = completed_laps(hist)
    best = hist and hist["bestLapTimeLapNum"]
    if not laps or not best or laps[-1][0] == best:
        return None
    rows = hist["lapHistoryData"]
    a, b = _sectors(rows[laps[-1][0] - 1]), _sectors(rows[best - 1])
    return [(x - y) / 1000 for x, y in zip(a, b)] if all(a) and all(b) else None


def sector_gap(mine, theirs, my_sc=(), their_sc=(), k=3):
    """Your sectors minus theirs in seconds (+ = you're slower), averaged over each car's last k
    representative laps: valid, green, and within 3% of their typical lap (drops in/out laps).
    With k=None it compares best laps (quali)."""
    if k is None:
        a, b = _best_sectors(mine), _best_sectors(theirs)
        return ([(x - y) / 1000 for x, y in zip(a, b)], 1, 1) if a and b else None
    a, b = _recent_sectors(mine, my_sc, k), _recent_sectors(theirs, their_sc, k)
    if not a or not b:
        return None
    avg = [sum(col) / len(col) for col in zip(*a)], [sum(col) / len(col) for col in zip(*b)]
    return [(x - y) / 1000 for x, y in zip(*avg)], len(a), len(b)


def _recent_sectors(hist, sc, k):
    laps = [(n, ms) for n, ms, ok in completed_laps(hist) if ok and n not in sc]
    if not laps:
        return []
    typical = statistics.median(ms for _, ms in laps[-5:])
    rows = [_sectors(hist["lapHistoryData"][n - 1]) for n, ms in laps if ms <= typical * 1.03]
    return [r for r in rows if all(r)][-k:]


def _best_sectors(hist):
    best = hist and hist["bestLapTimeLapNum"]
    r = best and _sectors(hist["lapHistoryData"][best - 1])
    return r if r and all(r) else None


def _sectors(r):
    return [r[f"sector{i}TimeMinutesPart"] * 60000 + r[f"sector{i}TimeMSPart"] for i in (1, 2, 3)]


def fitted_set(sets):
    if not sets or sets["fittedIdx"] >= len(sets["tyreSetData"]):
        return None
    return sets["tyreSetData"][sets["fittedIdx"]]


def fresh_gain(sets):
    """Seconds a lap the quickest available set would gain over the fitted one (game's estimate)."""
    fitted = fitted_set(sets)
    if not fitted:
        return None
    dry = fitted["visualTyreCompound"] in DRY
    deltas = [s["lapDeltaTime"] for i, s in enumerate(sets["tyreSetData"])
              if s["available"] and i != sets["fittedIdx"] and (s["visualTyreCompound"] in DRY) == dry]
    best = min(deltas, default=0)
    return -best / 1000 if best < 0 else None


def gaps(laps, me, cars, window=3, live=None):
    """{idx: {gap, trend, trendLaps, last}}: gap in seconds now (+ = behind you), from the game's live
    time to the leader (`live`: the lap data) when both cars have one, else at the last line both
    crossed; trend = change in the line gap per lap over up to `window` laps, last = change over the
    last lap alone. Windows never span a stop by either car. Trends can turn quickly, so the brief
    shows both."""
    mine = laps.cars.get(me)
    if not mine:
        return {}
    out = {}
    for idx in cars:
        if idx == me:
            continue
        lap = mine[-1]["lap"]
        a, b = laps.at(me, lap), laps.at(idx, lap)
        if not b:
            lap -= 1
            a, b = laps.at(me, lap), laps.at(idx, lap)
        if not (a and b):
            continue
        if a["pit"] or b["pit"]:
            continue  # crossed in the pit lane: that line time is from before the stop, so the gap would be stale
        line = b["t"] - a["t"]
        theirs, mine_now = (_to_leader(live, idx), _to_leader(live, me)) if live else (None, None)
        now = theirs - mine_now if theirs is not None and mine_now is not None else line
        g = {"gap": now, "trend": None, "trendLaps": None, "last": None}
        for k in range(window, 0, -1):
            change = _change(laps, me, idx, lap, k, a["stops"], b["stops"])
            if change is not None:
                g["trend"], g["trendLaps"] = (line - change) / k, k
                break
        change = _change(laps, me, idx, lap, 1, a["stops"], b["stops"])
        g["last"] = None if change is None else line - change
        out[idx] = g
    return out


def _to_leader(live, idx):
    """Seconds behind the leader as the game times it, or None where it doesn't: 0 in the pit lane."""
    c = live[idx]
    secs = c["deltaToRaceLeaderMinutesPart"] * 60 + c["deltaToRaceLeaderMSPart"] / 1000
    if c["pitStatus"] or c["resultStatus"] != 2 or not (secs or c["carPosition"] == 1):
        return None
    return secs


def _change(laps, me, idx, lap, k, my_stops, their_stops):
    """Gap at the line `k` laps before `lap`, if neither car stopped in between."""
    if not (_settled(laps, me, lap - k, my_stops) and _settled(laps, idx, lap - k, their_stops)):
        return None
    return laps.at(idx, lap - k)["t"] - laps.at(me, lap - k)["t"]


def _settled(laps, idx, lap, stops):
    """On the same set at `lap` and the line before it, so no in/out-lap sits inside the window."""
    x, prev = laps.at(idx, lap), laps.at(idx, lap - 1)
    return bool(x) and x["stops"] == stops and (prev["stops"] == stops if prev else stops == 0)


def stops_seen(laps, history):
    """Green-flag stops this race: [(idx, {lap: ms} without SC laps, in-lap, seconds lost)].
    Stops with SC/VSC in the laps measured are skipped: a stop under SC is a different number."""
    out = []
    for idx, xs in laps.cars.items():
        sc = laps.sc_laps(idx)
        times = {n: ms for n, ms, _ in completed_laps(history.get(idx)) if n not in sc}
        for a, b in zip(xs, xs[1:]):
            if b["stops"] > a["stops"] and b["lap"] == a["lap"] + 1:
                got = stop_loss(times, (a["lap"] - 1, a["lap"], a["lap"] + 1))
                if got:
                    out.append((idx, times, got[1], got[0]))
    return out


def pit_loss(laps, history):
    """(median seconds lost to a stop, number of stops measured) from stops seen this race, or None."""
    losses = [loss for *_, loss in stops_seen(laps, history)]
    return (statistics.median(losses), len(losses)) if losses else None


def fresh_gains(laps, history):
    """[(old visual compound, new one, s/lap quicker)] from the cars that stopped this race: the 3 laps
    before the in-lap against the first 3 after the out-lap, once 2 of those are run. What new tyres
    were really worth: the game's lapDeltaTime has said 0.84 for inters that were 1.8 quicker."""
    out = []
    for idx, times, in_lap, _ in stops_seen(laps, history):
        before = [times[n] for n in range(in_lap - 3, in_lap) if n in times]
        after = [times[n] for n in range(in_lap + 2, in_lap + 5) if n in times]
        old, new = laps.at(idx, in_lap), laps.at(idx, in_lap + 2)
        if len(before) >= 2 and len(after) >= 2 and old and new and "tyre" in new:
            gain = (statistics.median(before) - statistics.median(after)) / 1000
            out.append((old.get("tyre"), new["tyre"], gain))
    return out


def slicks_vs_wets(laps, active):
    """(lap, median slick lap s, median inter/wet lap s, cars on each) for the latest lap two cars ran
    on slicks and one on inters or wets, clean (no stop either side, no SC), or None. What slicks are really worth on
    this track right now; the sets' lapDeltaTime is the game's guess."""
    by_lap = {}
    for idx in active:
        sc = laps.sc_laps(idx)
        for x in laps.cars.get(idx, []):
            n = x["lap"] - 1
            before, start = laps.at(idx, n - 1), laps.at(idx, n)
            if not (before and start and x["lastMs"]) or n in sc or "tyre" not in start:
                continue
            if before["stops"] == start["stops"] == x["stops"] and not (start["pit"] or x["pit"]):
                by_lap.setdefault(n, ([], []))[start["tyre"] not in DRY].append(x["lastMs"] / 1000)
    for n in sorted(by_lap, reverse=True):
        dry, wet = by_lap[n]
        if len(dry) >= 2 and wet:  # often only the player is left on inters
            return n, statistics.median(dry), statistics.median(wet), len(dry), len(wet)
    return None


def stop_loss(times, around):
    """(seconds a stop cost, in-lap) or None. `times` {lap: ms}; `around` three laps the stop sits in.

    The box can be either side of the line, so the in- and out-lap are the slowest two in a row of
    those three. They're measured against two laps either side: the old set's pace alone hides part
    of the loss when it was dying (18.3 s against worn inters where it was 21.7 either side).
    Until two laps after the stop are run, the three before stand in."""
    pairs = [(n, n + 1) for n in around[:-1] if n in times and n + 1 in times]
    if not pairs:
        return None
    a, b = max(pairs, key=lambda p: times[p[0]] + times[p[1]])
    before = [times[n] for n in range(a - 3, a) if n in times]
    after = [times[n] for n in (b + 1, b + 2) if n in times]
    if len(before) < 2:
        return None
    ref = statistics.mean(before[-2:] + after) if len(after) == 2 and len(before) >= 2 else statistics.median(before)
    loss = (times[a] + times[b] - 2 * ref) / 1000
    return (loss, a) if 5 < loss < 60 else None


def loss_from_rejoin(gap_map, my_pos, rejoin_pos):
    """(low, high) seconds a stop costs, read off the game's rejoin estimate before we've seen a stop:
    rejoining P{rejoin} means that many cars behind get past, so the loss sits between their gaps.
    Gaps sorted, not positions: mid-lap the live order and the gaps at the line disagree.
    high is None when nobody is further back."""
    if not rejoin_pos or rejoin_pos <= my_pos:
        return None
    behind = sorted(g["gap"] for g in gap_map.values() if g["gap"] > 0)
    passed = rejoin_pos - my_pos
    if passed > len(behind):
        return None
    return behind[passed - 1], behind[passed] if passed < len(behind) else None


def free_stop_lap(gap, per_lap, loss, lap, last_lap):
    """First lap the gap to a car behind covers a stop at this rate: `lap` if it already does,
    None if it won't before last_lap."""
    if gap >= loss:
        return lap
    if per_lap <= 0:
        return None
    at = lap + math.ceil((loss - gap) / per_lap)
    return at if at <= last_lap else None


def rejoin(gap_map, loss):
    """If you stopped now: (position, (idx, s you'd be behind them) | None, (idx, s ahead) | None)."""
    if not gap_map:
        return None
    after = {idx: g["gap"] - loss for idx, g in gap_map.items()}
    ahead = [(idx, -v) for idx, v in after.items() if v < 0]
    behind = [(idx, v) for idx, v in after.items() if v >= 0]
    return (len(ahead) + 1, min(ahead, key=lambda x: x[1], default=None),
            min(behind, key=lambda x: x[1], default=None))
