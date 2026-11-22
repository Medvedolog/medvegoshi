"""Experimental Waveshare ESP32-S3-Touch-AMOLED-1.8 V1 bridge.

V1 ONLY: SH8601 QSPI + FT3168 I2C 0x38, TCA9554 0x20.
V2 CO5300/CST820 is explicitly rejected.

The existing game uses a 240x284 RGB565 framebuf and ST7789 byte-swapped
colors. Keep that exact drawing ABI and transfer its big-endian RGB565 bytes
into the centre of the 368x448 V1 display through the native QSPI panel
transport. The surrounding pixels remain black.

This module never flashes firmware. It must only run on a suitable
MicroPython build with amoled.QSPIPanel and amoled.AMOLED.
The default MedveGoshi launcher and IPS driver are not changed.
No attempt to emulate SH8601 with regular SPI. Not hardware-tested.

Reference: github.com/dobodu/Lilygo_Waveshare_Amoled_Micropython/
examples/config/WS_180_AMOLED.py (MIT)
"""
LOGICAL_W = 240
LOGICAL_H = 284
PANEL_W = 368
PANEL_H = 448
OFFSET_X = (PANEL_W - LOGICAL_W) // 2
OFFSET_Y = (PANEL_H - LOGICAL_H) // 2
FRAME_BYTES = LOGICAL_W * LOGICAL_H * 2

_LCD_CASET = 0x2A
_LCD_RASET = 0x2B


def _address_window(start, size):
    last = start + size - 1  # SH8601 RAM window uses inclusive end addresses.
    return bytes((start >> 8, start & 0xFF, last >> 8, last & 0xFF))


_COLUMN_WINDOW = _address_window(OFFSET_X, LOGICAL_W)
_ROW_WINDOW = _address_window(OFFSET_Y, LOGICAL_H)

TOUCH_ADDR = 0x38
V2_TOUCH_ADDR = 0x15
EXPANDER_ADDR = 0x20
I2C_SCL = 14
I2C_SDA = 15

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
        set_expander_bit(i2c, EXPANDER_TOUCH_RESET_BIT, True)
        # The FT3168 requires reset release before its first I2C response.
        import time
        time.sleep_ms(50) if hasattr(time, "sleep_ms") else time.sleep(0.05)
        present = set(i2c.scan())
    if TOUCH_ADDR not in present:
        raise BoardMismatch("FT3168 0x38 not found; confirm V1 label first")
    if V2_TOUCH_ADDR in present:
        raise BoardMismatch("Ambiguous FT3168+CST820 bus: no hardware writes")
    return present


def set_expander_bit(i2c, bit, enabled):
    """Set one TCA9554 output and retain every unrelated pin's state."""
    conf = i2c.readfrom_mem(EXPANDER_ADDR, 0x03, 1)[0]
    output = i2c.readfrom_mem(EXPANDER_ADDR, 0x01, 1)[0]
    mask = 1 << bit
    i2c.writeto_mem(EXPANDER_ADDR, 0x03, bytes((conf & ~mask,)))
    new_value = (output | mask) if enabled else (output & ~mask)
    i2c.writeto_mem(EXPANDER_ADDR, 0x01, bytes((new_value,)))


def enable_amoled_power(i2c):
    """Enable panel voltage on EXIO1 only."""
    set_expander_bit(i2c, EXPANDER_POWER_BIT, True)


def physical_to_logical(x, y):
    """Map only the letterboxed 240x284 game region; ignore black margins."""
    if not isinstance(x, int) or not isinstance(y, int):
        return None
    if not (OFFSET_X <= x < OFFSET_X + LOGICAL_W and
            OFFSET_Y <= y < OFFSET_Y + LOGICAL_H):
        return None
    return x - OFFSET_X, y - OFFSET_Y


def logical_to_physical(x, y):
    if not (0 <= x < LOGICAL_W and 0 <= y < LOGICAL_H):
        return None
    return x + OFFSET_X, y + OFFSET_Y


class FT3168Touch:
    """Minimal FT3168 register read, no reset/power writes during sampling."""
    def __init__(self, i2c):
        self.i2c = i2c

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
        return physical_to_logical(x, y)


class Tela:
    """Game-compatible 240x284 framebuffer; native driver owns AMOLED QSPI."""
    def __init__(self, display, panel, framebuffer_module):
        self.display = display
        self.panel = panel
        self.buf = bytearray(FRAME_BYTES)
        self.fb = framebuffer_module.FrameBuffer(
            self.buf, LOGICAL_W, LOGICAL_H, framebuffer_module.RGB565)

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
        self.panel.tx_param(_LCD_CASET, _COLUMN_WINDOW)
        self.panel.tx_param(_LCD_RASET, _ROW_WINDOW)
        self.panel.tx_color(0, self.buf)


def prepare_v1(i2c, machine_module=None, amoled_module=None,
               framebuffer_module=None, verified_v1=False):
    """Explicit opt-in driver init; fail closed when dependencies are absent.

    Requires separately built native MicroPython QSPI support. This module
    is NOT shipped or enabled by the IPS installer.
    """
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
    spi = SPI(2, baudrate=80_000_000, sck=clock,
              mosi=None, miso=None, polarity=0, phase=0)
    panel = amoled_module.QSPIPanel(
        spi=spi, data=data, dc=data[1], cs=cs, pclk=80_000_000,
        width=PANEL_W, height=PANEL_H)
    if not (callable(getattr(panel, "tx_param", None)) and
            callable(getattr(panel, "tx_color", None))):
        raise DriverUnavailable("Native SH8601 QSPI transport is unavailable")
    # Real V1 panel reset EXIO0 and touch reset EXIO2 are not ESP32 GPIOs.
    # Release the panel reset first. Power is on EXIO1.
    set_expander_bit(i2c, EXPANDER_PANEL_RESET_BIT, True)
    enable_amoled_power(i2c)
    display = amoled_module.AMOLED(
        panel, type=2, bpp=16, auto_refresh=False)
    display.reset()
    display.init()
    display.brightness(0)
    # Establish black borders once; only the centred game changes later.
    display.fill(0)
    display.refresh()
    screen = Tela(display, panel, framebuffer_module)
    screen.brilho(50)
    return screen, FT3168Touch(i2c)
