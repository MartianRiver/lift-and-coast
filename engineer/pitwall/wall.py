"""The pit wall: the strategy team behind the engineer.

Models only run when something has changed (`triggers`), or for a routine check when nothing
has for a while, within a budget per race. The lead strategist makes the call and a second model
reviews it; the engineer relays the call and only makes its own when there's no time to ask.
Times are session seconds, so a replay behaves like the live thing.
"""
import re
import threading
import time

from .. import brief, driver, log, prompts, strategy, usage
from ..llm import LLMError, api_key, stream
from ..race import Race, ready
from ..spec import MAX_CARS
from . import notes, prep, triggers

_log = log.get("pitwall")

MODELS = ("anthropic/claude-sonnet-5.5", "google/gemini-3.8-flash")  # lead, second opinion
BUDGET = 2.00          # $ a session; past it only urgent reasons and their questions get a run
GATHER = 10.0          # s to gather reasons into one run, unless one is urgent
HEARTBEAT = (5, 480)   # laps or s without a run before a routine check
QUIET = 5.0            # s without packets: nothing's moving, nothing to run
TICK = 1.0
PIT_ENTRY = 0.85       # share of the lap after which a "box?" can't wait for the team
BRIEF = "RIVER'S BRIEF FOR THIS RACE"
HIS_CALL = ("RIVER'S OWN CALL (it stands until he stops or makes another: plan A follows it. To change it, push back in SAY "
            "with the number that shows it can't work, never switch it quietly)")

STRATEGY = re.compile(r"\b(box|boxing|pit|pitting|stop now|stopping|a stop|another stop|one[- ]stop|two[- ]stop|"
                      r"when do i stop|undercut|overcut|strategy|plan|stay out|extend|stretch|inters|intermediates|"
                      r"wets|slicks|which tyres?|what tyres?|which compound|what compound|switch to)\b")
TELL = re.compile(r"^(?:tell|note for|message for|let) the (?:team|pit wall|strategists?)(?: know)?[,:]?\s+(?:that\s+)?(.+)$", re.I)
# the driver making the call himself ("Mediums on nine.", "Boxing this lap"): a statement, not a question
CALLED = re.compile(r"\b(softs?|mediums?|hards?|inters|intermediates|wets|box|boxing|pitting|stay(?:ing)? out)\b")
QUESTION = re.compile(r"^(?:what|when|where|which|who|why|how|should|shall|can|could|do|does|did|is|are|will|would|have|has)\b")
SWITCH = re.compile(r"^(?:let'?s |ok,? |okay,? )?(?:go|go to|switch to|we'?re on|run|use)?\s*plan ([abc])\W*$")


