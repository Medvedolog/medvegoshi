"""Run the real MedveGoshi game loop on a host-only V1 transport fixture.

This is not ESP32/MicroPython emulation, a hardware launcher, or a firmware
preview. It stages simulated peripherals through the same single-use V1
handoff consumed by the device game application.
"""

import argparse
import calendar
import hashlib
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
from ports.emulate_v1 import AMOLED, FrameBuffer, MONO_HLSB, Panel, RGB565, Rig

ROOT = Path(__file__).resolve().parents[1]
# Real game touch script: feed, drag settings down, then close with BOOT.
def _touch(x, y):
    return {"touch": (v1.OFFSET_X + x, v1.OFFSET_Y + y)}

SCRIPT = ({}, _touch(48, 259), {}, {}, {}, _touch(120, 6), _touch(120, 205),
          {}, {}, {}, {}, {"boot": 1}, {"boot": 1}, {}, {}, {}, {}, {},
          {}, {}, {}, {}, {}, {}, {}, {}, {}, {})


def _idle(count):
    return tuple({} for _ in range(count))


def _remap_inputs(inputs, screen_mode, physical_touches):
    """Legacy scripts use the 1:1 panel as their logical-coordinate carrier."""
    if screen_mode not in (v1.SCALE_NATIVE, v1.SCALE_LARGE):
        raise ValueError("invalid V1 screen mode: " + str(screen_mode))
    if screen_mode == v1.SCALE_NATIVE or physical_touches:
        return inputs
    mapped = []
    for event in inputs:
        point = event.get("touch")
        if point is None:
            mapped.append(event)
            continue
        logical = v1.physical_to_logical(*point)
        row = dict(event)
        if logical is None:
            # A deliberately rejected old margin sample must not become
            # an active touch when the large viewport covers that margin.
            row.pop("touch", None)
        else:
            row["touch"] = v1.VIEWPORT_LARGE.logical_to_physical(*logical)
        mapped.append(row)
    return tuple(mapped)


class _WireOverlayFrameBuffer:
    """Physical RGB565 fixture: native menu glyphs modify the scaled bytes."""
    def __init__(self, buf, width, height):
        self.buf, self.width, self.height = buf, width, height

    def fill_rect(self, x, y, width, height, color):
        left, top = max(0, x), max(0, y)
        right, bottom = min(self.width, x + width), min(self.height, y + height)
        if left >= right or top >= bottom:
            return
        # MicroPython RGB565 stores each 16-bit word little-endian.
        # The game's byte-swapped palette is already prepared for the wire.
        row = struct.pack("<H", color & 0xFFFF) * (right - left)
        for yy in range(top, bottom):
            start = 2 * (yy * self.width + left)
            self.buf[start:start + len(row)] = row


def _framebuffer(buf, width, height, fmt):
    viewport = v1.VIEWPORT_LARGE
    if fmt == RGB565 and (width, height) == (viewport.width, viewport.height):
        return _WireOverlayFrameBuffer(buf, width, height)
    return FrameBuffer(buf, width, height, fmt)


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


def _stage_extracted_app(entry):
    """Copy allowlisted, already extracted bundle files into the temp game cwd."""
    from ports.package_amoled_v1_app import APP_FILES, STATUS_NAME
    from ports.v1_bundle_guard import INDEX, MAX_INDEX, verify_files
    if entry.name != "v1_game_app.py":
        raise ValueError("expected extracted v1_game_app.py")
    allowed = {name for _, name in APP_FILES} | {STATUS_NAME, INDEX}

    def open_source(name, mode):
        if name not in allowed:
            raise OSError("unexpected extracted app member")
        return (entry.parent / name).open(mode)

    with open_source(INDEX, "rb") as handle:
        index = handle.read(MAX_INDEX + 1)
    if len(index) > MAX_INDEX:
        raise ValueError("oversized extracted application index")
    digest = hashlib.sha256(index).hexdigest()
    verify_files(digest, open_source)
    for line in index.decode("ascii").splitlines():
        _, name = line.split("  ", 1)
        target = Path(name)
        target.parent.mkdir(parents=True, exist_ok=True)
        with open_source(name, "rb") as source:
            target.write_bytes(source.read())
    Path(INDEX).write_bytes(index)
    return digest


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


