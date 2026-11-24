"""Experimental Waveshare ESP32-S3-Touch-AMOLED-1.8 V1 bridge.

V1 ONLY: SH8601 QSPI + FT3168 I2C 0x38, TCA9554 0x20.
V2 CO5300/CST820 is explicitly rejected.

The existing game uses a 240x284 RGB565 framebuf and ST7789 byte-swapped
colors. Preserve that drawing ABI; transmit either a 1:1 reference or a
near-full, aspect-preserving viewport through native QSPI. Touch uses the
same transform as the pixels.

This module never flashes firmware. It must only run on a suitable
MicroPython build with amoled.QSPIPanel and amoled.AMOLED.
The default MedveGoshi launcher and IPS driver are not changed.
No attempt to emulate SH8601 with regular SPI. Not hardware-tested.

Reference: github.com/dobodu/Lilygo_Waveshare_Amoled_Micropython/
examples/config/WS_180_AMOLED.py (MIT)
"""
import time as _time

from ports.v1_scale import (LOGICAL_W, LOGICAL_H, PANEL_W, PANEL_H,
                            SCALE_LARGE, SCALE_NATIVE, VIEWPORT_LARGE,
                            VIEWPORT_NATIVE, Scaler, viewport_for)

OFFSET_X, OFFSET_Y = VIEWPORT_NATIVE.x, VIEWPORT_NATIVE.y
FRAME_BYTES = LOGICAL_W * LOGICAL_H * 2

_LCD_CASET = 0x2A
_LCD_RASET = 0x2B


def _address_window(start, size):
    last = start + size - 1  # SH8601 RAM window uses inclusive end addresses.
    return bytes((start >> 8, start & 0xFF, last >> 8, last & 0xFF))


TOUCH_ADDR = 0x38
V2_TOUCH_ADDR = 0x15
EXPANDER_ADDR = 0x20
I2C_SCL = 14
I2C_SDA = 15

QSPI_HZ = 40_000_000  # Waveshare SH8601 QSPI preset
GPIO_CS = 12
GPIO_CLK = 11
GPIO_TE = 13  # NOT panel reset; reset goes through TCA9554 EXIO0
GPIO_DATA = (4, 5, 6, 7)
GPIO_TOUCH_IRQ = 21
EXPANDER_POWER_BIT = 1
EXPANDER_PANEL_RESET_BIT = 0
EXPANDER_TOUCH_RESET_BIT = 2


class BoardMismatch(RuntimeError):
    pass


class DriverUnavailable(RuntimeError):
    pass


def validate_v1_bus(i2c, verified_v1=False):
    """Never change board GPIOs before identifying the revision.

    FT3168 might be in reset at cold boot. If the board label was
    independently confirmed V1, only its reset may be released to probe.
    Never do this for an unidentified board or one with touch 0x15.
    """
    present = set(i2c.scan())
    if V2_TOUCH_ADDR in present:
        raise BoardMismatch("Touch 0x15 found: V2/CST820 or incompatible board")
    if EXPANDER_ADDR not in present:
        raise BoardMismatch("TCA9554 (0x20) not found; wrong board")
    if TOUCH_ADDR not in present and verified_v1:
        # FT3168 datasheet 3.5: at least 5ms reset and 70ms until
        # points are reported. Do not pulse a responding controller.
        set_expander_bit(i2c, EXPANDER_TOUCH_RESET_BIT, False)
        _settle(20)
        set_expander_bit(i2c, EXPANDER_TOUCH_RESET_BIT, True)
        _settle(80)
        present = set(i2c.scan())
    if TOUCH_ADDR not in present:
        raise BoardMismatch("FT3168 0x38 not found; confirm V1 label first")
    if V2_TOUCH_ADDR in present:
        raise BoardMismatch("Ambiguous FT3168+CST820 bus: no hardware writes")
    return present


def _settle(ms):
    if hasattr(_time, "sleep_ms"):
        _time.sleep_ms(ms)
    else:
        _time.sleep(ms / 1000)


def set_expander_bit(i2c, bit, enabled):
    """Set one TCA9554 output and retain every unrelated pin's state."""
    conf = i2c.readfrom_mem(EXPANDER_ADDR, 0x03, 1)[0]
    output = i2c.readfrom_mem(EXPANDER_ADDR, 0x01, 1)[0]
    mask = 1 << bit
    # Stage the latch before enabling an output, so a stale latch
    # cannot momentarily drive the opposite state when it was an input.
    new_value = (output | mask) if enabled else (output & ~mask)
    i2c.writeto_mem(EXPANDER_ADDR, 0x01, bytes((new_value,)))
    i2c.writeto_mem(EXPANDER_ADDR, 0x03, bytes((conf & ~mask,)))


