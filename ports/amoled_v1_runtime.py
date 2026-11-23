"""Explicit, experimental Waveshare ESP32-S3-Touch-AMOLED-1.8 V1 game profile.

No code here launches the game, writes the RTC, claims hardware validation,
starts networking, or changes power/charging policy. The caller must verify
the board label and opt in. The default profile is silent; an audio backend
is a separate explicit choice.

See the board schematic and QMI8658C, PCF85063A and AXP2101 datasheets:
https://docs.waveshare.com/ESP32-S3-Touch-AMOLED-1.8/Resources-And-Documents
"""
import math
import struct

from ports import amoled_v1, v1_game_hal
from ports.v1_bringup import BOOT_PIN, PowerKey

I2C_ID = 0
I2C_FREQ = 400000
I2C_TIMEOUT_US = 10000
PROFILE_ID = "amoled_1_8_v1"

_IMU_CTRL1 = 0x02
_IMU_CTRL2 = 0x03
_IMU_CTRL7 = 0x08
_IMU_STATUS0 = 0x2E
_IMU_AX_L = 0x35
_IMU_AEN = 0x01
_IMU_ACCEL_DATA = 0x01
_IMU_AUTOINC = 0x40
_IMU_4G_250HZ = 0x15
_IMU_COUNTS_PER_G = (16384, 8192, 4096, 2048)

_PMU_STATUS1 = 0x00
_PMU_STATUS2 = 0x01
_PMU_PERCENT = 0xA4
_PMU_BAT_PRESENT = 0x08


class ProfileUnavailable(v1_game_hal.GameHALUnavailable):
    """No safe V1 runtime profile can be supplied."""


def _read(bus, addr, reg, count):
    try:
        data = bus.readfrom_mem(addr, reg, count)
    except OSError:
        return None
    return data if isinstance(data, (bytes, bytearray)) and len(data) == count else None


def _byte(bus, addr, reg):
    data = _read(bus, addr, reg, 1)
    return data[0] if data is not None else None


class ReadOnlyClock:
    """PCF85063A calendar. Unavailable data is never mistaken for real time."""

    can_write = False

    def __init__(self, i2c, clock):
        self.i2c = i2c
        self._clock = clock

    def ler(self):
        return v1_game_hal.read_calendar(self.i2c)[1]

    def epoch(self):
        return self._to_epoch(self.ler())

    def _to_epoch(self, calendar):
        if calendar is None:
            return 0
        try:
            return int(self._clock.mktime(calendar + (0, 0)))
        except TypeError:
            # Host fixtures use CPython's 9-element struct_time contract.
            try:
                return int(self._clock.mktime(calendar + (0, 0, -1)))
            except (TypeError, ValueError, OverflowError, OSError):
                return 0
        except (ValueError, OverflowError, OSError):
            return 0

    def acertar(self, *_args):
        return False

    def somar_minutos(self, _minutes):
        return False


