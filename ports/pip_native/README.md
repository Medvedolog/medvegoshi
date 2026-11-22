# Experimental native Pip module

Optional MicroPython C user module. The game adapter is opt-in and the module
is not wired to I2S; see [the AMOLED guide](../README.md).
Includes the unchanged [Pip-KeyPet](https://github.com/NovikovVisuals/Pip-KeyPet)
MIT pet and voice cores from the pinned vendored source and the existing C
state validator used by the desktop replay. Does not include LVGL or graphics.

- `reset(seed, now, tz_min)`: reset the singleton in memory; input seconds
  are Unix/1970 and must be normalized by the caller. Timezone is fixed until
  reset or import. Seed is 0..2³²−1, timezone −840..840 minutes, and supported
  time runs from the epoch to 2100-01-01; reject times before local epoch.
- `advance(now)`, `event(name)`, `status()`: advance only forward, apply an
  upstream event by name, inspect mood, reason and the needs (each 0..1).
  The reason's `which` and `hold` use the upstream `pet.h` definitions.
- `export_state()`, `import_state(blob)`: bounded binary snapshots with
  module format/version, upstream version/revision, C layout/endianness,
  restored timezone, length and CRC32. This is not an authentication format;
  a CRC does not protect against deliberate edits. Validates every field before
  replacing live data. Do not exchange files with the desktop emulator or
  original Capigoshi. No filesystem access.
- `voice_start(name[, sample_rate])`, `voice_render_into(buf)`: nonverbal
  original Pip, not speech or TTS. Render into a writable buffer of an even
  length from 2 to 2048 bytes; signed 16-bit mono little-endian PCM. Returns
  whether more audio remains. The caller owns I2S and synchronization.

No code should use the module concurrently from several threads. After a
MicroPython soft reset, the app must initialize or restore the singleton
before using it. The bundled smoke script is runnable only in a MicroPython
build with the module enabled, not standard CPython.
