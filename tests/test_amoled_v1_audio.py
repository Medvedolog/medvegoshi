"""Playback-only AMOLED V1: bus guards, clock/format, nonblocking PCM, cleanup."""
import ctypes
import os
import shlex
import shutil
import struct
import tempfile
import unittest
from types import SimpleNamespace

from ports import amoled_v1_audio as a
from ports.amoled_v1 import BoardMismatch


class Bus:
    def __init__(self, trace, found=(0x18, 0x20, 0x38), chip=(0x83, 0x11)):
        self.trace, self.found, self.chip = trace, found, chip
        self.regs = {}
        self.fail_reg = None

    def scan(self):
        return self.found

    def readfrom_mem(self, address, reg, size):
        self.trace.append(("read", address, reg, size))
        if address != a.ES8311_ADDR or size != 1:
            raise AssertionError("unexpected bus read")
        return bytes((self.chip[reg - 0xFD],))

    def writeto_mem(self, address, reg, data):
        if address != a.ES8311_ADDR:
            raise AssertionError("unexpected device")
        self.trace.append(("reg", reg, data[0]))
        if reg == self.fail_reg:
            raise OSError("codec write failed")
        self.regs[reg] = data[0]


class Pin:
    OUT = 123

    def __init__(self, trace, number, mode=None, value=None):
        self.trace, self.number, self.mode = trace, number, mode
        self.value_now = value
        trace.append(("pin", number, mode, value))

    def value(self, state):
        self.value_now = state
        self.trace.append(("pa", state))


class TX:
    TX, STEREO = 2, 3

    def __init__(self, trace, ident, **opts):
        self.trace, self.ident, self.opts = trace, ident, opts
        self.active = True
        self.deinit_count = 0
        self.polled = False
        self.ready = True
        self.error = 0
        self.limit = None
        self.writes = []
        trace.append(("i2s",))

    def write(self, buf):
        if not self.polled:
            raise AssertionError("would block without poll(0)")
        if not self.active:
            raise AssertionError("deinitialized TX")
        count = len(buf) if self.limit is None else min(self.limit, len(buf))
        self.writes.append(bytes(buf[:count]))
        self.trace.append(("write", count))
        return count

    def deinit(self):
        self.active = False
        self.deinit_count += 1
        self.trace.append(("deinit",))


class Poll:
    def register(self, stream, mask):
        self.stream = stream
        assert mask == 4

    def unregister(self, stream):
        assert self.stream is stream

    def poll(self, timeout):
        assert timeout == 0
        self.stream.polled = True
        if self.stream.error:
            return [(self.stream, self.stream.error)]
        return [(self.stream, 4)] if self.stream.ready else []


class Clock:
    def __init__(self):
        self.ms = 0

    def ticks_ms(self): return self.ms

    def ticks_add(self, value, delta): return (value + delta) % 65536

    def ticks_diff(self, end, start):
        return (end - start + 32768) % 65536 - 32768

    def sleep_ms(self, n): self.ms = self.ticks_add(self.ms, n)


class Voice:
    def __init__(self):
        self.starts = []
        self.renders = 0
        self.more = False
        self.fail = False

    def voice_start(self, sound, rate):
        self.starts.append((sound, rate))

    def voice_render_into(self, buf):
        if self.fail:
            raise RuntimeError("native render failed")
        self.renders += 1
        buf[:] = b"\x34\x12\xcc\xed" + b"\0" * (len(buf) - 4)
        return self.more


class Fixture:
    def __init__(self, found=None, chip=None):
        self.trace, self.pins = [], []
        options = {}
        if found is not None:
            options["found"] = found
        if chip is not None:
            options["chip"] = chip
        self.bus = Bus(self.trace, **options)
        self.voice, self.clock = Voice(), Clock()
        def pin(*args, **kwargs):
            result = Pin(self.trace, *args, **kwargs)
            self.pins.append(result)
            return result
        pin.OUT = Pin.OUT
        def i2s(*args, **kwargs):
            self.tx = TX(self.trace, *args, **kwargs)
            return self.tx
        i2s.TX, i2s.STEREO = TX.TX, TX.STEREO
        self.machine = SimpleNamespace(Pin=pin, I2S=i2s)
        self.select = SimpleNamespace(poll=Poll, POLLOUT=4, POLLERR=8, POLLHUP=16)

    def make(self, confirmed=True, volume=a.DEFAULT_VOLUME, voice=True):
        return a.make_audio(self.bus, confirmed_v1=confirmed,
                            machine_module=self.machine, clock=self.clock,
                            select_module=self.select, volume=volume,
                            native_module=self.voice if voice else False)

    def advance(self, ms): self.clock.sleep_ms(ms)

    def amp(self): return self.pins[0].value_now


