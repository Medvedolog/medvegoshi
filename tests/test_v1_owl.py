"""The renamed owl retains the original pet ID, save and carousel position."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
import zipfile

from ports import amoled_v1, v1_full_game_emulate as game
from ports.package_amoled_v1_app import package_app
from zoo import pet_slots, registry
import vida


class OwlV1Test(TestCase):
    def test_stable_slot_and_owl_specific_russian_lines(self):
        self.assertEqual(registry.ELENCO[:4], ("capi", "elefante", "pato", "polvo"))
        self.assertEqual(registry.NOMES["pato"], "Совёнка")
        self.assertEqual(vida.NOMES["pato"], "Совёнка")
        self.assertEqual(pet_slots.pet_path("pato"), "pet_saves/pato/capi.json")
        phrases = vida.FRASES_CHAR["pato"]
        self.assertIn("Ух-ух!", phrases["ocioso"])
        self.assertIn("Люблю|свой берет!", phrases["ocioso"])
        for texts in phrases.values():
            for text in texts:
                self.assertNotIn("кря", text.lower())
                lines = text.split("|")
                self.assertLessEqual(len(lines), 2)
                self.assertTrue(all(1 <= len(line) <= 14 for line in lines))

    def test_existing_owl_slot_and_localized_label_in_actual_v1_package(self):
        selected = []
        native_queue = amoled_v1.Tela._queue_text

        def record(screen, text, *args, **kwargs):
            selected.append(text)
            return native_queue(screen, text, *args, **kwargs)

        previous_pet, next_pet = game._touch(44, 121), game._touch(194, 121)
        backward = game._OPEN + (previous_pet,) + game._CONFIRM + game._CLOSE
        forward = game._OPEN + (next_pet,) + game._CONFIRM + game._CLOSE
        fixtures = {"pato": 37, "elefante": 73}
        with TemporaryDirectory(prefix="medve-owl-app-test-") as directory:
            root = Path(directory)
            package = root / "app.zip"
            package_app(game.ROOT, package)
            staged = root / "staged"
            with zipfile.ZipFile(package) as handle:
                handle.extractall(staged)
            with patch.object(amoled_v1.Tela, "_queue_text", record):
                _, result = game.emulate(game._idle(2) + backward + forward,
                                         initial_pet="pato", fixtures=fixtures,
                                         screen_mode=amoled_v1.SCALE_LARGE,
                                         app_path=staged / "v1_game_app.py")
        self.assertTrue(result["packaged_entry"])
        self.assertEqual(result["runtime_profile"], "amoled_1_8_v1")
        self.assertTrue(result["offline_forced"])
        self.assertEqual([step["pet"] for step in result["pet_trace"]],
                         ["pato", "elefante", "pato"])
        self.assertEqual(fixtures, result["saved_food"])
        self.assertTrue(any(text.startswith("Совёнка") for text in selected))
        self.assertFalse(any("Утка" in text for text in selected))
