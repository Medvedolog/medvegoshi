"""Run real bringup, renderer and port against scripted host peripherals."""
import builtins
import unittest
from unittest.mock import patch

from ports import amoled_v1, emulate_v1


class V1EmulatorTest(unittest.TestCase):
    def test_real_renderer_and_v1_events_through_hardware_contract(self):
        original_open = builtins.open

        def guard(filename, *args, **kwargs):
            if str(filename).rsplit("/", 1)[-1] in (
                    "config.json", "capi.json", "brain.bin"):
                self.fail("bringup accessed a real game save")
            return original_open(filename, *args, **kwargs)

        with patch("builtins.open", side_effect=guard):
            rig, result = emulate_v1.emulate(wifi=True)
        self.assertEqual(result["touches"], 1)  # ignored outer-margin tap; drag counted once
        self.assertEqual(result["boot_presses"], 1)  # held key counted once
        self.assertEqual(result["power_presses"], 1)
        self.assertEqual(result["wifi"], "WIFI: SIMULATED")
        self.assertEqual(rig.panel.image.size, (368, 448))
        self.assertEqual(set(rig.panel.transfers), {(64, 82, 303, 365, 136320)})
        self.assertGreater(len(rig.panel.transfers), 1)
        self.assertEqual(rig.panel.image.getpixel((63, 100)), (0, 0, 0))
        self.assertEqual(rig.panel.image.getpixel((304, 100)), (0, 0, 0))
        self.assertNotEqual(rig.panel.image.getpixel((70, 100)), (0, 0, 0))
        self.assertEqual([w for w in rig.writes if w[0] == 0x34],
                         [(0x34, 0x49, b"\x08")])

    def test_same_bringup_rejects_v2(self):
        with self.assertRaises(amoled_v1.BoardMismatch):
            emulate_v1.emulate(revision="v2")
