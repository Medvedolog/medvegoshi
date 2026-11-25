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

# The files-only path discovers bundled plugins and publishes manifests last.
# Intercept every device command; the apparent serial port is only a temp file.
scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT HUP INT TERM
: > "$scratch/port"
cat > "$scratch/mpremote" <<'EOF'
#!/bin/sh
[ "$1" = connect ] && [ "$2" = "$TEST_PORT" ] || exit 1
if [ "$3" = cp ]; then
    case "$5" in
        :zoo/animals/bjorni/*)
            [ -f "$4" ] || exit 1
            printf '%s\n' "${5##*/}" >> "$TEST_LOG" ;;
    esac
fi
EOF
cat > "$scratch/esptool.py" <<'EOF'
#!/bin/sh
echo "Unexpected flash command" >&2
exit 1
EOF
cp "$scratch/esptool.py" "$scratch/curl"
chmod +x "$scratch/mpremote" "$scratch/esptool.py" "$scratch/curl"
PATH="$scratch:$PATH" TEST_PORT="$scratch/port" TEST_LOG="$scratch/log" \
    sh install.sh --board ips --files-only --port "$scratch/port" >/dev/null
printf '%s\n' __init__.py face.py manifest.json > "$scratch/expected"
cmp -s "$scratch/expected" "$scratch/log" || failed "Bjorni runtime deploy order or file set is wrong"

echo "PASS: IPS profile and Bjorni deployment available; AMOLED installer remains blocked"
