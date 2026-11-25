"""Explicit standalone V1 ES8311 capture/playback; no network or file writes.

Run only from an idle REPL after a fresh boot, not while the game or another
I2S user is active. No microphone activation on import or at game startup.
"""
from ports import amoled_v1_audio as audio
from ports import v1_game_hal as hal

MIC_DATA = 10
ALDO_ENABLE = 0x90
ALDO1_VOLTAGE = 0x92
ALDO1_BIT = 1
ALDO1_3V3 = 28
RX_CHUNK = 1024  # 128 stereo32 frames
SETTLE_MS = 100

# Keep our existing BCLK-derived 16 kHz clock/32-bit slots. XiaoZhi otherwise
# uses a different clock path (MCLK at GPIO16) and its entire codec setup is
# not interchangeable. ADC settings are from Espressif's ES8311 reference.
_ADC_PROFILE = (
    (0x14, 0x1A),  # analog mic/PGA (not a digital PDM microphone)
    (0x17, 0xBF),  # unity digital gain, not XiaoZhi's gain policy
    (0x1C, 0x6A),  # EQ bypass, DC cancellation
    (0x0E, 0x02),  # ADC and analog PGA on
    (0x0A, 0x10),  # 32-bit Philips serial audio, output enabled
)


def _get(bus, dev, reg):
    value = bus.readfrom_mem(dev, reg, 1)
    if not isinstance(value, (bytes, bytearray)) or len(value) != 1:
        raise audio.AudioUnavailable("invalid audio register read")
    return value[0]


def _put(bus, dev, reg, value):
    bus.writeto_mem(dev, reg, bytes((value,)))


def _codec(bus, reg, value):
    _put(bus, audio.ES8311_ADDR, reg, value)


def _capture(bus, machine, clock, select, pcm):
    rx = poller = None
    registered = claimed = rail = voltage_changed = False
    saved_voltage = None
    raw = bytearray(RX_CHUNK)
    # The pinned ESP32 port may expose reversed slot order. Keep both mono
    # candidates through the short RAM-only test; select after the utterance,
    # not on a few leading silent frames. At most 128 kB total PCM at 2 s.
    other = bytearray(len(pcm))
    pos = 0
    cleanup_error = None
    try:
        pa = machine.Pin(audio.PA_ENABLE, machine.Pin.OUT, value=0)
        enable = _get(bus, hal.PMU_ADDR, ALDO_ENABLE)
        saved_voltage = _get(bus, hal.PMU_ADDR, ALDO1_VOLTAGE)
        if (saved_voltage & 0x1F) != ALDO1_3V3:
            if enable & ALDO1_BIT:
                raise audio.AudioUnavailable("active ALDO1 has unexpected voltage")
            voltage_changed = True
            _put(bus, hal.PMU_ADDR, ALDO1_VOLTAGE,
                 (saved_voltage & ~0x1F) | ALDO1_3V3)
        if not enable & ALDO1_BIT:
            rail = True
            _put(bus, hal.PMU_ADDR, ALDO_ENABLE, enable | ALDO1_BIT)
        if (_get(bus, hal.PMU_ADDR, ALDO_ENABLE) & ALDO1_BIT == 0 or
                _get(bus, hal.PMU_ADDR, ALDO1_VOLTAGE) & 0x1F != ALDO1_3V3):
            raise audio.AudioUnavailable("microphone rail readback mismatch")
        i2s, pin = machine.I2S, machine.Pin
        rx = i2s(audio.I2S_ID, sck=pin(audio.I2S_BCLK), ws=pin(audio.I2S_WS),
                 sd=pin(MIC_DATA), mode=i2s.RX, bits=32, format=i2s.STEREO,
                 rate=audio.SAMPLE_RATE, ibuf=audio.DMA_BYTES)
        poller = select.poll()
        poller.register(rx, select.POLLIN)
        registered = True
        claimed = True
        _codec(bus, 0x00, 0x1F)
        clock.sleep_ms(20)
        _codec(bus, 0x00, 0x00)
        _codec(bus, audio.DAC_MUTE, audio.MUTE_BITS)
        _codec(bus, audio.DAC_VOLUME, 0)
        _codec(bus, 0x00, 0x80)
        for reg, value in audio._CODEC_PROFILE:
            _codec(bus, reg, value)
        for reg, value in _ADC_PROFILE:
            _codec(bus, reg, value)
        if (_get(bus, audio.ES8311_ADDR, audio.DAC_MUTE) & audio.MUTE_BITS != audio.MUTE_BITS or
                _get(bus, audio.ES8311_ADDR, 0x0A) != 0x10):
            raise audio.AudioUnavailable("codec ADC/DAC readback mismatch")
        start = clock.ticks_ms()
        faults = (getattr(select, "POLLERR", 0) | getattr(select, "POLLHUP", 0) |
                  getattr(select, "POLLNVAL", 0))
        deadline = len(pcm) * 1000 // (audio.SAMPLE_RATE * 2) + 1400
        low0 = low1 = 32767
        high0 = high1 = -32768
        while pos < len(pcm):
            elapsed = clock.ticks_diff(clock.ticks_ms(), start)
            if elapsed >= deadline:
                raise audio.AudioUnavailable("I2S capture timed out")
            n = 0
            for event in poller.poll(0):
                if event[0] is not rx:
                    continue
                events = event[1]
                if events & faults:
                    raise audio.AudioUnavailable("I2S capture poll failed")
                if events & select.POLLIN:
                    n = rx.readinto(raw)
                break
            if type(n) is not int or n < 0 or n > len(raw) or n % 8:
                raise audio.AudioUnavailable("invalid I2S capture length")
            if not n:
                clock.sleep_ms(1)
                continue
            if elapsed < SETTLE_MS:
                continue  # drain startup frames, not just wait with a full ring
            for at in range(0, n, 8):
                if pos >= len(pcm):
                    break
                v0, v1 = _sample(raw, at + 2), _sample(raw, at + 6)
                low0, high0 = min(low0, v0), max(high0, v0)
                low1, high1 = min(low1, v1), max(high1, v1)
                pcm[pos], pcm[pos + 1] = raw[at + 2], raw[at + 3]
                other[pos], other[pos + 1] = raw[at + 6], raw[at + 7]
                pos += 2
    finally:
        # Attempt every cleanup even when a previous cleanup action failed.
        actions = []
        if claimed:
            actions.extend((lambda: _codec(bus, 0x0A, 0x50),
                            lambda: _codec(bus, 0x0E, 0x7A),
                            lambda: _codec(bus, audio.DAC_MUTE, audio.MUTE_BITS)))
        if registered:
            actions.append(lambda: poller.unregister(rx))
        if rx is not None:
            actions.append(rx.deinit)
        if rail:
            actions.append(lambda: _restore_rail(bus))
        if voltage_changed:
            actions.append(lambda: _restore_voltage(bus, saved_voltage))
        for action in actions:
            try:
                action()
            except Exception as exc:
                if cleanup_error is None:
                    cleanup_error = exc
        if cleanup_error is not None:
            raise audio.AudioUnavailable("audio cleanup failed: " + str(cleanup_error))
    span0, span1 = high0 - low0, high1 - low1
    if max(span0, span1) < 64:
        raise audio.AudioUnavailable("no changing microphone signal; speak during capture")
    return (other, span1) if span1 > span0 else (pcm, span0)


