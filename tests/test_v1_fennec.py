"""Verify the real FT3168 menu wraps from the new fox back to Capi."""
from unittest import TestCase

from ports import amoled_v1, v1_full_game_emulate as game
from zoo import registry


class FennecV1Test(TestCase):
    def test_select_capi_after_fennec_and_return_by_left_arrow(self):
        self.assertEqual(registry.ELENCO[-2:], ("ryska", "fennec"))
        self.assertEqual(registry.ELENCO[0], "capi")
        self.assertEqual("Фенек", registry.NOMES["fennec"])
        self.assertIsNotNone(registry.renderer("fennec"))
        right, left = game._touch(194, 121), game._touch(44, 121)
        select = lambda arrow: game._OPEN + (arrow,) + game._CONFIRM + game._CLOSE
        frames = game._idle(2) + select(right) + select(left)
        fixtures = {"fennec": 49, "capi": 64}
        pictures = {}
        frame, report = game.emulate(frames, initial_pet="fennec",
                                     fixtures=fixtures, pet_images=pictures,
                                     screen_mode=amoled_v1.SCALE_LARGE)
        self.assertEqual(frame.size, (368, 448))
        self.assertEqual([step["pet"] for step in report["pet_trace"]],
                         ["fennec", "capi", "fennec"])
        self.assertEqual(fixtures, report["saved_food"])
        self.assertTrue(report["menu_closed_after_open"])
        self.assertTrue(report["offline_forced"])
        self.assertNotEqual(pictures["fennec"].tobytes(), pictures["capi"].tobytes())
