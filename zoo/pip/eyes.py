"""Small clipped tile for the original Pip C eyes; optional runtime feature."""
_CACHE = None
_TRIED = False


def pose_for(style, mood, now):
    gx = -0.42 if style in ("esquerda", "olhar_esq") else (
        0.42 if style in ("direita", "olhar_dir") else (0.0, 0.11, 0.0, -0.11)[(now // 700) % 4])
    close = style in ("fechados", "sono", "dormindo") or mood == "asleep"
    half = mood in ("sleepy", "tired", "exhausted", "bored")
    joy = style in ("feliz", "alegre") or mood in ("happy", "love", "cheeky", "content")
    lid = 1.0 if close else (0.42 if half else 0.0)
    return (gx, 0.16 if half else 0.0, lid, lid, 0.65 if joy and not close else 0.0,
            0.0, 0.72 if mood == "love" and not close else 0.0,
            0.38 if joy and not close else 0.0)


class Eyes:
    """One reusable RGB565 buffer; no touch, display, or GPIO access."""

    def __init__(self, native, framebuf):
        method = getattr(native, "eyes_draw_into", None)
        if not callable(method):
            raise ValueError("original Pip eyes are unavailable")
        self.draw = method
        self.framebuf = framebuf
        self.dimensions = None
        self.data = self.tile = self.last = None

    def prepare(self, w, h, pose):
        if not (16 <= w <= 84 and 12 <= h <= 50):
            return None
        if self.dimensions != (w, h):
            data = bytearray(w * h * 2)
            tile = self.framebuf.FrameBuffer(data, w, h, self.framebuf.RGB565)
            self.data, self.tile = data, tile
            self.dimensions, self.last = (w, h), None
        if self.last != pose:
            try:
                self.draw(self.data, w, h, pose, True)
            except (OSError, TypeError, ValueError, RuntimeError, MemoryError):
                self.last = None
                return None
            self.last = pose
        return self.tile


def try_tile(fb, x, y, w, h, style, mood, now, screen_width=240, screen_height=284):
    global _CACHE, _TRIED
    if not callable(getattr(fb, "blit", None)):
        return None
    if not (0 <= x and 0 <= y and x + w <= screen_width and y + h <= screen_height):
        return None
    if not _TRIED:
        _TRIED = True
        try:
            import framebuf
            import pip_native
            _CACHE = Eyes(pip_native, framebuf)
        except (ImportError, OSError, TypeError, ValueError, MemoryError):
            return None
    if _CACHE is None:
        return None
    try:
        return _CACHE.prepare(w, h, pose_for(style, mood, now))
    except MemoryError:
        return None
