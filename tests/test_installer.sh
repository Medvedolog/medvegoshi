#!/bin/sh
# Installer profile checks run without any ESP32 or serial port.
set -eu

cd "$(dirname "$0")/.."

failed() {
    echo "FAIL: $*" >&2
    exit 1
}

# Explicit board selection is mandatory.
if sh install.sh >/dev/null 2>&1; then
    failed "installer accepted missing --board"
fi
if sh install.sh --board amoled-v1 --port /dev/never >/dev/null 2>&1; then
    failed "AMOLED V1 must remain blocked until drivers are tested"
fi
if sh install.sh --board unknown >/dev/null 2>&1; then
    failed "unknown board was accepted"
fi

output=$(sh install.sh --board ips --dry-run)
printf '%s\n' "$output" | grep -q 'deploy.sh' || failed "IPS entrypoint is missing"

output=$(sh install.sh --board=ips --port /dev/ttyACM0 --files-only --dry-run)
printf '%s\n' "$output" | grep -q -- '--so-arquivos' || failed "files-only mode not forwarded"
printf '%s\n' "$output" | grep -q '/dev/ttyACM0' || failed "serial port not forwarded"

sh install.sh --help | grep -q -- 'amoled-v1' || failed "board profiles missing from help"

echo "PASS: IPS profile available; AMOLED blocked; update mode preserves old flags"
