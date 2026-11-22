import os
import shlex
import shutil
import sys
import unittest

from ports import amoled_v1 as port
from ports.v1_full_game_emulate import POLICY_SCRIPT, SCRIPT, SWITCH_SCRIPT, emulate


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
        self.assertEqual(data["runtime_profile"], "amoled_1_8_v1")
        self.assertFalse(data["rtc_write_enabled"])
        self.assertTrue(data["offline_forced"])
        self.assertEqual(data["simulated_i2c_write_addresses"], [0x20])
        self.assertEqual(data["v1_capabilities"], {
            "rtc_write": False, "audio": False, "microphone": False,
            "power_key": False, "network_managed": False,
        })
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

    def test_switch_pets_through_real_menu_without_resetting_separate_slots(self):
        pictures = {}
        pix, data = emulate(SWITCH_SCRIPT, fixtures={"girafa": 50, "pip": 36},
                            pet_images=pictures)
        self.assertEqual(data["frames"], len(SWITCH_SCRIPT))
        self.assertEqual(data["pet_trace"], [
            {"pet": "girafa", "food": 50, "life_stage": "adulto"},
            {"pet": "pip", "food": 36, "life_stage": "adulto"},
            {"pet": "girafa", "food": 75, "life_stage": "adulto"},
        ])
        self.assertEqual(data["saved_food"], {"girafa": 75, "pip": 61})
        self.assertEqual(data["fake_sound_events"].count("comer"), 2)
        self.assertTrue(data["menu_closed_after_open"])
        self.assertEqual(set(pictures), {"pip", "girafa"})
        self.assertNotEqual(pictures["pip"].tobytes(), pictures["girafa"].tobytes())
        self.assertEqual(pictures["girafa"].tobytes(), pix.tobytes())

    def test_v1_disables_clock_adjustment_and_default_wifi_shortcut(self):
        _, data = emulate(POLICY_SCRIPT)
        self.assertFalse(data["rtc_write_enabled"])
        self.assertTrue(data["offline_forced"])
        self.assertEqual(data["last_system_notice"], "Радио выкл.")

    def test_failed_v1_rtc_is_not_auto_set(self):
        with self.assertRaisesRegex(RuntimeError, "RTC stopped or unreadable"):
            emulate(({},), rtc_valid=False)

    @unittest.skipUnless(sys.platform != "win32" and
                         shutil.which(shlex.split(os.environ.get("CC", "cc"))[0]),
                         "desktop Pip C compiler required")
    def test_compiled_host_pip_reacts_and_flushes_its_own_sidecar_on_switch(self):
        _, data = emulate(SWITCH_SCRIPT, fixtures={"girafa": 50, "pip": 36},
                          native_pip=True)
        pip = data["native_pip"]
        self.assertEqual(pip["events"], [("feed", "nauseous")])
        self.assertEqual(pip["sidecar_owner"], "pip")
        self.assertGreater(pip["restored_food"], 0.99)
        self.assertAlmostEqual(data["saved_food"]["pip"], pip["restored_food"] * 100)
        self.assertEqual(data["saved_food"]["girafa"], 75)
        self.assertEqual(data["pet"], "girafa")


if __name__ == "__main__":
    unittest.main()

