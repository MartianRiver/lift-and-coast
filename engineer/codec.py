"""Declarative little-endian packed structs.

Each Struct compiles to a single struct format, so a whole packet decodes
with one unpack_from call and the flat tuple is rebuilt into nested dicts.
"""
import struct
from itertools import islice


class Str:
    def __init__(self, size):
        self.size = size


class F:
    __slots__ = ("name", "type", "n", "scale")

    def __init__(self, name, type, n=None, scale=None):
        self.name, self.type, self.n, self.scale = name, type, n, scale


class Struct:
    def __init__(self, name, fields):
        self.name = name
        self.fields = fields
        self.fmt = "".join(_field_fmt(f) for f in fields)
        self._s = struct.Struct("<" + self.fmt)
        self.size = self._s.size

    def unpack(self, buf, offset=0):
        return _read(self, iter(self._s.unpack_from(buf, offset)))

    def pack(self, value):
        out = []
        _write_one(self, value, None, out)
        return self._s.pack(*out)

    def blank(self):
        return _blank_one(self)


def _type_fmt(t):
    if isinstance(t, str):
        return t
    if isinstance(t, Str):
        return f"{t.size}s"
    return t.fmt


def _field_fmt(f):
    one = _type_fmt(f.type)
    if f.n is None:
        return one
    if isinstance(f.type, str):
        return f"{f.n}{one}"
    return one * f.n


def _read(t, it):
    if isinstance(t, str):
        return next(it)
    if isinstance(t, Str):
        return next(it).split(b"\0", 1)[0].decode("utf-8", "replace")
    return {f.name: _read_field(f, it) for f in t.fields}


def _read_field(f, it):
    if f.n is None:
        v = _read(f.type, it)
        return v / f.scale if f.scale else v
    if isinstance(f.type, str):
        vals = list(islice(it, f.n))
        return [v / f.scale for v in vals] if f.scale else vals
    return [_read(f.type, it) for _ in range(f.n)]


def _write_one(t, v, scale, out):
    if isinstance(t, str):
        if t.endswith("s"):  # raw bytes, e.g. the event details union
            out.append(v)
            return
        if scale:
            v = v * scale
        out.append(float(v) if t in "fd" else int(round(v)))
    elif isinstance(t, Str):
        out.append(v.encode()[: t.size])
    else:
        for f in t.fields:
            _write_field(f, v[f.name], out)


def _write_field(f, v, out):
    if f.n is None:
        _write_one(f.type, v, f.scale, out)
    else:
        for item in v:
            _write_one(f.type, item, f.scale, out)


def _blank_one(t):
    if isinstance(t, str):
        return b"" if t.endswith("s") else 0.0 if t in "fd" else 0
    if isinstance(t, Str):
        return ""
    return {f.name: _blank_field(f) for f in t.fields}


def _blank_field(f):
    if f.n is None:
        return _blank_one(f.type)
    return [_blank_one(f.type) for _ in range(f.n)]




def widen(t, value, n_cars):
    """Bring a dict decoded with an older layout up to `t`'s shape: fields that format
    doesn't send become None ([] for arrays of structs), per-car arrays are padded with
    blank (inactive) cars up to `n_cars`."""
    for f in t.fields:
        if f.name not in value:
            value[f.name] = [] if f.n is not None and isinstance(f.type, Struct) else None
            continue
        v = value[f.name]
        if isinstance(f.type, Struct):
            for item in (v if f.n is not None else [v]):
                widen(f.type, item, n_cars)
        if f.n == n_cars and len(v) < n_cars:
            v.extend(_blank_one(f.type) for _ in range(n_cars - len(v)))
    return value
