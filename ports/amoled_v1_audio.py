"""Opt-in, playback-only ES8311 audio for Waveshare AMOLED 1.8 *V1*.

Wiring: Waveshare V1 board_peripherals.yaml (I2S0, 9/45/8, PA 46).
Identity, mute, and word length: ES8311 datasheet and user guide at
files.waveshare.com/wiki/common/ES8311.{DS,user.Guide}.pdf.
Clock coefficients: Espressif esp-bsp's es8311.c (1024000/16000).

The pinned ESP32 I2S implementation leaves MCLK unused. Use Philips
I2S 32-bit stereo slots (64*Fs), and use their BCLK as the codec clock,
with x4 internal prescaling. No phase-independent PWM or ADC driver.
Host-checked, not verified on physical hardware. No boot activation.
"""

from ports.amoled_v1 import validate_v1_bus

ES8311_ADDR = 0x18
I2S_ID = 0
I2S_BCLK, I2S_WS, I2S_DOUT, PA_ENABLE = 9, 45, 8, 46
SAMPLE_RATE = 16000
DMA_BYTES = 8192
FRAMES = 256
FRAME_BYTES = 8
MAX_WRITES_PER_UPDATE = 4
DRAIN_MS = 90  # At most 64 ms in pinned ESP32 DMA, plus margin.
MAX_CLIP_MS = 4000

DAC_VOLUME, DAC_MUTE = 0x32, 0x31
MUTE_BITS = 0x60
# 0xBF is unity, 0.5 dB per step: default -14 dB, capped at -12 dB.
DEFAULT_VOLUME, MAX_VOLUME = 0xA3, 0xA7
_TONE, _PIP = 1, 2

_CODEC_PROFILE = (
    (0x01, 0xBF),             # SCLK/BCLK as clock source, no inversion
    (0x02, 0x10),             # predivide /1, pre-multiply x4
    (0x03, 0x10), (0x04, 0x10), (0x05, 0x00),
    (0x06, 0x03), (0x07, 0x10), (0x08, 0xFF),
    (0x09, 0x10),             # slave Philips I2S, left, 32-bit input
    (0x0A, 0x50),             # 32-bit serial output muted
    (0x0D, 0x01),             # analog circuitry powered
    (0x0E, 0x7A),             # ADC off and held in reset
    (0x12, 0x00), (0x13, 0x10),  # DAC on, output enabled
    (0x34, 0x00), (0x37, 0x08),  # automatic gain off, equalizer bypass
)

# Bounded UI sounds, independent of Pip's voice or any audio assets.
_TONES = {
    "clique": (1600, 35), "feliz": (900, 125), "amor": (780, 150),
    "comer": (630, 100), "banho": (1020, 110), "remedio": (800, 140),
    "susto": (1150, 90), "bocejo": (435, 145), "piu": (1400, 85),
    "triste": (365, 145), "festa": (1050, 200), "pulo": (860, 115),
}
_PIP_SOUNDS = ("poke", "happy", "sad", "growl", "oh", "love", "purr",
               "nom", "burp", "yawn", "dizzy", "derp", "hm", "censor",
               "alarm", "hmph", "tick")


class AudioUnavailable(RuntimeError):
    pass


