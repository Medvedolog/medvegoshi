"""Host-only emulator for the vendored Pip-KeyPet needs and mood engine.

Requires CPython, a local C11 compiler (CC or cc), and Linux/macOS. The C core
is compiled unchanged into a temporary shared library on first use, not run on
a board. Snapshots are opaque same-source, same-ABI host data; they are neither
Capigoshi saves nor portable Pip-KeyPet firmware saves.
"""

from ctypes import (
    CDLL, POINTER, byref, c_char_p, c_float, c_int, c_int32, c_int64, c_size_t,
    c_uint32, c_uint64, c_void_p, create_string_buffer,
)
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
import os
import platform
import shlex
import struct
import subprocess
import sys
import tempfile
import zlib

EVENTS = (
    "feed", "play", "stroke", "poke", "step", "shake", "wake", "sleep",
    "seen", "win", "lose", "record", "fright", "flood", "fed_up",
)
NEEDS = ("food", "energy", "fun", "love", "walk")
_DETAIL = (
    ("asleep", ("asleep",)),
    ("rare", ("stoned", "pinkeye")),
    ("body", ("battery_empty", "multiple_needs", "battery_tired", "battery_low")),
    ("after", ("win", "lose", "record", "fright", "flood", "sulk", "missed", "fed_up")),
    ("urge", ("food_critical", "food_low", "energy_critical", "energy_low",
              "love_critical", "love_low", "fun_low", "walk_low")),
    ("night", ("tired_at_night",)),
    ("situation", ("waking", "walking", "charging")),
    ("palette", ("great", "good", "neutral", "low", "evening_great",
                 "evening_good", "evening_neutral", "evening_low")),
)
MAX_TIME = 4_102_444_800  # 2100-01-01 UTC, keeps the vendored day/slot math bounded.
_SIGNATURE = b"MGP1"
_VERSION = 1
_HEADER = struct.Struct(">4sBh32sHI")  # format, version, timezone, compatible ABI, size, CRC32


def _integer(value, low, high, name):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{name} must be an integer from {low} to {high}")
    return value


def _time(now, tz_min):
    return _integer(now, max(0, -tz_min * 60), MAX_TIME, "now (Unix seconds)")


def _fn(dll, name, result, *args):
    function = getattr(dll, "pip_host_" + name)
    function.restype = result
    function.argtypes = args
    return function


class _Bridge:
    def __init__(self):
        if not (sys.platform.startswith("linux") or sys.platform == "darwin"):
            raise RuntimeError("The Pip C emulator supports Linux and macOS")
        here = Path(__file__).resolve().parent
        vendor = here.parent / "upstream" / "pip" / "ui"
        wrapper, pet = here / "pet_host_bridge.c", vendor / "pet.c"
        inputs = (wrapper, pet, vendor / "pet.h", vendor / "moods.h")
        temporary = tempfile.TemporaryDirectory(prefix="medvegoshi-pip-")
        try:
            dylib = sys.platform == "darwin"
            lib = Path(temporary.name) / ("pet.dylib" if dylib else "pet.so")
            command = shlex.split(os.environ.get("CC", "cc"))
            if not command:
                raise RuntimeError("Set CC to a C11 compiler")
            subprocess.run(
                command + ["-std=c11", "-O2", "-fPIC", "-dynamiclib" if dylib else "-shared",
                           "-I", str(vendor), str(wrapper), str(pet), "-lm", "-o", str(lib)],
                check=True, capture_output=True, text=True, timeout=60,
            )
            dll = CDLL(str(lib))
            self.new = _fn(dll, "new", c_void_p, c_uint32, c_int64, c_int)
            self.free = _fn(dll, "free", None, c_void_p)
            self.tick = _fn(dll, "update", c_int, c_void_p, c_int64, c_int)
            self.event = _fn(dll, "event", c_int, c_void_p, c_char_p, c_int)
            self.observe = _fn(dll, "observe", None, c_void_p, c_int,
                               POINTER(c_int32), POINTER(c_float), POINTER(c_int64))
            self.mood = _fn(dll, "mood_name", c_char_p, c_int)
            self.write = _fn(dll, "snapshot", None, c_void_p, c_void_p)
            self.read = _fn(dll, "restore", c_int, c_void_p, c_void_p, c_size_t, c_int)
            self.size = _fn(dll, "state_size", c_size_t)()
            layout = _fn(dll, "layout", c_uint64)()
            if not 1 <= self.size <= 256:
                raise RuntimeError("Unexpected Pip state size")
            h = sha256()
            for path in inputs:
                h.update(sha256(path.read_bytes()).digest())
            for value in (sys.platform, sys.byteorder, platform.machine(), str(layout)):
                h.update(value.encode("ascii") + b"\0")
            self.tag = h.digest()
        except subprocess.CalledProcessError as exc:
            raise RuntimeError("Unable to compile Pip C core:\n" + exc.stderr[-2000:]) from exc
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError("Unable to build/load Pip; check that a C11 compiler is available") from exc
        finally:
            # Linux/macOS keep the loaded mapping after unlink; there is no
            # build cache or native binary left in the working tree.
            temporary.cleanup()

    def name(self, mood):
        label = self.mood(mood)
        return label.decode("ascii") if label is not None else None


