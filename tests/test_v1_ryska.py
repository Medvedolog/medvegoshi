"""Actual native-V1 carousel regression for the last bundled Zoo character."""
from unittest import TestCase

from ports import amoled_v1, v1_full_game_emulate as game
from zoo import registry


class RyskaV1Test(TestCase):
    def test_select_ryska_after_bjorni_then_wrap_to_capi(self):
        self.assertEqual(registry.ELENCO[-2:], ("bjorni", "ryska"))
        self.assertEqual("Рыська", registry.NOMES["ryska"])
        self.assertIsNotNone(registry.renderer("ryska"))
        right = game._touch(194, 121)
        next_pet = game._OPEN + (right,) + game._CONFIRM + game._CLOSE
        fixtures = {"bjorni": 46, "ryska": 57, "capi": 68}
        pictures = {}
        frame, result = game.emulate(game._idle(2) + next_pet * 2, initial_pet="bjorni",
                                     fixtures=fixtures, pet_images=pictures,
                                     screen_mode=amoled_v1.SCALE_LARGE)
        self.assertEqual((368, 448), frame.size)
        self.assertEqual(["bjorni", "ryska", "capi"],
                         [step["pet"] for step in result["pet_trace"]])
        self.assertEqual(fixtures, result["saved_food"])
        self.assertEqual(set(fixtures), set(pictures))
        self.assertNotEqual(pictures["ryska"].tobytes(), pictures["bjorni"].tobytes())
        self.assertNotEqual(pictures["ryska"].tobytes(), pictures["capi"].tobytes())
        self.assertTrue(result["menu_closed_after_open"])
        self.assertEqual(result["saves"], "temporary")
        self.assertTrue(result["offline_forced"])
