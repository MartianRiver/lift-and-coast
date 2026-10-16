"""The driver's name and pronouns in the prompts, which are written about River, he/him."""
import unittest

from engineer import driver


class Words(unittest.TestCase):
    def tearDown(self):
        driver.FILE.unlink(missing_ok=True)

    def test_she(self):
        got = driver._words("River's brief: when he asks, tell him his tyres are fine. He's pushing.", "Ana", "she/her")
        self.assertEqual(got, "Ana's brief: when she asks, tell her her tyres are fine. She's pushing.")

    def test_they_agree_with_the_verb(self):
        got = driver._words("He boxes when he always tries; he has, he is, he's on it, he can, he said. RIVER'S BRIEF", "Sam", "they/them")
        self.assertEqual(got, "They box when they always try; they have, they are, they're on it, they can, they said. SAM'S BRIEF")

    def test_he_is_left_alone(self):
        text = "River (he/him) is driving; his engineer"
        self.assertEqual(driver._words(text, "Max", "he/him"), "Max (he/him) is driving; his engineer")
        self.assertEqual(driver._words(text, "Sam", "they/them"), "Sam (they/them) is driving; their engineer")

    def test_saved_and_asked_for(self):
        self.assertEqual(driver.get()["name"], None)
        self.assertEqual(driver.name(), "the driver")
        driver.save("  Ana  ", "she/her")
        self.assertEqual(driver.words("Tell River he's P3."), "Tell Ana she's P3.")
        with self.assertRaises(ValueError):
            driver.save("", "she/her")
        with self.assertRaises(ValueError):
            driver.save("Ana", "it/its")

    def test_game_name(self):
        self.assertEqual(driver.from_game({"name": "JAMES"}), "James")
        self.assertEqual(driver.from_game({"name": "River JAMES"}), "River James")
        self.assertEqual(driver.from_game({"name": "Car 19"}), None)
        self.assertEqual(driver.from_game(None), None)


if __name__ == "__main__":
    unittest.main()
