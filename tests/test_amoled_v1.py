"""AMOLED V1 host contracts: pinout, QSPI handoff, touch and safe V2 rejection.

No ESP32 or external amoled firmware is needed to run these tests.
"""
import tempfile
from pathlib import Path
import unittest
from PIL import Image
from ports import amoled_v1 as port
from ports.preview_amoled_v1 import render as preview_v1
from ports.amoled_v1_smoke import rgb565_swapped


class FakeI2C:
    def __init__(self, addresses=(0x20, 0x38)):
        self.addresses = list(addresses)
        self.register = {(0x20, 0x03): 0xFF, (0x20, 0x01): 0x24}
        self.touch = bytes((0, 0, 0, 0, 0))
        self.writes = []
    def scan(self):
        return list(self.addresses)
    def readfrom_mem(self, dev, reg, n):
        if dev == 0x38 and reg == 0x02 and n == 5:
            return self.touch
        return bytes((self.register[(dev, reg)],))
    def writeto_mem(self, dev, reg, data):
        self.writes.append((dev, reg, bytes(data)))
        self.register[(dev, reg)] = data[0]


class FakePin:
    OUT = 1
    IN = 0
    PULL_UP = 2
    creations = []
    def __init__(self, number, mode=None, pull=None, **kwargs):
        self.number, self.mode = number, mode
        self.creations.append((number, mode))
        self.level = 1
    def value(self):
        return self.level


class FakeSPI:
    calls = []
    def __init__(self, n, **kwargs):
        self.calls.append((n, kwargs))


class FakeMachine:
    Pin = FakePin
    SPI = FakeSPI


class FakeFramebuffer:
    def __init__(self, buf, width, height, color_format):
        self.buf, self.width, self.height = buf, width, height
        self.color_format = color_format
    def fill(self, color):
        for i in range(0, len(self.buf), 2):
            self.buf[i] = color & 255
            self.buf[i + 1] = (color >> 8) & 255
    def fill_rect(self, *args):
        pass
    def rect(self, *args):
        pass
    def text(self, *args):
        pass


class FramebufModule:
    FrameBuffer = FakeFramebuffer
    RGB565 = 2


class FakeNativePanel:
    def __init__(self):
        self.calls = []
    def tx_param(self, cmd, data):
        self.calls.append(("param", cmd, data))
    def tx_color(self, cmd, data):
        self.calls.append(("color", cmd, data))


class FakeNativeScreen:
    def __init__(self, panel, **kwargs):
        self.panel = panel
        self.kwargs = kwargs
        self.calls = []
    def reset(self):
        self.calls.append(("reset",))
    def init(self):
        self.calls.append(("init",))
    def brightness(self, value):
        self.calls.append(("brightness", value))
    def fill(self, value):
        self.calls.append(("fill", value))
    def refresh(self):
        self.calls.append(("refresh",))
    def bitmap(self, x0, y0, x1, y1, data):
        self.calls.append(("bitmap", x0, y0, x1, y1, data))


class NativeModule:
    last_panel = None
    last_display = None
    @classmethod
    def QSPIPanel(cls, **kwargs):
        cls.last_panel = kwargs
        return FakeNativePanel()
    @classmethod
    def AMOLED(cls, panel, **kwargs):
        cls.last_display = FakeNativeScreen(panel, **kwargs)
        return cls.last_display


def make_touch_packet(x, y, event=0, fingers=1):
    return bytes((fingers, ((event & 3) << 6) | ((x >> 8) & 15),
                  x & 255, (y >> 8) & 15, y & 255))