def enable_amoled_power(i2c):
    """Enable panel voltage on EXIO1 only."""
    set_expander_bit(i2c, EXPANDER_POWER_BIT, True)


# Compatibility for the small independent diagnostics and previews.
physical_to_logical = VIEWPORT_NATIVE.physical_to_logical
logical_to_physical = VIEWPORT_NATIVE.logical_to_physical


class FT3168Touch:
    """Minimal FT3168 register read, no reset/power writes during sampling."""
    def __init__(self, i2c, viewport=VIEWPORT_NATIVE):
        self.i2c = i2c
        self.viewport = viewport

    def ler(self):
        # TP_INT can be a pulse. Sampling its level would drop contacts
        # between polls. Perform one I2C read, without retries on idle NACK.
        try:
            # 0x02 = finger count, 0x03..0x06 = XH/XL/YH/YL.
            data = self.i2c.readfrom_mem(TOUCH_ADDR, 0x02, 5)
        except OSError:
            return None
        if len(data) != 5 or (data[0] & 0x0F) != 1:
            return None
        event = (data[1] >> 6) & 3
        if event not in (0, 2):  # down or contact, not up or invalid
            return None
        x = ((data[1] & 0x0F) << 8) | data[2]
        y = ((data[3] & 0x0F) << 8) | data[4]
        if not (0 <= x < PANEL_W and 0 <= y < PANEL_H):
            return None
        return self.viewport.physical_to_logical(x, y)


