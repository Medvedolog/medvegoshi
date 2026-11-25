"""Bounded, manually started SH8601/FT3168 V1 diagnostic; no game saves."""
from ports import amoled_v1

AXP_ADDR = 0x34
AXP_ID_REG = 0x03
AXP_ID = 0x4A
PWR_ENABLE_REG = 0x41
PWR_STATUS_REG = 0x49
PWR_SHORT = 0x08
BOOT_PIN = 0
FRAME_MS = 40
MAX_FRAMES = 1500


class PowerKey:
    """Observe an already-enabled short press; acknowledge only its W1C bit.

    Never enable IRQs or change voltage, charging, shutdown, or sleep policy.
    X-Powers AXP2101 datasheet, IRQ enable/status registers 41h and 49h.
    """

    def __init__(self, i2c):
        self.i2c = i2c
        self.enabled = False
        self._armed = False
        try:
            self.enabled = self._short_enabled()
        except OSError:
            pass
        # The first verified poll only establishes a fresh baseline.
        self.poll()

    def _read(self, register):
        data = self.i2c.readfrom_mem(AXP_ADDR, register, 1)
        if not isinstance(data, (bytes, bytearray)) or len(data) != 1:
            raise OSError("short AXP2101 read")
        return data[0]

    def _short_enabled(self):
        return (self._read(AXP_ID_REG) == AXP_ID and
                bool(self._read(PWR_ENABLE_REG) & PWR_SHORT))

    def poll(self):
        if not self.enabled:
            return None
        try:
            if not self._short_enabled():
                self._armed = False
                return None
            pressed = bool(self._read(PWR_STATUS_REG) & PWR_SHORT)
            if pressed:
                self.i2c.writeto_mem(AXP_ADDR, PWR_STATUS_REG, bytes((PWR_SHORT,)))
            if not self._armed:
                self._armed = True
                return False
            return pressed
        except OSError:
            # If a read or W1C failed, the next observable IRQ may be stale.
            self._armed = False
            return None


class BootKey:
    """Recognize active-low GPIO0 after two consecutive 40 ms samples."""

    def __init__(self, pin):
        self.pin = pin
        self.stable = bool(pin.value())
        self.last = self.stable

    def poll(self):
        raw = bool(self.pin.value())
        pressed = False
        if raw == self.last and raw != self.stable:
            self.stable = raw
            pressed = not raw
        self.last = raw
        return pressed


def read_wifi_label(network_module=None):
    """Inspect existing STA without activating, connecting, or scanning."""
    try:
        if network_module is None:
            import network as network_module
        iface = getattr(network_module, "STA_IF", None)
        if iface is None:
            iface = network_module.WLAN.IF_STA
        sta = network_module.WLAN(iface)
        if not sta.active():
            return "WIFI: OFF"
        if sta.isconnected():
            return "WIFI: LINK"
        return "WIFI: NO LINK"
    except (ImportError, AttributeError, OSError):
        return "WIFI: N/A"


def _draw(screen, art, point, contact, touches, boots, powers, power_available,
          wifi_label):
    fb = screen.fb
    art.usar(fb)
    fb.fill(art.C(art.CREME))
    ink = art.C(art.INK)
    fb.rect(0, 0, amoled_v1.LOGICAL_W, amoled_v1.LOGICAL_H, ink)
    art.centro("AMOLED V1", 12, art.INK, 1)
    art.centro("Жирафик", 28, art.TEXTO, 1)
    eyes = "feliz" if contact else ("normal", "feliz", "susto")[boots % 3]
    art.personagem("girafa", 120, 210, olhos=eyes, boca="sorriso", fase="adulto")
    fb.text("TOUCH:%d BOOT:%d" % (touches, boots), 8, 230, ink)
    fb.text("PWR:%d" % powers if power_available else "PWR: N/A", 8, 246, ink)
    fb.text(wifi_label, 8, 262, ink)
    if point is not None:
        x, y = point
        marker = art.C((226, 75, 74) if contact else (58, 138, 232))
        fb.fill_rect(x - 4, y, 9, 1, marker)
        fb.fill_rect(x, y - 4, 1, 9, marker)
    screen.mostrar()


def _validate_frames(frames):
    if type(frames) is not int or not (1 <= frames <= MAX_FRAMES):
        raise ValueError("frames must be an integer from 1 to %d" % MAX_FRAMES)


def run_loop(screen, touch, boot, power_key, *, frames, art, clock,
             wifi_label="WIFI: OFF"):
    """Poll a finite number of times; redraw only when something changes."""
    _validate_frames(frames)
    boot_key = BootKey(boot)
    touches = boots = powers = 0
    power_available = False
    contact = None
    point = None
    previous_state = None
    for frame in range(frames):
        sample = touch.ler()
        if sample is not None:
            if contact is None:
                touches += 1
            point = sample
        contact = sample
        if boot_key.poll():
            boots += 1
        power_sample = power_key.poll()
        power_available = power_sample is not None
        if power_sample is True:
            powers += 1
        state = (point, contact, touches, boots, powers, power_available)
        if state != previous_state:
            _draw(screen, art, point, contact is not None, touches, boots,
                  powers, power_available, wifi_label)
            previous_state = state
        if frame + 1 < frames:
            clock.sleep_ms(FRAME_MS)
    return {"frames": frames, "touches": touches, "boot_presses": boots,
            "power_presses": powers, "power_available": power_available,
            "wifi": wifi_label}


def run(*, confirmed_v1=False, frames=300, i2c=None, machine_module=None,
        prepare=None, art=None, clock=None, wifi_status=None):
    """Call from the REPL after checking the physical V1 label. Never auto-boot.

    A short PWR tap is the test input; do not hold the hardware power button.
    Wi-Fi is not touched by default. `wifi_status=True` observes existing STA.
    """
    if confirmed_v1 is not True:
        raise RuntimeError("Confirm the physical V1 label before running")
    _validate_frames(frames)
    if machine_module is None:
        import machine as machine_module
    if clock is None:
        import time as clock
    if prepare is None:
        prepare = amoled_v1.prepare_v1
    pin = machine_module.Pin
    if i2c is None:
        i2c = machine_module.I2C(0, scl=pin(amoled_v1.I2C_SCL),
                                 sda=pin(amoled_v1.I2C_SDA), freq=400000)
    # No GPIO0 or PMIC setup before the V1 display/touch guard succeeded.
    screen, touch = prepare(i2c, machine_module=machine_module, verified_v1=True)
    if art is None:
        import desenho as art
        from zoo import registry
        # The general game can fall back to Capy. A labelled V1 demo must not.
        if "girafa" not in art.ELENCO or registry.renderer("girafa") is None:
            raise RuntimeError("Giraffe plugin missing; include zoo/animals/girafa and zoo/giraffe")
    boot = pin(BOOT_PIN, pin.IN, pin.PULL_UP)
    power_key = PowerKey(i2c)
    if wifi_status is True:
        wifi_label = read_wifi_label()
    elif callable(wifi_status):
        wifi_label = wifi_status()
    else:
        wifi_label = "WIFI: OFF"
    return run_loop(screen, touch, boot, power_key, frames=frames, art=art,
                    clock=clock, wifi_label=wifi_label)
