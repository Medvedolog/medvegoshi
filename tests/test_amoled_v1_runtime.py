import struct
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from ports import amoled_v1, amoled_v1_runtime as rt

CAL = (2026, 11, 22, 17, 23, 42)
BCD = bytes((0x42, 0x23, 0x17, 0x22, 0, 0x11, 0x26))


class Rig:
    def __init__(self, touch=True, imu=0x6B):
        self.found = [0x20, 0x34, 0x51, imu] + ([0x38] if touch else [])
        self.cold_touch = not touch
        self.reg = {(0x20, 1): b"\xA8", (0x20, 3): b"\xFF",
                    (0x34, 3): b"\x4A", (0x34, 0x41): b"\x08",
                    (0x34, 0x49): b"\x00", (0x34, 0): b"\x08",
                    (0x34, 1): b"\x20", (0x34, 0xA4): b"\x52",
                    (0x51, 0): b"\x00", (0x51, 4): BCD,
                    (imu, 0): b"\x05", (imu, 2): b"\x20",
                    (imu, 3): b"\x00", (imu, 8): b"\x00",
                    (imu, 0x2E): b"\x01",
                    (imu, 0x35): struct.pack("<hhh", 0, -8192, 0),
                    (0x38, 2): bytes((1, 0, 84, 0, 112))}
        self.scans, self.reads, self.writes = 0, [], []
        self.pin_calls, self.spi, self.i2c_calls = [], [], []
        self.panel, self.display = None, None
        self.mktime_inputs = []
        self.fail_write, self.drop_write = None, None
        rig = self

        class Pin:
            IN, OUT, PULL_UP = 0, 1, 2

            def __init__(self, number, mode=None, pull=None):
                self.number = number
                rig.pin_calls.append((number, mode, pull))

            def value(self):
                return 1

        self.machine = SimpleNamespace(Pin=Pin, I2C=self.make_i2c, SPI=self.make_spi)
        self.native = SimpleNamespace(QSPIPanel=self.make_panel, AMOLED=self.make_display)
        self.framebuf = SimpleNamespace(
            FrameBuffer=lambda b, w, h, f: SimpleNamespace(buf=b, shape=(w, h), fmt=f),
            RGB565=1)
        self.clock = SimpleNamespace(mktime=self.mktime)

    def scan(self):
        self.scans += 1
        return list(self.found)

    def readfrom_mem(self, a, r, n):
        self.reads.append((a, r, n))
        if a not in self.found or (a, r) not in self.reg:
            raise OSError("fixture NACK")
        return self.reg[a, r]

    def writeto_mem(self, a, r, data):
        self.writes.append((a, r, data))
        if (a, r) == self.fail_write:
            raise OSError("fixture NACK")
        if (a, r) == self.drop_write:
            return
        if (a, r) == (0x34, 0x49):
            self.reg[a, r] = bytes((self.reg[a, r][0] & ~data[0],))
        else:
            self.reg[a, r] = data
        if self.cold_touch and (a, r) == (0x20, 1) and data[0] & 4:
            self.cold_touch = False
            self.found.append(0x38)

    def mktime(self, args):
        self.mktime_inputs.append(args)
        if args[:6] != CAL or len(args) != 8:
            raise ValueError("unexpected MicroPython calendar")
        return 1795368222

    def make_i2c(self, i, **kw):
        self.i2c_calls.append((i, kw))
        return self

    def make_spi(self, i, **kw):
        self.spi.append((i, kw))
        return object()

    def make_panel(self, **kw):
        tx = []
        self.panel = SimpleNamespace(opts=kw, tx=tx,
            tx_param=lambda cmd, val: tx.append((cmd, val)),
            tx_color=lambda cmd, val: tx.append((cmd, len(val))))
        return self.panel

    def make_display(self, panel, **kw):
        calls = []
        self.display = SimpleNamespace(opts=kw, calls=calls,
            reset=lambda: calls.append("reset"), init=lambda: calls.append("init"),
            brightness=lambda v: calls.append(("brightness", v)),
            fill=lambda v: calls.append(("fill", v)),
            refresh=lambda: calls.append("refresh"))
        return self.display

    def build(self, **opts):
        for k, v in (("enabled", True), ("confirmed_v1", True),
                     ("native_module", self.native), ("machine_module", self.machine),
                     ("framebuffer_module", self.framebuf), ("clock", self.clock)):
            opts.setdefault(k, v)
        return rt.create_profile(**opts)