class V1Audio:
    """Call atualizar() in the game loop and close() in its finally block."""

    microphone_available = False

    def __init__(self, i2c, machine, native, clock, select_api, volume):
        self._bus, self._native, self._clock = i2c, native, clock
        self._volume = volume
        self._mono = bytearray(FRAMES * 2)
        self._stereo = bytearray(FRAMES * FRAME_BYTES)
        self._view = memoryview(self._stereo)
        self._tx = self._poller = None
        self._codec_claimed = False
        self._active = self._amplifying = False
        self._enabled = True
        self._pending = None
        self._offset = self._end = 0
        self._drain_until = None
        self._natural_drain = False
        self._prime = self._more = False
        self._closed = False
        self._last_error = None

        pin, i2s = machine.Pin, machine.I2S
        self._pa = pin(PA_ENABLE, pin.OUT, value=0)
        self._poll_out = select_api.POLLOUT
        self._poll_fault = (getattr(select_api, "POLLERR", 0) |
                            getattr(select_api, "POLLHUP", 0) |
                            getattr(select_api, "POLLNVAL", 0))
        try:
            self._tx = i2s(I2S_ID, sck=pin(I2S_BCLK), ws=pin(I2S_WS),
                           sd=pin(I2S_DOUT), mode=i2s.TX, bits=32,
                           format=i2s.STEREO, rate=SAMPLE_RATE, ibuf=DMA_BYTES)
            self._poller = select_api.poll()
            self._poller.register(self._tx, self._poll_out)
            # Pinned ESP32 MP_STREAM_POLL enables the timeout=0 DMA writer.
            self._ready()
            self._codec_claimed = True
            self._configure(volume)
        except (Exception, KeyboardInterrupt):
            self.close()
            raise

    def _reg(self, address, value):
        self._bus.writeto_mem(ES8311_ADDR, address, bytes((value,)))

    def _verify_dac(self, muted):
        mute = self._bus.readfrom_mem(ES8311_ADDR, DAC_MUTE, 1)
        volume = self._bus.readfrom_mem(ES8311_ADDR, DAC_VOLUME, 1)
        want = MUTE_BITS if muted else 0
        if len(mute) != 1 or (mute[0] & MUTE_BITS) != want or volume != bytes((self._volume,)):
            raise AudioUnavailable("ES8311 DAC mute/volume readback mismatch")

    def _configure(self, volume):
        self._reg(0x00, 0x1F)
        self._clock.sleep_ms(20)
        self._reg(0x00, 0x00)
        self._reg(DAC_MUTE, MUTE_BITS)
        self._reg(DAC_VOLUME, 0)
        self._reg(0x00, 0x80)
        for addr, value in _CODEC_PROFILE:
            self._reg(addr, value)
        self._reg(DAC_VOLUME, volume)
        self._verify_dac(muted=True)

    @property
    def available(self):
        return not self._closed

    @property
    def native_voice_available(self):
        return self.available and self._native is not None

    @property
    def last_error(self):
        return self._last_error

    @property
    def ligado(self):
        return self.available and self._enabled

    @ligado.setter
    def ligado(self, value):
        enabled = bool(value)
        if not enabled and self._enabled and self.available:
            self._pending = None
            if self._active or self._amplifying:
                try:
                    self._mute()
                    self._active = self._natural_drain = False
                    self._offset = self._end = 0
                    # Drop old audio by letting its DMA drain with PA off.
                    self._drain_until = self._clock.ticks_add(
                        self._clock.ticks_ms(), DRAIN_MS)
                except (Exception, KeyboardInterrupt) as exc:
                    self._fail(exc)
                    if isinstance(exc, KeyboardInterrupt):
                        raise
        self._enabled = enabled

    def volume_mic(self):
        """Microphone deliberately unavailable; this never samples the ADC."""
        return 0

    def tocar(self, name):
        if self.ligado and isinstance(name, str) and name in _TONES:
            self._pending = (_TONE, _TONES[name])
            return True
        return False

    def play_pip(self, name):
        """Queue a supported nonverbal Pip sound (separate from UI sounds)."""
        if self.ligado and self.native_voice_available and name in _PIP_SOUNDS:
            self._pending = (_PIP, name)
            return True
        return False

    def _mute(self):
        try:
            self._pa.value(0)
        finally:
            self._amplifying = False
            if self._codec_claimed:
                self._reg(DAC_MUTE, MUTE_BITS)

    def _start(self, now):
        self._kind, payload = self._pending
        self._pending = None
        if self._kind == _PIP:
            self._native.voice_start(payload, SAMPLE_RATE)
        else:
            self._freq, duration = payload
            self._tone_total = duration * SAMPLE_RATE // 1000
            self._tone_at = self._phase = 0
        # Prime silence before unmuting the DAC and physical amp.
        for n in range(len(self._stereo)):
            self._stereo[n] = 0
        self._started = now
        self._active = self._more = self._prime = True
        self._offset, self._end = 0, len(self._stereo)

    def _render(self):
        mono, stereo = self._mono, self._stereo
        if self._kind == _PIP:
            self._more = bool(self._native.voice_render_into(mono))
            frames = FRAMES  # Native zero-fills the tail of the final chunk.
        else:
            frames = min(FRAMES, self._tone_total - self._tone_at)
            for i in range(frames):
                amp = min(64, self._tone_at, self._tone_total - 1 - self._tone_at) * 64
                v = amp if self._phase < SAMPLE_RATE // 2 else -amp
                mono[i * 2] = v & 255
                mono[i * 2 + 1] = (v >> 8) & 255
                self._phase = (self._phase + self._freq) % SAMPLE_RATE
                self._tone_at += 1
            self._more = self._tone_at < self._tone_total
        for i in range(frames):
            p, s = i * FRAME_BYTES, i * 2
            lo, hi = mono[s], mono[s + 1]
            # PCM16 -> PCM32 with a 16-bit left shift; little-endian, two slots.
            stereo[p] = stereo[p + 1] = stereo[p + 4] = stereo[p + 5] = 0
            stereo[p + 2] = stereo[p + 6] = lo
            stereo[p + 3] = stereo[p + 7] = hi
        self._offset, self._end = 0, frames * FRAME_BYTES

    def _ready(self):
        ready = False
        for event in self._poller.poll(0):
            if event[0] is self._tx:
                mask = event[1]
                if mask & self._poll_fault:
                    raise AudioUnavailable("I2S stream error")
                if mask & self._poll_out:
                    ready = True
        return ready

    def atualizar(self):
        """Bounded work; at most MAX_WRITES_PER_UPDATE zero-timeout writes."""
        if not self.available:
            return
        try:
            now = self._clock.ticks_ms()
            if self._drain_until is not None:
                if self._clock.ticks_diff(now, self._drain_until) < 0:
                    return
                self._drain_until = None
                if self._natural_drain:
                    self._mute()
                    self._natural_drain = False
            if not self.ligado:
                return
            if not self._active:
                if self._pending is None:
                    return
                self._start(now)
            if self._clock.ticks_diff(now, self._started) >= MAX_CLIP_MS:
                raise AudioUnavailable("audio exceeded playback watchdog")
            for _ in range(MAX_WRITES_PER_UPDATE):
                if not self._ready():
                    return
                if self._offset == self._end:
                    self._render()
                count = self._tx.write(self._view[self._offset:self._end])
                if (type(count) is not int or count < 0 or
                        count > self._end - self._offset or count % FRAME_BYTES):
                    raise AudioUnavailable("invalid I2S write length")
                if count == 0:
                    return
                self._offset += count
                if self._offset < self._end:
                    return
                if self._prime:
                    self._prime = False
                    self._reg(DAC_MUTE, 0)
                    # Keep the physical amp low until the digital mute and
                    # conservative volume are both independently confirmed.
                    self._verify_dac(muted=False)
                    self._pa.value(1)
                    self._amplifying = True
                elif not self._more:
                    self._active = False
                    self._natural_drain = True
                    self._drain_until = self._clock.ticks_add(now, DRAIN_MS)
                    return
        except (Exception, KeyboardInterrupt) as exc:
            self._fail(exc)
            if isinstance(exc, KeyboardInterrupt):
                raise

    def _fail(self, exc):
        self._last_error = str(exc)
        self.close()

    def close(self):
        """Latch off, muting both paths; success/failure prevents future playback."""
        if self._closed:
            return
        self._closed = True
        self._pending = None
        self._active = False
        try:
            self._mute()
        except Exception as exc:
            self._last_error = self._last_error or str(exc)
        if self._poller is not None:
            try:
                self._poller.unregister(self._tx)
            except Exception as exc:
                self._last_error = self._last_error or str(exc)
        if self._tx is not None:
            try:
                self._tx.deinit()
            except Exception as exc:
                self._last_error = self._last_error or str(exc)
        self._poller = self._tx = None


