"""Team radio: button-gated mic capture -> local STT -> radio messages.

The game's button events decide when the driver is talking, so there's no VAD. The mic runs
continuously into a short pre-roll ring and frames are only kept while the radio is open.
The mic and speech model are the `voice` extra (Apple Silicon); without them typed questions
still come through here.
"""
import threading
import time
from collections import deque
from pathlib import Path

from . import log, radiolog, usage
from .lexicon import Lexicon
from .lookups import BUTTONS

_log = log.get("radio")

TRIGGER = "UDP Action 1"  # bound to LS click in the game's controls
QUICK = "UDP Action 2"    # RS click
SAMPLE_RATE = 16_000      # what the speech model takes
BLOCK = 512
PRE_ROLL_S = 0.3   # button press lands a beat after the first syllable
POST_ROLL_S = 0.25  # and the release/tap a beat before the last one ends
MAX_OPEN_S = 30.0  # missed release or forgotten tap shouldn't leave a hot mic
MIN_AUDIO_S = 0.4
# loudest 100 ms (RMS) below this is nobody talking: parakeet hears "Yeah." in silence. Over 40 real clips
# everything under 0.01 was empty or "Yeah." (0.0016-0.0054); the quietest real question 0.0157
SILENT_RMS = 0.008
LEVEL_HZ = 15
CLIPS = radiolog.CLIPS


