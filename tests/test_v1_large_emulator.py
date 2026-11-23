"""Host-only large V1 viewport integration through the real game and touch."""

import unittest
from unittest.mock import patch

from ports import amoled_v1 as v1, emulate_v1 as panel_sim, v1_menu_font
from ports.v1_full_game_emulate import (
    SCRIPT, SWITCH_SCRIPT, _OPEN, _WireOverlayFrameBuffer, _remap_inputs, emulate,
)


def _legacy_touch(x, y, **buttons):
    return {"touch": (v1.OFFSET_X + x, v1.OFFSET_Y + y), **buttons}


class LargeV1EmulatorTest(unittest.TestCase):
    def test_native_overlay_rect_writes_directly_to_clipped_wire_buffer(self):
        data = bytearray(b"\xaa" * 12)
        surface = _WireOverlayFrameBuffer(data, 3, 2)
        surface.fill_rect(-1, 1, 3, 2, 0x00F8)
        self.assertEqual(data, b"\xaa" * 6 + b"\xf8\x00\xf8\x00\xaa\xaa")

    def test_legacy_scripts_follow_the_same_touch_transform_as_large_display(self):
        points = ((0, 0), (28, 240), (239, 283))
        samples = tuple(_legacy_touch(x, y, boot=1) for x, y in points)
        samples += ({"touch": (v1.OFFSET_X - 1, v1.OFFSET_Y), "power": 1},)
        mapped = _remap_inputs(samples, v1.SCALE_LARGE, False)
        self.assertEqual(mapped[-1], {"power": 1})
        self.assertIn("touch", samples[-1])
        viewport = v1.VIEWPORT_LARGE
        for expected, event in zip(points, mapped):
            self.assertEqual(event["boot"], 1)
            self.assertEqual(event["touch"], viewport.logical_to_physical(*expected))
            self.assertEqual(viewport.physical_to_logical(*event["touch"]), expected)
        self.assertIs(_remap_inputs(samples, v1.SCALE_NATIVE, False), samples)
        self.assertIs(_remap_inputs(samples, v1.SCALE_LARGE, True), samples)
        with self.assertRaises(ValueError):
            _remap_inputs(samples, "stretched", False)

    def test_large_care_touch_and_boot_use_aligned_full_width_viewport(self):
        image, result = emulate(SCRIPT, screen_mode=v1.SCALE_LARGE)
        self.assertEqual(result["screen_mode"], v1.SCALE_LARGE)
        self.assertEqual(result["runtime_profile"], "amoled_1_8_v1")
        self.assertEqual((result["food_before"], result["food_after"]), (50, 75))
        self.assertTrue(result["menu_opened"])
        self.assertTrue(result["menu_closed_after_open"])
        self.assertEqual(result["native_display_windows"], [
            (0, 6, 367, 440, 368 * 435 * 2),
        ] * len(SCRIPT))
        self.assertIsNone(image.crop((0, 0, 368, 6)).getbbox())
        self.assertIsNone(image.crop((0, 441, 368, 448)).getbbox())
        self.assertIsNotNone(image.crop((0, 6, 1, 441)).getbbox())
        self.assertIsNotNone(image.crop((367, 6, 368, 441)).getbbox())

    def test_raw_physical_touch_ignores_large_margin_then_hits_care(self):
        viewport = v1.VIEWPORT_LARGE
        x, y = viewport.logical_to_physical(28, 240)
        _, result = emulate((
            {"touch": (120, viewport.y - 1)}, {},
            {"touch": (120, viewport.y + viewport.height)}, {},
            {"touch": (x, y)}, {}, {},
        ), screen_mode=v1.SCALE_LARGE, physical_touches=True)
        self.assertEqual(result["fake_sound_events"].count("comer"), 1)
        self.assertEqual(result["food_after"], 75)
        self.assertFalse(result["menu_opened"])

    def test_large_menu_switches_giraffe_and_pip_without_reset(self):
        image, result = emulate(SWITCH_SCRIPT, screen_mode=v1.SCALE_LARGE,
                                fixtures={"girafa": 50, "pip": 36})
        self.assertEqual([row["pet"] for row in result["pet_trace"]],
                         ["girafa", "pip", "girafa"])
        self.assertEqual(result["saved_food"], {"girafa": 75, "pip": 61})
        self.assertTrue(result["menu_closed_after_open"])
        self.assertEqual(image.size, (368, 448))

    def test_large_rebuilds_complete_frame_after_dropped_transfer(self):
        inputs = ({}, _legacy_touch(28, 240), {}, {}, {})
        expected, baseline = emulate(inputs, screen_mode=v1.SCALE_LARGE)
        original = panel_sim.Panel

        class SkipFirstPanel(original):
            dropped = False

            def tx_color(self, command, data):
                if not self.dropped:
                    self.dropped = True
                    self.window.clear()
                    return
                super().tx_color(command, data)

        with patch.object(panel_sim, "Panel", SkipFirstPanel):
            actual, result = emulate(inputs, screen_mode=v1.SCALE_LARGE)
        self.assertEqual(result["native_display_windows"],
                         baseline["native_display_windows"][1:])
        self.assertEqual(result["food_after"], baseline["food_after"])
        self.assertEqual(actual.tobytes(), expected.tobytes())

    def test_real_settings_queue_native_cyrillic_in_large_mode_only(self):
        labels = []
        original_draw = v1_menu_font.draw

        def record(surface, text, *rest):
            self.assertIsInstance(surface, _WireOverlayFrameBuffer)
            labels.append(text)
            return original_draw(surface, text, *rest)

        with patch.object(v1_menu_font, "draw", side_effect=record):
            _, native = emulate(_OPEN, screen_mode=v1.SCALE_NATIVE)
            self.assertTrue(native["menu_opened"])
            self.assertEqual(labels, [])
            _, large = emulate(_OPEN, screen_mode=v1.SCALE_LARGE)
            self.assertTrue(large["menu_opened"])
        for label in ("Настройки", "Питомец", "Сменить друга", "Быстрое",
                      "Часы: только чтение"):
            self.assertIn(label, labels)

    def test_same_native_title_style_before_during_and_after_menu_motion(self):
        title = []
        original_draw = v1_menu_font.draw

        def record(surface, text, x, y, color, esc=1):
            if text == "Настройки":
                title.append((x, y, color, esc))
            return original_draw(surface, text, x, y, color, esc)

        with patch.object(v1_menu_font, "draw", side_effect=record):
            _, result = emulate(_OPEN, screen_mode=v1.SCALE_LARGE)
        self.assertTrue(result["menu_opened"])
        self.assertGreater(len(set(y for _, y, _, _ in title)), 1)
        self.assertEqual(len({(x, color, esc) for x, _, color, esc in title}), 1)
        self.assertEqual([y for _, y, _, _ in title],
                         sorted(y for _, y, _, _ in title))


if __name__ == "__main__":
    unittest.main()