def make_audio(i2c, *, confirmed_v1=False, machine_module=None,
               native_module=None, clock=None, select_module=None,
               volume=DEFAULT_VOLUME):
    """Prepare an explicitly confirmed and probed V1 in a muted state.

    Requires stream-pollable I2S TX, no blocking fallback. A missing native
    Pip module still allows bounded UI tones. This does not validate a speaker.
    """
    if confirmed_v1 is not True:
        raise AudioUnavailable("physical AMOLED V1 confirmation is required")
    if type(volume) is not int or not 1 <= volume <= MAX_VOLUME:
        raise ValueError("V1 DAC volume outside the conservative limit")
    validate_v1_bus(i2c)  # read-only; refuse V2/unknown, no expander writes
    if (i2c.readfrom_mem(ES8311_ADDR, 0xFD, 1) != b"\x83" or
            i2c.readfrom_mem(ES8311_ADDR, 0xFE, 1) != b"\x11"):
        raise AudioUnavailable("ES8311 identity mismatch")
    if machine_module is None:
        import machine as machine_module
    if native_module is None:
        try:
            import pip_native as native_module
        except ImportError:
            pass
    if (not callable(getattr(native_module, "voice_start", None)) or
            not callable(getattr(native_module, "voice_render_into", None))):
        native_module = None
    if clock is None:
        import time as clock
    if select_module is None:
        import select as select_module
    return V1Audio(i2c, machine_module, native_module, clock, select_module, volume)
