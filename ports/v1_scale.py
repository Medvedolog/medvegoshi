"""AMOLED V1 geometry and bounded nearest-neighbour RGB565 conversion.

Draw the game once at its original logical resolution. Panel and touch share
one mapping; no float math or per-frame buffer allocation in the scaler.
"""
from array import array

LOGICAL_W, LOGICAL_H = 240, 284
PANEL_W, PANEL_H = 368, 448
SCALE_NATIVE, SCALE_LARGE = "1:1", "large"


class Viewport:
    def __init__(self, width, height):
        self.width, self.height = width, height
        self.x, self.y = (PANEL_W - width) // 2, (PANEL_H - height) // 2

    def physical_to_logical(self, x, y):
        if not isinstance(x, int) or not isinstance(y, int):
            return None
        x, y = x - self.x, y - self.y
        if not (0 <= x < self.width and 0 <= y < self.height):
            return None
        return x * LOGICAL_W // self.width, y * LOGICAL_H // self.height

    def pixel_origin(self, x, y):
        # Inverse of the exact floor mapping used for pixels and touch.
        return ((x * self.width + LOGICAL_W - 1) // LOGICAL_W,
                (y * self.height + LOGICAL_H - 1) // LOGICAL_H)

    def logical_to_physical(self, x, y):
        if not (isinstance(x, int) and isinstance(y, int) and
                0 <= x < LOGICAL_W and 0 <= y < LOGICAL_H):
            return None
        left, top = self.pixel_origin(x, y)
        right, bottom = self.pixel_origin(x + 1, y + 1)
        return self.x + (left + right - 1) // 2, self.y + (top + bottom - 1) // 2


VIEWPORT_NATIVE = Viewport(LOGICAL_W, LOGICAL_H)
VIEWPORT_LARGE = Viewport(PANEL_W, LOGICAL_H * PANEL_W // LOGICAL_W)


def viewport_for(mode):
    if mode == SCALE_NATIVE:
        return VIEWPORT_NATIVE
    if mode == SCALE_LARGE:
        return VIEWPORT_LARGE
    raise ValueError("AMOLED V1 screen_mode must be 'large' or '1:1'")


try:
    import micropython
except ImportError:
    micropython = None


if micropython is not None:
    @micropython.viper
    def _scale(source, output, x_table, y_table, width: int, height: int):
        src = ptr16(source)
        dst = ptr16(output)
        xs = ptr16(x_table)
        ys = ptr32(y_table)
        i = 0
        for y in range(height):
            row = ys[y]
            for x in range(width):
                dst[i] = src[row + xs[x]]
                i += 1
else:
    def _scale(source, output, x_table, y_table, width, height):
        # Both use the same native halfword order, so wire bytes pass through
        # untouched (including high/low byte ordering set by the game).
        src = memoryview(source).cast("H")
        dst = memoryview(output).cast("H")
        for y, row in enumerate(y_table):
            base = y * width
            for x, sx in enumerate(x_table):
                dst[base + x] = src[row + sx]


class Scaler:
    def __init__(self, port):
        self.width, self.height = port.width, port.height
        self.x_table = array("H", (x * LOGICAL_W // self.width
                                   for x in range(self.width)))
        self.y_table = array("I", (y * LOGICAL_H // self.height * LOGICAL_W
                                   for y in range(self.height)))
        self.input_bytes = LOGICAL_W * LOGICAL_H * 2
        self.output_bytes = self.width * self.height * 2

    def copy(self, source, output):
        if (source is output or len(source) != self.input_bytes or
                len(output) != self.output_bytes):
            raise ValueError("Incorrect distinct buffers for AMOLED V1 scaler")
        _scale(source, output, self.x_table, self.y_table, self.width, self.height)
