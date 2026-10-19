"""Raw datagram capture and replay.

File format: b"F1CAP1\\n" then repeated (float64 seconds-since-start, uint16 length, bytes), optionally
xz-compressed (.f1cap.xz, ~9x smaller). Recording raw bytes means a session can be re-parsed after
the decoder changes. Recording itself is per session: see recorder.py.

    uv run python -m engineer.capture replay captures/<file>.f1cap [--speed 2] [--loop] [--start S] [--until S]

--start/--until are seconds into the capture: replay one session, or stop at a moment and leave
the server's state frozen there (e.g. to ask the engineer questions mid-race). Button events are
dropped unless --buttons: replaying the driver's radio presses opens the live mic on the room.
"""
import argparse
import lzma
import socket
import struct
import time
from pathlib import Path

from . import log

_log = log.get("capture")

MAGIC = b"F1CAP1\n"
_REC = struct.Struct("<dH")


class Writer:
    def __init__(self, path):
        self.path = Path(path)
        self._f = open(self.path, "wb")
        self._f.write(MAGIC)
        self._t0 = time.monotonic()
        self.wall0 = time.time()  # where t=0 is on the wall clock: lines the radio up with the packets
        self.count = 0
        _log.info("recording", path=str(self.path))

    def write(self, buf):
        self._f.write(_REC.pack(time.monotonic() - self._t0, len(buf)))
        self._f.write(buf)
        self.count += 1
        if self.count % 2000 == 0:
            self._f.flush()

    def move(self, path):
        # Windows won't rename a file that's open
        self._f.close()
        self.path = self.path.rename(path)
        self._f = open(self.path, "ab")

    def close(self):
        self._f.close()
        _log.info("recording closed", path=str(self.path), packets=self.count)


def read(path):
    """(seconds, datagram) pairs from a .f1cap or a compressed .f1cap.xz."""
    opener = lzma.open if str(path).endswith(".xz") else open
    with opener(path, "rb") as f:
        magic = f.read(len(MAGIC))
        if not magic:
            return  # server stopped before anything was flushed
        if magic != MAGIC:
            raise ValueError(f"{path} is not an f1cap file")
        while len(head := f.read(_REC.size)) == _REC.size:
            t, n = _REC.unpack(head)
            buf = f.read(n)
            if len(buf) < n:
                break  # truncated tail from an unclean shutdown
            yield t, buf


def write(path, records):
    """(seconds, datagram) pairs to a new .f1cap, or a .f1cap.xz compressed as the archive does. -> how many."""
    n = 0
    with (lzma.open(path, "wb", preset=1) if str(path).endswith(".xz") else open(path, "wb")) as f:
        f.write(MAGIC)
        for t, buf in records:
            f.write(_REC.pack(t, len(buf)))
            f.write(buf)
            n += 1
    return n


def _is_buttons(buf):
    # header is 29 bytes with packetId at offset 6; the event code follows the header
    return len(buf) > 33 and buf[6] == 3 and buf[29:33] == b"BUTN"


def replay(path, host, port, speed, loop, start=0.0, until=None, buttons=False):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    while True:
        began = time.monotonic()
        sent = 0
        first = None
        for t, buf in read(path):
            if t < start:
                continue
            if until is not None and t > until:
                break
            if not buttons and _is_buttons(buf):
                continue
            first = t if first is None else first  # skip idle time before the game started sending
            wait = (t - first) / speed - (time.monotonic() - began)
            if wait > 0:
                time.sleep(wait)
            sock.sendto(buf, (host, port))
            sent += 1
        _log.info("replay finished", path=str(path), packets=sent)
        if not loop:
            break


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    rp = sub.add_parser("replay")
    rp.add_argument("file")
    rp.add_argument("--host", default="127.0.0.1")
    rp.add_argument("--port", type=int, default=20777)
    rp.add_argument("--speed", type=float, default=1.0)
    rp.add_argument("--loop", action="store_true")
    rp.add_argument("--start", type=float, default=0.0, help="seconds into the capture to start from")
    rp.add_argument("--until", type=float, help="seconds into the capture to stop at")
    rp.add_argument("--buttons", action="store_true", help="also replay button events (opens the radio!)")
    args = ap.parse_args()
    replay(args.file, args.host, args.port, args.speed, args.loop, args.start, args.until, args.buttons)


if __name__ == "__main__":
    main()
