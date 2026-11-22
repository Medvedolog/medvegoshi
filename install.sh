#!/bin/sh
# MedveGoshi installer: keep the original IPS path while preparing a separate
# future hardware profile for the Waveshare AMOLED 1.8 V1.
set -eu

usage() {
    cat <<'EOF'
MedveGoshi — установка русскоязычной прошивки

  sh install.sh --board ips [--port PORT] [--files-only] [--dry-run]
  sh install.sh --board amoled-v1 [--port PORT]
  sh install.sh --help

Платы:
  ips        Waveshare ESP32-S3-Touch-LCD-1.83 (ST7789/CST816D).
             Рабочий путь установки оригинальной IPS-платформы.
  amoled-v1  Waveshare ESP32-S3-Touch-AMOLED-1.8 V1 (SH8601/FT3168).
             Порт ещё не готов: установка намеренно заблокирована.

Опции:
  --port PORT    Последовательный порт, например /dev/ttyACM0 или COM5.
  --files-only   Обновить файлы, не стирая сохранения (для уже прошитой IPS).
  --dry-run      Только показать команду, ничего не прошивать.
  --help         Показать помощь.

Внимание: IPS без --files-only запускает deploy.sh с полным стиранием Flash!
EOF
}

BOARD=
PORT=
FILES_ONLY=0
DRY_RUN=0
while [ "$#" -gt 0 ]; do
    case "$1" in
        --board)
            [ "$#" -ge 2 ] || { echo "Ошибка: укажите плату после --board" >&2; exit 2; }
            BOARD=$2; shift 2 ;;
        --board=*)
            BOARD=${1#--board=}; shift ;;
        --port)
            [ "$#" -ge 2 ] || { echo "Ошибка: укажите порт после --port" >&2; exit 2; }
            PORT=$2; shift 2 ;;
        --port=*)
            PORT=${1#--port=}; shift ;;
        --files-only|--update-only)
            FILES_ONLY=1; shift ;;
        --dry-run)
            DRY_RUN=1; shift ;;
        -h|--help)
            usage; exit 0 ;;
        *)
            echo "Неизвестный аргумент: $1" >&2
            usage >&2
            exit 2 ;;
    esac
done

if [ -z "$BOARD" ]; then
    echo "Ошибка: выберите --board ips или --board amoled-v1." >&2
    usage >&2
    exit 2
fi

case "$BOARD" in
    ips)
        : ;;
    amoled-v1)
        echo "AMOLED V1 пока не поддерживается: SH8601/FT3168 ещё не интегрированы." >&2
        echo "Установщик не будет записывать IPS-прошивку на AMOLED." >&2
        exit 3 ;;
    *)
        echo "Неизвестный профиль платы: $BOARD" >&2
        exit 2 ;;
esac

DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ "$DRY_RUN" -eq 1 ]; then
    if [ "$FILES_ONLY" -eq 1 ]; then
        echo "Профиль: IPS. Запуск: sh $DIR/deploy.sh --so-arquivos ${PORT:-[порт по умолчанию]}"
    else
        echo "Профиль: IPS. ВНИМАНИЕ: полное стирание Flash."
        echo "Запуск: sh $DIR/deploy.sh ${PORT:-[порт по умолчанию]}"
    fi
    exit 0
fi

# deploy.sh is a bash script and retains its original calling convention.
if [ "$FILES_ONLY" -eq 1 ]; then
    if [ -n "$PORT" ]; then
        exec bash "$DIR/deploy.sh" --so-arquivos "$PORT"
    fi
    exec bash "$DIR/deploy.sh" --so-arquivos
fi
if [ -n "$PORT" ]; then
    exec bash "$DIR/deploy.sh" "$PORT"
fi
exec bash "$DIR/deploy.sh"
