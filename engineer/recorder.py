"""Records every session to its own file, then hands it to the archive.

A new sessionUID opens a new file in captures/sessions/, stamped with the time; the first session
packet renames it to say where and what (2026-10-13_180121_Austria_P3.f1cap). When the session
changes or the server stops, the file is catalogued and compressed in the background. Packets with
no session (menus) are dropped. If the game goes quiet (saved and quit, console off) the file is
closed and archived after IDLE_CLOSE seconds; the same session resuming opens a second part.
"""
import struct
import threading
import time

from . import archive, log, radiolog
from .capture import Writer
from .decode import decode

_log = log.get("recorder")

_UID = struct.Struct("<Q")
IDLE_CLOSE = 120


class SessionRecorder:
    def __init__(self, folder=archive.SESSIONS):
        self.folder = folder
        self.folder.mkdir(parents=True, exist_ok=True)
        self.writer = None
        self.uid = None
        self.started = None
        self.named = False
        self.last_write = 0.0
        self.stopped = False
        self._lock = threading.RLock()  # the server's stop closes the file while the UDP thread may be writing
        archive.sweep(self.folder)  # anything a crashed or killed server left raw

    @property
    def path(self):
        return self.writer.path if self.writer else None

    def write(self, buf):
        if len(buf) < 29:
            return
        with self._lock:
            if self.stopped:
                return
            uid = _UID.unpack_from(buf, 7)[0]
            if uid and (uid != self.uid or not self.writer):
                self._open(uid)
            if not self.writer:
                return
            self.writer.write(buf)
            self.last_write = time.time()
            if not self.named and buf[6] == 1:
                self._name(buf)

    def idle(self):
        if self.writer and time.time() - self.last_write > IDLE_CLOSE:
            _log.info("game went quiet, archiving the session", path=str(self.writer.path), quiet_s=IDLE_CLOSE)
            self.close()

    def _open(self, uid):
        self.close()
        self.uid, self.started, self.named = uid, time.time(), False
        self.writer = Writer(archive.unique(self.folder / f"{archive.label(self.started, None)}.f1cap"))
        radiolog.record("recording", {"uid": str(uid), "started": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.started)),
                                      "wall0": self.writer.wall0})

    def _name(self, buf):
        try:
            _, session = decode(buf)
        except Exception as e:  # keep recording under the timestamp name
            self.named = True
            return _log.warn("couldn't name the session file", error=str(e))
        new = archive.unique(self.folder / f"{archive.label(self.started, session)}.f1cap")
        self.writer.move(new)
        self.named = True
        _log.info("session file", path=str(new), uid=str(self.uid))

    def close(self, wait=False):
        """wait: archive now (server shutdown, where the background worker would die with the process)."""
        with self._lock:
            self.stopped = self.stopped or wait  # shutting down: nothing after this is recorded
            if not self.writer:
                return
            writer, self.writer = self.writer, None
            writer.close()
            started = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.started))
        if wait:
            _log.info("archiving the session file before exit", path=str(writer.path))
            archive.finish(writer.path, started)
        else:
            archive.finish_later(writer.path, started)
