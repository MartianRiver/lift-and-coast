from .codec import widen
from .formats import LAYOUTS
from .spec import EVENT_DETAILS, FORMAT, HEADER, MAX_CARS, PACKETS


class DecodeError(Exception):
    pass


class WrongFormat(DecodeError):
    def __init__(self, fmt):
        super().__init__(f"packet format {fmt}, expected one of {sorted(LAYOUTS)}")
        self.fmt = fmt


def decode(buf):
    """bytes -> (packet_id, dict), always in the 2026 shape whatever format the game sends.
    Raises DecodeError on anything we can't trust."""
    if len(buf) < HEADER.size:
        raise DecodeError(f"short datagram ({len(buf)} bytes)")
    header = HEADER.unpack(buf)
    fmt = header["packetFormat"]
    if fmt not in LAYOUTS:
        raise WrongFormat(fmt)
    packets, events = LAYOUTS[fmt]

    pid = header["packetId"]
    layout = packets.get(pid)
    if layout is None:
        raise DecodeError(f"unknown packet id {pid} ({len(buf)} bytes)")
    if len(buf) != layout.size:
        raise DecodeError(f"packet {pid} is {len(buf)} bytes, format {fmt} says {layout.size}")

    data = layout.unpack(buf)
    if fmt != FORMAT:
        widen(PACKETS[pid], data, MAX_CARS)
    if pid == 3:
        code = data["eventStringCode"]
        detail = events.get(code)
        data["eventDetails"] = detail.unpack(data["eventDetails"]) if detail else None
        if detail and fmt != FORMAT:
            widen(EVENT_DETAILS[code], data["eventDetails"], MAX_CARS)
    return pid, data
