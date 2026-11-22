"""Fail-closed recovery for MedveGoshi's single-pet save slot.

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


def load_config(path, defaults, available):
    """Load config without silently discarding an existing active pet.

    A truly absent config is a normal first boot. A corrupt existing config
    or a saved ID missing from the available cast MUST stop before any save.
    """
    try:
        os.stat(path)
    except OSError:
        # New device, no active pet yet: use independent defaults.
        return dict(defaults)

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
            or saved_id not in available):
        raise RecoveryRequired("pet_missing", str(saved_id)[:40])
    return result


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
    else:
        desenho.centro("ОШИБКА НАСТРОЕК", 59, red)
        desenho.centro("config.json поврежден", 93, dark)
        desenho.centro("Восстановите файл", 137, dark)
    desenho.centro("Данные не изменены", 202, dark)
    desenho.centro("Подключите USB", 228, dark)
    tela.mostrar()


def require_config(path, defaults, available, tela, desenho):
    """Enforce no-write boot lock and show recovery if needed."""
    try:
        return load_config(path, defaults, available)
    except RecoveryRequired as exc:
        try:
            show_recovery(tela, desenho, exc)
        except Exception as show_error:
            print("Zoo recovery screen unavailable:", show_error)
        print("Zoo recovery: %s, pet_id=%s" % (exc.reason, exc.pet_id))
        raise RuntimeError("MedveGoshi data protected: " + exc.reason)
