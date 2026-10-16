import struct
import unittest

from engineer.codec import Struct
from engineer.decode import DecodeError, WrongFormat, decode
from engineer.formats import LAYOUTS, SPEC_SIZES as OLD_SIZES
from engineer.spec import EVENT_DETAILS, EVENT_DETAILS_SIZE, HEADER, PACKETS, SPEC_SIZES


def _packet(pid, fmt=2026, **fields):
    layout = LAYOUTS[fmt][0][pid]
    data = layout.blank()
    data["header"].update(packetFormat=fmt, gameYear=25, packetId=pid, sessionUID=2**63 + 7)
    data.update(fields)
    return layout, data


class Sizes(unittest.TestCase):
    def test_every_layout_matches_spec_size(self):
        self.assertEqual(HEADER.size, 29)
        for pid, layout in PACKETS.items():
            self.assertEqual(layout.size, SPEC_SIZES[pid], layout.name)
        for fmt, sizes in OLD_SIZES.items():
            self.assertEqual({pid: t.size for pid, t in LAYOUTS[fmt][0].items()}, sizes, fmt)

    def test_event_details_fit_union(self):
        for code, s in EVENT_DETAILS.items():
            self.assertLessEqual(s.size, EVENT_DETAILS_SIZE, code)


class RoundTrip(unittest.TestCase):
    def test_blank_packets_decode(self):
        for pid in PACKETS:
            layout, data = _packet(pid)
            if pid == 3:
                data["eventStringCode"] = "SSTA"
                data["eventDetails"] = bytes(EVENT_DETAILS_SIZE)
            got_pid, got = decode(layout.pack(data))
            self.assertEqual(got_pid, pid)
            self.assertEqual(got["header"]["sessionUID"], 2**63 + 7)

    def test_nested_values_and_offsets(self):
        layout, data = _packet(2)
        data["lapData"][23]["speedTrapFastestLap"] = 42
        data["lapData"][5]["lastLapTimeInMS"] = 91234
        data["timeTrialRivalCarIdx"] = 9
        _, got = decode(layout.pack(data))
        self.assertEqual(got["lapData"][23]["speedTrapFastestLap"], 42)
        self.assertEqual(got["lapData"][5]["lastLapTimeInMS"], 91234)
        self.assertEqual(got["timeTrialRivalCarIdx"], 9)

    def test_scaled_and_string_fields(self):
        layout, data = _packet(0)
        data["carMotionData"][3]["gForceLateral"] = -3.25
        _, got = decode(layout.pack(data))
        self.assertAlmostEqual(got["carMotionData"][3]["gForceLateral"], -3.25)

        layout, data = _packet(4)
        data["participants"][1]["name"] = "VERSTAPPEN"
        data["participants"][1]["teamId"] = 478
        _, got = decode(layout.pack(data))
        self.assertEqual(got["participants"][1]["name"], "VERSTAPPEN")
        self.assertEqual(got["participants"][1]["teamId"], 478)

    def test_event_union(self):
        layout, data = _packet(3)
        data["eventStringCode"] = "FTLP"
        data["eventDetails"] = struct.pack("<Bf", 4, 88.5).ljust(EVENT_DETAILS_SIZE, b"\0")
        _, got = decode(layout.pack(data))
        self.assertEqual(got["eventDetails"], {"vehicleIdx": 4, "lapTime": 88.5})


class OlderFormats(unittest.TestCase):
    """F1 24 / F1 25 packets come out in the 2026 shape: 24 car slots, unsent fields None."""

    def test_widened_to_2026_shape(self):
        for fmt in (2024, 2025):
            for pid, layout in LAYOUTS[fmt][0].items():
                _, data = _packet(pid, fmt)
                if pid == 3:
                    data["eventStringCode"] = "SSTA"
                    data["eventDetails"] = bytes(EVENT_DETAILS_SIZE)
                _, got = decode(layout.pack(data))
                _covers(self, PACKETS[pid], got, (fmt, pid))

    def test_values_survive_and_missing_fields_are_none(self):
        layout, data = _packet(2, 2025)
        data["lapData"][21]["carPosition"] = 22
        _, got = decode(layout.pack(data))
        self.assertEqual(len(got["lapData"]), 24)
        self.assertEqual(got["lapData"][21]["carPosition"], 22)
        self.assertEqual(got["lapData"][23]["resultStatus"], 0)

        layout, data = _packet(0, 2025)
        data["carMotionData"][3]["gForceLateral"] = -3.25
        _, got = decode(layout.pack(data))
        self.assertAlmostEqual(got["carMotionData"][3]["gForceLateral"], -3.25)

        layout, data = _packet(4, 2024)
        data["participants"][1].update(name="A" * 40, teamId=7)
        _, got = decode(layout.pack(data))
        self.assertEqual(got["participants"][1]["name"], "A" * 40)
        self.assertEqual(got["participants"][1]["teamId"], 7)
        self.assertEqual(got["participants"][1]["liveryColours"], [])
        self.assertIsNone(got["participants"][1]["numColours"])
        self.assertEqual(got["participants"][23]["numColours"], 0)  # padded slot

        layout, data = _packet(1, 2025)
        _, got = decode(layout.pack(data))
        self.assertEqual(got["drsZones"], [])
        self.assertIsNone(got["numDRSZones"])

    def test_event_details(self):
        layout, data = _packet(3, 2024)
        data["eventStringCode"] = "RTMT"
        data["eventDetails"] = bytes([5]).ljust(EVENT_DETAILS_SIZE, b"\0")
        _, got = decode(layout.pack(data))
        self.assertEqual(got["eventDetails"], {"vehicleIdx": 5, "reason": None})


def _covers(test, t, value, where):
    """Every 2026 field is there; arrays it does send have the 2026 length."""
    for f in t.fields:
        test.assertIn(f.name, value, where)
        v = value[f.name]
        if f.n is not None and v:
            test.assertEqual(len(v), f.n, (where, f.name))
        if isinstance(f.type, Struct) and v:
            for item in (v if f.n is not None else [v]):
                _covers(test, f.type, item, where)


class Rejects(unittest.TestCase):
    def test_wrong_format(self):
        layout, data = _packet(2)
        data["header"]["packetFormat"] = 2023
        with self.assertRaises(WrongFormat):
            decode(layout.pack(data))

    def test_wrong_size(self):
        layout, data = _packet(2)
        with self.assertRaises(DecodeError):
            decode(layout.pack(data)[:-1])


if __name__ == "__main__":
    unittest.main()
