"""The engineer's voice: local text-to-speech on MLX, played through the default output.

Two threads. One owns the model (MLX binds its Metal stream to the thread that loaded it, same
as stt.py) and turns queued text into audio; the other plays it, so the next sentence is ready
before the last one ends. Keying the radio calls `stop()`: playback cuts and anything still
queued from before that moment is dropped. Measured on the M3 Air (Kokoro bf16): ~0.5 s to
synthesise a 7 s call once warm, 4-7 s for the very first one (hence the warm-up at load).

    uv run python -m engineer.tts "Norris is closing, 0.7 a lap." --voice kokoro:bm_daniel --out call.wav
"""
import argparse
import os
import queue
import threading
import time

from . import log, usage
from .spoken import speakable

_log = log.get("tts")

STYLE = "Calm, clipped British male Formula 1 race engineer speaking over the radio."
# name -> (repo, default voice, fn(model, text, voice) -> results with .audio)
ENGINES = {
    "kokoro": ("mlx-community/Kokoro-82M-bf16", "bm_george",
               lambda m, t, v: m.generate(text=t, voice=v, speed=1.0, lang_code=v[0])),
    "soprano": ("mlx-community/Soprano-1.1-80M-bf16", None, lambda m, t, v: m.generate(text=t)),
    "kitten": ("mlx-community/kitten-tts-mini-0.8", "expr-voice-5-m", lambda m, t, v: m.generate(text=t, voice=v)),
    "qwen3": ("mlx-community/Qwen3-TTS-12Hz-0.6B-CustomVoice-8bit", "ryan",
              lambda m, t, v: m.generate_custom_voice(text=t, speaker=v, language="English", instruct=STYLE)),
}
DEFAULT_VOICE = "kokoro:bm_george"
BLOCK = 0.05  # s per write to the sound card: how quickly a stop takes effect
BAND = (300, 3400)  # the radio filter


def parse_voice(spec):
    name, _, voice = (spec or DEFAULT_VOICE).partition(":")
    if name not in ENGINES:
        raise ValueError(f"unknown voice engine {name!r}, have {', '.join(ENGINES)}")
    return name, voice or ENGINES[name][1]


def use_homebrew_espeak():
    """misaki's bundled espeak-ng has a CI build path baked in and dies on startup; Homebrew's works."""
    lib, data = "/opt/homebrew/lib/libespeak-ng.dylib", "/opt/homebrew/share/espeak-ng-data"
    if not (os.path.exists(lib) and os.path.isdir(data)):
        return
    import espeakng_loader

    espeakng_loader.get_library_path = lambda: lib
    espeakng_loader.get_data_path = lambda: data
    os.environ.setdefault("PHONEMIZER_ESPEAK_LIBRARY", lib)
    os.environ.setdefault("ESPEAK_DATA_PATH", data)


def radio_filter(audio, rate):
    """Telephone band and a little grit, so it sounds like it's coming down a radio."""
    import numpy as np

    spec = np.fft.rfft(audio)
    freqs = np.fft.rfftfreq(len(audio), 1 / rate)
    spec[(freqs < BAND[0]) | (freqs > BAND[1])] = 0
    out = np.fft.irfft(spec, len(audio))
    return np.tanh(2.0 * out / (np.abs(out).max() or 1)).astype(np.float32) * 0.8


class Voice:
    """Loads one engine and renders text to float32 mono audio; call from a single thread."""

    def __init__(self, spec=None, fx=False):
        self.name, self.voice = parse_voice(spec)
        self.fx = fx
        self._model = None

    def load(self):
        from mlx_audio.tts.utils import load_model

        t = time.perf_counter()
        if self.name == "kokoro":
            use_homebrew_espeak()
        self._model = load_model(ENGINES[self.name][0])
        loaded = time.perf_counter() - t
        list(self.render("Radio check."))  # first call pays for the phonemizer and graph; do it now
        _log.info("voice ready", engine=self.name, voice=self.voice, load_s=round(loaded, 2),
                  warmup_s=round(time.perf_counter() - t - loaded, 2))

    def render(self, text):
        """Yields (audio, rate) per segment as the engine produces them."""
        import numpy as np

        for r in ENGINES[self.name][2](self._model, speakable(text), self.voice):
            audio = np.array(r.audio, dtype=np.float32).reshape(-1)
            rate = getattr(r, "sample_rate", 24000)
            yield (radio_filter(audio, rate) if self.fx else audio), rate


