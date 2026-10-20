"""RaceState -> the compact text brief the engineer and strategists read.

Models make wrong calls when they do their own arithmetic, so anything that needs maths is worked out here: gaps and which way they're moving, wear rates and where
they lead, which lap the rain lands on, undercut range, where a stop rejoins.

    uv run python -m engineer.dev brief <session> --lap N    # print it at any point of a recorded session
"""
from statistics import median

from . import calc, grip, incidents, strategy, trace, wear
from . import lookups as L
from .fmt import WHEELS, clock, damage, gap, laptime, offset, trend, tyre, wheels
from .race import Race, ready

LOST_AFTER = 300  # s of silence: shorter than that is a pause, and the state is still right


def build(st):
    with st.lock:
        if not ready(st):
            return None
        return "\n".join(Brief(Race(st)).lines())


class Brief:
    def __init__(self, r):
        self.r = r
        self.st, self.s, self.lap_pkt, self.me, self.my = r.st, r.s, r.lap_pkt, r.me, r.my
        self.race, self.sc_laps, self.ref_ms, self.gaps = r.race, r.sc_laps, r.ref_ms, r.gaps
        rain = strategy.rain(r)
        self.rain_lap = rain[1] if rain and rain[0]["timeOffset"] else None  # rain still to come, before the flag

    def lines(self):
        out = self._feed() + self._session() + (self._situation() if self.race else []) + self._forecast() + self._you()
        if self.race:
            out += self._pit() + self._race_log()
        return out + self._time_lost() + [""] + self._field()

    # --- session --------------------------------------------------------------

    def _feed(self):
        quiet = self.st.silent_for()
        if not self.st.check_feed or quiet is None or quiet < LOST_AFTER:
            return []
        return [f"FEED LOST  no data from the car for {clock(int(quiet))} (saved and quit, or switched off): "
                "everything below is how it was when it stopped, not live"]

    def _session(self):
        s = self.s
        kind = L.name(L.SESSION_TYPES, s["sessionType"])
        where = f"{kind} · {L.name(L.TRACKS, s['trackId'])}"
        if self.race:
            where += f" · lap {self.my['currentLapNum']} of {s['totalLaps']}"
            where += " · you've taken the chequered flag: the race is over" if self.my["resultStatus"] == 3 else ""
        else:
            where += f" · {clock(s['sessionTimeLeft'])} left"
        sc = L.name(L.SAFETY_CAR, s["safetyCarStatus"])
        line = (f"SESSION  {where} · {L.name(L.WEATHER, s['weather']).lower()} · "
                f"track {s['trackTemperature']}°C air {s['airTemperature']}°C")
        line += f" · {sc} out" if s["safetyCarStatus"] else ""
        if self.race:
            line += f" · SC {s['numSafetyCarPeriods']} VSC {s['numVirtualSafetyCarPeriods']} so far"
        return [line]

    def _situation(self):
        """Safety car phase and what matters for the restart, spelled out so it isn't missed."""
        if self.r.red_flag():
            return ["SITUATION RED FLAG: race suspended · everyone gets a free tyre change before it restarts from the grid "
                    "with a standing start · the game can skip laps before the restart"]
        ev = next((e for e in reversed(self.st.events) if e["code"] == "SCAR"), None)
        if not ev:
            return []
        kind, phase = ev["details"]["safetyCarType"], ev["details"]["eventType"]
        now = self.lap_pkt["header"]["sessionTime"]
        if phase == 3 and now - ev["sessionTime"] > (self.ref_ms or 90000) / 1000:
            return []  # restart was over a lap ago
        vsc = kind == 2
        text = {0: "VSC deployed" if vsc else "SAFETY CAR deployed",
                1: "VSC ending" if vsc else "SAFETY CAR IN THIS LAP, restart at the line",
                2: "VSC ending" if vsc else "SAFETY CAR IN THIS LAP, restart at the line",
                3: "green: first racing lap after the VSC" if vsc else "green: restart lap"}[phase]
        parts = [text]
        status = self.r.status()
        tel = self.r.telemetry()
        if status:
            if self.my["numPitStops"] and status["tyresAgeLaps"] <= 2:
                parts.append(f"you already stopped ({tyre(status['visualTyreCompound'])}, {status['tyresAgeLaps']} laps old), no reason to stop again")
            battery = status["ersStoreEnergy"] / calc.ERS_STORE
            parts.append(f"battery {battery:.0%}" + (", full: use it on the restart" if battery > 0.9 else ""))
        if tel:
            parts.append("tyre inner temps " + wheels(tel["tyresInnerTemperature"], "{:.0f}°C"))
        return ["SITUATION " + " · ".join(parts)]

    def _forecast(self):
        samples = [w for w in self.s["weatherForecastSamples"][:self.s["numWeatherForecastSamples"]]
                   if w["sessionType"] == self.s["sessionType"]][:6]
        if not samples:
            return []
        parts = [f"{offset(w['timeOffset'])} {L.name(L.WEATHER, w['weather']).lower()} {w['rainPercentage']}%"
                 for w in samples]
        out = [f"FORECAST {' · '.join(parts)}"]
        r, eases = strategy.rain(self.r), strategy.easing(self.r)
        if r and r[0]["timeOffset"] == 0:  # raining now: when it stops is what matters, not that it's "likely"
            out.append("         raining now and through the forecast" if not eases else
                       f"         raining now, easing: below {strategy.RAIN_PCT}% from {offset(eases[0]['timeOffset'])}"
                       + (f" ≈ lap {eases[1]}" if eases[1] else ", after the flag")
                       + ("; more rain forecast after that" if eases[2] else "; no more rain forecast: the track is drying"))
        elif r and not r[1]:
            out.append(f"         rain likely from +{r[0]['timeOffset']}m — after the flag at your pace")
        elif r:
            out.append(f"         rain likely from +{r[0]['timeOffset']}m ≈ lap {r[1]} (at your {laptime(self.ref_ms)} pace)")
            out += self._rain_plan()
        return out + self._slicks()

    def _slicks(self):
        p = strategy.slicks(self.r)
        if not p or not (strategy.easing(self.r) or self.s["weather"] < 3 or p["options"][0][1] > -1):
            return []  # still raining hard: slicks 4-5 s/lap off are noise
        opts = ", ".join(f"{tyre(c)} {abs(g):.1f} s/lap {'quicker' if g > 0 else 'slower'} (lasts ~{life} laps)"
                         for c, g, life in p["options"])
        line = f"SLICKS   vs your fitted set now (set's estimate): {opts} · {p['left']} laps after this one"
        pick = p["pick"]
        if pick and pick[1] > 0:
            line += f" → box this lap for {tyre(pick[0])}: the quickest that lasts to the flag; every lap on these now loses ≈{pick[1]:.1f}s"
        elif pick:
            line += " → stay on these: no slick is quicker yet"
        out = [line]
        on = [self.r.status(i)["visualTyreCompound"] for i in self.r.active() if i != self.me]
        dry = [c for c in on if c in calc.DRY]
        if dry:
            counts = " ".join(f"{tyre(c)} ×{dry.count(c)}" for c in sorted(set(dry)))
            out.append(f"         on slicks already: {len(dry)} of {len(on)} cars ({counts})")
        if p["seen"]:
            n, d, w, nd, nw = p["seen"]
            out.append(f"         measured L{n}: slicks {laptime(d * 1000)} vs inters/wets {laptime(w * 1000)} ({nd} vs {nw} cars):"
                       f" slicks {abs(w - d):.1f} s/lap {'quicker' if d < w else 'slower'}")
        return out

    def _rain_plan(self):
        p = strategy.rain_plan(self.r)
        if not p:
            return []
        line = (f"         rain plan: stay out and stop once for inters at L{p['lap']}, or stop now for fresh dries and again"
                f" at L{p['lap']}: the extra stop costs ≈{p['loss']:.0f}s, new dries buy back ≈{p['gain']:.1f} s/lap ×"
                f" {p['laps']} laps ≈ {p['back']:.0f}s → ")
        line += (f"staying out saves ≈{p['saves']:.0f}s" if p["saves"] > 0 else f"stopping now gains ≈{-p['saves']:.0f}s")
        if p["worn"]:
            w, pct = p["worn"]
            line += f" · your {WHEELS[w]} ≈{pct:.0f}% by L{p['lap']}" + (
                f" (past {strategy.WORN}%: a long way to stretch this set)" if pct > strategy.WORN else "")
        return [line + f" · only {p['pct']}% likely" if p["pct"] < 70 else line]

    # --- the player -----------------------------------------------------------

    def _you(self):
        me, st = self.me, self.st
        status = self.r.status(me)
        dmg = self.r.damage(me)
        grid = self.race and self.my["gridPosition"]
        head = f"YOU      P{self.r.pos(me)}{f' (started P{grid})' if grid else ''} · {self.r.name(me)} ({self.r.team(me)})"
        if status:
            head += (f" · {tyre(status['visualTyreCompound'])} "
                     f"({L.name(L.ACTUAL_COMPOUNDS, status['actualTyreCompound'])}), "
                     f"{status['tyresAgeLaps']} lap{'' if status['tyresAgeLaps'] == 1 else 's'} old")
        head += f" · stops {self.my['numPitStops']}"
        out = [head]
        if dmg:
            out += self._wear(dmg["tyresWear"])
        crossings = st.laps.cars.get(me, [])
        if crossings and crossings[-1].get("peakTemps"):
            out.append("  temps  peak surface last lap " + wheels(crossings[-1]["peakTemps"], "{:.0f}°C"))
        out += self._pace()
        if status:
            out += self._fuel_ers(status)
        if dmg:
            first = next((x for x in crossings if "pu" in x), None)
            out += damage(dmg, first and first["pu"])
        out += self._sets()
        return out

    def _wear(self, wear):
        line = "  wear   " + wheels(wear, "{:.0f}%")
        rates = strategy.stint_rates(self.r)
        out = self._wear_around(wear)
        if rates:
            w = max(range(4), key=lambda i: rates[i])
            line += f" · fastest-wearing {WHEELS[w]} {rates[w]:+.1f}%/lap"
            ahead = []
            if self.rain_lap:
                n = self.rain_lap - self.my["currentLapNum"]
                ahead.append(f"≈{wear[w] + rates[w] * n:.0f}% by the rain (lap {self.rain_lap})")
            if self.race:
                n = self.s["totalLaps"] - self.my["currentLapNum"] + 1
                ahead.append(f"≈{wear[w] + rates[w] * n:.0f}% at the flag if you don't stop")
            if ahead:
                out.append(f"         {WHEELS[w]} " + ", ".join(ahead))
        worn = strategy.worn_in(self.r)
        if worn and worn[1] is not None:
            w, n = worn
            at, last = self.my["currentLapNum"] + n, self.s["totalLaps"]
            line += f" · {WHEELS[w]} reaches {strategy.WORN}% (worn out) in ≈{n} laps, L{at}" + (
                (" — before the flag" if at <= last else " — after the flag") if self.race else "")
        if self.race and self.my["numPitStops"]:
            t = strategy.target(self.r, self.s["totalLaps"])
            if t:
                out.append("         to the flag: " + strategy.target_text(t, "the flag"))
        return [line] + out

    def _wear_around(self, wear):
        """Your most-worn tyre against the same corner on the cars within 3 places. Needs no laps, so it's
        there from the first lap of a resumed save."""
        dmg, status = self.st.latest.get(10), self.st.latest.get(7)
        if not self.race or not dmg or not status:
            return []
        w, pos = max(range(4), key=lambda i: wear[i]), self.r.pos(self.me)
        near = [i for i in self.r.active() if i != self.me and abs(self.r.pos(i) - pos) <= 3]
        if not near:
            return []
        theirs = [dmg["carDamageData"][i]["tyresWear"][w] for i in near]
        ages = [status["carStatusData"][i]["tyresAgeLaps"] for i in near]
        span = lambda xs, f: f.format(min(xs)) if f.format(min(xs)) == f.format(max(xs)) else f.format(min(xs)) + "–" + f.format(max(xs))
        return [f"         {WHEELS[w]} {wear[w]:.0f}% vs {span(theirs, '{:.0f}')}% on the cars within 3 places"
                f" (their sets {span(ages, '{}')} laps old)"]

    def _pace(self):
        hist = self.st.history.get(self.me)
        laps = calc.completed_laps(hist)
        if not laps:
            return []
        last = laps[-5:]
        line = "  pace   last " + " ".join(laptime(ms) + ("" if ok else "(inv)") for _, ms, ok in last)
        deg = calc.deg(laps, self.my["currentLapNum"], self.r.status(), self.sc_laps)
        if deg is not None:
            line += f" · deg {deg:+.2f} s/lap this stint"
        best = hist["bestLapTimeLapNum"]
        if best:
            line += f" · best {laptime(hist['lapHistoryData'][best - 1]['lapTimeInMS'])} (L{best})"
        if self.race:
            line += self._fastest()
        out = [line]
        sectors = calc.sector_deltas(hist)
        if sectors:
            out.append("  sector last lap vs your best: " + " ".join(f"S{i + 1} {d:+.3f}" for i, d in enumerate(sectors)))
        return out

    def _fastest(self):
        """The race's fastest lap so far: nothing else here has the others' best laps."""
        laps = [(ms, i) for i in self.r.active() + self.r.retired() if (ms := calc.best_ms(self.st.history.get(i)))]
        if not laps:
            return ""
        ms, idx = min(laps)
        who = "yours" if idx == self.me else self.r.name(idx)
        return f" · fastest lap of the race {laptime(ms)} ({who}, L{self.st.history[idx]['bestLapTimeLapNum']})"

    def _fuel_ers(self, status):
        # fuelRemainingLaps is the MFD's fuel delta: laps of fuel over (+) or under (−) what's needed
        delta = status["fuelRemainingLaps"]
        line = f"  fuel   {delta:+.1f} laps vs target ({status['fuelInTank']:.1f} kg in tank)"
        if self.race and delta < 0:
            line += ' — short, needs saving'
        mode = status["ersDeployMode"]
        return [line + f" · ERS {status['ersStoreEnergy'] / calc.ERS_STORE:.0%}" + (f" ({L.name(L.ERS_MODES, mode)} mode)" if mode else "")]

    def _sets(self):
        sets = self.st.tyre_sets.get(self.me)
        if not sets:
            return []
        groups = {}
        for i, s in enumerate(sets["tyreSetData"]):
            if s["available"] and i != sets["fittedIdx"]:
                key = (tyre(s["visualTyreCompound"]), "new" if s["wear"] == 0 else f"used {s['wear']}%")
                groups.setdefault(key, []).append(s["lapDeltaTime"])
        parts = [f"{kind} {state} ×{len(d)} ({min(d) / 1000:+.2f} s/lap vs fitted)" for (kind, state), d in groups.items()]
        return ["  sets   " + (" · ".join(parts) if parts else "none left")]

    # --- pit and rivals (race only) ------------------------------------------

    def _pit(self):
        loss = self.r.loss()
        s = self.s
        neutral = s["safetyCarStatus"] in (1, 2)
        line = "PIT     "
        if loss:
            line += f"green-flag loss ≈{loss[0]:.1f}s ({loss[1]})"
            rejoin = None if neutral else calc.rejoin(self.gaps, loss[0])
            if rejoin:
                pos, ahead, behind = rejoin
                line += f" · box this lap: rejoin ≈P{pos}"
                if ahead:
                    line += f", {ahead[1]:.1f}s behind {self.r.name(ahead[0])}"
                if behind:
                    line += f", {behind[1]:.1f}s ahead of {self.r.name(behind[0])}"
        else:
            line += "loss not measured yet (no stops seen)"
            est = None if neutral else calc.loss_from_rejoin(self.gaps, self.r.pos(self.me), s["pitStopRejoinPosition"])
            if est:
                lo, hi = est
                shown = f"{lo:.0f}+" if hi is None else f"{lo:.0f}" if round(lo) == round(hi) else f"{lo:.0f}–{hi:.0f}"
                line += f", ≈{shown}s going by the rejoin estimate"
                loss = (hi or lo, None)  # the top of the range: a free stop has to cover it
        if neutral:
            sc = strategy.sc_stop(self.r)
            line += (" · SC/VSC OUT NOW: a stop costs much less than the green-flag loss"
                     + (f" (≈{sc[0]:.0f}s, {sc[1]})" if sc else " (no figure to quote)")
                     + " and the field will bunch up behind the safety car")
        if s["pitStopRejoinPosition"] and not neutral:  # the game's estimate assumes a green-flag stop too
            line += f" · rejoin estimate P{s['pitStopRejoinPosition']}"
        if s["pitStopWindowIdealLap"]:
            line += f" · pit window ideal L{s['pitStopWindowIdealLap']}, latest L{s['pitStopWindowLatestLap']}"
        out = [line]
        if loss and not neutral:
            out += self._free_stop(loss[0])
        if not neutral:  # gaps mean nothing behind the safety car
            out += self._undercut()
        return out + self._stop()

    def _stop(self):
        p = strategy.dry_stop(self.r)
        if not p:
            return []
        rule = (f"the second compound is still owed, so not {'/'.join(tyre(c) for c in sorted(p['run']))}"
                if p["owed"] else "any set")
        how = (f"wear = your {WHEELS[p['wheel']]} at the flag at its rate this stint, scaled to each compound's life"
               if p["wheel"] is not None else "life = the set's own estimate")
        sets = " · ".join(f"{self._set(o)} {abs(o['gain']):.2f} s/lap {'quicker' if o['gain'] > 0 else 'slower'}, "
                          + (f"≈{o['at_flag']:.0f}% at the flag" if o["at_flag"] is not None else ("lasts" if o["lasts"] else "short"))
                          for o in p["options"])
        out = [f"STOP     if you box this lap ({p['left']} laps after it; {rule}; pace = the set's estimate vs your fitted set; {how}): {sets}"]
        pick, top = p["pick"], p["options"][0]
        if not pick:
            out.append(f"         → none of them reaches the flag under {strategy.WORN}% (worn out) from this lap")
        else:
            line = f"         → {self._set(pick)}: the quickest that reaches the flag under {strategy.WORN}% (worn out)"
            if pick is not top:
                line += f"; the {self._set(top)} is {top['gain'] - pick['gain']:.2f} s/lap quicker but " + (
                    f"reaches ≈{top['at_flag']:.0f}%" if top["at_flag"] is not None else "won't last")
            elif len(p["options"]) > 1:
                line += f", {pick['gain'] - p['options'][1]['gain']:.2f} s/lap quicker than the {self._set(p['options'][1])}"
            out.append(line)
        return out + self._stop_field()

    def _set(self, o):
        state = "new" if not o["wear"] else f"used {o['wear']}%"
        return f"{tyre(o['compound'])} {state}"

    def _stop_field(self):
        """What the others took at their stops, and what the cars near you are on."""
        stopped, near, mine = [], [], self.r.pos(self.me)
        for i in self.r.active():
            if i == self.me:
                continue
            c = self.r.status(i)["visualTyreCompound"]
            if self.lap_pkt["lapData"][i]["numPitStops"]:
                stopped.append(c)
            elif abs(self.r.pos(i) - mine) <= 3:
                near.append(c)
        count = lambda cs: ", ".join(f"{tyre(c)} ×{cs.count(c)}" for c in sorted(set(cs)))
        parts = ([f"cars that have stopped, now on: {count(stopped)}"] if stopped else [])
        parts += [f"not stopped yet, within 3 places of you: {count(near)}"] if near else []
        return ["         " + " · ".join(parts)] if parts else []

    def _undercut(self):
        """What new tyres were worth to the cars that stopped, and the undercut range from it (from
        stops onto the same kind of tyre as yours, dry or wet), else the tyre sets' own estimate."""
        seen = calc.fresh_gains(self.st.laps, self.st.history)
        out = []
        if seen:
            groups = {}
            for old, new, g in seen:
                groups.setdefault(f"{tyre(old)}→{tyre(new)}", []).append(g)
            out.append("         new tyres were worth (cars that stopped, 3 laps before vs first 3 after): "
                       + " · ".join(f"{k} {median(v):.2f} s/lap ({len(v)})" for k, v in groups.items()))
        got = strategy.fresh_gain(self.r)
        if not got:
            return out
        gain, source = got
        wait = strategy.sc_wait(self.r)
        status = self.r.status()
        if wait and status and status["tyresAgeLaps"] >= 5:  # just stopped: nothing to wait for
            out.append(f"         waiting for a safety car: each lap out costs ≈{wait[0]:.1f}s against new tyres, a stop under"
                       f" the SC would save ≈{wait[1]:.0f}s (rule of thumb), so waiting pays only if one comes within ≈{wait[2]:.0f} laps")
        reach = 2 * gain
        line = f"         undercut range ≈{reach:.1f}s ({source}: {gain:.2f} s/lap quicker, over 2 laps)"
        threat = [self.r.name(i) for i, g in self.gaps.items() if 0 < g["gap"] < reach]
        chance = [self.r.name(i) for i, g in self.gaps.items() if -reach < g["gap"] < 0]
        line += f" · could undercut you: {', '.join(threat)}" if threat else ""
        line += f" · you could undercut: {', '.join(chance)}" if chance else ""
        return out + [line]

    def _free_stop(self, loss):
        """When the gap to the car behind covers a stop, at the rate it's moving."""
        behind = next((i for i in self.gaps if self.r.pos(i) == self.r.pos(self.me) + 1), None)
        g = self.gaps.get(behind)
        if not g or g["gap"] <= 0:
            return []
        rate = g["trend"] if g["trendLaps"] and g["trendLaps"] > 1 else g["last"]
        lap, last = self.my["currentLapNum"], self.s["pitStopWindowLatestLap"] or self.s["totalLaps"]
        line = f"         free stop (box and still come out ahead) vs {self.r.name(behind)} (behind, {g['gap']:.1f}s): needs ≈{loss:.0f}s"
        if g["gap"] >= loss:
            return [line + " · you have it now"]
        at = None if rate is None else calc.free_stop_lap(g["gap"], rate, loss, lap, last)
        if at:
            return [line + f" · at {rate:+.2f}/lap you'd have it around L{at}"]
        return [line + f" · not by L{last} at the current rate ({'unknown' if rate is None else f'{rate:+.2f}/lap'});"
                       " stretching this set buys laps to build it, or come out behind and pass"]

    def _race_log(self):
        lines = incidents.summary(self.st.incidents, self.my, self.r.name, self.s["trackLength"])
        return ["RACE LOG (lap numbers are yours)"] + lines if lines else []

    def _time_lost(self):
        rows = sorted(self.r.active(), key=self.r.pos)
        mine = rows.index(self.me) if self.me in rows else None
        if mine is None:
            return []
        if self.race:  # the cars either side
            rivals = [(rows[mine - 1], "ahead")] if mine else []
            rivals += [(rows[mine + 1], "behind")] if mine + 1 < len(rows) else []
        else:  # quali/practice: the fastest car, best laps compared
            rivals = [(rows[0], "fastest")] if mine else [(rows[1], "next fastest")] if len(rows) > 1 else []
        gaps = {idx: self._sector_gap(idx) for idx, _ in rivals}
        out = [self._sectors_vs(idx, label, gaps[idx]) for idx, label in rivals if gaps[idx]]
        out += trace.summary(self.st.traces, self.me, rivals, self.r.name, self.s["trackLength"], self.race)
        return (["WHERE THE TIME GOES"] + out if out else []) + self._tyres_by_sector(rivals[:1], gaps)

    def _sector_gap(self, idx):
        """(your sectors minus theirs, laps of yours, laps of theirs): race = recent laps, else best laps."""
        hist = self.st.history
        return calc.sector_gap(hist.get(self.me), hist.get(idx), self.sc_laps, self.st.laps.sc_laps(idx), 3 if self.race else None)

    def _tyres_by_sector(self, rivals, gaps):
        timed = {}
        for idx, label in rivals:
            if gaps[idx]:
                timed = {n: (f"{self.r.name(idx)} ({label})", d) for n, d in enumerate(gaps[idx][0], 1)}
        spans, track_len = wear.sectors(self.s), self.s["trackLength"]
        lines = wear.summary(self.st.wear, self.me, self.r.active(), spans, track_len, timed.get)
        if self.race:
            lines += grip.summary(self.st.grip, spans, track_len)
        return ["WHERE THE TYRES GO"] + lines if lines else []

    def _sectors_vs(self, idx, label, res):
        deltas, n, m = res
        basis = f"avg of your last {n} green laps vs their last {m}" if self.race else "best laps"
        return (f"  sectors vs {self.r.name(idx)} ({label}, {basis}): "
                + ", ".join(f"S{i + 1} {_quicker(d)}" for i, d in enumerate(deltas)) + f" · lap: {_quicker(sum(deltas))}")

    def _field(self):
        rows = sorted(self.r.active(), key=self.r.pos)
        if self.race:
            head = "FIELD (gap to you at the line, + = behind; tyre, age; last lap time; worst wear; how the gap is moving)"
            out = [head] + [self._race_row(i) for i in rows if i != self.me]
            gone = self.r.retired()
            return out + (["  out: " + ", ".join(self.r.name(i) for i in gone)] if gone else [])
        mine = calc.best_ms(self.st.history.get(self.me))
        head = "FIELD (best lap, gap to your best; tyre now; status)"
        return [head] + [self._practice_row(i, mine) for i in rows]

    def _race_row(self, idx):
        c = self.lap_pkt["lapData"][idx]
        g = self.gaps.get(idx)
        shown = "  —  " if not g else gap(g["gap"], self.ref_ms)
        row = f"  P{self.r.pos(idx):<2} {self.r.name(idx):11} {self.r.team(idx):15} {shown:>7}"
        row += self._tyre_cols(idx)
        if c["lastLapTimeInMS"]:
            row += f"  {laptime(c['lastLapTimeInMS'])}"
        dmg = self.r.damage(idx)
        if dmg and max(dmg["tyresWear"]):
            w = max(range(4), key=lambda i: dmg["tyresWear"][i])
            row += f"  {WHEELS[w]} {dmg['tyresWear'][w]:.0f}%"
        if g and g["last"] is not None:
            row += f"  last lap: {trend(g['gap'], g['last'])}"
            if g["trendLaps"] and g["trendLaps"] > 1:
                row += f"; over {g['trendLaps']} laps: {trend(g['gap'], g['trend'])}"
                if self._adjacent(idx):
                    row += self._at_flag(g)
        if c["numPitStops"]:
            row += f"  stops {c['numPitStops']}"
        if c["pitStatus"]:
            row += "  IN PIT"
        return row

    def _adjacent(self, idx):
        return abs(self.r.pos(idx) - self.r.pos(self.me)) == 1

    def _at_flag(self, g):
        """Where the gap ends up if the last lap's change keeps going, for the cars either side."""
        return " → at last lap's rate " + at_flag_words(self.r.at_flag(g))

    def _practice_row(self, idx, mine):
        c = self.lap_pkt["lapData"][idx]
        best = calc.best_ms(self.st.history.get(idx))
        row = f"  P{self.r.pos(idx):<2} {self.r.name(idx):11} {self.r.team(idx):15}"
        row += f" {laptime(best) if best else 'no time':>8}"
        if best and mine and idx != self.me:
            row += f" {(best - mine) / 1000:+.3f}"
        row += self._tyre_cols(idx)
        row += f"  {L.name(L.DRIVER_STATUS, c['driverStatus']).lower()}"
        return row + ("  ← you" if idx == self.me else "")

    def _tyre_cols(self, idx):
        status = self.r.status(idx)
        return f"  {tyre(status['visualTyreCompound'])[0]} {status['tyresAgeLaps']:>2}" if status else ""


def _quicker(secs):
    """Spelled out, like trends: models flip the sign of a bare -0.071."""
    if abs(secs) < 0.005:
        return "level"
    return f"you're {abs(secs):.3f} {'slower' if secs > 0 else 'quicker'}"


def at_flag_words(got):
    kind, n, left = got
    if kind == "closes":
        return f"the gap closes in ≈{n:.0f} laps ({left} left)"
    return f"≈{n:.1f}s at the flag ({left} laps left)"