class Tela:
    """Game-compatible 240x284 framebuffer; native driver owns AMOLED QSPI."""
    def __init__(self, display, panel, framebuffer_module, viewport=VIEWPORT_NATIVE):
        self.display = display
        self.panel = panel
        self.buf = bytearray(FRAME_BYTES)
        self.fb = framebuffer_module.FrameBuffer(
            self.buf, LOGICAL_W, LOGICAL_H, framebuffer_module.RGB565)
        self.viewport = viewport
        self._columns = _address_window(viewport.x, viewport.width)
        self._rows = _address_window(viewport.y, viewport.height)
        self.menu_text = self.menu_notice = None
        self.scene_text = self.scene_metrics = self.scene_cover = None
        self._notice = None
        self._scene_top = 0
        self._scaler = self._menu = self._scene = self._native_fb = None
        self.wire_buf = self.buf
        if viewport is VIEWPORT_LARGE:
            from ports import v1_menu_font
            self._font = v1_menu_font
            self._scaler = Scaler(viewport)
            self.wire_buf = bytearray(self._scaler.output_bytes)
            self._native_fb = framebuffer_module.FrameBuffer(
                self.wire_buf, viewport.width, viewport.height, framebuffer_module.RGB565)
            self._menu = []
            self._scene = []
            self.menu_text = self._queue_text
            self.menu_notice = self._queue_notice
            self.scene_text = self._queue_scene_text
            self.scene_metrics = self._scene_metrics
            self.scene_cover = self._scene_cover

    def _queue_text(self, text, x, y, color, esc=1, box=None):
        return self._queue_label(self._menu, text, x, y, color, esc, box)

    def _queue_scene_text(self, text, x, y, color, esc=1, box=None):
        return self._queue_label(self._scene, text, x, y, color, esc, box)

    def _scene_metrics(self, text, esc=1):
        if esc not in (1, 2) or not self._font.supports(text):
            return None
        w, h = self._font.measure(text, esc), self._font.height(esc)
        vw, vh = self.viewport.width, self.viewport.height
        return ((w * LOGICAL_W + vw - 1) // vw, (h * LOGICAL_H + vh - 1) // vh)

    def _scene_cover(self, logical_y):
        # Logical RGB565 already contains the sliding panel. Never paint
        # delayed scene letters over it; suppress labels intersecting its edge.
        self._scene_top = self.viewport.pixel_origin(0, max(0, int(logical_y)))[1]

    def _queue_label(self, queue, text, x, y, color, esc, box):
        if esc not in (1, 2) or len(queue) >= 32 or not self._font.supports(text):
            return False
        origin = self.viewport.pixel_origin
        x, y = origin(x, y)
        y -= 2  # baseline aligns with the legacy label anchor
        if box is not None:
            bx, by, bw, bh = box
            left, top = origin(bx, by)
            right, bottom = origin(bx + bw, by + bh)
            x = (left + right - self._font.measure(text, esc)) // 2
            if bh:
                y = (top + bottom - self._font.height(esc)) // 2
        if y + self._font.height(esc) > 0 and y < self.viewport.height:
            queue.append((text, x, y, color, esc))
        return True

    def _queue_notice(self, text, bg, fg):
        self._notice = (text, bg, fg)
        return True

    def _draw_notice(self):
        text, bg, fg = self._notice
        width = self._font.measure(text)
        w = min(self.viewport.width - 16, width + 32)
        x = (self.viewport.width - w) // 2
        _, y = self.viewport.pixel_origin(0, 36)
        h = 27
        # Rounded corners without relying on framebuf ellipse in host fixtures.
        for row in range(h):
            edge = min(row, h - 1 - row)
            inset = (9, 6, 4, 3, 2, 1, 1)[edge] if edge < 7 else 0
            self._native_fb.fill_rect(x + inset, y + row, w - 2 * inset, 1, bg)
        self._font.draw(self._native_fb, text, (self.viewport.width - width) // 2,
                        y + (h - self._font.height()) // 2, fg)

    def brilho(self, percent):
        if not (0 <= percent <= 100):
            raise ValueError("AMOLED brightness must be 0..100 percent")
        self.display.brightness(int(percent * 255 / 100 + 0.5))

    def mostrar(self):
        if len(self.buf) != FRAME_BYTES:
            raise ValueError("Incorrect AMOLED V1 RGB565 frame size")
        # The pinned native bitmap() disagrees on inclusive end coordinates
        # and payload length. Its separate framebuffer is not updated by the
        # direct transfer, so refresh() afterwards would overwrite this frame.
        # Set the SH8601 window ourselves and send all RGB565 wire bytes;
        # native tx_color issues RAMWR and uses the actual buffer length.
        try:
            if self._scaler is not None:
                self._scaler.copy(self.buf, self.wire_buf)
                if self._scene:
                    for label in self._scene:
                        if not self._scene_top or label[2] >= self._scene_top:
                            self._font.draw(self._native_fb, *label)
                if self._menu:
                    for label in self._menu:
                        self._font.draw(self._native_fb, *label)
                if self._notice is not None:
                    self._draw_notice()
            self.panel.tx_param(_LCD_CASET, self._columns)
            self.panel.tx_param(_LCD_RASET, self._rows)
            self.panel.tx_color(0, self.wire_buf)
        finally:
            if self._menu:
                self._menu.clear()
            if self._scene:
                self._scene.clear()
            self._scene_top = 0
            self._notice = None


def prepare_v1(i2c, machine_module=None, amoled_module=None,
               framebuffer_module=None, verified_v1=False, screen_mode=SCALE_NATIVE):
    """Explicit opt-in driver init; fail closed when dependencies are absent.

    Requires separately built native MicroPython QSPI support. This module
    is NOT shipped or enabled by the IPS installer.
    """
    viewport = viewport_for(screen_mode)  # validate before any hardware I/O
    validate_v1_bus(i2c, verified_v1=verified_v1)
    if amoled_module is None:
        try:
            import amoled as amoled_module
        except ImportError:
            raise DriverUnavailable(
                "Firmware lacks the native SH8601 QSPI amoled module")
    if machine_module is None:
        import machine as machine_module
    if framebuffer_module is None:
        import framebuf as framebuffer_module
    if not all(hasattr(amoled_module, k) for k in ("QSPIPanel", "AMOLED")):
        raise DriverUnavailable("Incomplete native AMOLED module")

    Pin = machine_module.Pin
    SPI = machine_module.SPI
    cs = Pin(GPIO_CS, Pin.OUT)
    clock = Pin(GPIO_CLK, Pin.OUT)
    data = tuple(Pin(pin, Pin.OUT) for pin in GPIO_DATA)

    # Requires a compiled QSPI controller; ordinary SPI is insufficient.
    spi = SPI(2, baudrate=QSPI_HZ, sck=clock,
              mosi=None, miso=None, polarity=0, phase=0)
    panel = amoled_module.QSPIPanel(
        spi=spi, data=data, dc=data[1], cs=cs, pclk=QSPI_HZ,
        width=PANEL_W, height=PANEL_H)
    if not (callable(getattr(panel, "tx_param", None)) and
            callable(getattr(panel, "tx_color", None))):
        raise DriverUnavailable("Native SH8601 QSPI transport is unavailable")
    # Waveshare pulses its V1 panel reset through EXIO0. Assert it
    # while powering/stabilizing EXIO1, but do not cycle an already-on rail.
    set_expander_bit(i2c, EXPANDER_PANEL_RESET_BIT, False)
    enable_amoled_power(i2c)
    _settle(20)
    set_expander_bit(i2c, EXPANDER_PANEL_RESET_BIT, True)
    _settle(20)
    display = amoled_module.AMOLED(
        panel, type=2, bpp=16, auto_refresh=False)
    display.reset()
    display.init()
    display.brightness(0)
    # Establish black borders once; only the centred game changes later.
    display.fill(0)
    display.refresh()
    screen = Tela(display, panel, framebuffer_module, viewport)
    screen.brilho(50)
    return screen, FT3168Touch(i2c, viewport)