class Radio:
    def __init__(self, hub, mode="hold", driver=lambda: None, names=lambda: [], lexicon=None, at=lambda: usage.NOWHERE,
                 trigger=TRIGGER, quick=QUICK):
        self.hub = hub
        self.at = at  # which session a message belongs to, for the timings
        self.mode = mode
        self.driver = driver
        self.names = names
        self.lexicon = lexicon or Lexicon()
        self.listeners = []  # fn(msg) for every finished message, called on the STT thread
        self.on_open = []    # fn() when the radio opens: the engineer stops talking
        self.trigger, self.quick = button(trigger), button(quick)
        self.stt = None
        self.status = "loading"
        self.error = None
        self.device = None
        self.messages = deque(maxlen=30)
        self._lock = threading.Lock()
        self._pre_roll = deque(maxlen=int(PRE_ROLL_S * SAMPLE_RATE / BLOCK) + 1)
        self._frames = None      # list while capturing
        self._opened_at = None
        self._close_at = None    # set on close; capture continues until post-roll ends
        self._source = None
        self._level = 0.0

    # --- lifecycle ---------------------------------------------------------

    def start(self):
        try:
            import sounddevice as sd

            from .stt import STT
        except ImportError as e:  # not on Apple Silicon, or installed with --no-group voice
            _log.warn("no mic: the voice group isn't installed; typed questions still work", missing=e.name)
            self.error = "no mic or speech model on this machine: type questions on the Radio tab"
            return self._set_status("off")
        self.stt = STT()
        try:
            self.device = sd.query_devices(kind="input")["name"]
            self._stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                                          blocksize=BLOCK, callback=self._on_audio)
            self._stream.start()
            _log.info("mic open", device=self.device)
        except Exception as e:
            return self._fail(f"mic unavailable: {e}")
        self.stt.load().add_done_callback(self._loaded)
        threading.Thread(target=self._tick, name="radio-tick", daemon=True).start()

    def _loaded(self, fut):
        if fut.exception():
            return self._fail(f"speech model failed to load: {fut.exception()}")
        self._set_status("ready")

    def _fail(self, msg):
        _log.error("radio disabled", exc=False, reason=msg)
        self.error = msg
        self._set_status("error")

    # --- inputs ------------------------------------------------------------

    def on_buttons(self, prev, now):
        was, held = prev >> self.trigger & 1, now >> self.trigger & 1
        if was != held:
            self.edge(bool(held), "game")
        if now >> self.quick & 1 and not prev >> self.quick & 1:
            _log.info("quick brief requested")
            self.hub.publish("quick", {"at": time.time()})

    def edge(self, pressed, source):
        """Trigger pressed/released. Toggle mode flips on press; hold mode follows the button."""
        with self._lock:
            if self._close_at is not None:
                return  # still in post-roll; a re-tap here would throw that message away
            capturing = self._frames is not None
            if self.mode == "toggle":
                if pressed:
                    self._close() if capturing else self._open(source)
            elif pressed and not capturing:
                self._open(source)
            elif not pressed and capturing and self._source == source:
                self._close()

    # --- capture -----------------------------------------------------------

    def _open(self, source):
        if self.status not in ("ready", "transcribing"):
            _log.warn("radio pressed but not ready", status=self.status)
            return
        self._frames = list(self._pre_roll)
        self._opened_at = time.time()
        self._close_at = None
        self._source = source
        _log.info("radio open", source=source)
        self._set_status("open")
        for fn in self.on_open:
            fn()

    def _close(self):
        self._close_at = time.time() + POST_ROLL_S

    def _on_audio(self, indata, _frames, _time, _status):
        import numpy as np

        frame = indata[:, 0].copy()
        self._level = max(float(np.sqrt(np.mean(frame ** 2))), self._level * 0.85)
        with self._lock:
            self._pre_roll.append(frame)
            if self._frames is not None:
                self._frames.append(frame)

    def _tick(self):
        while True:
            time.sleep(1 / LEVEL_HZ)
            if self._frames is None:
                continue
            done = self._poll(time.time())
            if done:
                self._finish(*done)
            else:
                self.hub.publish("level", {"rms": round(self._level, 4)})

    def _poll(self, now):
        """Auto-close if open too long; hand back (audio, closed_at) once post-roll has elapsed."""
        with self._lock:
            if self._frames is None:
                return None
            if self._close_at is None and now - (self._opened_at or now) > MAX_OPEN_S:
                _log.warn("radio auto-closed", after_s=MAX_OPEN_S)
                self._close_at = now + POST_ROLL_S
            if self._close_at is None or now < self._close_at:
                return None
            import numpy as np

            done = (np.concatenate(self._frames), self._close_at - POST_ROLL_S)
            self._frames = self._close_at = None
            return done

    def _finish(self, audio, closed_at):
        secs = len(audio) / SAMPLE_RATE
        peak = float(abs(audio).max()) if len(audio) else 0.0
        loud = loudest(audio)
        clip = self._save(audio, closed_at)
        _log.info("radio closed", audio_s=round(secs, 2), peak=round(peak, 3), loud=round(loud, 4), clip=clip)
        extra = {"clip": clip and Path(clip).name, "loud": round(loud, 4)}
        if secs < MIN_AUDIO_S:
            return self._message("", secs, 0, closed_at, note="too short", **extra)
        if loud < SILENT_RMS:
            return self._message("", secs, 0, closed_at, note="silence, nobody talking", **extra)
        self._set_status("transcribing")
        t = time.perf_counter()
        fut = self.stt.transcribe(audio)
        fut.add_done_callback(lambda f: self._transcribed(f, secs, t, closed_at, extra))

    def _save(self, audio, closed_at):
        # every clip is kept so STT misses can be listened to and re-run offline
        import soundfile as sf

        try:
            CLIPS.mkdir(parents=True, exist_ok=True)
            path = CLIPS / time.strftime("%Y%m%d-%H%M%S.wav", time.localtime(closed_at))
            sf.write(path, audio, SAMPLE_RATE)
            return str(path)
        except Exception as e:
            _log.error("couldn't save radio clip", error=str(e))
            return None

    def _transcribed(self, fut, secs, t, closed_at, extra):
        stt_ms = (time.perf_counter() - t) * 1000
        if fut.exception():
            _log.error("transcription failed", exc=False, error=str(fut.exception()))
            return self._message("", secs, stt_ms, closed_at, note="transcription failed", **extra)
        self._message(fut.result(), secs, stt_ms, closed_at, **extra)

    def typed(self, text):
        """A question typed in the dashboard, handled exactly like a spoken one."""
        self._message(text.strip(), 0, 0, time.time(), source="typed")

    def _message(self, heard, secs, stt_ms, closed_at, note=None, source="radio", clip=None, loud=None):
        text, changes = self.lexicon.correct(heard, self.names()) if heard else (heard, [])
        msg = {
            "id": f"{closed_at:.3f}",
            "text": text,
            "heard": heard,
            "changes": changes,
            "note": note or ("nothing heard" if not text else None),
            "audioSec": round(secs, 2),
            "sttMs": round(stt_ms),
            "releaseToTextMs": round((time.time() - closed_at) * 1000),
            "at": time.time(),
            "driver": self.driver(),
            "source": source,
            "clip": clip,
            "loud": loud,
        }
        self.messages.append(msg)
        radiolog.record("message", msg)
        if source == "radio":
            where = self.at()
            usage.metric("radio_heard" if text else "radio_empty", 1, where, note=msg["note"])
            if text:
                usage.metric("stt_ms", msg["sttMs"], where)
                usage.metric("release_ms", msg["releaseToTextMs"], where)
        _log.info("radio message", text=text, heard=heard if changes else None, audio_s=msg["audioSec"], stt_ms=msg["sttMs"],
                  release_to_text_ms=msg["releaseToTextMs"])
        self.hub.publish("message", msg)
        for fn in self.listeners:
            fn(msg)
        if source == "radio":
            self._set_status("ready" if self._frames is None else "open")

    # --- state -------------------------------------------------------------

    def _set_status(self, status):
        self.status = status
        self.hub.publish("radio", self.snapshot())

    def snapshot(self):
        return {
            "status": self.status,
            "error": self.error,
            "mode": self.mode,
            "trigger": BUTTONS[self.trigger],
            "quick": BUTTONS[self.quick],
            "device": self.device,
            "openedAt": self._opened_at if self.status == "open" else None,
            "source": self._source,
        }


def loudest(audio, window=0.1):
    """RMS of the loudest `window` seconds: the room's hiss sits well under any word."""
    import numpy as np

    n = int(SAMPLE_RATE * window)
    if len(audio) < n:
        return float(np.sqrt(np.mean(audio ** 2))) if len(audio) else 0.0
    frames = audio[:len(audio) // n * n].reshape(-1, n)
    return float(np.sqrt((frames ** 2).mean(axis=1)).max())


def button(name):
    """A button by name ("UDP Action 1", "Left Stick Click") or a UDP action number -> its bit."""
    name = str(name).strip()
    if name.isdigit():
        name = f"UDP Action {name}"
    try:
        return next(i for i, b in enumerate(BUTTONS) if b.lower() == name.lower())
    except StopIteration:
        raise ValueError(f"unknown button {name!r}: one of {', '.join(BUTTONS)}") from None
