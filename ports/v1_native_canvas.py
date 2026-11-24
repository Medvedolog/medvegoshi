"""Draw the 240x284 scene, in order, directly to an AMOLED RGB565 surface.

The panel viewport is already trimmed to its active pixels. Coordinates passed
to this canvas are local to that viewport, never global panel coordinates.
Rectangle endpoints share one mapping, so adjacent same-layer regions cannot
split because their widths were rounded separately. The raw `fb` is available
for authored native sizes (notably text and high resolution animal sprites).
"""
from array import array
import math
from ports.v1_scale import LOGICAL_W, LOGICAL_H

# Two authored rectangles can reach the same edge by different float
# operations. Subtract a tiny tolerance (well below a physical pixel) so
# round-off around an exact physical integer does not separate that edge.
_EDGE_EPSILON = 0.0001


def _wire_word(color):
    """CPython host fixture RGB tuple -> MicroPython wire-order RGB565."""
    if type(color) is int:
        return color
    if isinstance(color, tuple):
        r, g, b = color
        word = ((r & 248) << 8) | ((g & 252) << 3) | (b >> 3)
        return ((word & 255) << 8) | (word >> 8)
    return None


class NativeCanvas:
    native_art = True

    def __init__(self, buffer, framebuffer_module, viewport,
                 logical_width=None, logical_height=None):
        self._module = framebuffer_module
        self._viewport = viewport
        self._vw, self._vh = viewport.width, viewport.height
        self.sx, self.sy = self._vw / LOGICAL_W, self._vh / LOGICAL_H
        self.logical_width = LOGICAL_W if logical_width is None else logical_width
        self.logical_height = LOGICAL_H if logical_height is None else logical_height
        if not (1 <= self.logical_width <= LOGICAL_W and 1 <= self.logical_height <= LOGICAL_H):
            raise ValueError("invalid native canvas extent")
        self.width = self.map_x(self.logical_width)
        self.height = self.map_y(self.logical_height)
        if len(buffer) != self.width * self.height * 2:
            raise ValueError("invalid native RGB565 buffer length")
        self.buf = buffer
        self.fb = framebuffer_module.FrameBuffer(
            buffer, self.width, self.height, framebuffer_module.RGB565)
        self._glyph = None
        self._glyph_buf = None

    def map_x(self, x):
        if type(x) is int:
            return (x * self._vw + LOGICAL_W - 1) // LOGICAL_W
        return int(math.ceil(x * self.sx - _EDGE_EPSILON))

    def map_y(self, y):
        if type(y) is int:
            return (y * self._vh + LOGICAL_H - 1) // LOGICAL_H
        return int(math.ceil(y * self.sy - _EDGE_EPSILON))

    def new_tile(self, logical_width, logical_height):
        if not (1 <= logical_width <= LOGICAL_W and 1 <= logical_height <= LOGICAL_H):
            raise ValueError("invalid native tile extent")
        size = self.map_x(logical_width) * self.map_y(logical_height) * 2
        return NativeCanvas(bytearray(size), self._module, self._viewport,
                            logical_width, logical_height)

    def flush(self):
        """Host image-backed framebuffers need a wire snapshot; device does not."""
        flush = getattr(self.fb, "flush", None)
        if flush is not None:
            flush()

    def fill(self, color):
        self.fb.fill(color)

    def fill_rect(self, x, y, w, h, color):
        if w <= 0 or h <= 0:
            return
        left, top = max(0, self.map_x(x)), max(0, self.map_y(y))
        right = min(self.width, self.map_x(x + w))
        bottom = min(self.height, self.map_y(y + h))
        if left < right and top < bottom:
            self.fb.fill_rect(left, top, right - left, bottom - top, color)

    def pixel(self, x, y, color=None):
        if not (0 <= x < self.logical_width and 0 <= y < self.logical_height):
            return None
        if color is not None:
            self.fill_rect(x, y, 1, 1, color)
            return None
        return _wire_word(self.fb.pixel(self.map_x(x), self.map_y(y)))

    def rect(self, x, y, w, h, color, fill=False):
        if fill or w <= 1 or h <= 1:
            self.fill_rect(x, y, w, h, color)
        else:
            self.fill_rect(x, y, w, 1, color)
            self.fill_rect(x, y + h - 1, w, 1, color)
            if h > 2:
                self.fill_rect(x, y + 1, 1, h - 2, color)
                self.fill_rect(x + w - 1, y + 1, 1, h - 2, color)

    def hline(self, x, y, w, color):
        self.fill_rect(x, y, w, 1, color)

    def vline(self, x, y, h, color):
        self.fill_rect(x, y, 1, h, color)

    def line(self, x, y, x1, y1, color):
        if x == x1:
            self.fill_rect(x, min(y, y1), 1, abs(y1 - y) + 1, color)
        elif y == y1:
            self.fill_rect(min(x, x1), y, abs(x1 - x) + 1, 1, color)
        else:
            self.fb.line(self.map_x(x), self.map_y(y),
                         self.map_x(x1), self.map_y(y1), color)

    def ellipse(self, x, y, rx, ry, color, fill=False, mask=15):
        if rx < 0 or ry < 0:
            return
        cx, cy = self.map_x(x), self.map_y(y)
        # Native and host half-ellipse masks require nonempty quadrants.
        phys_rx = max(1, (self.map_x(x + rx) - self.map_x(x - rx)) // 2)
        phys_ry = max(1, (self.map_y(y + ry) - self.map_y(y - ry)) // 2)
        self.fb.ellipse(cx, cy, phys_rx, phys_ry, color, fill, mask)

    def poly(self, x, y, coords, color, fill=False):
        points = array("h")
        for i in range(0, len(coords) - 1, 2):
            px, py = self.map_x(x + coords[i]), self.map_y(y + coords[i + 1])
            points.append(max(-32768, min(32767, px)))
            points.append(max(-32768, min(32767, py)))
        if len(points) >= 6:
            self.fb.poly(0, 0, points, color, fill)

    def text(self, text, x, y, color):
        # Legacy callers want the eight-logical-pixel advance. Runtime native
        # font callers draw on .fb instead, with physical coordinates.
        if self._glyph is None:
            data = bytearray(8)
            glyph = self._module.FrameBuffer(data, 8, 8, self._module.MONO_HLSB)
            self._glyph_buf, self._glyph = data, glyph
        glyph = self._glyph
        for index, ch in enumerate(text):
            gx = x + index * 8
            if gx >= self.logical_width:
                break
            if gx + 8 <= 0:
                continue
            glyph.fill(0)
            glyph.text(ch, 0, 0, 1)
            for gy in range(8):
                run = -1
                for xx in range(9):
                    if xx < 8 and glyph.pixel(xx, gy):
                        if run < 0:
                            run = xx
                    elif run >= 0:
                        self.fill_rect(gx + run, y + gy, xx - run, 1, color)
                        run = -1

    def blit(self, source, x, y, key=-1, palette=None, width=None, height=None):
        """Nearest-mapped logical RGB565 blit, honoring the transparent key.

        MicroPython's raw FrameBuffer has no public dimensions; pixel()
        returns None outside it. Discover only bounded game-sized extents
        when an existing raw source does not expose dimensions.
        """
        if width is None:
            width = getattr(source, "logical_width", None)
        if height is None:
            height = getattr(source, "logical_height", None)
        if width is None:
            width = _extent(source, 0, LOGICAL_W)
        if height is None:
            height = _extent(source, 1, LOGICAL_H)
        get = source.pixel
        left, top = max(0, -x), max(0, -y)
        right = min(width, self.logical_width - x)
        bottom = min(height, self.logical_height - y)
        for sy in range(top, bottom):
            previous, run = None, left
            for sx in range(left, right):
                color = _wire_word(get(sx, sy))
                if color == key:
                    color = None
                if color is not None and palette is not None:
                    color = _wire_word(palette.pixel(color, 0))
                if color != previous:
                    if previous is not None:
                        self.fill_rect(x + run, y + sy, sx - run, 1, previous)
                    previous, run = color, sx
            if previous is not None:
                self.fill_rect(x + run, y + sy, right - run, 1, previous)


def _extent(src, axis, limit):
    # Find the first out-of-bounds sample in O(log logical extent).
    left, right = 0, limit
    while left < right:
        middle = (left + right) // 2
        value = src.pixel(middle, 0) if axis == 0 else src.pixel(0, middle)
        if value is None:
            right = middle
        else:
            left = middle + 1
    return left
