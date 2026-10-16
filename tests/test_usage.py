"""Cost and timings: every call lands in the archive and adds up per session, and the report reads it back."""
import unittest

from engineer import diagnostics, usage
from engineer.state import RaceState
from tests.test_brief import Hub


class Usage(unittest.TestCase):
    def setUp(self):
        self.st = RaceState(Hub())
        self.st.session_uid = 4242
        self.st.latest[1] = {"sessionType": 15, "trackId": 10}
        self.at = usage.where(self.st)

    def test_where(self):
        self.assertEqual(self.at, ("4242", "Race", "Spa"))
        self.assertEqual(usage.where(RaceState(Hub())), usage.NOWHERE)

    def test_spend_adds_up_per_session_and_off_session_is_kept_apart(self):
        usage.llm("engineer", "kimi", {"cost": 0.01, "firstMs": 900, "provider": "x"}, self.at, "question")
        usage.llm("engineer", "kimi", {"cost": 0.02, "firstMs": 1500}, self.at, "question")
        usage.llm("engineer", "kimi", at=self.at, error="HTTP 500")
        usage.llm("judge", "sonnet", {"cost": 0.05})
        usage.metric("stt_ms", 160, self.at)
        usage.metric("cut_off", 1, self.at)
        usage.flush()
        self.assertAlmostEqual(usage.session_cost("4242"), 0.03)
        d = diagnostics.report(self.st)
        self.assertAlmostEqual(d["session"]["cost"], 0.03)
        self.assertEqual(d["session"]["roles"]["engineer"]["calls"], 3)
        self.assertEqual(d["errors"]["session"], 1)
        self.assertIn({"role": "judge", "calls": 1, "cost": 0.05}, d["offSession"])
        first = d["latency"][0]["session"]
        self.assertEqual((first["n"], first["p50"], first["p90"]), (2, 1500, 1500))
        self.assertEqual(next(c["n"] for c in d["counts"] if c["label"].startswith("times you cut")), 1)
        self.assertEqual(d["byType"][0]["type"], "Race")


if __name__ == "__main__":
    unittest.main()