@lru_cache(maxsize=1)
def _bridge():
    return _Bridge()


def _explanation(kind, detail, value, hold):
    key, labels = _DETAIL[kind]
    # The urge tree adds eight for the alternate expression, not another need.
    alternate = key == "urge" and detail >= 8
    label = labels[detail % 8] if alternate else labels[detail]
    return {"kind": key, "detail": label, "detail_id": detail, "value": float(value),
            "hold": None if hold < 0 else hold, "alternate": alternate}


class Pet:
    """Drive the original C logic using explicit Unix timestamps and events.

    Construct with an explicit integer 'now'. The timezone is a fixed offset,
    not an IANA zone. This prototype is single-threaded per instance.
    """

    def __init__(self, seed=1, now=None, tz_min=0):
        seed = _integer(seed, 0, 0xFFFFFFFF, "seed")
        self._tz_min = _integer(tz_min, -840, 840, "tz_min")
        now = _time(now, self._tz_min)
        self._bridge = _bridge()
        self._state = self._bridge.new(seed, now, self._tz_min)
        if not self._state:
            raise MemoryError("Unable to allocate a Pip state")

    def __del__(self):
        p = getattr(self, "_state", None)
        if p:
            self._bridge.free(p)

    def __copy__(self):
        return type(self).restore(self.snapshot())

    def __deepcopy__(self, memo):
        clone = self.__copy__()
        memo[id(self)] = clone
        return clone

    @property
    def tz_min(self):
        return self._tz_min

    def update(self, now):
        """Catch up to 'now'; timestamps cannot run backward."""
        now = _time(now, self._tz_min)
        if not self._bridge.tick(self._state, now, self._tz_min):
            raise ValueError("Pip time cannot run backward")
        return self.explain()

    def event(self, name):
        """Apply a named event at the current clock, returning an immediate mood or None."""
        if not isinstance(name, str):
            raise ValueError("Pip event name must be text")
        name = name.lower().replace("-", "_")
        if name not in EVENTS:
            raise ValueError(f"Unknown Pip event: {name!r}")
        reaction = self._bridge.event(self._state, name.encode("ascii"), self._tz_min)
        if reaction < -1:
            raise ValueError("Pip event cannot be applied")
        return self._bridge.name(reaction)

    def explain(self):
        """Return the C decision tree's reason for the current baseline mood."""
        codes, values, now = (c_int32 * 5)(), (c_float * 7)(), c_int64()
        self._bridge.observe(self._state, self._tz_min, codes, values, byref(now))
        mood, kind, detail, hold, asleep = codes
        return {"mood": self._bridge.name(mood), "mood_id": mood,
                "reason": _explanation(kind, detail, values[6], hold),
                "needs": dict(zip(NEEDS, values[:5])), "valence": values[5],
                "asleep": bool(asleep), "now": now.value, "tz_min": self._tz_min}

    def snapshot(self):
        """Encode an opaque versioned bytes payload, without doing file I/O."""
        raw = create_string_buffer(self._bridge.size)
        self._bridge.write(self._state, raw)
        payload = raw.raw
        prefix = struct.pack(">h", self._tz_min)
        checksum = zlib.crc32(payload, zlib.crc32(prefix))
        return (_HEADER.pack(_SIGNATURE, _VERSION, self._tz_min, self._bridge.tag,
                             len(payload), checksum) + payload)

    @classmethod
    def restore(cls, blob, now=None):
        """Restore validated same-source host bytes; optionally catch up to 'now'."""
        if not isinstance(blob, (bytes, bytearray)):
            raise ValueError("Pip snapshot must be bytes")
        if not _HEADER.size < len(blob) <= _HEADER.size + 256:
            raise ValueError("Invalid Pip snapshot size")
        magic, version, tz, tag, size, checksum = _HEADER.unpack_from(blob)
        if magic != _SIGNATURE or version != _VERSION or size != len(blob) - _HEADER.size:
            raise ValueError("Invalid or incompatible Pip snapshot header")
        _integer(tz, -840, 840, "snapshot timezone")
        payload = bytes(blob[_HEADER.size:])
        if zlib.crc32(payload, zlib.crc32(struct.pack(">h", tz))) != checksum:
            raise ValueError("Damaged Pip snapshot (CRC32 mismatch)")
        bridge = _bridge()
        if size != bridge.size or tag != bridge.tag:
            raise ValueError("Pip snapshot has an incompatible source or host ABI")
        result = cls(seed=1, now=max(0, -tz * 60), tz_min=tz)
        raw = create_string_buffer(payload, len(payload))
        if not bridge.read(result._state, raw, len(payload), tz):
            raise ValueError("Pip snapshot contains invalid native state")
        if now is not None:
            result.update(now)
        return result