class TestAMOLEDV1Runtime(unittest.TestCase):
    def test_real_transport_and_pins_through_profile(self):
        rig = Rig()
        p = rig.build()
        self.assertIs(p.i2c, rig)
        self.assertEqual(p.profile_id, "amoled_1_8_v1")
        self.assertEqual(p.capabilities,
            {"rtc_write": False, "audio": False, "microphone": False,
             "power_key": False, "network_managed": False})
        ident, cfg = rig.i2c_calls[0]
        self.assertEqual((ident, cfg["scl"].number, cfg["sda"].number,
                          cfg["freq"], cfg["timeout"]), (0, 14, 15, 400000, 10000))
        self.assertIn((0, 0, 2), rig.pin_calls)
        self.assertEqual((p.botao.number, p.botao.value()), (0, 1))
        opts = rig.panel.opts
        self.assertEqual((opts["cs"].number, *(pin.number for pin in opts["data"])),
                         (12, 4, 5, 6, 7))
        self.assertEqual(rig.spi[0][1]["sck"].number, 11)
        self.assertEqual(rig.display.calls,
                         ["reset", "init", ("brightness", 0),
                          ("fill", 0), "refresh", ("brightness", 128)])
        self.assertEqual(p.tela.fb.shape, (240, 284))
        p.tela.mostrar()
        self.assertEqual(rig.panel.tx, [(0x2A, b"\x00\x40\x01\x2F"),
                                       (0x2B, b"\x00\x52\x01\x6D"), (0, 136320)])
        self.assertEqual(p.toque.ler(), (20, 30))
        self.assertEqual(p.mov.read_g(), 1.0)
        self.assertEqual(p.relogio.ler(), CAL)
        self.assertEqual(p.relogio.epoch(), 1795368222)
        self.assertEqual(rig.mktime_inputs, [CAL + (0, 0)] * 2)
        self.assertFalse(p.relogio.acertar(2026, 11, 22, 5, 0))
        self.assertFalse(p.relogio.somar_minutos(5))
        self.assertEqual(p.bateria.porcentagem(), 82)
        self.assertTrue(p.bateria.carregando())
        self.assertFalse(p.bateria.tecla())
        p.som.ligado = True
        self.assertFalse(p.som.ligado)
        self.assertFalse(p.som.tocar("fala1"))
        self.assertEqual(p.som.volume_mic(), 0)
        self.assertEqual([w for w in rig.writes if w[0] == 0x6B],
                         [(0x6B, 2, b"\x60"), (0x6B, 3, b"\x15"), (0x6B, 8, b"\x01")])
        self.assertTrue(all(w[0] in (0x6B, 0x20) for w in rig.writes))
        self.assertEqual(rig.reg[0x20, 1][0] & 0xFC, 0xA8)
        self.assertEqual(rig.reg[0x20, 3][0] & 0xFC, 0xFC)

    def test_flags_and_dependencies_fail_before_bus(self):
        rig = Rig()
        for opts in ({"enabled": False}, {"confirmed_v1": False}, {"enabled": 1},
                     {"confirmed_v1": 1}, {"native_module": object()},
                     {"framebuffer_module": object()}):
            with self.subTest(opts=opts), self.assertRaises(rt.ProfileUnavailable):
                rig.build(**opts)
        self.assertEqual((rig.pin_calls, rig.i2c_calls, rig.scans, rig.writes), ([], [], 0, []))

    def test_v2_and_mixed_touch_never_configure_peripherals(self):
        for touch in (False, True):
            rig = Rig(touch=touch)
            rig.found.append(0x15)
            with self.assertRaises(amoled_v1.BoardMismatch):
                rig.build(i2c=rig)
            self.assertEqual((rig.writes, rig.pin_calls, rig.panel), ([], [], None))

    def test_device_identity_checked_before_cold_touch_reset(self):
        for wrong in ("tca", "pmu", "rtc", "imu", "ambiguous", "audio"):
            with self.subTest(wrong=wrong):
                r, opts = Rig(touch=False), {}
                if wrong == "tca":
                    r.found.remove(0x20)
                elif wrong == "pmu":
                    r.reg[0x34, 3] = b"\x00"
                elif wrong == "rtc":
                    r.reg[0x51, 4] = b"\x80" + BCD[1:]
                elif wrong == "imu":
                    r.reg[0x6B, 0] = b"\xff"
                elif wrong == "ambiguous":
                    r.found.append(0x6A)
                    r.reg[0x6A, 0] = b"\x05"
                else:
                    opts["audio_factory"] = lambda *_a, **_k: None
                with self.assertRaises((rt.ProfileUnavailable, amoled_v1.BoardMismatch)):
                    r.build(i2c=r, **opts)
                self.assertEqual((r.writes, r.pin_calls, r.panel), ([], [], None))
                self.assertTrue(r.cold_touch)

    def test_confirmed_cold_board_may_release_only_touch_reset_first(self):
        r = Rig(touch=False)
        with patch("time.sleep") as sleeper:
            p = r.build(i2c=r)
        sleeper.assert_called_once_with(0.05)
        self.assertEqual(r.writes[:2], [(0x20, 3, b"\xFB"), (0x20, 1, b"\xAC")])
        self.assertEqual(p.toque.ler(), (20, 30))

    def test_active_accelerometer_is_read_without_reconfiguration(self):
        imu = 0x6A
        r = Rig(imu=imu)
        r.reg.update({(imu, 2): b"\x60", (imu, 3): b"\x26", (imu, 8): b"\x03",
                      (imu, 0x35): struct.pack("<hhh", -4096, 4096, 0)})
        p = r.build(i2c=r)
        self.assertAlmostEqual(p.mov.read_g(), 2 ** 0.5)
        self.assertFalse(any(w[0] == imu for w in r.writes))
        r.reg[imu, 0x2E] = b"\x00"
        self.assertIsNone(p.mov.read_g())
        self.assertEqual(p.mov.forca_g(), 1.0)
        r.reg[imu, 0x2E], r.reg[imu, 0x35] = b"\x01", b"\x00"
        self.assertIsNone(p.mov.read_g())

    def test_failed_or_unsupported_imu_does_not_configure_display(self):
        r = Rig()
        r.reg[0x6B, 8] = b"\x81"
        with self.assertRaises(rt.ProfileUnavailable):
            r.build(i2c=r)
        self.assertEqual((r.writes, r.pin_calls), ([], []))
        r.reg[0x6B, 8], r.fail_write = b"\x00", (0x6B, 3)
        with self.assertRaises(OSError):
            r.build(i2c=r)
        self.assertEqual(r.pin_calls, [])
        self.assertTrue(all(w[0] == 0x6B for w in r.writes))


    def test_suspect_imu_control_states_never_get_reconfigured(self):
        for ctrl1, ctrl2, ctrl7 in ((0x60, 0, 0x80), (0x60, 0x80, 0),
                                     (0x60, 0x15, 0), (0x60, 0x15, 4),
                                     (0x60, 0x15, 0x41), (0x21, 0, 0)):
            with self.subTest(ctrl1=ctrl1, ctrl2=ctrl2, ctrl7=ctrl7):
                r = Rig()
                for reg, value in ((2, ctrl1), (3, ctrl2), (8, ctrl7)):
                    r.reg[0x6B, reg] = bytes((value,))
                with self.assertRaises(rt.ProfileUnavailable):
                    r.build(i2c=r)
                self.assertFalse(r.writes)
                self.assertIsNone(r.panel)

    def test_imu_dropped_preconfiguration_write_stops_before_enable(self):
        for register in (2, 3):
            r = Rig()
            r.drop_write = (0x6B, register)
            with self.subTest(register=register), self.assertRaisesRegex(
                    rt.ProfileUnavailable, "standby configuration"):
                r.build(i2c=r)
            self.assertNotIn((0x6B, 8, b"\x01"), r.writes)
            self.assertIsNone(r.panel)

    def test_failed_imu_recheck_never_reuses_previous_scale(self):
        r = Rig()
        mov = r.build(i2c=r).mov
        self.assertEqual(mov.read_g(), 1.0)
        del r.reg[0x6B, 3]
        with self.assertRaises(rt.ProfileUnavailable):
            mov.setup()
        self.assertIsNone(mov.read_g())

    def test_rtc_leap_day_is_one_burst_and_fault_recovery_not_cached(self):
        r = Rig()
        rtc = rt.ReadOnlyClock(r, r.clock)
        leap = bytes((0x59, 0x59, 0x23, 0x29, 6, 0x02, 0x28))
        for data, expected in ((leap, (2028, 2, 29, 23, 59, 59)),
                               (leap[:-1] + b"\x27", None),
                               (leap[:4] + b"\x07" + leap[5:], None),
                               (None, None), (BCD, CAL)):
            r.reads.clear()
            r.reg[0x51, 4] = data
            self.assertEqual(rtc.ler(), expected)
            self.assertEqual(r.reads, [(0x51, 0, 1), (0x51, 4, 7)])
        self.assertFalse(r.writes)

    def test_short_power_clears_only_its_w1c_when_armed(self):
        r = Rig()
        r.reg[0x34, 0x49] = b"\x0C"
        p = r.build(i2c=r, allow_power_key=True)
        self.assertTrue(p.capabilities["power_key"])
        self.assertEqual(r.reg[0x34, 0x49], b"\x04")
        r.reg[0x34, 0x49] = b"\x0C"
        self.assertTrue(p.bateria.tecla())
        self.assertFalse(p.bateria.tecla())
        self.assertEqual(r.reg[0x34, 0x49], b"\x04")
        r.reg[0x34, 0x49], r.reg[0x34, 0x41] = b"\x0C", b"\x00"
        self.assertFalse(p.bateria.tecla())
        r.reg[0x34, 0x41], r.reg[0x34, 3] = b"\x08", b"\x00"
        self.assertFalse(p.bateria.tecla())
        self.assertEqual([w for w in r.writes if w[0] == 0x34],
                         [(0x34, 0x49, b"\x08")] * 2)

    def test_invalid_battery_is_unknown_not_a_fake_percent(self):
        r = Rig()
        b = r.build(i2c=r).bateria
        r.reg[0x34, 0xA4] = b"\xff"
        self.assertIsNone(b.porcentagem())
        for status in (b"\x00", b""):
            r.reg[0x34, 0] = status
            self.assertIsNone(b.porcentagem())
            self.assertFalse(b.carregando())

    def test_bad_rtc_calendar_is_not_time_and_never_written(self):
        r = Rig()
        rtc = rt.ReadOnlyClock(r, r.clock)
        for ctrl, date in ((0x20, BCD), (0x02, BCD), (0x80, BCD), (0, b""),
                           (0, b"\x80" + BCD[1:]), (0, b"\x6A" + BCD[1:]),
                           (0, BCD[:3] + b"\x30\x00\x02\x26"),
                           (0, BCD[:-1] + b"\x24")):
            with self.subTest(ctrl=ctrl, date=date):
                r.reg[0x51, 0], r.reg[0x51, 4] = bytes((ctrl,)), date
                self.assertIsNone(rtc.ler())
                self.assertEqual(rtc.epoch(), 0)
        self.assertEqual(r.writes, [])

    def test_optional_audio_is_injected_and_closed(self):
        r, calls = Rig(), []
        r.found.append(0x18)
        sound = SimpleNamespace(ligado=False, available=True, microphone_available=False,
                                tocar=lambda name: calls.append(name),
                                atualizar=lambda: None, volume_mic=lambda: 0,
                                close=lambda: calls.append("end"))

        def factory(bus, **opts):
            self.assertIs(bus, r)
            self.assertEqual(opts, {"confirmed_v1": True, "machine_module": r.machine,
                                    "clock": r.clock})
            calls.append("start")
            return sound

        p = r.build(i2c=r, audio_factory=factory)
        self.assertIs(p.som, sound)
        self.assertTrue(p.capabilities["audio"])
        self.assertFalse(p.capabilities["microphone"])
        p.som.tocar("feliz")
        p.close()
        self.assertEqual(calls, ["start", "feliz", "end"])
        self.assertFalse(any(w[0] == 0x18 for w in r.writes))

    def test_invalid_audio_adapter_is_closed_when_not_usable(self):
        r, events = Rig(), []
        r.found.append(0x18)
        with self.assertRaises(rt.ProfileUnavailable):
            r.build(i2c=r, audio_factory=lambda *_a, **_k:
                    SimpleNamespace(close=lambda: events.append("close")))
        self.assertEqual(events, ["close"])


if __name__ == "__main__":
    unittest.main()