class PitWall:
    def __init__(self, state, hub, models=MODELS, budget=BUDGET, at=None, persist=True):
        self.state, self.hub, self.models, self.budget = state, hub, tuple(models), budget
        self.at = at or (lambda: usage.where(state))
        self.persist = persist
        self.role = "pitwall" if persist else "dev"
        self.error = None if api_key() is not None else "no OPENROUTER_API_KEY in .env, the pit wall is off"
        self.say = lambda text, urgent: None     # the engineer relays the team's call (crew wires it)
        self.fallback = lambda calls: None        # the code's own calls, when the team can't answer
        self.heard = lambda: []                   # recent radio lines, for context
        self._wake = threading.Event()
        self._lock = threading.Lock()  # pending reasons: added from the engineer's thread too
        self._n = 0
        self.prep = {"running": False, "error": None, **(prep.load() or {})}  # the race plan made before it loads
        self._reset(None)

    def _reset(self, uid):
        self._uid, self.mem, self.pending, self._since = uid, {}, [], None
        self.notes, self.plans, self.active, self.box, self._box_stops = [], {}, None, None, None
        self.spent, self.running, self._last = 0.0, None, None  # _last: (session time, lap) of the last run
        self.his_call = None  # {text, lap, stops}: the last call the driver made himself
        if uid and self.persist:
            for n in notes.load(str(uid)):
                self._apply(n, publish=False)

    def start(self):
        threading.Thread(target=self._loop, name="pitwall", daemon=True).start()

    def _loop(self):
        while True:
            self._wake.wait(TICK)
            self._wake.clear()
            try:
                job = self.step()
                if job:
                    self.run(*job)
            except Exception as e:  # keep the wall alive whatever happens
                _log.error("pit wall step crashed", error=str(e))

    # --- when -------------------------------------------------------------------

    def step(self):
        """One look at the state -> (reasons, lap, session time, their stops) when it's time for a run, else None."""
        st = self.state
        with st.lock:
            if not ready(st):
                return None
            if st.session_uid != self._uid:
                self._reset(st.session_uid)
            if (st.silent_for() or 0) > QUIET:
                return None
            b = Race(st)
            if not b.race or b.me >= MAX_CARS:
                return None
            lap, now = b.my["currentLapNum"], b.now
            if not self.plans and not self.mem.get("planned"):
                self.mem["planned"] = True
                self._add([self._first(b, lap)])
            box = self.planned_box(b)
            self._add(triggers.scan(b, self.mem, box))
            if self._last and not self.pending and (lap - self._last[1] >= HEARTBEAT[0] or now - self._last[0] >= HEARTBEAT[1]):
                self._add([triggers.reason(("routine", lap), "routine check: nothing has called the team for a while")])
            with self._lock:
                due = self._due(lap, now)
            return due and (due, lap, now, b.my["numPitStops"])

    def _first(self, b, lap):
        """The first run of a race: check the pre-race plan against the live race, or write plans."""
        made = prep.load(b.s["trackId"])
        if made and made.get("note") and lap <= 1:
            n = made["note"]
            self.plans, self.active, self.box, self._box_stops = n.get("plans") or {}, n.get("active") or "A", n.get("box"), 0
            self.notes.append({**n, "lap": 0})
            return triggers.reason(("plans",), "the race has loaded: check the pre-race plan (fuel and start tyre are already "
                                   "chosen) against the live race (laps, grid, weather, sets) and keep or adjust plans A, B and C")
        return triggers.reason(("plans",), "the race is starting: write plans A, B and C" if lap <= 1
                               else f"no plans yet and it's lap {lap}: write plans A, B and C from here")

    def _add(self, reasons):
        with self._lock:
            for r in reasons:
                if not any(p["key"] == r["key"] for p in self.pending):
                    self.pending.append(r)

    def _due(self, lap, now):
        if not self.pending:
            self._since = None
            return None
        self._since = self._since if self._since is not None and self._since <= now else now
        if not any(r["urgent"] or r["question"] for r in self.pending):
            if self.spent >= self.budget:
                _log.info("over budget, skipping", reasons=[r["text"] for r in self.pending], spent=round(self.spent, 3))
                self.pending = []
                return None
            if now - self._since < GATHER or (self._last and self._last[1] == lap):
                return None  # one routine run a lap at most
        reasons, self.pending, self._since = self.pending, [], None
        self._last = (now, lap)
        return reasons

    # --- their questions and commands ---------------------------------------------------

    def routes(self, text):
        """A strategy question: "team" (copy, checking) or "now" (no time to ask: the engineer answers
        from the plans and the team reviews it after). "called": the driver made the call himself; the
        engineer confirms it and the team plans around it. None: not ours."""
        low = text.lower().strip()
        called = CALLED.search(low) and not low.endswith("?") and not QUESTION.match(low)
        if self.error or not (called or STRATEGY.search(low)):
            return None
        with self.state.lock:
            if not ready(self.state):
                return None
            b = Race(self.state)
            if not b.race or not b.my:
                return None
            hurry = b.s["safetyCarStatus"] in (1, 2) or b.my["pitStatus"] or b.my["lapDistance"] > PIT_ENTRY * b.s["trackLength"]
        return "called" if called else "now" if hurry else "team"

    def ask(self, text):
        self._add([triggers.reason(("question", time.time()), f'{driver.name()} asked: "{text}"', urgent=True, question=text)])
        self._wake.set()

    def answered(self, question, answer):
        """The engineer answered a strategy question itself: the team looks at it next."""
        self._add([triggers.reason(("answered", time.time()), f'{driver.name()} asked "{question}" with no time to check; '
                                   + driver.words("the engineer told him") + f' "{answer}". Review it')])

    def called(self, text, answer):
        """The driver made the call: the team plans around it at once, and every run after until he stops."""
        with self.state.lock:
            my = ready(self.state) and Race(self.state).my
            self.his_call = my and {"text": text, "lap": my["currentLapNum"], "stops": my["numPitStops"]}
        self._add([triggers.reason(("called", time.time()), driver.words("River made the call himself: ") + f'"{text}"; '
                                   + driver.words("the engineer told him") + f' "{answer}". '
                                   + driver.words("His call is the plan now: rewrite the plans around it"), urgent=True)])
        self._wake.set()

    def command(self, text):
        """"go plan B" switches plans, "tell the team ..." goes in the driver's brief; answers for the radio, else None."""
        told = TELL.match(text.strip())
        if told:
            self.tell(told.group(1))
            return "Copy, I'll pass it on."
        m = SWITCH.match(text.lower().strip())
        if not m or m.group(1).upper() not in self.plans:
            return None
        self.active = m.group(1).upper()
        _log.info("plan switched", plan=self.active)
        self._add([triggers.reason(("switch", self.active, time.time()), driver.words("River switched to plan ") + self.active)])
        return f"Copy, plan {self.active}."

    def tell(self, text):
        """The driver's brief for the team: added to what's there, and the team looks at the plans again.
        A line it already has isn't added twice (the same text sent again from the tab)."""
        old = notes.read_brief()
        if old and text.strip() in old["text"].splitlines():
            return
        notes.write_brief(f"{old['text']}\n{text}" if old else text)
        _log.info("brief", text=text)
        self._add([triggers.reason(("brief", time.time()), f'{driver.name()} told the team: "{text}"')])

    # --- before the race ---------------------------------------------------------------

    def prepare(self):
        """Race prep in the background: fuel, start tyre and plans from the last session here and their history."""
        if self.prep.get("running") or self.error:
            return
        self.prep = {**self.prep, "running": True, "error": None}
        threading.Thread(target=self._prepare, name="pitwall-prep", daemon=True).start()

    def _prepare(self):
        try:
            text, info = prep.facts()
            if not text:
                raise LLMError(info)
            told = notes.read_brief()
            ask = driver.words(text) + (f"\n\n{driver.words(BRIEF)}\n  {told['text']}" if told else "") + "\n\nWrite the race plan."
            version, rules = prompts.pick("prep")
            messages = [{"role": "system", "content": driver.words(rules)}, {"role": "user", "content": ask}]
            raw, cost, ms = self._plan(messages, version)
            wrong = prep.check(notes.lead(raw), info)
            if wrong:  # one more go, told what's wrong
                _log.warn("race prep broke a rule", problem=wrong)
                messages += [{"role": "assistant", "content": raw}, {"role": "user", "content": f"That plan doesn't work: {driver.words(wrong)}. Write the whole plan again."}]
                raw, more, ms = self._plan(messages, version)
                cost = (cost or 0) + (more or 0)
            note = {"id": f"prep-{int(time.time())}", "who": "lead", "kind": "prep", "model": self.models[0], "at": time.time(),
                    "lap": 0, "stops": 0, "reasons": ["race prep, before the race loads"], "question": None,
                    **notes.lead(raw), "text": raw, "cost": cost, "ms": ms, "prompt": version}
            review = None
            if len(self.models) > 1:
                rout, (second, rules) = [], prompts.pick("second")
                rstats = stream(self.models[1], [{"role": "system", "content": driver.words(rules)},
                                                 {"role": "user", "content": f"{ask}\n\nTHE LEAD STRATEGIST'S CALL\n{raw}"}],
                                rout.append, role=self.role, at=usage.NOWHERE, why="pitwall: race prep review", prompt=second)
                agree, why = notes.review("".join(rout))
                review = {"agree": agree, "text": why, "model": self.models[1], "cost": rstats.get("cost"), "prompt": second}
            self.prep = {**info, "at": time.time(), "facts": text, "note": note, "review": review, "running": False, "error": None}
            prep.save({k: v for k, v in self.prep.items() if k not in ("running", "error")})
            _log.info("race prep", track=info["track"], fuel=note.get("fuel"), start=note.get("start"), call=note.get("call"))
        except (LLMError, OSError) as e:
            _log.error("race prep failed", exc=False, error=str(e))
            self.prep = {**self.prep, "running": False, "error": str(e)}
        self.hub.publish("pitwall", {"prep": True})

    def _plan(self, messages, version):
        out = []
        stats = stream(self.models[0], messages, out.append, role=self.role, at=usage.NOWHERE, why="pitwall: race prep", prompt=version)
        return "".join(out).strip(), stats.get("cost"), stats.get("totalMs")

    # --- a run ----------------------------------------------------------------------

    def run(self, reasons, lap, now, stops, wait=False):
        """The lead strategist's call, then the second opinion (in the background unless wait). -> the lead's note."""
        data = brief.build(self.state)
        if not data:
            return None
        question = next((r["question"] for r in reasons if r["question"]), None)
        self._n += 1
        note = {"id": f"n{self._n}-{int(time.time())}", "who": "lead", "model": self.models[0], "at": time.time(),
                "sessionTime": round(now, 1), "lap": lap, "stops": stops, "reasons": [r["text"] for r in reasons],
                "question": question}
        note["prompt"], rules = prompts.pick("lead")
        self.running = note
        self.hub.publish("pitwall", {"running": note})
        messages = [{"role": "system", "content": driver.words(rules)},
                    {"role": "user", "content": self._input(data, reasons, lap, stops)}]
        _log.info("team run", reasons=note["reasons"], model=self.models[0])
        out = []
        try:
            stats = stream(self.models[0], messages, out.append, role=self.role, at=self.at(), why="pitwall: " + reasons[0]["key"][0],
                           prompt=note["prompt"])
        except LLMError as e:
            _log.error("team run failed", exc=False, error=str(e))
            self.running = None
            self._apply({**note, "error": str(e)})
            self.fallback([c for r in reasons for c in r["fallback"]])
            return note
        self.running = None
        text = "".join(out).strip()
        note.update(notes.lead(text), text=text, cost=stats.get("cost"), ms=stats.get("totalMs"))
        self._apply(note)
        if note["say"]:
            self.say(note["say"], any(r["urgent"] or r["question"] for r in reasons))
        if len(self.models) > 1 and self.spent < self.budget:
            if wait:
                self._review(data, note)
            else:
                threading.Thread(target=self._review, args=(data, note), name="pitwall-review", daemon=True).start()
        return note

    def _review(self, data, lead):
        version, rules = prompts.pick("second")
        messages = [{"role": "system", "content": driver.words(rules)},
                    {"role": "user", "content": f"{data}\n\nTHE LEAD STRATEGIST'S CALL\n{lead['text']}"}]
        out = []
        try:
            stats = stream(self.models[1], messages, out.append, role=self.role, at=self.at(), why="pitwall review", prompt=version)
        except LLMError as e:
            _log.error("review failed", exc=False, error=str(e))
            return
        text = "".join(out).strip()
        agree, why = notes.review(text)
        self._apply({"id": lead["id"] + "r", "who": "review", "of": lead["id"], "model": self.models[1], "at": time.time(),
                     "sessionTime": lead["sessionTime"], "lap": lead["lap"], "agree": agree, "text": why,
                     "cost": stats.get("cost"), "ms": stats.get("totalMs"), "prompt": version})

    def _apply(self, note, publish=True):
        self.notes.append(note)
        self.spent += note.get("cost") or 0
        if note.get("plans"):
            self.plans = note["plans"]
            self.active = note.get("active") or self.active or "A"
        elif note.get("active"):
            self.active = note["active"]
        if note["who"] == "lead" and not note.get("error"):
            self.box, self._box_stops = note.get("box"), note.get("stops")  # a planned stop belongs to that stint
        if publish:
            self.hub.publish("pitwall", {"note": note})
            if self.persist and self._uid:
                notes.save(str(self._uid), note)

    def _input(self, data, reasons, lap, stops):
        parts = [data, "", *notes.section(self, *self._where())]
        told = notes.read_brief()
        if told:
            parts += [driver.words(BRIEF + " (how he wants to race it: plan around it)"), f"  {told['text']}"]
        call = self.his_call
        if call and call["stops"] == stops:
            parts += [driver.words(HIS_CALL), f'  L{call["lap"]}: "{call["text"]}"']
        mine = notes.history(self)
        if mine:
            parts += ["YOUR TEAM'S RECENT NOTES", *mine]
        heard = self.heard()
        if heard:
            parts += ["RADIO (recent, oldest first)", *[f"  {line}" for line in heard]]
        parts += ["WHY YOU'RE CALLED NOW", *[f"  - {r['text']}" for r in reasons]]
        if not self.plans:
            parts.append("There are no plans yet: write plans A, B and C.")
        return "\n".join(parts)

    # --- for the engineer and the dashboard ------------------------------------------------

    def section(self):
        lap, tyres = self._where()
        return "\n".join(notes.section(self, lap, tyres, calls=True))

    def _where(self):
        """(the player's lap, the tyre target line) for the PIT WALL section."""
        with self.state.lock:
            if not ready(self.state):
                return 0, None
            b = Race(self.state)
            if not b.my or b.me >= MAX_CARS:
                return 0, None
            box = self.planned_box(b)
            got = b.race and box and triggers.tyre_target(b, box)  # to the flag is in the brief already
            return b.my["currentLapNum"], got and strategy.target_text(*got)

    def planned_box(self, b):
        """The lap the team plans to stop at the end of, or None: a planned stop belongs to the stint it was made in."""
        return self.box if self._box_stops == b.my["numPitStops"] else None

    def glance(self):
        """For the Race tab: the active plan and the team's latest call."""
        last = next((n for n in reversed(self.notes) if n["who"] == "lead" and n.get("call")), None)
        return {"active": self.active, "plan": self.plans.get(self.active), "box": self.box,
                "call": last and {"lap": last["lap"], "text": last["call"]}, "running": bool(self.running)}

    def snapshot(self):
        return {"brief": notes.read_brief(), "prep": {k: v for k, v in self.prep.items() if k != "facts"}, "models": self.models, "error": self.error, "budget": self.budget, "spent": round(self.spent, 4),
                "running": self.running, "pending": [r["text"] for r in self.pending],
                "plans": self.plans, "active": self.active, "box": self.box, "notes": self.notes[-40:]}
