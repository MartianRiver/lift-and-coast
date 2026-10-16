import json
import logging
import os
import time
import traceback
from collections import deque

TRACE = 5
logging.addLevelName(TRACE, "TRACE")

# dev: DEBUG+, prod: WARN+. RE_LOG_LEVEL overrides either.
_default = "WARNING" if os.environ.get("RE_ENV") == "prod" else "DEBUG"
LEVEL = logging.getLevelName(os.environ.get("RE_LOG_LEVEL", _default).upper())
if not isinstance(LEVEL, int):
    LEVEL = logging.DEBUG

ring = deque(maxlen=2000)


class _RingHandler(logging.Handler):
    def emit(self, record):
        ring.append({
            "t": record.created,
            "level": record.levelname,
            "module": getattr(record, "mod", record.name),
            "msg": record.getMessage(),
            "data": getattr(record, "data", None) or None,
            "exc": "".join(traceback.format_exception(*record.exc_info)) if record.exc_info else None,
        })


class _Formatter(logging.Formatter):
    def format(self, record):
        line = f"[{record.levelname}] [{getattr(record, 'mod', record.name)}] {record.getMessage()}"
        data = getattr(record, "data", None)
        if data:
            line += " " + json.dumps(data, default=str)
        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)
        return time.strftime("%H:%M:%S ") + line


_root = logging.getLogger("re")
_root.setLevel(LEVEL)
_root.propagate = False
for h in (logging.StreamHandler(), _RingHandler()):
    h.setFormatter(_Formatter())
    _root.addHandler(h)


class Log:
    def __init__(self, module):
        self.module = module
        self._log = logging.getLogger(f"re.{module}")

    def _emit(self, level, msg, exc=False, **data):
        if self._log.isEnabledFor(level):
            self._log.log(level, msg, exc_info=exc, extra={"mod": self.module, "data": data})

    def trace(self, msg, **data):
        self._emit(TRACE, msg, **data)

    def debug(self, msg, **data):
        self._emit(logging.DEBUG, msg, **data)

    def info(self, msg, **data):
        self._emit(logging.INFO, msg, **data)

    def warn(self, msg, **data):
        self._emit(logging.WARNING, msg, **data)

    def error(self, msg, exc=True, **data):
        self._emit(logging.ERROR, msg, exc=exc, **data)


def get(module):
    return Log(module)
