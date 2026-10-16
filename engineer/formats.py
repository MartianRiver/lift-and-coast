"""The older UDP formats, F1 25's 2025 and F1 24's 2024, as edits to the 2026 layouts.

Same header since F1 23, so `packetFormat` picks the layout. Differences come from
diffing EA's struct files for each year (sizes checked against each spec's "Size:" line).
Everything is widened back to the 2026 shape after decoding.
"""
from .codec import F, Str, Struct
from .spec import EVENT_DETAILS, MAX_CARS, PACKETS

# fields 2026 added or changed; edits apply by name in every struct
_2025 = {
    "cars": 22,
    "types": {"gForceLateral": "f", "gForceLongitudinal": "f", "gForceVertical": "f",
              "driverId": "B", "networkId": "B", "teamId": "B", "engineTemperature": "H"},
    "drop": {"activeAeroTrackStatus", "numActiveAeroZonesFull", "activeAeroZonesFull",
             "numActiveAeroZonesPartial", "activeAeroZonesPartial", "numDRSZones", "drsZones",
             "startReactionTime", "antiLockBrakesAssist", "tractionControlAssist",
             "dynamicRacingLineHiVis", "dynamicRacingLineColourBlind", "recurringRewindPrompt",
             "ersHarvestedLimitPerLap", "severity"},
    "packets": set(range(16)),
}

# and what F1 25 added over F1 24
_2024 = {
    "cars": 22,
    "types": {**_2025["types"], "name": Str(48)},
    "drop": _2025["drop"] | {"numColours", "liveryColours", "resultReason", "tyreBlisters",
                             "chassisPitch", "wheelCamber", "wheelCamberGain", "reason", "stopTime"},
    "packets": set(range(15)),
}


def _edit(t, edits, cache):
    if id(t) in cache:
        return cache[id(t)]
    fields = []
    for f in t.fields:
        if f.name in edits["drop"]:
            continue
        kind = edits["types"].get(f.name, f.type)
        if isinstance(kind, Struct):
            kind = _edit(kind, edits, cache)
        n = edits["cars"] if f.n == MAX_CARS else f.n
        scale = None if kind != f.type else f.scale  # 2026 packs g-forces as scaled int16
        fields.append(F(f.name, kind, n, scale))
    cache[id(t)] = Struct(t.name, fields)
    return cache[id(t)]


def _layouts(edits):
    cache = {}
    packets = {pid: _edit(t, edits, cache) for pid, t in PACKETS.items() if pid in edits["packets"]}
    events = {code: _edit(t, edits, {}) for code, t in EVENT_DETAILS.items()}
    return packets, events


LAYOUTS = {2026: (PACKETS, EVENT_DETAILS), 2025: _layouts(_2025), 2024: _layouts(_2024)}
GAMES = {2026: "2026 (F1 25)", 2025: "2025 (F1 25)", 2024: "2024 (F1 24)"}

# "Size:" line under each packet in that year's spec
SPEC_SIZES = {
    2025: {0: 1349, 1: 753, 2: 1285, 3: 45, 4: 1284, 5: 1133, 6: 1352, 7: 1239, 8: 1042,
           9: 954, 10: 1041, 11: 1460, 12: 231, 13: 273, 14: 101, 15: 1131},
    2024: {0: 1349, 1: 753, 2: 1285, 3: 45, 4: 1350, 5: 1133, 6: 1352, 7: 1239, 8: 1020,
           9: 1306, 10: 953, 11: 1460, 12: 231, 13: 237, 14: 101},
}
