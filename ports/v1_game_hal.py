"""Read-only AMOLED 1.8 V1 game HAL preflight; not a game launcher.

Requires an already-open I2C bus on explicitly confirmed V1 hardware. Does
not run any IPS constructor, release reset, configure a peripheral, write
the RTC, load a save, or call main.py.
"""
from ports import amoled_v1


RTC_ADDR = 0x51
RTC_CTRL1_REG = 0x00
RTC_TIME_REG = 0x04
IMU_ADDRS = (0x6A, 0x6B)
IMU_WHO_AM_I = 0x00
IMU_ID = 0x05
PMU_ADDR = 0x34
PMU_ID_REG = 0x03
PMU_ID = 0x4A
CODEC_ADDR = 0x18


class GameHALUnavailable(RuntimeError):
    pass


def _read(i2c, address, reg, n):
    try:
        data = i2c.readfrom_mem(address, reg, n)
    except OSError:
        return None
    return data if isinstance(data, (bytes, bytearray)) and len(data) == n else None


def _bcd(value):
    low, high = value & 15, value >> 4
    if low > 9 or high > 9:
        raise ValueError("invalid BCD")
    return high * 10 + low


def read_calendar(i2c):
    """Return (status, calendar) from the NXP PCF85063A, without writes."""
    # NXP PCF85063A datasheet 7.2.1: game expects a running 24-hour RTC.
    control = _read(i2c, RTC_ADDR, RTC_CTRL1_REG, 1)
    if control is None:
        return "unreadable", None
    if control[0] & 0x20:
        return "stopped", None
    if control[0] & 0x82:  # 12-hour mode or external clock test mode
        return "unsupported_mode", None
    # NXP PCF85063A sections 7.3-7.4: all calendar counters latch during
    # one transfer. Do not split date and time across a rollover.
    data = _read(i2c, RTC_ADDR, RTC_TIME_REG, 7)
    if data is None:
        return "unreadable", None
    if data[0] & 0x80:  # oscillator stop: don't invent a date or clear it
        return "unset", None
    try:
        second = _bcd(data[0] & 0x7F)
        minute = _bcd(data[1] & 0x7F)
        hour = _bcd(data[2] & 0x3F)
        day = _bcd(data[3] & 0x3F)
        month = _bcd(data[5] & 0x1F)
        year = 2000 + _bcd(data[6])
    except ValueError:
        return "invalid", None
    if not (second < 60 and minute < 60 and hour < 24 and 1 <= month <= 12
            and (data[4] & 7) <= 6):
        return "invalid", None
    days = (31, 28 + (year % 4 == 0), 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
    if not 1 <= day <= days[month - 1]:
        return "invalid", None
    # The existing game treats older times as unset; let the user choose
    # whether to correct the actual clock outside the read-only probe.
    if year < 2025:
        return "stale", None
    return "valid", (year, month, day, hour, minute, second)


def probe(i2c, *, confirmed_v1=False, native_module=None):
    """Inspect bus/identity without writes; presence never means hardware QA."""
    if confirmed_v1 is not True:
        raise GameHALUnavailable("Confirm the physical Waveshare AMOLED 1.8 V1 label")
    # Do not use verified_v1=True here: it can release the touch reset.
    # An FT3168 still held in reset is a failed read-only probe by design.
    present = amoled_v1.validate_v1_bus(i2c, verified_v1=False)
    matches = []
    for address in IMU_ADDRS:
        if address in present and _read(i2c, address, IMU_WHO_AM_I, 1) == bytes((IMU_ID,)):
            matches.append(address)
    return {
        "board": "amoled_1_8_v1",
        "touch_present": True,
        "native_display_api_present": all(
            callable(getattr(native_module, name, None))
            for name in ("QSPIPanel", "AMOLED")
        ),
        "imu_addr": matches[0] if len(matches) == 1 else None,
        "rtc": read_calendar(i2c)[0] if RTC_ADDR in present else "missing",
        "pmu_identified": (
            PMU_ADDR in present
            and _read(i2c, PMU_ADDR, PMU_ID_REG, 1) == bytes((PMU_ID,))
        ),
        "audio_codec_present": CODEC_ADDR in present,
    }


def require_game_hal(report, *, display_touch_tested=False,
                     audio_tested=False, rtc_read_only_in_game=False):
    """Fail closed until a future V1 launcher can supply verified adapters.

    This function never launches or configures hardware. The explicit flags
    mean hand-verified game integration, not test doubles or I2C presence.
    """
    blockers = []
    if report.get("board") != "amoled_1_8_v1" or not report.get("touch_present"):
        blockers.append("unverified V1 display/touch profile")
    if not report.get("native_display_api_present") or display_touch_tested is not True:
        blockers.append("V1 native display/touch not tested")
    if report.get("imu_addr") not in IMU_ADDRS:
        blockers.append("QMI8658 not identified unambiguously")
    if report.get("rtc") != "valid" or rtc_read_only_in_game is not True:
        blockers.append("valid PCF85063A time and read-only game policy required")
    if not report.get("pmu_identified"):
        blockers.append("AXP2101 not identified")
    if not report.get("audio_codec_present") or audio_tested is not True:
        blockers.append("ES8311 audio not tested")
    if blockers:
        raise GameHALUnavailable("; ".join(blockers))
