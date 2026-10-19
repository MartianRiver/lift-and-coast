import json
import logging
import os
import sys
import threading
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
    def __init__(self, when="%H:%M:%S "):
        super().__init__()
        self.when = when

    def format(self, record):
        line = f"[{record.levelname}] [{getattr(record, 'mod', record.name)}] {record.getMessage()}"
        data = getattr(record, "data", None)
        if data:
            line += " " + json.dumps(data, default=str)
        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)
        return time.strftime(self.when, time.localtime(record.created)) + line


_root = logging.getLogger("re")
_root.setLevel(LEVEL)
_root.propagate = False
for h in (logging.StreamHandler(), _RingHandler()):
    h.setFormatter(_Formatter())
    h.setLevel(LEVEL)
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


def to_file(folder):
    """INFO+ into folder/<start>.log for this run, whatever the console shows, plus uncaught errors and threads that die."""
    folder.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(folder / time.strftime("%Y%m%d-%H%M%S.log"), encoding="utf-8")
    handler.setFormatter(_Formatter("%Y-%m-%d %H:%M:%S "))
    handler.setLevel(logging.INFO)
    _root.addHandler(handler)
    _root.setLevel(min(LEVEL, logging.INFO))
    crashed = get("crash")

    def uncaught(kind, e, tb):
        if issubclass(kind, KeyboardInterrupt):
            return sys.__excepthook__(kind, e, tb)
        crashed.error("uncaught", exc=(kind, e, tb))

    def thread_died(a):
        if issubclass(a.exc_type, SystemExit):  # as threading's own hook: a thread may exit this way
            return
        crashed.error("thread died", exc=(a.exc_type, a.exc_value, a.exc_traceback), thread=a.thread and a.thread.name)
    sys.excepthook, threading.excepthook = uncaught, thread_died
    return handler