class V1AudioTests(unittest.TestCase):
    def test_no_writes_or_pins_on_false_confirmation_v2_and_wrong_codec(self):
        for fx, confirmed, error in (
            (Fixture(), 1, a.AudioUnavailable),
            (Fixture(found=(0x15, 0x18, 0x20)), True, BoardMismatch),
            (Fixture(found=(0x18, 0x20)), True, BoardMismatch),
            (Fixture(chip=(0x83, 0x12)), True, a.AudioUnavailable),
        ):
            with self.assertRaises(error):
                fx.make(confirmed=confirmed)
            self.assertEqual(fx.pins, [])
            self.assertFalse(any(row[0] == "reg" for row in fx.trace))

    def test_conservative_format_clock_and_no_adc_activation(self):
        fx = Fixture()
        with self.assertRaises(ValueError):
            fx.make(volume=a.MAX_VOLUME + 1)
        self.assertEqual(fx.trace, [])
        sound = fx.make()
        self.assertTrue(sound.available)
        self.assertTrue(sound.native_voice_available)
        self.assertEqual([p.number for p in fx.pins], [46, 9, 45, 8])
        self.assertEqual(fx.amp(), 0)
        self.assertEqual(fx.tx.ident, 0)
        self.assertEqual((fx.tx.opts["format"], fx.tx.opts["rate"], fx.tx.opts["bits"]),
                         (TX.STEREO, 16000, 32))
        self.assertNotIn("mck", fx.tx.opts)
        self.assertEqual(fx.bus.regs[0x01], 0xBF)
        self.assertEqual(fx.bus.regs[0x02], 0x10)
        self.assertEqual(fx.bus.regs[0x09], 0x10)
        self.assertEqual(fx.bus.regs[0x0E] & 0x30, 0x30)
        self.assertEqual(fx.bus.regs[0x31], 0x60)
        self.assertEqual(fx.bus.regs[0x32], a.DEFAULT_VOLUME)
        self.assertFalse(sound.microphone_available)
        self.assertEqual(sound.volume_mic(), 0)
        sound.close()

    def test_partial_dma_signed_conversion_and_end_drain_across_tick_wrap(self):
        fx = Fixture()
        sound = fx.make()
        fx.clock.ms = 65500
        fx.tx.limit = 8
        self.assertTrue(sound.play_pip("happy"))
        sound.atualizar()
        self.assertEqual(fx.tx.writes, [b"\0" * 8])
        self.assertEqual(fx.amp(), 0)
        fx.tx.limit = None
        sound.atualizar()
        self.assertEqual(fx.voice.starts, [("happy", 16000)])
        self.assertEqual(fx.tx.writes[1], b"\0" * (a.FRAMES * 8 - 8))
        self.assertEqual(fx.tx.writes[2][:16],
                         b"\0\0\x34\x12\0\0\x34\x12\0\0\xcc\xed\0\0\xcc\xed")
        self.assertEqual(fx.amp(), 1)
        fx.advance(a.DRAIN_MS - 1)
        sound.atualizar()
        self.assertEqual(fx.amp(), 1)
        fx.advance(1)
        sound.atualizar()
        self.assertEqual(fx.amp(), 0)
        self.assertEqual(fx.bus.regs[a.DAC_MUTE], a.MUTE_BITS)
        sound.close()
        sound.close()
        self.assertEqual(fx.tx.deinit_count, 1)

    def test_poll_stall_and_timeout_latch_off_no_blocking_write(self):
        fx = Fixture()
        sound = fx.make()
        fx.tx.ready = False
        self.assertTrue(sound.play_pip("nom"))
        sound.atualizar()
        self.assertEqual(fx.tx.writes, [])
        self.assertEqual(fx.amp(), 0)
        fx.advance(a.MAX_CLIP_MS)
        sound.atualizar()
        self.assertFalse(sound.available)
        self.assertEqual(fx.amp(), 0)
        self.assertFalse(fx.tx.active)
        self.assertIn("watchdog", sound.last_error)

    def test_muting_cancels_pending_and_old_dma_stays_muted(self):
        fx = Fixture()
        sound = fx.make()
        fx.voice.more = True
        self.assertTrue(sound.play_pip("purr"))
        sound.atualizar()
        self.assertEqual(fx.amp(), 1)
        self.assertLessEqual(len(fx.tx.writes), a.MAX_WRITES_PER_UPDATE)
        sound.ligado = False
        self.assertEqual(fx.amp(), 0)
        self.assertFalse(sound.play_pip("nom"))
        sound.ligado = True
        self.assertTrue(sound.play_pip("nom"))
        sound.atualizar()
        self.assertEqual(fx.voice.starts, [("purr", 16000)])
        fx.advance(a.DRAIN_MS)
        sound.atualizar()
        self.assertEqual(fx.voice.starts[-1], ("nom", 16000))
        sound.close()
        self.assertEqual(fx.amp(), 0)

    def test_any_runtime_driver_fault_turns_off_amp_and_i2s(self):
        for fault in ("native", "poll", "short_unaligned", "mute_write"):
            with self.subTest(fault=fault):
                fx = Fixture()
                sound = fx.make()
                fx.voice.more = True
                sound.play_pip("nom")
                sound.atualizar()
                self.assertEqual(fx.amp(), 1)
                if fault == "native":
                    fx.voice.fail = True
                elif fault == "poll":
                    fx.tx.error = 8
                elif fault == "short_unaligned":
                    fx.tx.limit = 3
                else:
                    fx.bus.fail_reg = a.DAC_MUTE
                    sound.ligado = False
                sound.atualizar()
                self.assertFalse(sound.available)
                self.assertEqual(fx.amp(), 0)
                self.assertFalse(fx.tx.active)
                self.assertTrue(sound.last_error)

    def test_ui_tone_works_without_native_and_is_not_pip(self):
        fx = Fixture()
        sound = fx.make(voice=False)
        self.assertFalse(sound.native_voice_available)
        self.assertFalse(sound.play_pip("tick"))
        self.assertFalse(sound.tocar("unknown"))
        self.assertTrue(sound.tocar("clique"))
        sound.atualizar()
        self.assertGreater(len(fx.tx.writes), 1)
        self.assertTrue(any(fx.tx.writes[1]))
        self.assertEqual(fx.voice.starts, [])
        self.assertEqual(fx.voice.renders, 0)

    def test_initial_i2c_failure_leaves_no_energized_amp_or_stream(self):
        fx = Fixture()
        fx.bus.fail_reg = 0x07
        with self.assertRaises(OSError):
            fx.make()
        self.assertEqual(fx.amp(), 0)
        self.assertFalse(fx.tx.active)
        self.assertEqual(fx.bus.regs[a.DAC_MUTE], a.MUTE_BITS)
        self.assertNotIn(("pa", 1), fx.trace)


