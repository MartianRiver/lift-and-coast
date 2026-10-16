"""Race log: flashbacks must undo warnings like the game does, and re-sent events must not double up."""
import unittest

from engineer.incidents import Incidents, summary


def car(**kw):
    c = dict(currentLapNum=5, lapDistance=1000.0, carPosition=1, pitStatus=0, resultStatus=2,
             cornerCuttingWarnings=0, totalWarnings=0, penalties=0,
             numUnservedDriveThroughPens=0, numUnservedStopGoPens=0)
    c.update(kw)
    return c


def lap_pkt(t, me=None, other=None):
    return {"header": {"playerCarIndex": 0, "sessionTime": t},
            "lapData": [me or car(), other or car(carPosition=2)] + [car(resultStatus=0)] * 20}


def event(t, code, **details):
    return {"sessionTime": t, "code": code, "details": details}


class Warnings(unittest.TestCase):
    def test_flashback_takes_the_warning_back(self):
        inc = Incidents()
        inc.on_lap_data(lap_pkt(10))
        inc.on_lap_data(lap_pkt(11, car(cornerCuttingWarnings=1, totalWarnings=1, lapDistance=3950.0)))
        self.assertEqual([(e["kind"], e["dist"]) for e in inc.log], [("limits", 3950)])

        inc.on_event(event(12, "FLBK", flashbackSessionTime=9.0), lap_pkt(12))
        inc.on_lap_data(lap_pkt(9.1))  # counters back to 0: nothing recorded
        self.assertEqual(inc.log, [])

        inc.on_lap_data(lap_pkt(14, car(cornerCuttingWarnings=1, totalWarnings=1, lapDistance=3940.0)))
        self.assertEqual([e["dist"] for e in inc.log], [3940])

    def test_summary_counts_from_the_game_and_warns_before_the_penalty(self):
        inc = Incidents()
        inc.on_lap_data(lap_pkt(10))
        inc.on_lap_data(lap_pkt(11, car(cornerCuttingWarnings=1, totalWarnings=1)))
        inc.on_lap_data(lap_pkt(12, car(cornerCuttingWarnings=2, totalWarnings=2)))
        text = "\n".join(summary(inc, car(cornerCuttingWarnings=2, totalWarnings=2, penalties=3),
                                 lambda i: f"CAR{i}", 4361))
        self.assertIn("2 warnings (L5 at 1000 m, L5 at 1000 m of 4361 m) · one more is a time penalty", text)
        self.assertIn("3 s time penalty to come", text)


class Field(unittest.TestCase):
    def test_retirement_resent_after_flashback_is_logged_once(self):
        inc = Incidents()
        inc.on_event(event(100, "RTMT", vehicleIdx=1, reason=3), lap_pkt(100))
        inc.on_event(event(200, "FLBK", flashbackSessionTime=150.0), lap_pkt(200))
        inc.on_event(event(150.1, "RTMT", vehicleIdx=1, reason=3), lap_pkt(150.1))
        self.assertEqual(len([e for e in inc.log if e["kind"] == "out"]), 1)

    def test_pit_stop_records_where_the_car_came_out(self):
        inc = Incidents()
        inc.on_lap_data(lap_pkt(10, other=car(carPosition=3)))
        inc.on_lap_data(lap_pkt(11, other=car(carPosition=3, pitStatus=1)))
        inc.on_lap_data(lap_pkt(30, other=car(carPosition=9, pitStatus=0)))
        self.assertEqual([(e["before"], e["after"]) for e in inc.log], [(3, 9)])

    def test_car_already_in_the_pit_lane_is_not_a_stop(self):
        inc = Incidents()
        inc.on_lap_data(lap_pkt(10, other=car(pitStatus=1)))
        inc.on_lap_data(lap_pkt(11, other=car(pitStatus=1)))
        self.assertEqual(inc.log, [])


if __name__ == "__main__":
    unittest.main()
