import tempfile
import unittest
from pathlib import Path

from engineer.lexicon import Lexicon

GRID = ["PIASTRI", "NORRIS", "LECLERC", "HAMILTON", "VERSTAPPEN", "TSUNODA", "RUSSELL", "ANTONELLI",
        "STROLL", "ALONSO", "GASLY", "COLAPINTO", "OCON", "LAWSON", "HADJAR", "ALBON", "SAINZ",
        "HULKENBERG", "BORTOLETO", "BEARMAN", "River JAMES"]

# things River might actually say; none of these should be touched
ORDINARY = [
    "How are my tires looking?", "Box box.", "What does the weather look like?", "Nurse the tyres for me.",
    "Where is Russell?", "How is Kimi doing?", "Should I lift and coast?", "Is Ocon faster than me?",
    "Okay, on it.", "What's the gap behind?", "How many laps are left?", "Is it going to rain?",
    "Copy that.", "What position am I in?", "How much fuel do I have?", "Can I push now?",
    "Am I losing time anywhere?", "What's my delta?", "When's the pit window?", "Tell me about the car behind.",
    "Who's on the softs?", "Are the hards going to last?", "I've got understeer in the slow corners.",
    "The rear is stepping out on exit.", "Front wing feels damaged.", "Is there a safety car?",
    "How far ahead is Max?", "What tyres is Lando on?", "Should we stay out?", "Mate, the car is fine.",
    "Are we on plan A or plan B?", "Give me the gap to the leader.", "I think it's drying up.",
    "What's the track temperature?", "Medium is fine, so if it rains we stay out.", "Tsunoda's closing.",
    "Two klicks down at Stowe.", "Stroll’s on the hards.", "We did a lap on the wet use.",
    "Is Charles pitting this lap?", "Let me know when to save fuel.",
]


class Correct(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.lx = Lexicon(Path(self.dir.name) / "fixes.json")

    def tearDown(self):
        self.dir.cleanup()

    def fix(self, s):
        return self.lx.correct(s, GRID)[0]

    def test_ordinary_speech_untouched(self):
        for s in ORDINARY:
            with self.subTest(s=s):
                self.assertEqual(self.lx.correct(s, GRID), (s, []))

    def test_misheard_names(self):
        self.assertEqual(self.fix("How far back is Sonoda?"), "How far back is Tsunoda?")
        self.assertEqual(self.fix("What is the gap to hull can berg?"), "What is the gap to Hulkenberg?")
        self.assertEqual(self.fix("Is Anton Ellie pitting?"), "Is Antonelli pitting?")
        self.assertEqual(self.fix("What lap is Hajar on?"), "What lap is Hadjar on?")
        self.assertEqual(self.fix("Tell me about Ver stopping."), "Tell me about Verstappen.")

    def test_names_only_from_this_session(self):
        self.assertEqual(self.lx.correct("How far back is Sonoda?", [])[0], "How far back is Sonoda?")

    def test_jargon(self):
        self.assertEqual(self.fix("Is gas lee on inters?"), "Is Gasly on inters?")
        self.assertEqual(self.fix("Are we on the under cut?"), "Are we on the undercut?")
        self.assertEqual(self.fix("How much D R S do I have?"), "How much DRS do I have?")

    def test_changes_reported(self):
        _, changes = self.lx.correct("Is Sonoda close?", GRID)
        self.assertEqual(changes, [{"heard": "Sonoda", "meant": "Tsunoda", "how": "sounds like"}])

    def test_taught_fix_persists(self):
        self.lx.teach("look like", "Leclerc")
        again = Lexicon(self.lx.path)
        self.assertEqual(again.correct("What's the gap to look like?", GRID)[0], "What's the gap to Leclerc?")
        again.forget("LOOK LIKE")
        self.assertEqual(Lexicon(self.lx.path).fixes, [])

    def test_teach_rejects_blank(self):
        with self.assertRaises(ValueError):
            self.lx.teach(" ", "Leclerc")


if __name__ == "__main__":
    unittest.main()
