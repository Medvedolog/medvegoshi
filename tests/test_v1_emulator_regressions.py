"""Regression scenarios through the real V1 bridge and game on CPython."""

from pathlib import Path
import struct
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

from ports import amoled_v1 as port, emulate_v1 as panel_sim
from ports import amoled_v1_launch
from ports.package_amoled_v1_app import package_app
from ports import v1_full_game_emulate as game_module
from ports.v1_full_game_emulate import emulate as game_sim


def _idle(count):
    return tuple({} for _ in range(count))


def _touch(x, y, **buttons):
    return {"touch": (port.OFFSET_X + x, port.OFFSET_Y + y), **buttons}


# Drag from the settings handle, then allow release debouncing and settling.
_OPEN = (_touch(120, 6), _touch(120, 238)) + _idle(12)
_SWITCH_SLOTS = {"girafa": 50, "pip": 36}


class V1EmulatorRegressions(unittest.TestCase):
    def test_touch_on_both_corners_and_simultaneous_boot_and_power(self):
        x, y = port.OFFSET_X, port.OFFSET_Y
        right, bottom = x + port.LOGICAL_W - 1, y + port.LOGICAL_H - 1
        # Reject every adjacent margin; accept real edge coords, even while
        # both buttons are held. The second accepted contact is a separate tap.
        inputs = (
            {}, {"touch": (x - 1, y)}, {"touch": (x, y - 1)},
            {"touch": (right + 1, bottom)}, {"touch": (right, bottom + 1)},
            {"touch": (x, y), "boot": 1, "power": 1},
            {"touch": (x + 1, y), "boot": 1}, {}, {},
            {"touch": (right, bottom)}, {},
        )
        rig, result = panel_sim.emulate(inputs)
        self.assertEqual((result["touches"], result["boot_presses"], result["power_presses"]),
                         (2, 1, 1))
        self.assertEqual([w for w in rig.writes if w[0] == 0x34],
                         [(0x34, 0x49, b"\x08")])
        for point in ((x - 1, y), (x, y - 1), (right + 1, bottom), (right, bottom + 1)):
            self.assertEqual(rig.panel.image.getpixel(point), (0, 0, 0))

    def test_held_touch_with_one_missing_sample_only_feeds_once(self):
        # x=28 and y=240 are inclusive edges of the care button's hit box.
        meal = _touch(28, 240)
        inputs = ({},) + (meal,) * 14 + ({},) + (meal,) * 14 + _idle(3)
        _, result = game_sim(inputs)
        self.assertEqual(result["food_after"], 75)
        self.assertEqual(result["fake_sound_events"].count("comer"), 1)

    def test_boot_long_press_never_enables_v1_radio(self):
        # 81 input reports at fixed 40 ms/step cross the 3 s hold threshold.
        inputs = ({},) + ({"boot": 1},) * 81 + _idle(3)
        _, result = game_sim(inputs)
        self.assertEqual(result["last_system_notice"], "Радио выкл.")
        self.assertTrue(result["offline_forced"])
        self.assertEqual(result["network"], "disabled")
        self.assertEqual(result["simulated_i2c_write_addresses"], [0x20])

    def test_touch_confirmation_overlapping_boot_completes_once(self):
        inputs = (_OPEN + (_touch(44, 121),) + _idle(3)
                  + (_touch(55, 218, boot=1),) + _idle(16))
        _, result = game_sim(inputs, fixtures=_SWITCH_SLOTS)
        self.assertEqual([row["pet"] for row in result["pet_trace"]], ["girafa", "pip"])
        self.assertEqual(result["pet"], "pip")
        self.assertEqual(result["saved_food"], _SWITCH_SLOTS)
        self.assertTrue(result["menu_closed_after_open"])

    def test_ten_menu_switches_keep_both_saved_values(self):
        # Touching an arrow and then confirmation while leaving the panel
        # open makes this 10-switch run fit the bounded 96-frame emulator.
        inputs = _OPEN
        expected = ["girafa"]
        for step in range(10):
            target = "pip" if step % 2 == 0 else "girafa"
            arrow = 44 if target == "pip" else 194
            inputs += (_touch(arrow, 121),) + _idle(3) + (_touch(55, 218),) + _idle(3)
            expected.append(target)
        _, result = game_sim(inputs, fixtures=_SWITCH_SLOTS)
        self.assertEqual([row["pet"] for row in result["pet_trace"]], expected)
        self.assertTrue(all(row["food"] == _SWITCH_SLOTS[row["pet"]]
                            for row in result["pet_trace"]))
        self.assertTrue(all(row["life_stage"] == "adulto" for row in result["pet_trace"]))
        self.assertEqual(result["saved_food"], _SWITCH_SLOTS)

    def test_extracted_app_entry_is_executed_under_staged_module_name(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "app.zip"
            extracted = root / "app"
            package_app(game_module.ROOT, archive)
            with zipfile.ZipFile(archive) as archive:
                archive.extractall(extracted)
            app = extracted / "v1_game_app.py"
            with patch.object(amoled_v1_launch, "run", wraps=amoled_v1_launch.run) as launch:
                _, report = game_sim(({},), app_path=app)
            launch.assert_called_once_with(enabled=True, confirmed_v1=True)
        self.assertEqual(report["frames"], 1)
        self.assertEqual(report["runtime_profile"], "amoled_1_8_v1")
        self.assertTrue(report["packaged_entry"])

    def test_full_frame_repaints_after_simulated_missing_panel_transfer(self):
        inputs = ({}, _touch(28, 240)) + _idle(4)
        normal, expected = game_sim(inputs)
        original = panel_sim.Panel

        class DropOncePanel(original):
            dropped = 0
            def tx_color(self, command, data):
                if len(self.transfers) == 1 and not self.dropped:
                    self.dropped += 1
                    self.window.clear()
                    return
                super().tx_color(command, data)

        # Report a successful return to the sender but ignore the color
        # transaction once. The following frame must rebuild the full image.
        with patch.object(panel_sim, "Panel", DropOncePanel):
            got, result = game_sim(inputs)
        self.assertEqual(len(expected["native_display_windows"]), len(inputs))
        self.assertEqual(result["native_display_windows"],
                         expected["native_display_windows"][:1] + expected["native_display_windows"][2:])
        self.assertEqual(result["food_after"], 75)
        self.assertEqual(got.tobytes(), normal.tobytes())

    def test_wire_order_corner_colors_and_reused_framebuffer(self):
        panel = panel_sim.Panel(width=port.PANEL_W, height=port.PANEL_H)
        driver = panel_sim.AMOLED(panel)
        framebuf = SimpleNamespace(FrameBuffer=panel_sim.FrameBuffer, RGB565=panel_sim.RGB565)
        tela = port.Tela(driver, panel, framebuf)

        def paint(corners):
            for (px, py), word in corners.items():
                struct.pack_into(">H", tela.buf, 2 * (py * port.LOGICAL_W + px), word)
            tela.mostrar()

        a = (0, 0)
        b = (port.LOGICAL_W - 1, 0)
        c = (0, port.LOGICAL_H - 1)
        d = (port.LOGICAL_W - 1, port.LOGICAL_H - 1)
        buffer = tela.buf
        paint({a: 0xF800, b: 0x07E0, c: 0x001F, d: 0xFFFF})
        captured = panel.image.copy()
        for point, color in ((a, (255, 0, 0)), (b, (0, 255, 0)),
                             (c, (0, 0, 255)), (d, (255, 255, 255))):
            self.assertEqual(captured.getpixel(port.logical_to_physical(*point)), color)
        # Repaint the same object, not a new frame: stale data must not
        # survive at the first or last pixel after zeroing the wire buffer.
        tela.buf[:] = bytes(port.FRAME_BYTES)
        paint({a: 0x001F, d: 0xF800})
        self.assertIs(tela.buf, buffer)
        self.assertEqual(panel.image.getpixel(port.logical_to_physical(*a)), (0, 0, 255))
        self.assertEqual(panel.image.getpixel(port.logical_to_physical(*d)), (255, 0, 0))
        self.assertEqual(panel.image.getpixel(port.logical_to_physical(*b)), (0, 0, 0))
        self.assertEqual(panel.image.getpixel(port.logical_to_physical(*c)), (0, 0, 0))
        self.assertEqual(panel.image.getbbox(), (
            port.OFFSET_X, port.OFFSET_Y,
            port.OFFSET_X + port.LOGICAL_W, port.OFFSET_Y + port.LOGICAL_H,
        ))
        self.assertEqual(panel.transfers, [
            (port.OFFSET_X, port.OFFSET_Y,
             port.OFFSET_X + port.LOGICAL_W - 1,
             port.OFFSET_Y + port.LOGICAL_H - 1, port.FRAME_BYTES),
        ] * 2)


if __name__ == "__main__":
    unittest.main()