class AMOLEDV1Contracts(unittest.TestCase):
    def setUp(self):
        FakePin.creations.clear()
        FakeSPI.calls.clear()
        NativeModule.last_display = None
        self.bus = FakeI2C()

    def test_exact_chip_pair_and_geometry(self):
        self.assertEqual((port.PANEL_W, port.PANEL_H), (368, 448))
        self.assertEqual((port.LOGICAL_W, port.LOGICAL_H), (240, 284))
        self.assertEqual((port.OFFSET_X, port.OFFSET_Y), (64, 82))
        self.assertEqual((port.TOUCH_ADDR, port.V2_TOUCH_ADDR), (0x38, 0x15))
        self.assertEqual((port.GPIO_CS, port.GPIO_CLK, port.GPIO_TE),
                         (12, 11, 13))
        self.assertEqual((port.EXPANDER_PANEL_RESET_BIT,
                          port.EXPANDER_POWER_BIT,
                          port.EXPANDER_TOUCH_RESET_BIT), (0, 1, 2))
        self.assertEqual(port.GPIO_DATA, (4, 5, 6, 7))

    def test_pixel_and_touch_coordinate_inverse(self):
        for point in ((0, 0), (239, 283), (120, 142)):
            with self.subTest(point=point):
                self.assertEqual(port.physical_to_logical(
                    *port.logical_to_physical(*point)), point)
        for point in ((0, 200), (367, 200), (64, 0), (64, 447),
                      (-1, 100), (368, 200)):
            self.assertIsNone(port.physical_to_logical(*point))
        self.assertIsNone(port.logical_to_physical(240, 0))

    def test_ft3168_reads_down_and_contact_only(self):
        touch = port.FT3168Touch(self.bus)
        self.bus.touch = make_touch_packet(64, 82, event=0)
        self.assertEqual(touch.ler(), (0, 0))
        self.bus.touch = make_touch_packet(303, 365, event=2)
        self.assertEqual(touch.ler(), (239, 283))
        self.bus.touch = make_touch_packet(100, 100, event=1)
        self.assertIsNone(touch.ler())
        self.bus.touch = make_touch_packet(100, 100, event=3)
        self.assertIsNone(touch.ler())
        self.bus.touch = make_touch_packet(100, 100, fingers=0)
        self.assertIsNone(touch.ler())
        self.bus.touch = make_touch_packet(15, 200)
        self.assertIsNone(touch.ler())

    def test_power_expander_preserves_other_pins(self):
        port.enable_amoled_power(self.bus)
        self.assertEqual(self.bus.register[(0x20, 0x03)], 0xFD)
        self.assertEqual(self.bus.register[(0x20, 0x01)], 0x26)
        self.assertEqual([x[1] for x in self.bus.writes], [3, 1])
        self.assertTrue(all(x[0] == 0x20 for x in self.bus.writes))

    def test_v2_rejected_before_any_gpio_or_i2c_write(self):
        self.bus.addresses = [0x20, 0x15]
        with self.assertRaisesRegex(port.BoardMismatch, "V2"):
            port.prepare_v1(self.bus, FakeMachine, NativeModule, FramebufModule)
        self.assertEqual(self.bus.writes, [])
        self.assertEqual(FakePin.creations, [])
        self.assertEqual(FakeSPI.calls, [])

    def test_ambiguous_touch_pair_is_rejected(self):
        self.bus.addresses = [0x20, 0x38, 0x15]
        with self.assertRaises(port.BoardMismatch):
            port.validate_v1_bus(self.bus)
        self.assertEqual(self.bus.writes, [])

    def test_missing_touch_or_expander_rejected(self):
        for addresses in ([0x20], [0x38], []):
            with self.subTest(addresses=addresses):
                with self.assertRaises(port.BoardMismatch):
                    port.prepare_v1(FakeI2C(addresses), FakeMachine,
                                    NativeModule, FramebufModule)

    def test_ft3168_poll_catches_contact_without_irq_and_does_not_retry_nack(self):
        class CountingTouchBus(FakeI2C):
            def __init__(self):
                super().__init__()
                self.reads = []
                self.nack = False

            def readfrom_mem(self, dev, reg, n):
                self.reads.append((dev, reg, n))
                if self.nack:
                    raise OSError("idle NACK")
                return super().readfrom_mem(dev, reg, n)

        bus = CountingTouchBus()
        sensor = port.FT3168Touch(bus)
        bus.touch = make_touch_packet(100, 100)
        self.assertEqual(sensor.ler(), (36, 18))
        self.assertEqual(bus.reads, [(0x38, 0x02, 5)])
        bus.nack = True
        self.assertIsNone(sensor.ler())
        self.assertEqual(bus.reads, [(0x38, 0x02, 5)] * 2)
        self.assertEqual(bus.writes, [])

    def test_touch_reset_requires_explicit_v1_label_confirmation(self):
        class ResetHeldI2C(FakeI2C):
            def __init__(self):
                super().__init__([0x20])
            def writeto_mem(self, dev, reg, data):
                super().writeto_mem(dev, reg, data)
                if reg == 1 and data[0] & 4:
                    self.addresses.append(0x38)
        bus = ResetHeldI2C()
        with self.assertRaises(port.BoardMismatch):
            port.validate_v1_bus(bus)
        self.assertEqual(bus.writes, [])
        self.assertIn(0x38, port.validate_v1_bus(bus, verified_v1=True))
        self.assertEqual([i[1] for i in bus.writes], [3, 1])
        self.assertEqual(bus.register[(0x20, 0x03)] & 4, 0)

    def test_native_compiled_qspi_dependencies_required(self):
        class Incomplete:
            pass
        with self.assertRaisesRegex(port.DriverUnavailable, "Incomplete"):
            port.prepare_v1(self.bus, FakeMachine, Incomplete(), FramebufModule)
        self.assertEqual(self.bus.writes, [])

    def test_native_driver_initialization_and_correct_frame_transfer(self):
        screen, touch = port.prepare_v1(
            self.bus, FakeMachine, NativeModule, FramebufModule)
        self.assertIsInstance(touch, port.FT3168Touch)
        self.assertEqual(len(screen.buf), 240 * 284 * 2)
        self.assertIs(screen.fb.buf, screen.buf)
        self.assertEqual(NativeModule.last_panel["width"], 368)
        self.assertEqual(NativeModule.last_panel["height"], 448)
        self.assertEqual(NativeModule.last_display.kwargs["type"], 2)
        self.assertIs(NativeModule.last_display.kwargs["auto_refresh"], False)
        self.assertEqual(FakeSPI.calls[0][0], 2)
        self.assertEqual(FakeSPI.calls[0][1]["baudrate"], 80_000_000)
        self.assertEqual(FakeSPI.calls[0][1]["mosi"], None)
        self.assertEqual(self.bus.register[(0x20, 0x01)] & 0x03, 0x03)
        self.assertNotIn((21, FakePin.IN), FakePin.creations)
        self.assertNotIn((13, FakePin.OUT), FakePin.creations)
        screen.buf[:4] = b"\xf8\x00\x07\xe0"
        screen.buf[-2:] = b"\x00\x1f"
        native = NativeModule.last_display
        startup = list(native.calls)
        self.assertEqual(startup.count(("refresh",)), 1)
        screen.mostrar()
        self.assertEqual(native.calls, startup)  # no framebuffer refresh over our blit
        col, row, color = native.panel.calls
        self.assertEqual(col, ("param", 0x2A, b"\x00\x40\x01\x2f"))
        self.assertEqual(row, ("param", 0x2B, b"\x00\x52\x01\x6d"))
        self.assertEqual(color[:2], ("color", 0))
        self.assertIs(color[2], screen.buf)
        self.assertEqual(len(color[2]), 136320)
        self.assertEqual(color[2][:4], b"\xf8\x00\x07\xe0")
        self.assertEqual(color[2][-2:], b"\x00\x1f")

    def test_bad_frame_size_rejected_before_qspi_writes(self):
        screen, _ = port.prepare_v1(
            self.bus, FakeMachine, NativeModule, FramebufModule)
        screen.buf = bytearray(136318)
        with self.assertRaisesRegex(ValueError, "frame size"):
            screen.mostrar()
        self.assertEqual(NativeModule.last_display.panel.calls, [])

    def test_raw_qspi_transport_required_before_display_power(self):
        class NoRawTransport(NativeModule):
            @classmethod
            def QSPIPanel(cls, **kwargs):
                return object()

        with self.assertRaisesRegex(port.DriverUnavailable, "transport"):
            port.prepare_v1(self.bus, FakeMachine, NoRawTransport, FramebufModule)
        self.assertEqual(self.bus.writes, [])

    def test_rgb565_endianness_matches_ips_byte_swapped_helper(self):
        self.assertEqual(rgb565_swapped(255, 0, 0), 0x00F8)
        self.assertEqual(rgb565_swapped(0, 255, 0), 0xE007)
        self.assertEqual(rgb565_swapped(0, 0, 255), 0x1F00)

    def test_letterboxed_amoled_preview_matches_exact_game_pixels(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            inp, out = root / "ips.png", root / "v1.png"
            im = Image.new("RGB", (240, 284), (255, 0, 0))
            im.putpixel((239, 283), (0, 0, 255))
            im.save(inp)
            preview_v1(inp, out)
            with Image.open(out) as assembled:
                self.assertEqual(assembled.size, (368, 448))
                self.assertEqual(assembled.getpixel((0, 0)), (0, 0, 0))
                self.assertEqual(assembled.getpixel((63, 100)), (0, 0, 0))
                self.assertEqual(assembled.getpixel((64, 82)), (255, 0, 0))
                self.assertEqual(assembled.getpixel((303, 365)), (0, 0, 255))
                self.assertEqual(assembled.getpixel((304, 365)), (0, 0, 0))
            with self.assertRaisesRegex(ValueError, "overwrite"):
                preview_v1(inp, inp)

    def test_invalid_brightness_rejected(self):
        screen, _ = port.prepare_v1(
            self.bus, FakeMachine, NativeModule, FramebufModule)
        for n in (-1, 101):
            with self.assertRaises(ValueError):
                screen.brilho(n)
        for percent, raw in ((0, 0), (50, 128), (75, 191), (100, 255)):
            with self.subTest(percent=percent):
                screen.brilho(percent)
                self.assertEqual(NativeModule.last_display.calls[-1],
                                 ("brightness", raw))


if __name__ == "__main__":
    unittest.main()
