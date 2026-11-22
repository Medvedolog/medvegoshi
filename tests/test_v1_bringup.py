import unittest
from types import SimpleNamespace

from ports import amoled_v1, v1_bringup as bringup


class Bus:
    def __init__(self, chip_id=0x4A, enabled=0x08, status=0):
        self.regs = {0x03: chip_id, 0x41: enabled, 0x49: status}
        self.writes = []

    def readfrom_mem(self, addr, reg, count):
        assert (addr, count) == (0x34, 1)
        return bytes((self.regs[reg],))

    def writeto_mem(self, addr, reg, data):
        self.writes.append((addr, reg, data))
        assert (addr, reg, data) == (0x34, 0x49, b"\x08")
        self.regs[reg] &= ~data[0]


class Visuals:
    def __init__(self):
        self.draws = []
        self.texts = []
        self.faces = []
        self.marks = []
        self.fb = SimpleNamespace(fill=lambda *a: None, rect=lambda *a: None,
                                  text=lambda *a: self.texts.append(a[0]),
                                  fill_rect=lambda *a: self.marks.append(a))
        self.art = SimpleNamespace(usar=lambda *a: None, centro=lambda *a: None,
                                   C=lambda c: c, CREME=(), INK=(), TEXTO=(),
                                   personagem=self.face)

    def face(self, animal, *args, **kwargs):
        self.faces.append((animal, kwargs["olhos"]))

    def mostrar(self):
        self.draws.append(tuple(self.texts[-3:]))


class V1BringupTest(unittest.TestCase):
    def test_touch_drag_boot_bounce_power_and_persistent_feedback(self):
        visual = Visuals()
        contacts = iter([None, (10, 20), (12, 20), None, None, (100, 100), None])
        # Constructor starts released; a one-sample bounce isn't a press.
        pins = iter([1, 0, 1, 0, 0, 0, 1, 1])
        powers = iter([False, False, False, True, False, False, False])
        sleeps = []
        result = bringup.run_loop(
            visual, SimpleNamespace(ler=lambda: next(contacts)),
            SimpleNamespace(value=lambda: next(pins)),
            SimpleNamespace(poll=lambda: next(powers)),
            frames=7, art=visual.art, clock=SimpleNamespace(sleep_ms=sleeps.append),
            wifi_label="WIFI: LINK")
        self.assertEqual(result, {"frames": 7, "touches": 2, "boot_presses": 1,
                                  "power_presses": 1, "power_available": True,
                                  "wifi": "WIFI: LINK"})
        self.assertEqual(sleeps, [40] * 6)
        self.assertEqual(visual.draws[-1], ("TOUCH:2 BOOT:1", "PWR:1", "WIFI: LINK"))
        self.assertEqual(visual.faces[0], ("girafa", "normal"))
        self.assertIn(("girafa", "feliz"), visual.faces)
        self.assertEqual(visual.marks[-1][:4], (100, 96, 1, 9))

    def test_idle_does_not_repaint_or_fabricate_buttons(self):
        visual = Visuals()
        result = bringup.run_loop(visual, SimpleNamespace(ler=lambda: None),
                                 SimpleNamespace(value=lambda: 1),
                                 SimpleNamespace(poll=lambda: None), frames=3,
                                 art=visual.art, clock=SimpleNamespace(sleep_ms=lambda _: None))
        self.assertEqual(visual.draws, [("TOUCH:0 BOOT:0", "PWR: N/A", "WIFI: OFF")])
        self.assertFalse(result["power_available"])

    def test_short_key_ack_does_not_touch_other_flags_or_configuration(self):
        bus = Bus(status=0x8C)
        key = bringup.PowerKey(bus)
        self.assertEqual(bus.regs[0x49], 0x84)
        self.assertFalse(key.poll())
        bus.regs[0x49] |= 0x08
        self.assertTrue(key.poll())
        self.assertFalse(key.poll())
        self.assertEqual(bus.writes, [(0x34, 0x49, b"\x08")] * 2)
        self.assertEqual(bus.regs[0x49], 0x84)
        for disabled in (Bus(chip_id=0x47, status=0x08), Bus(enabled=0, status=0x08)):
            self.assertIsNone(bringup.PowerKey(disabled).poll())
            self.assertEqual(disabled.writes, [])

    def test_opt_in_and_revision_guard_before_boot_or_pmic(self):
        calls = []
        fake_machine = SimpleNamespace(Pin=lambda *args: calls.append(args))
        with self.assertRaises(RuntimeError):
            bringup.run(machine_module=fake_machine)
        with self.assertRaises(ValueError):
            bringup.run(confirmed_v1=True, machine_module=fake_machine, frames=0)
        bus = Bus()

        def refuse(i2c, *, machine_module, verified_v1):
            self.assertIs(i2c, bus)
            self.assertIs(machine_module, fake_machine)
            self.assertTrue(verified_v1)
            raise amoled_v1.BoardMismatch("V2")

        with self.assertRaises(amoled_v1.BoardMismatch):
            bringup.run(confirmed_v1=True, machine_module=fake_machine, i2c=bus, prepare=refuse)
        self.assertEqual(calls, [])
        self.assertEqual(bus.writes, [])

    def test_wifi_inspection_is_read_only(self):
        created = []
        status = SimpleNamespace(active=lambda: True, isconnected=lambda: False)

        def wlan(which):
            created.append(which)
            return status

        network = SimpleNamespace(STA_IF=0, WLAN=wlan)
        self.assertEqual(bringup.read_wifi_label(network), "WIFI: NO LINK")
        status.isconnected = lambda: True
        self.assertEqual(bringup.read_wifi_label(network), "WIFI: LINK")
        status.active = lambda: False
        self.assertEqual(bringup.read_wifi_label(network), "WIFI: OFF")
        self.assertEqual(created, [0, 0, 0])


if __name__ == "__main__":
    unittest.main()
