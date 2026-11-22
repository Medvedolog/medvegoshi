#!/usr/bin/env bash
# Build-only. NEVER erase or flash hardware.
set -euo pipefail

MICROPYTHON_SHA=e0e9fbb17ed6fd06bb76e266ae554784c9c80804
AMOLED_SHA=97934b7c35b1720a14fd69e4e1322bb5684b9b2c
IDF_VERSION=v5.5.2

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "$ROOT/.." && pwd)
WORK="${BUILD_ROOT:-$REPO_ROOT/build/amoled-v1-native}"
MP="$WORK/micropython"
DRIVER="$WORK/amoled-upstream"
OUTPUT="$WORK/output"
mkdir -p "$WORK"
if [ -d "$MP/.git" ] || [ -d "$DRIVER/.git" ]; then
  echo "Refusing to reuse stale source checkout at $WORK" >&2
  exit 2
fi

clone_at_sha() {
  local remote=$1 sha=$2 destination=$3 actual
  git init -q "$destination"
  git -C "$destination" remote add origin "$remote"
  git -C "$destination" fetch -q --depth 1 origin "$sha"
  git -C "$destination" -c advice.detachedHead=false checkout -q FETCH_HEAD
  actual=$(git -C "$destination" rev-parse HEAD)
  [ "$actual" = "$sha" ] || { echo "PIN MISMATCH: $actual" >&2; exit 2; }
}

clone_at_sha https://github.com/micropython/micropython.git "$MICROPYTHON_SHA" "$MP"
clone_at_sha https://github.com/dobodu/Lilygo_Waveshare_Amoled_Micropython.git "$AMOLED_SHA" "$DRIVER"

python3 "$ROOT/prepare_firmware.py" "$MP" "$DRIVER" > "$WORK/preparation.json"

make -C "$MP/mpy-cross" -j2
make -C "$MP/ports/esp32" submodules
make -C "$MP/ports/esp32" -j2 \
  BOARD=ESP32_GENERIC_S3 BOARD_VARIANT=SPIRAM_OCT \
  USER_C_MODULES="$DRIVER/micropython.cmake" \
  CFLAGS_EXTRA=-DMODULE_AMOLED_ENABLED=1

FW="$MP/ports/esp32/build-ESP32_GENERIC_S3-SPIRAM_OCT/firmware.bin"
[ -s "$FW" ] || { echo "Firmware image was not produced" >&2; exit 1; }
mkdir -p "$OUTPUT"
cp "$FW" "$OUTPUT/medvegoshi-amoled-v1-experimental.bin"
cp "$DRIVER/LICENSE" "$OUTPUT/AMOLED-UPSTREAM-LICENSE.txt"
cp "$WORK/preparation.json" "$OUTPUT/preparation.json"
(
  cd "$OUTPUT"
  sha256sum medvegoshi-amoled-v1-experimental.bin > SHA256SUMS
)
python3 - "$OUTPUT" "$MICROPYTHON_SHA" "$AMOLED_SHA" "$IDF_VERSION" <<'PY'
import json
import pathlib
import sys
out, micro, driver, idf = sys.argv[1:]
info = {
    "status": "BUILT_NOT_HARDWARE_TESTED",
    "installable": False,
    "board": "Waveshare ESP32-S3-Touch-AMOLED-1.8 V1 ONLY",
    "display": "SH8601 QSPI",
    "touch": "FT3168",
    "micropython_sha": micro,
    "amoled_driver_sha": driver,
    "idf_version": idf,
    "warnings": [
        "Not flashed or tested on real hardware",
        "No bundled MedveGoshi game scripts",
        "Do not use on AMOLED V2 (CO5300/CST820) or IPS",
        "No automated firmware installer: factory firmware would be replaced",
    ],
}
pathlib.Path(out, "BUILD-METADATA.json").write_text(
    json.dumps(info, indent=2, ensure_ascii=False) + "\n",
    encoding="utf-8",
)
PY
echo "Native SH8601 MicroPython built. Artifact is EXPERIMENTAL and NOT hardware-tested."
