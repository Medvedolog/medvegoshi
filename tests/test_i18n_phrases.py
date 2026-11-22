"""Regression checks for short Russian speech bubbles in the IPS interface."""
import unittest
import vida


class RussianBubbleTests(unittest.TestCase):
    def test_all_pet_lines_fit_original_240px_speech_bubble(self):
        groups = []
        for action, spec in vida.MOVE_FALAS.items():
            groups.append((action, spec[3]))
        groups.extend(vida.FRASES.items())
        for character, moods in vida.FRASES_CHAR.items():
            groups.extend((character + ":" + mood, phrases)
                          for mood, phrases in moods.items())

        for group, phrases in groups:
            for phrase in phrases:
                parts = phrase.split("|")
                self.assertLessEqual(len(parts), 2, (group, phrase))
                for part in parts:
                    self.assertLessEqual(len(part), 14, (group, phrase, part))

    def test_dog_has_russian_name_and_speech(self):
        self.assertEqual(vida.NOMES["cachorro"], "Карамелька")
        self.assertTrue(any("Гав" in s for s in vida.FRASES_CHAR["cachorro"]["ocioso"]))


if __name__ == "__main__":
    unittest.main()
