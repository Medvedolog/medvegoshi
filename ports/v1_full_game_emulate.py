"""Run the real MedveGoshi game loop on a host-only V1 transport fixture.

This is not ESP32/MicroPython emulation, a hardware launcher, or a firmware
preview. It replaces hardware constructors only in this isolated CPython run.
"""

import argparse
import importlib
import json
import os
from pathlib import Path
import random
import runpy
import sys
import tempfile
import time
from types import SimpleNamespace

from ports import amoled_v1 as v1
from ports.emulate_v1 import AMOLED, FrameBuffer, MONO_HLSB, RGB565, Rig

ROOT = Path(__file__).resolve().parents[1]
# Real game touch script: feed, drag settings down, then close with BOOT.
def _touch(x, y):
    return {"touch": (v1.OFFSET_X + x, v1.OFFSET_Y + y)}

SCRIPT = ({}, _touch(48, 259), {}, {}, {}, _touch(120, 6), _touch(120, 205),
          {}, {}, {}, {}, {"boot": 1}, {"boot": 1}, {}, {}, {}, {}, {},
          {}, {}, {}, {}, {}, {}, {}, {}, {}, {})


class _FrameLimit(BaseException):
    pass


def _blocked(*_args, **_kwargs):
    raise AssertionError("network must not be activated by the host V1 smoke")


def emulate(inputs=SCRIPT):
    """Run real principal() with scripted touch/BOOT and no live saves."""
    if not inputs or len(inputs) > 64:
        raise ValueError("1..64 frames required")
    rig = Rig(inputs, "v1")
    machine = rig.machine()
    machine.I2C = lambda *_args, **_kw: rig
    framebuf = SimpleNamespace(FrameBuffer=FrameBuffer, RGB565=RGB565,
                               MONO_HLSB=MONO_HLSB)
    native = SimpleNamespace(QSPIPanel=rig.native_panel, AMOLED=AMOLED)
    sound_events, menu_history = [], []
    rtc_start = 1795345200  # 2026-11-22 11:00 UTC
    clock = SimpleNamespace(ticks_ms=lambda: 10_000 + rig.frame * 40,
                            ticks_diff=lambda a, b: a - b,
                            ticks_add=lambda a, b: a + b,
                            localtime=lambda epoch: time.gmtime(epoch))
    rtc = SimpleNamespace(epoch=lambda: rtc_start + rig.frame * 40 // 1000,
                          ler=lambda: time.gmtime(rtc_start + rig.frame * 40 // 1000)[:6],
                          acertar=_blocked, somar_minutos=_blocked)
    movement = SimpleNamespace(forca_g=lambda: 1.0)
    battery = SimpleNamespace(porcentagem=lambda: None, carregando=lambda: False,
                              tecla=lambda: False)
    sound = SimpleNamespace(ligado=False, tocar=sound_events.append,
                            volume_mic=lambda: 0, atualizar=lambda: None)

    hardware = {}

    def screen():
        tela, touch = v1.prepare_v1(rig, machine_module=machine,
                                    amoled_module=native, framebuffer_module=framebuf,
                                    verified_v1=True)
        draw_to_panel = tela.mostrar

        def render_and_limit():
            tela.fb.flush()
            draw_to_panel()
            menu_history.append(game_state["menu_alvo"])
            rig.frame += 1
            if rig.frame >= len(inputs):
                raise _FrameLimit

        tela.mostrar = render_and_limit
        hardware["touch"] = touch
        return tela

    network = SimpleNamespace(iniciar=lambda: None, ficar_offline=lambda yes: None if yes else _blocked(),
                              passo=lambda *_: (), amigo=lambda: None, wx=lambda _: None,
                              clima={}, situacao=lambda: 0, ler_wifi=_blocked, desligar_wifi=lambda: None)
    no_socket = SimpleNamespace(socket=_blocked, getaddrinfo=_blocked, create_connection=_blocked)
    shims = {"machine": machine, "framebuf": framebuf, "time": clock,
             "rede": network, "network": SimpleNamespace(WLAN=_blocked), "socket": no_socket}
    keys = (*shims, "hw", "desenho", "vida")
    prior = {key: sys.modules.get(key) for key in keys}
    original_cwd = Path.cwd()
    random_state = random.getstate()
    with tempfile.TemporaryDirectory(prefix="medve-v1-host-") as directory:
        try:
            from zoo import pet_slots
            os.chdir(directory)
            # Isolated starting fixtures: an adult, hungry Little Giraffe.
            Path("config.json").write_text(json.dumps({
                "personagem": "girafa", "modo": "pet", "hora": "real",
                "vel": 2, "offline": True, "som": False, "casa": "pet",
            }), encoding="utf-8")
            slot = Path(pet_slots.pet_path("girafa"))
            slot.parent.mkdir(parents=True)
            slot.write_text(json.dumps({
                "fome": 50, "alegria": 80, "energia": 80, "saude": 100,
                "cocos": 0, "doente": False, "dormindo": False, "cochilo": False,
                "epoch": rtc_start, "idade_min": 7200, "vida_adulto": 15, "morto": False,
            }), encoding="utf-8")
            for key in ("hw", "desenho", "vida"):
                sys.modules.pop(key, None)
            sys.modules.update(shims)
            hw = importlib.import_module("hw")
            hw.Tela = screen
            hw.Toque = lambda _bus: hardware["touch"]
            hw.Movimento = lambda _bus: movement
            hw.Relogio = lambda _bus: rtc
            hw.Som = lambda _bus: sound
            hw.Bateria = lambda _bus: battery
            random.seed(1)
            main = runpy.run_path(str(ROOT / "main.py"), run_name="_medve_v1_host")
            game_state = main["principal"].__globals__
            try:
                main["principal"]()
            except _FrameLimit:
                pass
            report = {"scope": "HOST_ONLY", "frames": rig.frame,
                      "pet": game_state["cfg"]["personagem"],
                      "life_stage": game_state["fase_vida"](),
                      "mode": game_state["cfg"]["modo"],
                      "food_before": 50, "food_after": game_state["pet"]["fome"],
                      "menu_opened": any(menu_history),
                      "menu_closed_after_open": any(menu_history) and menu_history[-1] == 0,
                      "fake_sound_events": sound_events,
                      "native_display_windows": rig.panel.transfers,
                      "network": "disabled", "saves": "temporary"}
            return rig.panel.image.copy(), report
        finally:
            os.chdir(original_cwd)
            random.setstate(random_state)
            for key, module in prior.items():
                if module is None:
                    sys.modules.pop(key, None)
                else:
                    sys.modules[key] = module


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    image, report = emulate()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("xb") as file:
        image.save(file, format="PNG")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