class Speaker:
    """Queue of things to say. `say` never blocks; `stop` cuts what's playing and what's waiting."""

    def __init__(self, hub, spec=None, fx=False, device=None, at=lambda: usage.NOWHERE):
        self.hub, self.device, self.at = hub, device, at
        self.voice = Voice(spec, fx)
        self.state = "loading"
        self.error = None
        self._text = queue.Queue()
        self._audio = queue.Queue(maxsize=4)
        self._cut = 0.0       # anything asked for before this has been cancelled
        self._gen = 0         # bumps on stop so playback notices mid-utterance
        self._pending = 0     # items asked for and not yet finished playing
        self._lock = threading.Lock()

    def start(self):
        threading.Thread(target=self._synth, name="tts", daemon=True).start()
        threading.Thread(target=self._play, name="tts-play", daemon=True).start()

    def say(self, text, at=None):
        """`at` is when the text was asked for (wall clock); dropped if the driver cut in after that."""
        if not text or (at or time.time()) < self._cut:
            return
        with self._lock:
            self._pending += 1
        self._text.put((text, self._gen))

    def stop(self):
        if self._pending:
            usage.metric("cut_off", 1, self.at())  # keyed the radio over the engineer
        with self._lock:
            self._cut, self._gen = time.time(), self._gen + 1
        for q in (self._text, self._audio):
            while True:
                try:
                    q.get_nowait()
                except queue.Empty:
                    break
        with self._lock:
            self._pending = 0
        self._set("ready")

    def busy(self):
        return self._pending > 0

    def _set(self, state, **extra):
        self.state = state
        self.hub.publish("speech", {"state": state, **extra})

    def _synth(self):
        try:
            self.voice.load()
        except Exception as e:
            self.error = str(e)
            _log.error("voice failed to load", engine=self.voice.name, error=str(e))
            return self._set("error", error=self.error)
        self._set("ready")
        while True:
            text, gen = self._text.get()
            t = time.perf_counter()
            try:
                for i, (audio, rate) in enumerate(self.voice.render(text)):
                    if i == 0:
                        usage.metric("tts_ms", round((time.perf_counter() - t) * 1000), self.at(), chars=len(text))
                    if gen != self._gen:
                        break
                    self._audio.put((audio, rate, gen))
            except Exception as e:  # one bad line shouldn't silence the engineer
                _log.error("synthesis failed", text=text, error=str(e))
            self._audio.put((None, 0, gen))  # end of this item

    def _play(self):
        import sounddevice as sd

        while True:
            audio, rate, gen = self._audio.get()
            if audio is None:
                with self._lock:
                    self._pending = max(0, self._pending - 1) if gen == self._gen else self._pending
                if self._pending == 0 and self.state == "speaking":
                    self._set("ready")
                continue
            if gen != self._gen:
                continue
            self._set("speaking")
            try:
                with sd.OutputStream(samplerate=rate, channels=1, dtype="float32", device=self.device) as out:
                    step = int(rate * BLOCK)
                    for i in range(0, len(audio), step):
                        if gen != self._gen:
                            break
                        out.write(audio[i:i + step].reshape(-1, 1))
            except Exception as e:
                _log.error("playback failed", error=str(e))


def main():
    ap = argparse.ArgumentParser(description="render a line to a wav (no playback)")
    ap.add_argument("text")
    ap.add_argument("--voice", default=DEFAULT_VOICE, help="engine[:voice], e.g. kokoro:bm_daniel")
    ap.add_argument("--fx", action="store_true", help="radio filter")
    ap.add_argument("--out", default="say.wav")
    args = ap.parse_args()
    import numpy as np
    import soundfile as sf

    voice = Voice(args.voice, args.fx)
    voice.load()
    t = time.perf_counter()
    parts = list(voice.render(args.text))
    audio, rate = np.concatenate([a for a, _ in parts]), parts[0][1]
    sf.write(args.out, audio, rate)
    print(f"{len(audio) / rate:.1f}s of audio in {time.perf_counter() - t:.2f}s -> {args.out}")
    print(f"said: {speakable(args.text)}")


if __name__ == "__main__":
    main()
