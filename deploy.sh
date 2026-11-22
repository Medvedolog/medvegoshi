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
mpremote connect "$PORT" \
  cp "$DIR/main.py" : \
  + cp "$DIR/hw.py" : \
  + cp "$DIR/desenho.py" : \
  + cp "$DIR/font_ru.py" : \
  + cp "$DIR/zoo/__init__.py" :zoo/__init__.py \
  + cp "$DIR/zoo/pip/__init__.py" :zoo/pip/__init__.py \
  + cp "$DIR/zoo/pip/face.py" :zoo/pip/face.py \
  + cp "$DIR/vida.py" : \
  + cp "$DIR/rede.py" : \
  + cp "$DIR/portal.py" : \
  + cp -r "$DIR/sons" : \
  + cp "$DIR/companion/raiox.html" :raiox.html
mpremote connect "$PORT" mkdir :companion 2>/dev/null || true
mpremote connect "$PORT" cp "$DIR"/companion/*.py :companion/      # o cerebro (sem sim/ e testes/)

# Acerta o relógio da placa com a hora deste computador (não precisa de internet)
AGORA=$(date "+%Y, %-m, %-d, %-H, %-M, %-S")
echo "→ Синхронизация часов устройства: $(date "+%d/%m/%Y %H:%M:%S")"
mpremote connect "$PORT" \
  exec "from machine import I2C, Pin; import hw; hw.Relogio(I2C(0, scl=Pin(14), sda=Pin(15), freq=400000)).acertar($AGORA)" \
  + reset

echo ""
echo "✓ Готово! Питомец появится на экране при успешной загрузке."
