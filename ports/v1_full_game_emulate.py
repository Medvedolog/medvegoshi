"""Run the real MedveGoshi game loop on a host-only V1 transport fixture.

This is not ESP32/MicroPython emulation, a hardware launcher, or a firmware
preview. It stages simulated peripherals through the same single-use V1
handoff consumed by the device game application.
"""

import argparse
import calendar
import json
import os
from pathlib import Path
import random
import runpy
import struct
import sys
import tempfile
import time
from types import SimpleNamespace

from ports import amoled_v1 as v1, amoled_v1_runtime, runtime_handoff
from ports.emulate_v1 import AMOLED, FrameBuffer, MONO_HLSB, RGB565, Rig

ROOT = Path(__file__).resolve().parents[1]
# Real game touch script: feed, drag settings down, then close with BOOT.
def _touch(x, y):
    return {"touch": (v1.OFFSET_X + x, v1.OFFSET_Y + y)}

SCRIPT = ({}, _touch(48, 259), {}, {}, {}, _touch(120, 6), _touch(120, 205),
          {}, {}, {}, {}, {"boot": 1}, {"boot": 1}, {}, {}, {}, {}, {},
          {}, {}, {}, {}, {}, {}, {}, {}, {}, {})


def _idle(count):
    return tuple({} for _ in range(count))


# Each touch moves through the real FT3168 register/data path; in particular
# do not call a pet switch function directly. Include release/animation time
# so menu hit areas correspond to the externally visible controls.
_OPEN = (_touch(120, 6), _touch(120, 238)) + _idle(12)
_CONFIRM = _idle(3) + (_touch(55, 218),) + _idle(3)
_CLOSE = ({"boot": 1},) + _idle(16)
SWITCH_SCRIPT = (
    ({}, _touch(48, 259)) + _idle(3)
    + _OPEN + (_touch(44, 121),) + _CONFIRM + _CLOSE
    + (_touch(48, 259),) + _idle(4)
    + _OPEN + (_touch(194, 121),) + _CONFIRM + _CLOSE
)
POLICY_SCRIPT = (
    _OPEN + (_touch(38, 222),) + _idle(3)
    + (_touch(38, 18),) + _idle(16)
)


class _FrameLimit(BaseException):
    pass


