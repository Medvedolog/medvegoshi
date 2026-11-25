"""Single-use, in-process handoff from an explicit experimental V1 launcher."""
_PENDING = None
_REQUIRED = ("i2c", "tela", "toque", "mov", "relogio", "som", "bateria", "botao")


def stage(profile, allow_wifi=False):
    global _PENDING
    if _PENDING is not None:
        raise RuntimeError("an AMOLED V1 profile is already pending")
    if type(allow_wifi) is not bool:
        raise ValueError("allow_wifi must be a bool")
    if (getattr(profile, "profile_id", None) != "amoled_1_8_v1" or
            not isinstance(getattr(profile, "capabilities", None), dict) or
            profile.capabilities.get("rtc_write") is not False or
            any(not hasattr(profile, item) for item in _REQUIRED)):
        raise ValueError("incomplete or unexpected AMOLED V1 profile")
    _PENDING = (profile, allow_wifi)


def take():
    global _PENDING
    result = _PENDING
    _PENDING = None
    return result


def clear():
    global _PENDING
    _PENDING = None
