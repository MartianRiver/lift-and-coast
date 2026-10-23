"""The engineer, the radio, the voice, the unprompted calls and the pit wall, wired to one race state."""
import importlib.util
import time
from dataclasses import dataclass

from . import driver, log, prompts, quick, radiolog, usage, view
from .calls import NORMAL, URGENT, Caller
from .calls.common import call
from .engineer import DEFAULT_MODEL, FALLBACK, Engineer
from .pitwall import MODELS, PitWall
from .radio import Radio, button
from .settings import SPECS

HEARD_SECS = 300  # radio the team sees with each run
_log = log.get("crew")


def _have(*modules):
    return all(importlib.util.find_spec(m) for m in modules)


@dataclass
class Crew:
    engineer: Engineer | None
    radio: Radio
    speaker: object | None
    caller: Caller | None
    wall: PitWall | None = None
    hub: object = None

    def apply(self, cfg, keys):
        """Settings changed in the tab, put into what's running -> {key: why it waits for the next start}."""
        later = {}
        for key in keys:
            v = cfg.get(key)
            if key == "engineerModel" and self.engineer:
                self.engineer.model = v
            elif key == "engineerFallback" and self.engineer:
                self.engineer.fallback = v
            elif key in ("voice", "radioFx") and self.speaker:
                if not self.speaker.use(cfg.get("voice"), cfg.get("radioFx")):
                    later["voice"] = "another voice engine loads on the next start"
            elif key == "calls" and self.caller:
                self.caller.level = v
            elif key == "topics" and self.caller:
                self.caller.topics = {g for g, on in v.items() if on}
            elif key in ("lead", "second") and self.wall:
                self.wall.models = tuple(m for m in (cfg.get("lead"), cfg.get("second")) if m)
            elif key == "budget" and self.wall:
                self.wall.budget = v
            elif key in ("radioButton", "quickButton", "radioMode"):
                self.radio.trigger, self.radio.quick = button(cfg.get("radioButton")), button(cfg.get("quickButton"))
                self.radio.mode = cfg.get("radioMode")
                if self.hub:
                    self.hub.publish("radio", self.radio.snapshot())
            elif key == "prompts":
                prompts.use(v)
            elif SPECS[key].restart:
                later[key] = "on the next start"
        if keys:
            _log.info("settings applied", keys=sorted(keys), later=sorted(later))
        return later


def assemble(hub, state, model=DEFAULT_MODEL, engineer=True, mic=True, radio_mode="hold",
             voice=None, fx=False, device=None, calls=True, live=True, team=MODELS, budget=None, buttons=None,
             fallback=FALLBACK):
    """voice: engine[:voice] spec, or None for text only. mic=False still takes typed questions.
    team: the pit wall's models (lead, second opinion), or None for no team. live=False (a replay):
    spend is logged as dev, not against the session being replayed."""
    def at():
        return usage.where(state) if live else usage.NOWHERE

    eng = Engineer(hub, state, model, role="engineer" if live else "dev", at=at, fallback=fallback) if engineer else None
    radio = Radio(hub, mode=radio_mode, driver=lambda: view.player_identity(state), names=lambda: view.session_names(state), at=at,
                  **(buttons or {}))
    if eng:
        radio.listeners.append(eng.ask)
    speaker = None
    if voice and not _have("mlx_audio", "sounddevice"):
        _log.warn("no voice: the voice group isn't installed (Apple Silicon only); answers are text only")
    elif voice:
        from .tts import Speaker

        speaker = Speaker(hub, voice, fx=fx, device=device, at=at, record=live)
        speaker.start()
        radio.on_open.append(speaker.stop)  # keying the radio cuts the engineer off
        if eng:
            eng.speak = speaker.say
    if mic:
        state.button_listeners.append(radio.on_buttons)
        radio.start()
    else:
        radio.status = "off"
    wall = PitWall(state, hub, team, at=at, persist=live, **({"budget": budget} if budget else {})) if team and eng else None
    if wall and wall.error:
        wall = None  # no key: the engineer's off too, and the code keeps its own strategy calls
    caller = None
    if calls or wall:
        def said(text):
            if eng:
                eng.said(text)
            if speaker:
                speaker.say(text)

        caller = Caller(state, hub, said=said, at=at if live else None, scan=calls, busy=lambda: radio.status in ("open", "transcribing")
                        or bool(eng and eng.busy()) or bool(speaker and speaker.busy()))
        caller.start()
        if eng:
            eng.commands.append(caller.command)
    if wall:
        _staff(wall, eng, caller, radio)
    radio.on_quick.append(lambda: _quick(state, hub, eng, speaker, live, caller))
    return Crew(eng, radio, speaker, caller, wall, hub)


def _quick(state, hub, eng, speaker, live, caller):
    """The second button: the quick brief, said now whatever the session."""
    out = quick.brief(state)
    if not out:
        return
    if caller:
        caller.quick_said(out["text"])
    out.update(id=f"q{time.time_ns()}", at=time.time())
    hub.publish("call", out)
    if live:
        radiolog.record("call", out)
    _log.info("quick brief", text=out["text"])
    if eng:
        eng.said(out["text"])
    if speaker:
        speaker.say(out["text"])


def _staff(wall, eng, caller, radio):
    """The team speaks through the engineer's calls and hears the radio."""
    caller.team = True
    caller.box = wall.planned_box
    wall.say = lambda text, urgent: caller.push([call(("team", text), "team", URGENT if urgent else NORMAL,
                                                       lambda b: text, ttl=60 if urgent else 90)])
    wall.fallback = caller.push
    wall.heard = lambda: heard(radio, eng, caller)
    eng.wall = wall
    eng.commands.append(wall.command)
    wall.start()


def heard(radio, eng, caller):
    since = time.time() - HEARD_SECS
    said = {r["to"]: r["text"] for r in eng.replies if r["status"] == "done"}
    lines = [(m["at"], f'{driver.name()}: "{m["text"]}" → engineer: "{said.get(m["id"], "…")}"') for m in radio.messages
             if m.get("text") and m.get("at", 0) >= since]
    lines += [(c["at"], f'engineer, unprompted (L{c["lap"]}): "{c["text"]}"') for c in caller.sent if c["at"] >= since]
    return [line for _, line in sorted(lines)]
