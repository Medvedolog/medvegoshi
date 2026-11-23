"""Explicit experimental V1 game launcher, never an installer or boot hook.

The V1 game application must be available as v1_game_app.py, the
paired application from the build artifact, not installed as boot-time main.py on this board.
Leave this entry point gated until physical V1 smoke tests pass.
"""
import sys

from ports import runtime_handoff

APP_NAME = "v1_game_app"


def _launch(profile, allow_wifi, importer=None):
    if APP_NAME in sys.modules:
        raise RuntimeError("restart before selecting AMOLED V1 again")
    if importer is None:
        importer = __import__
    runtime_handoff.stage(profile, allow_wifi)
    try:
        game = importer(APP_NAME)
    finally:
        # Also clear the request if the module was absent or failed to load.
        runtime_handoff.clear()
    if getattr(game, "runtime_profile_id", None) != "amoled_1_8_v1":
        raise RuntimeError("the application did not accept the AMOLED V1 profile")
    return game.principal()


def run(*, enabled=False, confirmed_v1=False, allow_wifi=False,
        allow_power_key=False, audio_factory=None):
    """Start a verified V1 profile explicitly. Wi-Fi is off unless opted in."""
    if enabled is not True or confirmed_v1 is not True:
        raise RuntimeError("experimental launch requires explicit V1 label confirmation")
    if type(allow_wifi) is not bool or type(allow_power_key) is not bool:
        raise ValueError("experimental flags must be bool")
    import os
    if APP_NAME in sys.modules:
        raise RuntimeError("restart before selecting AMOLED V1 again")
    try:
        os.stat(APP_NAME + ".py")
    except OSError:
        raise RuntimeError("the separately staged V1 application is missing")
    from ports.v1_bundle_guard import verify_runtime
    verify_runtime()  # no GPIO, hardware profile or save access before this
    from ports.amoled_v1_runtime import create_profile
    profile = create_profile(enabled=True, confirmed_v1=True,
                             allow_power_key=allow_power_key,
                             audio_factory=audio_factory)
    try:
        result = _launch(profile, allow_wifi)
    except BaseException:
        try:
            profile.close()
        except Exception:
            pass  # preserve the original failure
        raise
    profile.close()
    return result
