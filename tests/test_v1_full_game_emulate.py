import os
import unittest

from ports import amoled_v1 as port
from ports.v1_full_game_emulate import SCRIPT, emulate


class FullGameV1HostTest(unittest.TestCase):
    def test_real_care_game_handles_touch_and_boot_through_v1_bridge(self):
        cwd = os.getcwd()
        pix, data = emulate()
        self.assertEqual(os.getcwd(), cwd)
        self.assertEqual(data.get("scope"), "HOST_ONLY")
        self.assertEqual(data.get("frames"), len(SCRIPT))
        self.assertEqual(data.get("pet"), "girafa")
        self.assertEqual(data.get("life_stage"), "adulto")
        self.assertEqual(data.get("mode"), "pet")
        self.assertEqual((data["food_before"], data["food_after"]), (50, 75))
        self.assertIn("comer", data["fake_sound_events"])
        self.assertTrue(data["menu_opened"])
        self.assertTrue(data["menu_closed_after_open"])
        self.assertEqual(data["network"], "disabled")
        self.assertEqual(data["saves"], "temporary")
        self.assertEqual(pix.size, (port.PANEL_W, port.PANEL_H))
        self.assertEqual(pix.getpixel((0, 0)), (0, 0, 0))
        self.assertEqual(pix.getpixel((port.PANEL_W - 1, port.PANEL_H - 1)), (0, 0, 0))
        self.assertNotEqual(pix.crop((port.OFFSET_X, port.OFFSET_Y,
                                      port.OFFSET_X + port.LOGICAL_W,
                                      port.OFFSET_Y + port.LOGICAL_H)).getbbox(), None)
        transfer = (port.OFFSET_X, port.OFFSET_Y,
                    port.OFFSET_X + port.LOGICAL_W - 1,
                    port.OFFSET_Y + port.LOGICAL_H - 1, port.FRAME_BYTES)
        self.assertEqual(data["native_display_windows"], [transfer] * len(SCRIPT))


if __name__ == "__main__":
    unittest.main()
