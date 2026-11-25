"""Run explicitly on a MicroPython build which imports pip_native."""
import pip_native as pip


def raises(kind, func, *args):
    try:
        func(*args)
    except kind:
        return
    raise AssertionError("expected exception")


def run():
    now = 1795377600
    assert pip.ABI_VERSION == 1
    pip.reset(1, now, 180)
    initial = pip.status()
    assert initial["now"] == now and initial["tz_min"] == 180
    assert set(initial["needs"]) == {"food", "energy", "fun", "love", "walk"}
    assert set(initial["reason"]) == {"kind", "which", "value", "hold"}
    pip.advance(now + 3600)
    raises(ValueError, pip.advance, now)
    raises(ValueError, pip.event, "feed\0")
    raises(ValueError, pip.event, "unknown")
    pip.event("feed")
    pip.event("sleep")
    saved = pip.export_state()
    assert 26 < len(saved) <= pip.MAX_STATE_BYTES
    parked = pip.status()
    assert parked["asleep"] and parked["mood"] == "asleep"
    pip.reset(98, now + 2 * 3600, -60)
    pip.import_state(saved)
    assert pip.status() == parked
    corrupt = bytearray(saved)
    corrupt[-1] ^= 1
    raises(ValueError, pip.import_state, corrupt)
    raises(ValueError, pip.import_state, saved[:-1])
    assert pip.status() == parked

    raises(ValueError, pip.voice_start, "not-a-sound")
    raises(ValueError, pip.voice_render_into, bytearray(3))
    raises(ValueError, pip.voice_render_into, bytearray(pip.VOICE_MAX_BYTES + 2))
    raises(TypeError, pip.voice_render_into, bytes(64))
    # Offset intentionally misaligned to exercise the byte-wise PCM copy.
    backing = bytearray(257)
    chunk = memoryview(backing)[1:]
    pip.voice_start("happy")
    heard = False
    for _ in range(200):
        more = pip.voice_render_into(chunk)
        heard = heard or any(chunk)
        if not more:
            break
    else:
        raise AssertionError("voice never finished")
    assert heard and not pip.voice_render_into(chunk) and not any(chunk)
    eyes = bytearray(72 * 36 * 2)
    neutral = (0, 0, 0, 0, 0, 0, 0, 0)
    x1, y1, x2, y2 = pip.eyes_draw_into(eyes, 72, 36, neutral)
    assert 0 <= x1 <= x2 < 72 and 0 <= y1 <= y2 < 36
    assert any(eyes) and eyes[:2] == bytes(2) and pip.EYES_BLACK_KEY == 0
    prior = bytes(eyes)
    raises(ValueError, pip.eyes_draw_into, eyes, 72, 36, (float("nan"),) + neutral[1:])
    assert prior == eyes
    raises(ValueError, pip.eyes_draw_into, bytearray(36), 72, 36, neutral)
    raises(TypeError, pip.eyes_draw_into, prior, 72, 36, neutral)
    pip.eyes_draw_into(eyes, 72, 36, (0, 0, 1, 1, 0, 0, 0, 0))
    assert prior != eyes
    print("Pip native C smoke passed")


if __name__ == "__main__":
    run()
