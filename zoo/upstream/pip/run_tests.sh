#!/bin/sh
# Build and run the UNMODIFIED upstream Pip-KeyPet MIT unit tests.
# No ESP32 toolchain or hardware needed; requires a C compiler.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
OUT=$(mktemp -d)
trap 'rm -rf "$OUT"' EXIT HUP INT TERM
CC=${CC:-cc}

echo "Pip-KeyPet upstream reference tests (MIT, pinned revision)"
"$CC" -std=c11 -O2 -I"$ROOT/ui" "$ROOT/sim/face_test.c" "$ROOT/ui/face.c" -lm -o "$OUT/face_test"
"$OUT/face_test"
"$CC" -std=c11 -O2 -I"$ROOT/ui" "$ROOT/sim/maze_test.c" "$ROOT/ui/maze.c" -lm -o "$OUT/maze_test"
"$OUT/maze_test"
"$CC" -std=c11 -O2 -I"$ROOT/ui" "$ROOT/sim/pet_test.c" "$ROOT/ui/pet.c" -lm -o "$OUT/pet_test"
"$OUT/pet_test"
echo "All three original Pip C test executables passed."