class _GameRig(Rig):
    """Hardware register fixture for the real V1 profile factory."""

    epoch_start = 1795345200  # 2026-11-22 11:00 UTC

    def __init__(self, inputs):
        super().__init__(inputs, "v1")
        self.rtc_valid = True

    def scan(self):
        return super().scan() + [0x51, 0x6B]

    def readfrom_mem(self, address, register, size):
        def bcd(n):
            return ((n // 10) << 4) + n % 10
        if (address, register, size) == (0x51, 0x04, 7):
            y, month, day, h, m, s = time.gmtime(self.epoch_start + self.frame * 40 // 1000)[:6]
            return bytes((bcd(s) if self.rtc_valid else 0x80, bcd(m), bcd(h),
                          bcd(day), 0, bcd(month), bcd(y - 2000)))
        table = {
            (0x51, 0x00): b"\x00",     # RTC control: 24-hour, running
            (0x6B, 0x00): b"\x05",     # QMI8658 WHO_AM_I
            (0x6B, 0x02): b"\x40",     # auto-increment already enabled
            (0x6B, 0x03): b"\x15",     # active ±4 g
            (0x6B, 0x08): b"\x01",     # accelerometer enabled
            (0x6B, 0x2E): b"\x01",     # data ready
            (0x6B, 0x35): struct.pack("<hhh", 0, 0, 8192),
            (0x34, 0x00): b"\x00",     # no battery attached
        }
        data = table.get((address, register))
        if data is not None and len(data) == size:
            return data
        return super().readfrom_mem(address, register, size)


def _blocked(*_args, **_kwargs):
    raise AssertionError("no network or RTC writes in host V1 smoke")


class _HostPipModule:
    """Translate the desktop C core into the MicroPython module's shape.

    The host exercise covers the same C rules and game wiring. It does
    not execute the ESP32 module or assert binary snapshot interchange.
    """

    def __init__(self):
        from zoo.pip.pet_host import Pet
        self.Pet = Pet
        self.events = []

    def reset(self, seed, now, tz_min):
        self.pet = self.Pet(seed, now, tz_min)

    def advance(self, now):
        self.pet.update(now)

    def status(self):
        return self.pet.explain()

    def event(self, name):
        reaction = self.pet.event(name)
        self.events.append((name, reaction))
        return reaction

    def export_state(self):
        return self.pet.snapshot()

    def import_state(self, blob):
        self.pet = self.Pet.restore(blob)


def emulate(inputs=SCRIPT, *, fixtures=None, pet_images=None, rtc_valid=True, native_pip=False):
    """Run real principal() with scripted touch/BOOT and no live saves."""
    if not inputs or len(inputs) > 96:
        raise ValueError("1..96 frames required")
    fixtures = {"girafa": 50} if fixtures is None else dict(fixtures)
    if "girafa" not in fixtures:
        raise ValueError("adult Little Giraffe is the initial fixture")
    if native_pip and "pip" not in fixtures:
        raise ValueError("native Pip scenario requires a Pip slot")
    host_pip = None
    if native_pip:
        # Import before applying shims so the persistent Python package
        # cannot retain a fake clock after the harness has returned.
        from zoo.pip import game as pip_game
        host_pip = _HostPipModule()
    rig = _GameRig(inputs)
    machine = rig.machine()
    machine.I2C = lambda *_args, **_kw: rig
    framebuf = SimpleNamespace(FrameBuffer=FrameBuffer, RGB565=RGB565,
                               MONO_HLSB=MONO_HLSB)
    native = SimpleNamespace(QSPIPanel=rig.native_panel, AMOLED=AMOLED)
    sound_events, menu_history, pet_trace = [], [], []
    clock = SimpleNamespace(ticks_ms=lambda: 10_000 + rig.frame * 40,
                            ticks_diff=lambda a, b: a - b,
                            ticks_add=lambda a, b: a + b,
                            gmtime=time.gmtime,
                            mktime=calendar.timegm,
                            localtime=lambda epoch: time.gmtime(epoch))

    def wrap_screen(tela):
        draw_to_panel = tela.mostrar

        def render_and_limit():
            tela.fb.flush()
            draw_to_panel()
            menu_history.append(game_state["menu_alvo"])
            active = game_state["cfg"]["personagem"]
            if not pet_trace or pet_trace[-1]["pet"] != active:
                pet_trace.append({"pet": active, "food": game_state["pet"]["fome"],
                                  "life_stage": game_state["fase_vida"]()})
            if pet_images is not None and game_state["menu_borda"] == 0:
                pet_images[active] = rig.panel.image.copy()
            rig.frame += 1
            if rig.frame >= len(inputs):
                raise _FrameLimit

        tela.mostrar = render_and_limit

    offline_calls = []

    def offline(yes):
        if yes is not True:
            _blocked()
        offline_calls.append(yes)

    network = SimpleNamespace(iniciar=_blocked, ficar_offline=offline,
                              passo=lambda *_: (), amigo=lambda: None, wx=lambda _: None,
                              clima={}, situacao=lambda: 0, ler_wifi=_blocked, desligar_wifi=lambda: None)
    no_socket = SimpleNamespace(socket=_blocked, getaddrinfo=_blocked, create_connection=_blocked)
    shims = {"machine": machine, "framebuf": framebuf, "time": clock,
             "rede": network, "network": SimpleNamespace(WLAN=_blocked), "socket": no_socket}
    if host_pip is not None:
        shims["pip_native"] = host_pip
    keys = (*shims, "hw", "desenho", "vida")
    prior = {key: sys.modules.get(key) for key in keys}
    original_cwd = Path.cwd()
    random_state = random.getstate()
    game_state = {}
    profile = None
    with tempfile.TemporaryDirectory(prefix="medve-v1-host-") as directory:
        try:
            from zoo import pet_slots, registry
            os.chdir(directory)
            # Isolated adult slots; never migrate or open an owner's save.
            Path("config.json").write_text(json.dumps({
                "personagem": "girafa", "modo": "pet", "hora": "real",
                "vel": 2, "offline": False, "som": False, "casa": "pet",
                "pip_native": native_pip,
            }), encoding="utf-8")
            for pet_id, food in fixtures.items():
                if registry.renderer(pet_id) is None:
                    raise RuntimeError("Zoo renderer required for: " + pet_id)
                slot = Path(pet_slots.pet_path(pet_id))
                slot.parent.mkdir(parents=True)
                slot.write_text(json.dumps({
                    "fome": food, "alegria": 80, "energia": 80, "saude": 100,
                    "cocos": 0, "doente": False, "dormindo": False, "cochilo": False,
                    "epoch": rig.epoch_start, "idade_min": 7200, "vida_adulto": 15, "morto": False,
                }), encoding="utf-8")
            for key in ("hw", "desenho", "vida"):
                sys.modules.pop(key, None)
            sys.modules.update(shims)
            import hw
            profile = amoled_v1_runtime.create_profile(
                enabled=True, confirmed_v1=True, machine_module=machine,
                native_module=native, framebuffer_module=framebuf, clock=clock)
            wrap_screen(profile.tela)
            original_sound = profile.som.tocar
            def log_silent_sound(name):
                sound_events.append(name)
                return original_sound(name)
            profile.som.tocar = log_silent_sound
            # For the invalid case, lose valid RTC *after* factory preflight
            # to verify the real main handles a subsequently failed read.
            rig.rtc_valid = rtc_valid
            def forbid_ips(*args, **kwargs):
                raise AssertionError("V1 handoff fell back to legacy IPS hardware")
            # Keep actual dimensions and color conversion, but trap all
            # legacy constructor calls. The game's V1 branch must consume
            # the explicit profile rather than accidentally driving IPS pins.
            for name in ("Tela", "Toque", "Movimento", "Relogio", "Som", "Bateria"):
                setattr(hw, name, forbid_ips)
            random.seed(1)
            runtime_handoff.stage(profile, allow_wifi=False)
            try:
                main = runpy.run_path(str(ROOT / "main.py"), run_name="_medve_v1_host")
                if runtime_handoff.take() is not None:
                    raise AssertionError("main did not consume the V1 profile")
            finally:
                runtime_handoff.clear()
            game_state = main["principal"].__globals__
            if game_state["runtime_profile_id"] != profile.profile_id:
                raise AssertionError("main did not enter the staged V1 profile")
            try:
                main["principal"]()
            except _FrameLimit:
                pass
            report = {"scope": "HOST_ONLY", "frames": rig.frame,
                      "pet": game_state["cfg"]["personagem"],
                      "life_stage": game_state["fase_vida"](),
                      "runtime_profile": game_state["runtime_profile_id"],
                      "rtc_write_enabled": game_state["runtime_clock_write"],
                      "offline_forced": bool(offline_calls),
                      "last_system_notice": game_state["sis_txt"],
                      "mode": game_state["cfg"]["modo"],
                      "food_before": fixtures["girafa"], "food_after": game_state["pet"]["fome"],
                      "pet_trace": pet_trace,
                      "saved_food": {
                          pet_id: json.loads(Path(pet_slots.pet_path(pet_id)).read_text())["fome"]
                          for pet_id in fixtures
                      },
                      "menu_opened": any(menu_history),
                      "menu_closed_after_open": any(menu_history) and menu_history[-1] == 0,
                      "fake_sound_events": sound_events,
                      "native_display_windows": rig.panel.transfers,
                      "simulated_i2c_write_addresses": sorted({entry[0] for entry in rig.writes}),
                      "v1_capabilities": dict(profile.capabilities),
                      "network": "disabled", "saves": "temporary"}
            if host_pip is not None:
                sidecar = Path(pet_slots.brain_dir("pip")) / pip_game.STATE_NAME
                data = json.loads(sidecar.read_text())
                restored = host_pip.Pet.restore(bytes.fromhex(data["state_hex"]))
                report["native_pip"] = {
                    "implementation": "desktop C fixture, not ESP32",
                    "events": host_pip.events,
                    "sidecar_owner": data["pet_id"],
                    "restored_food": restored.explain()["needs"]["food"],
                }
            return rig.panel.image.copy(), report
        finally:
            session = game_state.get("pip_session")
            if session is not None:
                session.close()
            if profile is not None:
                profile.close()
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
    parser.add_argument("--scenario", choices=("care", "switch"), default="care")
    parser.add_argument("--native-pip", action="store_true",
                        help="exercise Pip through the optional desktop C adapter")
    parser.add_argument("--pip-out", type=Path,
                        help="save the simulated Pip frame in the switch scenario")
    args = parser.parse_args(argv)
    if args.pip_out is not None and args.scenario != "switch":
        parser.error("--pip-out requires --scenario switch")
    if args.native_pip and args.scenario != "switch":
        parser.error("--native-pip requires --scenario switch")
    if args.scenario == "switch":
        pictures = {} if args.pip_out is not None else None
        image, report = emulate(SWITCH_SCRIPT, fixtures={"girafa": 50, "pip": 36},
                                pet_images=pictures, native_pip=args.native_pip)
    else:
        image, report = emulate()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("xb") as file:
        image.save(file, format="PNG")
    if args.pip_out is not None:
        args.pip_out.parent.mkdir(parents=True, exist_ok=True)
        with args.pip_out.open("xb") as file:
            pictures["pip"].save(file, format="PNG")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())

