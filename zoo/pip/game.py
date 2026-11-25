"""Optional hardware-game adapter for the native Pip engine (not the host emulator).

The caller must opt in for animal "pip" after preparing the standard save
slots. Missing firmware, a corrupt sidecar, or an incompatible snapshot just
leave the legacy Pip game in charge. No other animal is touched. Never wire
this into a board's auto-start before its native firmware is tested.
"""

import os
import time
import binascii
try:
    import ujson as json
except ImportError:
    import json

from zoo import pet_slots

PIP_ID = "pip"
STATE_NAME = "pip-native-v1.json"
STATE_VERSION = 1
STATE_LIMIT = 2048
MAX_NATIVE_BYTES = 282
EPOCH_2000_OFFSET = 946684800
MAX_UNIX = 4102444800
NEEDS = ("food", "energy", "fun", "love", "walk")
NATIVE_EVENTS = (
    "feed", "play", "stroke", "poke", "step", "shake", "wake", "sleep",
    "seen", "win", "lose", "record", "fright", "flood", "fed_up",
)
EVENTS = {
    "comida": "feed", "fome": "feed", "brincar": "play", "alegria": "play",
    "carinho": "stroke", "colo": "stroke", "toque": "seen", "estrela": "seen",
    "shh": "poke", "passo": "step", "sacudida_leve": "shake",
    "sacudida_forte": "shake", "barulho": "fright", "acordar": "wake",
    "dormir": "sleep",
}
ERRORS = (ImportError, AttributeError, OSError, ValueError, TypeError, MemoryError,
          OverflowError, RuntimeError, pet_slots.SlotError)
_active = None


def unix_from_rtc(rtc_epoch, tz_min=0, epoch_year=None):
    """Convert ESP32 or Unix port RTC wall seconds to Unix UTC seconds.

    The game's RTC is wall time. A fixed configured offset is removed here
    and passed to native Pip's hour logic. Without a known offset, 0 keeps
    the existing displayed hour. Zero RTC means uninitialized in the game.
    See https://docs.micropython.org/en/latest/library/time.html#time .
    """
    if (type(rtc_epoch) is not int or rtc_epoch <= 0 or
            type(tz_min) is not int or not -840 <= tz_min <= 840):
        raise ValueError("invalid Pip RTC or timezone")
    if epoch_year is None:
        epoch_year = time.gmtime(0)[0]
    if epoch_year not in (1970, 2000):
        raise ValueError("unsupported RTC epoch")
    value = rtc_epoch + (EPOCH_2000_OFFSET if epoch_year == 2000 else 0) - tz_min * 60
    if not 0 <= value <= MAX_UNIX or value + tz_min * 60 < 0:
        raise ValueError("Pip RTC outside native range")
    return value


def _read_existing(path):
    try:
        mode = getattr(os, "lstat", os.stat)(path)[0]
    except OSError as error:
        code = getattr(error, "errno", None)
        code = code if code is not None else (error.args[0] if error.args else None)
        if code == 2:  # absent is not the same as unreadable
            return None
        raise
    if mode & 0xF000 != 0x8000:
        raise ValueError("Pip sidecar is not a regular file")
    with open(path, "rb") as source:
        raw = source.read(STATE_LIMIT + 1)
    if not raw or len(raw) > STATE_LIMIT:
        raise ValueError("invalid Pip sidecar size")
    return raw


def _payload(data):
    if not isinstance(data, (bytes, bytearray)) or not 1 <= len(data) <= MAX_NATIVE_BYTES:
        raise ValueError("invalid native Pip payload")
    return bytes(data)


def _decode(raw):
    row = json.loads(raw.decode("utf-8"))
    if (not isinstance(row, dict) or type(row.get("schema")) is not int
            or row["schema"] != STATE_VERSION or row.get("pet_id") != PIP_ID
            or row.get("engine") != "pip_native"):
        raise ValueError("Pip sidecar schema or owner mismatch")
    code = row.get("state_hex")
    if not isinstance(code, str) or not 1 <= len(code) <= MAX_NATIVE_BYTES * 2:
        raise ValueError("Pip sidecar has invalid state encoding")
    return _payload(binascii.unhexlify(code.encode("ascii")))


def _status(native, tz_min):
    row = native.status()
    if (not isinstance(row, dict) or not isinstance(row.get("mood"), str)
            or not row["mood"] or type(row.get("now")) is not int
            or not 0 <= row["now"] <= MAX_UNIX
            or type(row.get("tz_min")) is not int or row["tz_min"] != tz_min
            or type(row.get("asleep")) is not bool
            or not isinstance(row.get("reason"), dict)
            or not isinstance(row["reason"].get("kind"), str)
            or not isinstance(row.get("needs"), dict)):
        raise ValueError("unsupported native Pip status")
    for name in NEEDS:
        value = row["needs"].get(name)
        if type(value) not in (int, float) or not 0 <= value <= 1:
            raise ValueError("invalid native Pip need")
    return row


