"""Fail-closed recovery for MedveGoshi settings and pet saves.

This module must stay compatible with MicroPython on the original IPS.
If config.json names an unavailable plugin, NEVER substitute Capi and write
over capi.json. Pause boot instead so the owner can restore the Zoo module.

No board or filesystem writes are performed by load_config().
"""
try:
    import ujson as json
except ImportError:
    import json
import os


class RecoveryRequired(Exception):
    def __init__(self, reason, pet_id=None):
        self.reason = reason
        self.pet_id = pet_id
        Exception.__init__(self, reason)


_SLOT_MESSAGES = {
    "slot_filesystem": "Нужна LittleFS2",
    "slot_bad_id": "Неизвестный ID питомца",
    "slot_destination_conflict": "Есть другое сохранение",
    "slot_io": "Нет доступа к файлам",
    "slot_journal_conflict": "Конфликт журнала переноса",
    "slot_not_ready": "Перенос не завершён",
    "slot_owner_conflict": "Владелец не совпадает",
    "slot_owner_unknown": "Кому принадлежит файл?",
    "slot_source_changed": "Старый файл изменился",
}


def load_config(path, defaults, available, retired=()):
    """Load config without silently discarding an existing active pet.

    A truly absent config is a normal first boot. A corrupt existing config
    or a saved ID missing from the cast MUST stop before any save, unless
    explicitly retired for a copy-only migration.
    """
    try:
        os.stat(path)
    except OSError as err:
        # Only ENOENT means a normal new device. An I/O error must NOT
        # be treated as an empty save and followed by a new write.
        code = getattr(err, "errno", None)
        if code is None and err.args:
            code = err.args[0]
        if code == 2:
            return dict(defaults)
        raise RecoveryRequired("config_corrupt")

    try:
        with open(path, "r") as fd:
            data = json.load(fd)
    except (OSError, ValueError, TypeError, MemoryError):
        raise RecoveryRequired("config_corrupt")
    if not isinstance(data, dict):
        raise RecoveryRequired("config_corrupt")

    result = dict(defaults)
    result.update(data)
    saved_id = result.get("personagem")
    if (not isinstance(saved_id, str) or not saved_id
            or (saved_id not in available and saved_id not in retired)):
        raise RecoveryRequired("pet_missing", str(saved_id)[:40])
    return result


def load_pet(path, defaults):
    """Read the shared capi.json slot without ever accepting invalid JSON."""
    try:
        os.stat(path)
    except OSError as err:
        code = getattr(err, "errno", None)
        if code is None and err.args:
            code = err.args[0]
        if code == 2:
            return dict(defaults)
        raise RecoveryRequired("pet_corrupt")
    try:
        with open(path, "r") as fd:
            data = json.load(fd)
    except (OSError, ValueError, TypeError, MemoryError):
        raise RecoveryRequired("pet_corrupt")
    if not isinstance(data, dict):
        raise RecoveryRequired("pet_corrupt")
    result = dict(defaults)
    result.update(data)
    # Schema invariants: do not run the simulation on values that will
    # later crash or silently turn into a freshly initialized animal.
    for key in ("fome", "alegria", "energia", "saude", "cocos",
                "epoch", "idade_min", "vida_adulto"):
        number = result.get(key)
        if isinstance(number, bool) or not isinstance(number, (int, float)):
            raise RecoveryRequired("pet_corrupt")
    for key in ("doente", "dormindo", "cochilo", "morto"):
        if not isinstance(result.get(key), bool):
            raise RecoveryRequired("pet_corrupt")
    return result


def require_pet(path, defaults, tela, desenho):
    """Stop without overwriting a broken or partial shared save."""
    try:
        return load_pet(path, defaults)
    except RecoveryRequired as exc:
        try:
            show_recovery(tela, desenho, exc)
        except Exception as show_error:
            print("Zoo recovery screen unavailable:", show_error)
        print("Zoo recovery: invalid save, file=" + path)
        raise RuntimeError("MedveGoshi data protected: pet_corrupt")


def show_recovery(tela, desenho, error):
    """Show a diagnostic screen; device must not continue the game loop."""
    fb = tela.fb
    fb.fill(desenho.C((255, 248, 234)))
    dark = (58, 40, 32)
    red = (185, 55, 48)
    desenho.centro("MedveGoshi", 17, dark, 2)
    if error.reason == "pet_missing":
        desenho.centro("НЕТ ПИТОМЦА", 59, red)
        desenho.centro("Модуль Zoo пропал", 83, dark)
        if error.pet_id:
            desenho.centro(error.pet_id[:28], 105, red)
        desenho.centro("Верните папку", 137, dark)
        desenho.centro("zoo/animals", 158, dark)
    elif error.reason == "pet_corrupt":
        desenho.centro("ОШИБКА СОХРАНЕНИЯ", 59, red)
        desenho.centro("capi.json повреждён", 93, dark)
        if error.pet_id:
            desenho.centro(error.pet_id[:28], 112, red)
        desenho.centro("Восстановите файл", 137, dark)
    elif error.reason == "config_corrupt":
        desenho.centro("ОШИБКА НАСТРОЕК", 59, red)
        desenho.centro("config.json повреждён", 93, dark)
        desenho.centro("Восстановите файл", 137, dark)
    else:
        desenho.centro("СЛОТ НЕ ОТКРЫТ", 59, red)
        desenho.centro(_SLOT_MESSAGES.get(error.reason, "Ошибка чтения данных"), 93, dark)
        if error.pet_id:
            desenho.centro(error.pet_id[:28], 112, red)
        desenho.centro("Не сбрасывайте данные", 137, dark)
    desenho.centro("Старые файлы не стёрты" if error.reason.startswith("slot_") else
                   "Данные не изменены", 202, dark)
    desenho.centro("Подключите USB", 228, dark)
    tela.mostrar()


def require_config(path, defaults, available, tela, desenho, retired=()):
    """Enforce no-write boot lock and show recovery if needed."""
    try:
        return load_config(path, defaults, available, retired)
    except RecoveryRequired as exc:
        try:
            show_recovery(tela, desenho, exc)
        except Exception as show_error:
            print("Zoo recovery screen unavailable:", show_error)
        print("Zoo recovery: %s, pet_id=%s" % (exc.reason, exc.pet_id))
        raise RuntimeError("MedveGoshi data protected: " + exc.reason)