def _restore_rail(bus):
    now = _get(bus, hal.PMU_ADDR, ALDO_ENABLE)
    _put(bus, hal.PMU_ADDR, ALDO_ENABLE, now & ~ALDO1_BIT)
    if _get(bus, hal.PMU_ADDR, ALDO_ENABLE) & ALDO1_BIT:
        raise audio.AudioUnavailable("ALDO1 did not turn off")


def _restore_voltage(bus, value):
    if _get(bus, hal.PMU_ADDR, ALDO_ENABLE) & ALDO1_BIT:
        raise audio.AudioUnavailable("refusing to change voltage on a live rail")
    _put(bus, hal.PMU_ADDR, ALDO1_VOLTAGE, value)
    if _get(bus, hal.PMU_ADDR, ALDO1_VOLTAGE) != value:
        raise audio.AudioUnavailable("ALDO1 voltage did not restore")


def _sample(raw, at):
    v = raw[at] | raw[at + 1] << 8
    return v if v < 32768 else v - 65536


def run(i2c, *, confirmed_v1=False, enabled=False, duration_ms=1000, machine_module=None,
        clock=None, select_module=None, announce=print):
    """Record a short spoken phrase in RAM, then play it via the existing V1 TX."""
    if enabled is not True or confirmed_v1 is not True:
        raise audio.AudioUnavailable("explicit V1 confirmation and opt-in required")
    if type(duration_ms) is not int or not 250 <= duration_ms <= 2000:
        raise ValueError("capture must be 250–2000 ms")
    audio.validate_v1_bus(i2c)  # no reset or fallback to the V2/IPS code
    if (_get(i2c, hal.PMU_ADDR, hal.PMU_ID_REG) != hal.PMU_ID or
            _get(i2c, audio.ES8311_ADDR, 0xFD) != 0x83 or
            _get(i2c, audio.ES8311_ADDR, 0xFE) != 0x11):
        raise audio.AudioUnavailable("AXP2101 or ES8311 identity mismatch")
    if machine_module is None:
        import machine as machine_module
    if clock is None:
        import time as clock
    if select_module is None:
        import select as select_module
    pcm = bytearray(duration_ms * audio.SAMPLE_RATE // 1000 * 2)
    announce("Говорите: проверка микрофона")
    pcm, peak_to_peak = _capture(i2c, machine_module, clock, select_module, pcm)
    announce("Воспроизведение записи")
    tx = audio.make_audio(i2c, confirmed_v1=True, machine_module=machine_module,
                          clock=clock, select_module=select_module)
    try:
        if not tx.play_pcm(bytes(pcm)):
            raise audio.AudioUnavailable("could not queue recorded audio")
        start = clock.ticks_ms()
        while tx.busy and clock.ticks_diff(clock.ticks_ms(), start) < audio.MAX_CLIP_MS + 600:
            tx.atualizar()
            clock.sleep_ms(1)
        if tx.busy or tx.last_error:
            raise audio.AudioUnavailable(tx.last_error or "I2S playback timed out")
    finally:
        tx.close()
    if tx.last_error:
        raise audio.AudioUnavailable(tx.last_error)
    return {"frames": len(pcm) // 2, "sample_rate": audio.SAMPLE_RATE,
            "peak_to_peak": peak_to_peak, "audibility_requires_operator": True}
