"""V1 standalone microphone/PCM/SD smoke flow on mock hardware."""
import struct
import unittest
from types import SimpleNamespace

from ports import amoled_v1 as board
from ports import amoled_v1_audio as audio
from ports import amoled_v1_sd_smoke as sd
from ports import amoled_v1_voice_smoke as voice
from test_amoled_v1_audio import Bus, Clock, Pin, TX


class VoiceBus(Bus):
    def __init__(self, trace):
        super().__init__(trace, found=(0x18, 0x20, 0x34, 0x38))
        self.pmu = {3: 0x4A, 0x90: 0x40, 0x92: 0x99}

    def readfrom_mem(self, addr, reg, size):
        if addr == 0x34:
            return bytes((self.pmu[reg],))
        return super().readfrom_mem(addr, reg, size)

    def writeto_mem(self, addr, reg, data):
        if addr == 0x34:
            self.trace.append(("pmu", reg, data[0]))
            self.pmu[reg] = data[0]
        else:
            super().writeto_mem(addr, reg, data)


class RX:
    def __init__(self, fixture):
        self.f = fixture
        self.calls = 0

    def readinto(self, buf):
        assert self.f.polled and self.f.pa.value_now == 0
        self.f.clock.sleep_ms(8)
        self.calls += 1
        if self.f.broken:
            return 7
        # Early quiet frames, then sound only in the second DMA slot.
        data = 0 if self.f.silent or self.calls < 18 else 0x12340000
        buf[:] = struct.pack("<iiii", 0, data, 0, -data) * (len(buf) // 16)
        return len(buf)

    def deinit(self):
        self.f.trace.append(("rx closed",))


class Fixture:
    def __init__(self):
        self.trace = []
        self.clock = Clock()
        self.clock.ms = 65500
        self.bus = VoiceBus(self.trace)
        self.silent = self.broken = self.no_data = self.polled = False
        self.tx = None
        def pin(*args, **kwargs):
            p = Pin(self.trace, *args, **kwargs)
            if args[0] == audio.PA_ENABLE:
                self.pa = p
            return p
        pin.OUT = Pin.OUT
        def i2s(ident, **kwargs):
            if kwargs["mode"] == 1:
                assert ident == 0 and kwargs["sd"].number == 10
                assert kwargs["bits"] == 32 and kwargs["rate"] == 16000
                return RX(self)
            assert ("rx closed",) in self.trace
            self.tx = TX(self.trace, ident, **kwargs)
            return self.tx
        i2s.RX, i2s.TX, i2s.STEREO = 1, 2, 3
        self.machine = SimpleNamespace(Pin=pin, I2S=i2s)
        def make_poll():
            fixture = self
            class Poll:
                def register(self, stream, mask):
                    self.stream, self.mask = stream, mask
                def unregister(self, stream):
                    assert stream is self.stream
                def poll(self, timeout):
                    assert timeout == 0
                    fixture.polled = self.stream.polled = True
                    return [] if fixture.no_data else [(self.stream, self.mask)]
            return Poll()
        self.select = SimpleNamespace(poll=make_poll, POLLIN=1, POLLOUT=4, POLLERR=8)

    def run(self, enabled=True, confirmed_v1=True):
        return voice.run(self.bus, enabled=enabled, confirmed_v1=confirmed_v1,
                         duration_ms=250, machine_module=self.machine, clock=self.clock,
                         select_module=self.select, announce=lambda _: None)


class VoiceTests(unittest.TestCase):
    def test_capture_then_play_with_restored_rail_and_clocks(self):
        f = Fixture()
        result = f.run()
        self.assertEqual(result["frames"], 4000)
        self.assertEqual(result["peak_to_peak"], 0x2468)
        self.assertEqual(f.bus.pmu, {3: 0x4A, 0x90: 0x40, 0x92: 0x99})
        self.assertIn(("pmu", 0x92, 0x9c), f.trace)
        self.assertIn(("pmu", 0x90, 0x41), f.trace)
        self.assertIn(bytes.fromhex("0000341200003412"), b"".join(f.tx.writes))
        self.assertEqual(f.pa.value_now, 0)
        self.assertGreater(len(f.tx.writes), 3)

    def test_refuses_without_opt_in_or_with_wrong_board_or_codec(self):
        f = Fixture()
        with self.assertRaisesRegex(audio.AudioUnavailable, "opt-in"):
            f.run(enabled=False)
        self.assertFalse(f.trace)
        f.bus.found = (0x15, 0x18, 0x20, 0x34)
        with self.assertRaises(board.BoardMismatch):
            f.run()
        self.assertFalse(f.trace)
        f.bus.found = (0x18, 0x20, 0x34, 0x38)
        f.bus.chip = (0, 0)
        with self.assertRaisesRegex(audio.AudioUnavailable, "identity"):
            f.run()
        self.assertFalse(any(x[0] in ("pmu", "reg", "pin") for x in f.trace))

    def test_capture_errors_never_play_and_restore_owned_rail(self):
        for attr, expected in (("broken", "length"), ("silent", "signal"),
                               ("no_data", "timed out")):
            with self.subTest(attr=attr):
                f = Fixture()
                setattr(f, attr, True)
                with self.assertRaisesRegex(audio.AudioUnavailable, expected):
                    f.run()
                self.assertIn(("rx closed",), f.trace)
                self.assertEqual(f.bus.pmu, {3: 0x4A, 0x90: 0x40, 0x92: 0x99})
                self.assertEqual(f.pa.value_now, 0)
                self.assertIsNone(f.tx)

    def test_never_reprogram_a_live_rail(self):
        f = Fixture()
        f.bus.pmu[0x90] = 0x41
        with self.assertRaisesRegex(audio.AudioUnavailable, "unexpected voltage"):
            f.run()
        self.assertFalse(any(x[0] in ("pmu", "reg") for x in f.trace))
        f.bus.pmu[0x92] = 0x9c
        self.assertEqual(f.run()["frames"], 4000)
        self.assertFalse(any(x[0] == "pmu" for x in f.trace))

    def test_codec_write_error_still_releases_receive_channel(self):
        f = Fixture()
        f.bus.fail_reg = 0x14
        with self.assertRaisesRegex(OSError, "write failed"):
            f.run()
        self.assertIn(("rx closed",), f.trace)
        self.assertEqual(f.bus.pmu[0x90], 0x40)


class SDTests(unittest.TestCase):
    def test_only_reads_and_closes(self):
        trace = []
        class Card:
            def __init__(self, **kw):
                trace.append(kw)
            def ioctl(self, op, arg):
                trace.append((op, arg))
                return {4: 4096, 5: 512}[op]
            def readblocks(self, block, buf):
                trace.append((block, len(buf)))
                return True
            def deinit(self):
                trace.append("close")
        options = dict(enabled=True, confirmed_v1=True,
                       machine_module=SimpleNamespace(SDCard=Card))
        self.assertEqual(sd.probe(Bus([]), **options)["bytes"], 4096 * 512)
        self.assertEqual(trace, [
            dict(slot=1, width=1, sck=2, cmd=1, data=(3,), freq=10_000_000),
            (4, 0), (5, 0), (0, 512), "close"])
        with self.assertRaises(board.BoardMismatch):
            sd.probe(Bus([], found=(0x15,)), **options)
        self.assertEqual(len(trace), 5)
        Card.readblocks = lambda *_: False
        with self.assertRaisesRegex(OSError, "sector zero"):
            sd.probe(Bus([]), **options)
        self.assertEqual(trace[-1], "close")
