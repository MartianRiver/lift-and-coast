"""Local speech-to-text: parakeet-tdt 0.6B on MLX.

Measured on an M3 MacBook Air: 5.7s load, ~3s first transcription (graph warmup), then
~200-260ms for 3-5s of speech. Driver names are the weak spot ("Leclerc" -> "look like").
"""
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from . import log

_log = log.get("stt")

MODEL = "mlx-community/parakeet-tdt-0.6b-v3"
SAMPLE_RATE = 16_000

# MLX binds its Metal stream to the thread that loaded the weights; calling from any other
# thread raises "no Stream in current thread". One worker, every call.
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="stt")


class STT:
    def __init__(self):
        self._model = None

    def load(self):
        return _executor.submit(self._load)

    def transcribe(self, audio):
        return _executor.submit(self._run, audio)

    def _load(self):
        t = time.perf_counter()
        from parakeet_mlx import from_pretrained

        self._model = from_pretrained(MODEL)
        loaded = time.perf_counter() - t
        # first call compiles the graph; pay it now rather than on the first radio message
        rng = np.random.default_rng(0)
        self._run(rng.normal(0, 0.05, SAMPLE_RATE * 2).astype(np.float32))
        _log.info("model ready", model=MODEL, load_s=round(loaded, 2),
                  warmup_s=round(time.perf_counter() - t - loaded, 2))

    def _run(self, audio):
        import mlx.core as mx
        from parakeet_mlx.audio import get_logmel

        # must be float32: get_logmel views the complex STFT as the input dtype (bf16 doubles its width)
        mel = get_logmel(mx.array(audio, dtype=mx.float32), self._model.preprocessor_config)
        return self._model.generate(mel)[0].text.strip()
