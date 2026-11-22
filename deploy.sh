#!/bin/bash
set -e

SO_ARQUIVOS=0
if [ "$1" = "--so-arquivos" ]; then SO_ARQUIVOS=1; shift; fi
PORT=${1:-/dev/cu.usbmodem101}
FIRMWARE=/tmp/micropython_s3_spiram_oct.bin
DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== MedveGoshi: установка на ESP32-S3 IPS 1.83 ==="
echo "ВНИМАНИЕ: эта установка только для IPS ST7789/CST816D."
echo "Waveshare AMOLED 1.8 V1 (SH8601/FT3168) пока НЕ поддерживается."
echo ""

# Verifica porta
if [ ! -e "$PORT" ]; then
  echo "Порт $PORT не найден."
  echo ""
  echo "Переведите плату в режим прошивки:"
  echo "  Удерживайте BOOT, нажмите и отпустите RST, затем отпустите BOOT"
  echo ""
  echo "Затем повторите: bash deploy.sh"
  exit 1
fi

if [ "$SO_ARQUIVOS" = 0 ]; then
  # Baixa firmware se não existir
  if [ ! -f "$FIRMWARE" ]; then
    echo "Загрузка MicroPython ESP32-S3 SPIRAM_OCT..."
    curl -L "https://micropython.org/resources/firmware/ESP32_GENERIC_S3-SPIRAM_OCT-20250415-v1.25.0.bin" \
         -o "$FIRMWARE" --progress-bar
    echo ""
  fi
  echo "Порт: $PORT"
  echo "Firmware: $FIRMWARE"
  echo ""
  echo "→ Стирание Flash (все сохранения питомца будут удалены)..."
  esptool.py --chip esp32s3 --port "$PORT" erase_flash
  echo ""
  echo "→ Запись MicroPython..."
  esptool.py --chip esp32s3 --port "$PORT" write_flash -z 0 "$FIRMWARE"
  echo ""
  echo "→ Перезагрузка платы..."
  sleep 3
fi

echo ""
echo "→ Копирование файлов и звуков..."
# Upload only the optional Pip runtime, never Zoo test fixtures or upstream sources.
mpremote connect "$PORT" mkdir :zoo 2>/dev/null || true
mpremote connect "$PORT" mkdir :zoo/pip 2>/dev/null || true
mpremote connect "$PORT" mkdir :zoo/giraffe 2>/dev/null || true
mpremote connect "$PORT" mkdir :zoo/packs 2>/dev/null || true
mpremote connect "$PORT" mkdir :zoo/animals 2>/dev/null || true
mpremote connect "$PORT" \
  cp "$DIR/hw.py" : \
  + cp "$DIR/desenho.py" : \
  + cp "$DIR/font_ru.py" : \
  + cp "$DIR/zoo/__init__.py" :zoo/__init__.py \
  + cp "$DIR/zoo/registry.py" :zoo/registry.py \
  + cp "$DIR/zoo/recovery.py" :zoo/recovery.py \
  + cp "$DIR/zoo/pet_slots.py" :zoo/pet_slots.py \
  + cp "$DIR/zoo/switch_pet.py" :zoo/switch_pet.py \
  + cp "$DIR/zoo/animals/__init__.py" :zoo/animals/__init__.py \
  + cp "$DIR/zoo/sprites.py" :zoo/sprites.py \
  + cp "$DIR/zoo/pip/__init__.py" :zoo/pip/__init__.py \
  + cp "$DIR/zoo/pip/face.py" :zoo/pip/face.py \
  + cp "$DIR/zoo/pip/game.py" :zoo/pip/game.py \
  + cp "$DIR/zoo/giraffe/__init__.py" :zoo/giraffe/__init__.py \
  + cp "$DIR/zoo/giraffe/face.py" :zoo/giraffe/face.py \
  + cp "$DIR/vida.py" : \
  + cp "$DIR/rede.py" : \
  + cp "$DIR/portal.py" : \
  + cp -r "$DIR/sons" : \
  + cp "$DIR/companion/raiox.html" :raiox.html
# Discover any validated optional animal directory on the host. Ship only
# manifest/face/__init__, NOT host tools, tests, artwork sources or build dirs.
# Every future Zoo animal can be added without updating this deploy script.
for ANIMAL_DIR in "$DIR"/zoo/animals/*; do
  [ -d "$ANIMAL_DIR" ] || continue
  ANIMAL_ID=${ANIMAL_DIR##*/}
  case "$ANIMAL_ID" in
    ''|*[!a-z0-9_-]*|[!a-z]*) continue ;;
  esac
  [ -f "$ANIMAL_DIR/manifest.json" ] || continue
  [ -f "$ANIMAL_DIR/face.py" ] || continue
  [ -f "$ANIMAL_DIR/__init__.py" ] || continue
  mpremote connect "$PORT" mkdir ":zoo/animals/$ANIMAL_ID" 2>/dev/null || true
  mpremote connect "$PORT" cp "$ANIMAL_DIR/__init__.py" ":zoo/animals/$ANIMAL_ID/__init__.py"
  mpremote connect "$PORT" cp "$ANIMAL_DIR/face.py" ":zoo/animals/$ANIMAL_ID/face.py"
  mpremote connect "$PORT" cp "$ANIMAL_DIR/manifest.json" ":zoo/animals/$ANIMAL_ID/manifest.json"
done
mpremote connect "$PORT" mkdir :companion 2>/dev/null || true
mpremote connect "$PORT" cp "$DIR"/companion/*.py :companion/      # o cerebro (sem sim/ e testes/)

# Acerta o relógio da placa com a hora deste computador (não precisa de internet)
# Copy boot entrypoint LAST. If transfer is interrupted, do not leave
# a new main.py requiring unavailable modules. The existing app/save stays.
AGORA=$(date "+%Y, %-m, %-d, %-H, %-M, %-S")
echo "→ Синхронизация часов устройства: $(date "+%d/%m/%Y %H:%M:%S")"
mpremote connect "$PORT" \
  exec "from machine import I2C, Pin; import hw; hw.Relogio(I2C(0, scl=Pin(14), sda=Pin(15), freq=400000)).acertar($AGORA)" \
  + cp "$DIR/main.py" : \
  + reset

echo ""
echo "✓ Готово! Питомец появится на экране при успешной загрузке."