class Accel:
    """QMI8658C accelerometer; cold standby setup or read an active config."""

    def __init__(self, i2c, address):
        self.i2c = i2c
        self.address = address
        self.counts_per_g = None

    def _reg(self, register):
        return _byte(self.i2c, self.address, register)

    def _set(self, register, value):
        self.i2c.writeto_mem(self.address, register, bytes((value,)))

    def setup(self):
        # Never reuse the previous range after a failed (re)initialization.
        self.counts_per_g = None
        ctrl1, ctrl2, ctrl7 = (self._reg(r) for r in (_IMU_CTRL1, _IMU_CTRL2, _IMU_CTRL7))
        if ctrl1 is None or ctrl2 is None or ctrl7 is None:
            raise ProfileUnavailable("QMI8658 control registers unreadable")
        if ctrl7 == 0 and ctrl2 == 0 and not ctrl1 & 1:
            # Only the power-on/default standby register combination may be
            # modified; a merely disabled sensor may be owned by other code.
            revised = ctrl1 | _IMU_AUTOINC
            self._set(_IMU_CTRL1, revised)
            self._set(_IMU_CTRL2, _IMU_4G_250HZ)
            # Do not enable measurement if either setting failed silently.
            if (self._reg(_IMU_CTRL1) != revised or
                    self._reg(_IMU_CTRL2) != _IMU_4G_250HZ or
                    self._reg(_IMU_CTRL7) != 0):
                raise ProfileUnavailable("QMI8658 standby configuration not confirmed")
            self._set(_IMU_CTRL7, _IMU_AEN)
            ctrl1, ctrl2, ctrl7 = revised, _IMU_4G_250HZ, self._reg(_IMU_CTRL7)
            if ctrl7 != _IMU_AEN:
                raise ProfileUnavailable("QMI8658 accelerometer enable not confirmed")
        # Reject unknown scaling, active self-test, sync and reserved modes
        # instead of forcefully modifying a sensor already owned by other code.
        scale = (ctrl2 >> 4) & 7
        odr = ctrl2 & 0x0F
        if (not ctrl7 & _IMU_AEN or ctrl7 & 0xCC or ctrl2 & 0x80
                or not ctrl1 & _IMU_AUTOINC or ctrl1 & 0x01
                or scale >= len(_IMU_COUNTS_PER_G) or 9 <= odr <= 11):
            raise ProfileUnavailable("Unsupported active QMI8658 configuration")
        self.counts_per_g = _IMU_COUNTS_PER_G[scale]

    def read_g(self):
        """Return a fresh acceleration norm in g, or None without data."""
        if self.counts_per_g is None:
            return None
        ready = self._reg(_IMU_STATUS0)
        if ready is None or not ready & _IMU_ACCEL_DATA:
            return None
        sample = _read(self.i2c, self.address, _IMU_AX_L, 6)
        if sample is None:
            return None
        x, y, z = struct.unpack("<hhh", sample)
        return math.sqrt(x * x + y * y + z * z) / self.counts_per_g

    def forca_g(self):
        # Old main.py requires a float. A missing sample is a non-motion
        # sentinel, not inferred hardware data; callers can use read_g().
        value = self.read_g()
        return value if value is not None else 1.0


class Battery:
    """AXP2101 read-only status, with separate opt-in short PWR W1C."""

    def __init__(self, i2c, power_key=None):
        self.i2c = i2c
        self._power_key = power_key

    def _reg(self, reg):
        return _byte(self.i2c, v1_game_hal.PMU_ADDR, reg)

    def porcentagem(self):
        status = self._reg(_PMU_STATUS1)
        if status is None or not status & _PMU_BAT_PRESENT:
            return None
        value = self._reg(_PMU_PERCENT)
        return value if value is not None and value <= 100 else None

    def carregando(self):
        status = self._reg(_PMU_STATUS1)
        if status is None or not status & _PMU_BAT_PRESENT:
            return False
        current = self._reg(_PMU_STATUS2)
        return current is not None and ((current >> 5) & 3) == 1

    def tecla(self):
        if self._power_key is None:
            return False
        return self._power_key.poll() is True


class SilentAudio:
    """Explicitly disabled audio, not a microphone or detected backend."""

    available = False
    microphone_available = False

    @property
    def ligado(self):
        return False

    @ligado.setter
    def ligado(self, _value):
        # The shared menu preference does not turn missing hardware on.
        pass

    def tocar(self, _name):
        return False

    def atualizar(self):
        return None

    def volume_mic(self):
        return 0

    def close(self):
        return None


class V1Profile:
    profile_id = PROFILE_ID

    def __init__(self, i2c, screen, touch, movement, rtc, sound, battery, boot, pwr):
        self.i2c = i2c
        self.tela, self.toque = screen, touch
        self.mov, self.relogio = movement, rtc
        self.som, self.bateria, self.botao = sound, battery, boot
        self.capabilities = {
            "rtc_write": False,
            "audio": getattr(sound, "available", False) is True,
            "microphone": getattr(sound, "microphone_available", False) is True,
            "power_key": pwr is not None and pwr.enabled,
            "network_managed": False,
        }

    def close(self):
        close_audio = getattr(self.som, "close", None)
        if callable(close_audio):
            close_audio()