class PipGame:
    """Optional runtime session; persist explicitly, not on every frame."""

    def __init__(self, native, root, tz_min, epoch_year, old, row):
        self._native, self._root = native, root
        self._tz_min, self._epoch_year = tz_min, epoch_year
        self._previous, self._row = old, row
        self._dirty = old is None
        self._ready = True

    def status(self):
        return self._row if _active is self else None

    def tick(self, rtc_epoch):
        if _active is not self:
            return None
        try:
            now = unix_from_rtc(rtc_epoch, self._tz_min, self._epoch_year)
        except ERRORS:
            # Temporarily absent RTC: retain the last valid mood but do not
            # add activity, wind back the native core, or write new data.
            self._ready = False
            return self._row
        if now < self._row["now"]:
            self._ready = False
            return self._row
        self._ready = True
        if now == self._row["now"]:
            return self._row
        try:
            if self._native.advance(now) is not None:
                raise ValueError("unsupported native Pip advance")
            row = _status(self._native, self._tz_min)
            if row["now"] != now:
                raise ValueError("native Pip did not advance to RTC")
            self._row = row
            self._dirty = True
            return row
        except ERRORS:
            self.close()
            return None

    def event(self, name, rtc_epoch=None):
        """Send an existing game event or native event; return transient mood."""
        if _active is not self or not isinstance(name, str):
            return None
        what = EVENTS.get(name, name)
        if what not in NATIVE_EVENTS:
            return None
        if rtc_epoch is not None:
            self.tick(rtc_epoch)
        if _active is not self or not self._ready:
            return None
        try:
            mood = self._native.event(what)
            if mood is not None and not isinstance(mood, str):
                raise ValueError("unsupported native Pip reaction")
            row = _status(self._native, self._tz_min)
            if row["now"] != self._row["now"]:
                raise ValueError("native Pip event changed the clock")
            self._row = row
            self._dirty = True
            return mood
        except ERRORS:
            self.close()
            return None

    def flush(self):
        """Save only our last good native state; never repair a different file."""
        if _active is not self:
            return False
        if not self._dirty:
            return True
        try:
            # has_pet also verifies that slots are prepared and the slot
            # directory is safe; its False result is fine for a fresh Pip.
            pet_slots.has_pet(PIP_ID, self._root)
            path = pet_slots.brain_dir(PIP_ID, self._root) + STATE_NAME
            if _read_existing(path) != self._previous:
                raise ValueError("native Pip sidecar changed during play")
            data = _payload(self._native.export_state())
            pet_slots.ensure_slot(PIP_ID, self._root)
            pet_slots.save_json(path, {"schema": STATE_VERSION, "engine": "pip_native",
                                      "pet_id": PIP_ID,
                                      "state_hex": binascii.hexlify(data).decode("ascii")})
            saved = _read_existing(path)
            if saved is None or _decode(saved) != data:
                raise ValueError("native Pip sidecar did not verify")
            self._previous = saved
            self._dirty = False
            return True
        except ERRORS:
            self.close()
            return False

    def close(self):
        """Release the native singleton; call flush explicitly if desired."""
        global _active
        if _active is self:
            _active = None


def open_pip(pet_id, rtc_epoch, *, enabled=False, seed=1, tz_min=0, root="",
             native=None, epoch_year=None):
    """Try the native engine for an explicitly opted-in Pip; else return None.

    A sidecar rejected by the native module is left byte-for-byte untouched.
    Never start a fresh native state over an unknown or corrupt snapshot.
    """
    global _active
    if pet_id != PIP_ID or enabled is not True:
        return None
    try:
        if type(seed) is not int or not 0 <= seed <= 0xFFFFFFFF:
            raise ValueError("invalid Pip seed")
        if native is None:
            import pip_native as native
        for name in ("reset", "advance", "event", "status", "export_state", "import_state"):
            if not callable(getattr(native, name, None)):
                return None
        if epoch_year is None:
            epoch_year = time.gmtime(0)[0]
        now = unix_from_rtc(rtc_epoch, tz_min, epoch_year)
        if _active is not None:
            if (_active._native is native and _active._root == root
                    and _active._tz_min == tz_min and _active._epoch_year == epoch_year):
                return _active if _active.tick(rtc_epoch) is not None else None
            return None
        pet_slots.has_pet(PIP_ID, root)
        path = pet_slots.brain_dir(PIP_ID, root) + STATE_NAME
        old = _read_existing(path)
        if old is None:
            if native.reset(seed, now, tz_min) is not None:
                raise ValueError("unsupported native Pip reset")
        else:
            if native.import_state(_decode(old)) is not None:
                raise ValueError("unsupported native Pip import")
        state = _status(native, tz_min)
        if state["now"] > now or (old is None and state["now"] != now):
            raise ValueError("native Pip snapshot clock disagrees with RTC")
        session = PipGame(native, root, tz_min, epoch_year, old, state)
        _active = session
        return session if session.tick(rtc_epoch) is not None else None
    except ERRORS:
        return None