class RealVoicePcmTest(unittest.TestCase):
    def test_upstream_dsp_reaches_padded_stereo_and_drains(self):
        cc = shlex.split(os.environ.get("CC", "cc"))
        if not cc or not shutil.which(cc[0]):
            self.skipTest("real upstream DSP test requires C compiler")
        from zoo.tools.preview_pip_voice import build, open_voice

        with tempfile.TemporaryDirectory() as temp:
            voice = open_voice(build(temp))
            samples = (ctypes.c_int16 * 128)()

            def start(name, rate):
                voice.voice_init(rate)
                matches = [n for n in range(17)
                           if voice.voice_name(n) == name.encode("ascii")]
                if not matches:
                    raise ValueError(name)
                voice.voice_say(matches[0])

            def render(out):
                # Mirror the native module's 128-frame, signed LE staging.
                for offset in range(0, len(out), 256):
                    count = min(128, (len(out) - offset) // 2)
                    voice.voice_render(samples, count)
                    for i in range(count):
                        struct.pack_into("<h", out, offset + i * 2, samples[i])
                return voice.voice_busy()

            fx = Fixture()
            fx.voice = SimpleNamespace(voice_start=start, voice_render_into=render)
            sound = fx.make()
            self.assertTrue(sound.play_pip("yawn"))
            for _ in range(a.MAX_CLIP_MS // 64):
                sound.atualizar()
                fx.advance(64)
                if fx.tx.writes and fx.amp() == 0:
                    break
            self.assertTrue(sound.available, sound.last_error)
            self.assertEqual(fx.amp(), 0)
            result = b"".join(fx.tx.writes)
            self.assertGreater(len(result), 4 * a.FRAMES * 8)
            self.assertEqual(result[:a.FRAMES * 8], b"\0" * (a.FRAMES * 8))
            frames = list(struct.iter_unpack("<ii", result))
            self.assertTrue(all(l == r and not (l & 0xffff) for l, r in frames))
            self.assertLess(min(x[0] for x in frames), 0)
            self.assertGreater(max(x[0] for x in frames), 0)
            sound.close()


if __name__ == "__main__":
    unittest.main()