def _preflight(i2c, clock, audio_requested):
    # Check required device identity and clock before any device writes.
    try:
        present = set(i2c.scan())
    except OSError as exc:
        raise ProfileUnavailable("Unable to scan V1 I2C bus") from exc
    if amoled_v1.V2_TOUCH_ADDR in present or amoled_v1.EXPANDER_ADDR not in present:
        raise amoled_v1.BoardMismatch("Unsupported V1 touch/expander bus identity")
    if (v1_game_hal.PMU_ADDR not in present or
            _byte(i2c, v1_game_hal.PMU_ADDR, v1_game_hal.PMU_ID_REG) != v1_game_hal.PMU_ID):
        raise ProfileUnavailable("AXP2101 identity not confirmed")
    rtc = ReadOnlyClock(i2c, clock)
    if v1_game_hal.RTC_ADDR not in present:
        raise ProfileUnavailable("PCF85063A RTC is missing")
    status, calendar = v1_game_hal.read_calendar(i2c)
    if status != "valid" or rtc._to_epoch(calendar) <= 0:
        raise ProfileUnavailable("A valid running PCF85063A RTC is required: " +
                                 ("clock_api" if status == "valid" else status))
    imu = [address for address in v1_game_hal.IMU_ADDRS if address in present and
           _byte(i2c, address, v1_game_hal.IMU_WHO_AM_I) == v1_game_hal.IMU_ID]
    if len(imu) != 1:
        raise ProfileUnavailable("QMI8658 address not identified unambiguously")
    if audio_requested and v1_game_hal.CODEC_ADDR not in present:
        raise ProfileUnavailable("Requested V1 ES8311 codec is not on the bus")
    return rtc, Accel(i2c, imu[0])


def create_profile(*, enabled=False, confirmed_v1=False, allow_power_key=False,
                   audio_factory=None, i2c=None, machine_module=None,
                   native_module=None, framebuffer_module=None, clock=None,
                   screen_mode=amoled_v1.SCALE_NATIVE):
    """Construct a game-compatible runtime, never autorun or flash anything.

    confirmed_v1 refers to the actual physical label, not a signature inferred
    from an address scan. Only after device identity and valid time are
    confirmed may the existing driver request touch reset release and set up
    the display. Set the actual clock separately; we never alter it.
    """
    if enabled is not True or confirmed_v1 is not True:
        raise ProfileUnavailable("Enable explicitly and confirm the physical AMOLED V1 label")
    amoled_v1.viewport_for(screen_mode)  # reject invalid layout before scanning or writing
    if type(allow_power_key) is not bool:
        raise TypeError("allow_power_key must be a bool")
    if audio_factory is not None and not callable(audio_factory):
        raise TypeError("audio_factory must be callable")
    if native_module is None:
        try:
            import amoled as native_module
        except ImportError as exc:
            raise ProfileUnavailable("Native V1 AMOLED module is unavailable") from exc
    if not all(callable(getattr(native_module, name, None))
               for name in ("QSPIPanel", "AMOLED")):
        raise ProfileUnavailable("Incomplete native V1 AMOLED module")
    if machine_module is None:
        import machine as machine_module
    if framebuffer_module is None:
        import framebuf as framebuffer_module
    if not callable(getattr(framebuffer_module, "FrameBuffer", None)) or not hasattr(framebuffer_module, "RGB565"):
        raise ProfileUnavailable("V1 RGB565 framebuffer API is unavailable")
    if clock is None:
        import time as clock
    Pin = machine_module.Pin
    if i2c is None:
        i2c = machine_module.I2C(I2C_ID, scl=Pin(amoled_v1.I2C_SCL),
                                  sda=Pin(amoled_v1.I2C_SDA),
                                  freq=I2C_FREQ, timeout=I2C_TIMEOUT_US)

    rtc, movement = _preflight(i2c, clock, audio_factory is not None)
    # No sensor or display writes until the touch ID is known. For an
    # explicitly confirmed cold V1 this may release only FT3168 reset first.
    amoled_v1.validate_v1_bus(i2c, verified_v1=True)
    movement.setup()
    screen, touch = amoled_v1.prepare_v1(
        i2c, machine_module=machine_module, amoled_module=native_module,
        framebuffer_module=framebuffer_module, verified_v1=False, screen_mode=screen_mode)
    boot = Pin(BOOT_PIN, Pin.IN, Pin.PULL_UP)
    pwr = PowerKey(i2c) if allow_power_key else None
    battery = Battery(i2c, pwr)
    if audio_factory is None:
        sound = SilentAudio()
    else:
        sound = audio_factory(i2c, confirmed_v1=True, machine_module=machine_module,
                              clock=clock)
        if not hasattr(sound, "ligado") or not all(
                callable(getattr(sound, method, None))
                for method in ("tocar", "atualizar", "volume_mic")):
            close = getattr(sound, "close", None)
            if callable(close):
                close()
            raise ProfileUnavailable("Incomplete V1 audio adapter")
    return V1Profile(i2c, screen, touch, movement, rtc, sound, battery, boot, pwr)