def emulate(inputs=SCRIPT, *, fixtures=None, pet_images=None, rtc_valid=True,
            native_pip=False, app_path=None, screen_mode="1:1",
            physical_touches=False):
    """Run real principal() with scripted touch/BOOT and no live saves.

    app_path may name a trusted v1_game_app.py in an extracted bundle. Run
    the real launcher with simulated native module identities and register
    I/O. Already imported host packages can still come from this checkout.

    By default, scripted touch samples use the legacy 1:1 panel coordinates,
    translated through the selected viewport. Pass physical_touches=True
    for raw samples already expressed in the active physical panel space.
    """
    if not inputs or len(inputs) > 96:
        raise ValueError("1..96 frames required")
    fixtures = {"girafa": 50} if fixtures is None else dict(fixtures)
    if "girafa" not in fixtures:
        raise ValueError("adult Little Giraffe is the initial fixture")
    if native_pip and "pip" not in fixtures:
        raise ValueError("native Pip scenario requires a Pip slot")
    entry = ROOT / "main.py" if app_path is None else Path(app_path).resolve(strict=True)
    host_pip = None
    if native_pip:
        # Import before applying shims so the persistent Python package
        # cannot retain a fake clock after the harness has returned.
        from zoo.pip import game as pip_game
        host_pip = _HostPipModule()
    rig = _GameRig(_remap_inputs(inputs, screen_mode, physical_touches))
    machine = rig.machine()
    machine.I2C = lambda *_args, **_kw: rig
    if app_path is not None:
        # V1 still needs MicroPython SPI(2) as the native QSPI bus carrier,
        # but must not use IPS SPI pins, PWM backlight or I2S/audio methods.
        def qspi_only(bus, *, sck, **opts):
            if bus != 2 or sck.number != v1.GPIO_CLK or opts.get("mosi") is not None:
                raise AssertionError("application attempted non-V1 SPI")
            return object()
        machine.SPI = qspi_only
        del machine.PWM, machine.I2S
    framebuf = SimpleNamespace(FrameBuffer=_framebuffer, RGB565=RGB565,
                               MONO_HLSB=MONO_HLSB)
    native = SimpleNamespace(QSPIPanel=rig.native_panel, AMOLED=AMOLED)
    if app_path is not None:
        class NativePanel(Panel):
            def __init__(self, **kwargs):
                super().__init__(**kwargs)
                rig.panel = self
        native.QSPIPanel = NativePanel
    sound_events, menu_history, pet_trace = [], [], []
    clock = SimpleNamespace(ticks_ms=lambda: 10_000 + rig.frame * 40,
                            ticks_diff=lambda a, b: a - b,
                            ticks_add=lambda a, b: a + b,
                            sleep_ms=lambda _ms: None,  # setup settling on simulated hardware
                            gmtime=time.gmtime,
                            mktime=calendar.timegm,
                            localtime=lambda epoch: time.gmtime(epoch))

    def wrap_screen(tela):
        draw_to_panel = tela.mostrar

        def render_and_limit():
            nonlocal game_state
            if not game_state and app_path is not None:
                game_state = vars(sys.modules["v1_game_app"])
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
    keys = (*shims, "hw", "desenho", "vida", "amoled", "pip_native", "v1_game_app")
    prior = {key: sys.modules.get(key) for key in keys}
    original_cwd = Path.cwd()
    original_sys_path = sys.path[:]
    random_state = random.getstate()
    game_state = {}
    profile = None
    with tempfile.TemporaryDirectory(prefix="medve-v1-host-") as directory:
        try:
            from zoo import pet_slots, registry
            os.chdir(directory)
            if app_path is not None:
                from ports import amoled_v1_launch, v1_bundle_guard
                digest = _stage_extracted_app(entry)
                native_pip_api = host_pip or SimpleNamespace()
                native_pip_api.ABI_VERSION = 1
                native_pip_api.APP_INDEX_SHA256 = digest
                for name in v1_bundle_guard.REQUIRED_PIP:
                    if not hasattr(native_pip_api, name):
                        setattr(native_pip_api, name, lambda *_a, **_kw: None)
                shims.update(amoled=native, pip_native=native_pip_api)
                sys.modules.pop("v1_game_app", None)
                sys.path.insert(0, directory)
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
            create_profile = amoled_v1_runtime.create_profile

            def instrument_profile(**opts):
                nonlocal profile
                profile = create_profile(
                    machine_module=machine, native_module=native,
                    framebuffer_module=framebuf, clock=clock, **opts)
                wrap_screen(profile.tela)
                original_sound = profile.som.tocar

                def log_silent_sound(name):
                    sound_events.append(name)
                    return original_sound(name)

                profile.som.tocar = log_silent_sound
                # Simulate loss after factory preflight, not at its probe.
                rig.rtc_valid = rtc_valid
                return profile
            def forbid_ips(*args, **kwargs):
                raise AssertionError("V1 handoff fell back to legacy IPS hardware")
            # Keep actual dimensions and color conversion, but trap all
            # legacy constructor calls. The game's V1 branch must consume
            # the explicit profile rather than accidentally driving IPS pins.
            for name in ("Tela", "Toque", "Movimento", "Relogio", "Som", "Bateria"):
                setattr(hw, name, forbid_ips)
            random.seed(1)
            if app_path is None:
                instrument_profile(enabled=True, confirmed_v1=True, screen_mode=screen_mode)
                runtime_handoff.stage(profile, allow_wifi=False)
                try:
                    main = runpy.run_path(str(entry), run_name="_medve_v1_host")
                    if runtime_handoff.take() is not None:
                        raise AssertionError("main did not consume the V1 profile")
                finally:
                    runtime_handoff.clear()
                game_state = main["principal"].__globals__
                try:
                    main["principal"]()
                except _FrameLimit:
                    pass
            else:
                amoled_v1_runtime.create_profile = instrument_profile
                try:
                    amoled_v1_launch.run(enabled=True, confirmed_v1=True, screen_mode=screen_mode)
                except _FrameLimit:
                    pass
                finally:
                    amoled_v1_runtime.create_profile = create_profile
                if (game_state.get("__name__") != amoled_v1_launch.APP_NAME or
                        Path(game_state["__file__"]).parent != Path(directory)):
                    raise AssertionError("launcher did not execute the staged application")
            if game_state["runtime_profile_id"] != profile.profile_id:
                raise AssertionError("main did not enter the staged V1 profile")
            report = {"scope": "HOST_ONLY", "frames": rig.frame,
                      "pet": game_state["cfg"]["personagem"],
                      "life_stage": game_state["fase_vida"](),
                      "runtime_profile": game_state["runtime_profile_id"],
                      "screen_mode": screen_mode,
                      "rtc_write_enabled": game_state["runtime_clock_write"],
                      "offline_forced": game_state["runtime_allow_wifi"] is False,
                      "offline_callback_used": bool(offline_calls),
                      "packaged_entry": app_path is not None,
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
            if profile is not None and app_path is None:
                profile.close()
            os.chdir(original_cwd)
            sys.path[:] = original_sys_path
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
    parser.add_argument("--screen-mode", choices=(v1.SCALE_NATIVE, v1.SCALE_LARGE),
                        default=v1.SCALE_NATIVE)
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
                                pet_images=pictures, native_pip=args.native_pip,
                                screen_mode=args.screen_mode)
    else:
        image, report = emulate(screen_mode=args.screen_mode)
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

