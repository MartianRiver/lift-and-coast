"""What the Settings tab sets, kept in the data folder as settings.json.

Each value comes from the first of: the command line, the environment or .env, the file, the default.
One given on the command line or in the environment shows locked in the tab: a change made there
would be overruled on the next start without anyone noticing.
"""
import json
import threading
from dataclasses import dataclass

from . import archive, llm, log
from .calls.caller import LEVELS
from .calls.common import GROUPS
from .engineer import DEFAULT_MODEL, FALLBACK
from .pitwall import BUDGET, MODELS
from .radio import QUICK, TRIGGER, button
from .tts import DEFAULT_VOICE, parse_voice

_log = log.get("settings")

FILE = archive.DATA / "settings.json"
MAX_BUDGET = 50.0


def _model(v):
    v = str(v or "").strip()
    if not v or len(v) > 200 or any(c.isspace() for c in v):
        raise ValueError("a model id, like moonshotai/kimi-k3")
    return v


def _optional_model(v):
    return None if v is None or str(v).strip().lower() in ("", "none") else _model(v)


def _voice(v):
    name, voice = parse_voice(str(v))
    return f"{name}:{voice}" if voice else name


def _budget(v):
    v = float(v)
    if not 0 < v <= MAX_BUDGET:
        raise ValueError(f"between 0 and {MAX_BUDGET:g} dollars")
    return round(v, 2)


def _button(v):
    button(v)
    return str(v).strip()


def _choice(*options):
    def check(v):
        if v not in options:
            raise ValueError("one of " + ", ".join(options))
        return v
    return check


def _topics(v):
    if not isinstance(v, dict) or not set(v) <= set(GROUPS):
        raise ValueError("switches for " + ", ".join(GROUPS))
    return {g: bool(v.get(g, True)) for g in GROUPS}


def _flag(v):
    if not isinstance(v, bool):
        raise ValueError("true or false")
    return v


def _device(v):
    return (str(v).strip() or None) if v is not None else None


@dataclass(frozen=True)
class Spec:
    default: object
    check: object
    flag: str | None = None   # the server's command-line option
    env: str | None = None
    part: int | None = None   # which of the comma-separated values in the flag or env var
    restart: bool = False     # takes effect on the next start


SPECS = {
    "engineerModel": Spec(DEFAULT_MODEL, _model, "--engineer-model", "RE_ENGINEER_MODEL"),
    "engineerFallback": Spec(FALLBACK, _optional_model, "--engineer-fallback", "RE_ENGINEER_FALLBACK"),
    "voice": Spec(DEFAULT_VOICE, _voice, "--voice", "RE_VOICE"),
    "radioFx": Spec(False, _flag, "--radio-fx"),
    "calls": Spec("normal", _choice(*LEVELS)),
    "topics": Spec({g: True for g in GROUPS}, _topics),
    "lead": Spec(MODELS[0], _model, "--pitwall-models", "RE_PITWALL_MODELS", part=0),
    "second": Spec(MODELS[1], _optional_model, "--pitwall-models", "RE_PITWALL_MODELS", part=1),
    "budget": Spec(BUDGET, _budget, "--pitwall-budget"),
    "radioButton": Spec(TRIGGER, _button, "--radio-button", "RE_RADIO_BUTTON"),
    "radioMode": Spec("hold", _choice("hold", "toggle"), "--radio-mode"),
    "quickButton": Spec(QUICK, _button, "--quick-button", "RE_QUICK_BUTTON"),
    "audioOut": Spec(None, _device, "--audio-out", restart=True),
}


class Settings:
    """cli: {"--engineer-model": value} for the options given when the server started."""

    def __init__(self, cli=None, path=None, env=llm.env_where):
        self.cli = {k: v for k, v in (cli or {}).items() if v is not None}
        self.path, self._env = path or FILE, env
        self._lock = threading.Lock()
        self._file = self._read()

    def _read(self):
        try:
            got = json.loads(self.path.read_text())
            return got if isinstance(got, dict) else {}
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as e:
            _log.error("couldn't read settings, using the defaults", exc=False, error=str(e))
            return {}

    def _given(self, key):
        """(raw value, where) from the command line or the environment, or None."""
        spec = SPECS[key]
        if spec.flag in self.cli:
            raw, where = self.cli[spec.flag], spec.flag
        elif spec.env and self._env(spec.env)[0] is not None:
            raw, src = self._env(spec.env)
            where = f"{spec.env} in {src}"
        else:
            return None
        if spec.part is not None:
            parts = str(raw).split(",")
            raw = parts[spec.part] if spec.part < len(parts) else None
        return raw, where

    def resolve(self, key):
        """(value, where it came from: a flag, an env var, "file" or "default")."""
        spec = SPECS[key]
        given = self._given(key)
        if given:
            try:
                return spec.check(given[0]), given[1]
            except ValueError as e:
                _log.error("bad setting, using the default", exc=False, setting=key, source=given[1], error=str(e))
                return spec.default, given[1]
        if key in self._file:
            try:
                return spec.check(self._file[key]), "file"
            except (TypeError, ValueError) as e:
                _log.error("bad setting in settings.json, using the default", exc=False, setting=key, error=str(e))
        return spec.default, "default"

    def get(self, key):
        return self.resolve(key)[0]

    def all(self):
        return {k: self.get(k) for k in SPECS}

    def view(self):
        out = {}
        for key, spec in SPECS.items():
            value, where = self.resolve(key)
            out[key] = {"value": value, "default": spec.default, "restart": spec.restart,
                        "locked": where if where not in ("file", "default") else None}
        return out

    def set(self, changes):
        """Saves what the tab changed -> {key: value}. Refuses a key that's locked, or a bad value, before saving any."""
        if not isinstance(changes, dict):
            raise ValueError("send {setting: value}")
        clean = {}
        for key, value in changes.items():
            if key not in SPECS:
                raise ValueError(f"no setting {key!r}")
            given = self._given(key)
            if given:
                raise ValueError(f"{key} is set by {given[1]}")
            try:
                clean[key] = SPECS[key].check(value)
            except (TypeError, ValueError) as e:
                raise ValueError(f"{key}: {e}") from None
        with self._lock:
            self._file.update(clean)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._file, indent=1))
            tmp.replace(self.path)
        _log.info("settings saved", **{k: v for k, v in clean.items() if k != "topics"})
        return clean
