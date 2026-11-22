"""Companion save fault tests plus real menu/Pip integration under CPython.

Only synthetic state and mocked hardware/network interfaces are used.
"""
from contextlib import contextmanager, redirect_stdout
import io
import json
import os
from pathlib import Path
import runpy
import struct
import sys
import tempfile
import time
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch
from zlib import crc32

from companion import placa
from zoo import pet_slots
from zoo.pip import game as pip_game

ROOT = Path(__file__).resolve().parents[1]
EPOCH = 1795345200
PET = {"fome": 80, "alegria": 80, "energia": 80, "saude": 100, "cocos": 0,
       "doente": False, "dormindo": False, "cochilo": False, "morto": False,
       "epoch": 0, "idade_min": 0.0, "vida_adulto": 15}


def blocked(*_args, **_kwargs):
    raise AssertionError("unexpected network or clock write")


class Canvas:
    def __getattr__(self, _name):
        return lambda *_args, **_kwargs: None


class Pin:
    IN, PULL_UP, OUT = 0, 1, 2

    def __init__(self, *_args, **_kwargs):
        pass

    def value(self):
        return 1


class HostNative:
    """Real vendored C rules behind the host bridge, not on-device firmware."""
    ABI_VERSION = 1
    MAX_STATE_BYTES = 282

    def reset(self, seed, now, tz_min):
        from zoo.pip.pet_host import Pet
        self.pet = Pet(seed=seed, now=now, tz_min=tz_min)

    def advance(self, now):
        self.pet.update(now)

    def event(self, name):
        return self.pet.event(name)

    def status(self):
        return self.pet.explain()

    def export_state(self):
        return self.pet.snapshot()

    def import_state(self, raw):
        from zoo.pip.pet_host import Pet
        self.pet = Pet.restore(raw)


class Board:
    def __init__(self, native=None):
        self.now, self.ms, self.native = EPOCH, 2000, native

    @contextmanager
    def boot(self):
        rtc = NS(epoch=lambda: self.now, ler=lambda: time.gmtime(self.now)[:6],
                 acertar=blocked, somar_minutos=blocked)
        clock = NS(ticks_ms=lambda: self.ms, ticks_add=lambda a, b: a+b,
                   ticks_diff=lambda a, b: a-b, localtime=time.gmtime, gmtime=time.gmtime)
        sound = NS(tocar=lambda *_: None, ligado=False, atualizar=lambda: None, volume_mic=lambda: 0)
        hw = NS(W=240, H=284, cor=lambda *_: 0,
                Tela=lambda: NS(fb=Canvas(), mostrar=lambda: None),
                Toque=lambda _bus: NS(ler=lambda: None),
                Movimento=lambda _bus: NS(forca_g=lambda: 1.0),
                Relogio=lambda _bus: rtc, Som=lambda _bus: sound,
                Bateria=lambda _bus: NS(porcentagem=lambda: None, carregando=lambda: False,
                                        tecla=lambda: False))
        modules = {"hw": hw, "machine": NS(I2C=lambda *_a, **_kw: object(), Pin=Pin),
                   "time": clock, "rede": NS(iniciar=blocked, wx=lambda *_: None),
                   "network": NS(WLAN=blocked), "pip_native": self.native,
                   "framebuf": NS(FrameBuffer=lambda *_: Canvas(), MONO_HLSB=0, RGB565=1)}
        with patch.dict(sys.modules, modules), redirect_stdout(io.StringIO()):
            for key in ("desenho", "vida", "font_ru"):
                sys.modules.pop(key, None)
            loaded = runpy.run_path(str(ROOT / "main.py"), run_name="_medve_persistence_host")
            state = loaded["acao_menu"].__globals__
            try:
                yield state
            finally:
                if state.get("pip_session"):
                    state["pip_session"].close()

    def touch(self, state, x, y):
        self.ms += 40
        state["menu_alvo"] = state["menu_borda"] = state["d"].MENU_FUNDO
        state["pressionar"](x, y, self.ms)

    def preview(self, state, target):
        cast = state["d"].ELENCO
        steps = (cast.index(target) - cast.index(state["cfg"]["personagem"])) % len(cast)
        if steps <= len(cast)//2:
            for _ in range(steps):
                self.touch(state, 214, 118)
        else:
            for _ in range(len(cast)-steps):
                self.touch(state, 30, 118)
        if state["menu_pend"] != target:
            raise AssertionError("could not preview installed pet")


class PersistenceRuntimeTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="medve-persistence-")
        self.addCleanup(temp.cleanup)
        previous = Path.cwd()
        os.chdir(temp.name)
        self.addCleanup(os.chdir, previous)

    def config(self, selected="girafa", **opts):
        cfg = dict({"personagem": selected, "modo": "pet", "hora": "real", "vel": 2,
                    "offline": True, "som": False}, **opts)
        Path("config.json").write_text(json.dumps(cfg), encoding="utf-8")
        return Path("config.json").read_bytes()

    def brain(self, seed, weight, age, folder=""):
        ponte = placa.Ponte(EPOCH, pasta=folder, semente=seed)
        ponte.cer.rede.w_ih[0] = weight
        ponte.cer.idade_s = age
        return ponte

    def assert_brain(self, folder, seed, weight, age, now):
        result = placa.carregar(folder)
        self.assertIsNotNone(result, "neither main nor backup brain is readable")
        brain, saved = result
        self.assertEqual((brain.semente, brain.rede.w_ih[0], brain.idade_s, saved),
                         (seed, weight, age, now))

    def fail_final_brain(self, src, dst):
        if dst == placa.ARQ:
            raise OSError("injected final brain rename failure")
        return self.publish(src, dst)

    def test_repeated_fault_preserves_the_only_valid_primary_and_success_rotates(self):
        brain = self.brain(211, 27, 800)
        placa.gravar(brain.cer, EPOCH)
        before = Path(placa.ARQ).read_bytes()
        self.assertEqual(struct.unpack("<I", before[-4:])[0], crc32(before[:-4]))
        brain.cer.rede.w_ih[0] = 91
        self.publish = placa._publish_brain
        with patch.object(placa, "_publish_brain", side_effect=self.fail_final_brain):
            for step in (1, 2, 3):
                with self.assertRaises(OSError):
                    placa.gravar(brain.cer, EPOCH+step)
                self.assertEqual(Path(placa.ARQ).read_bytes(), before)
                self.assert_brain("", 211, 27, 800, EPOCH)
        placa.gravar(brain.cer, EPOCH+5)
        self.assertEqual(Path(placa.BAK).read_bytes(), before)
        self.assert_brain("", 211, 91, 800, EPOCH+5)

    def test_corrupt_or_missing_primary_never_evicts_good_backup(self):
        brain = self.brain(223, -29, 1400)
        placa.gravar(brain.cer, EPOCH)
        before = Path(placa.ARQ).read_bytes()
        Path(placa.BAK).write_bytes(before)
        brain.cer.rede.w_ih[0] = 19
        self.publish = placa._publish_brain
        with patch.object(placa, "_publish_brain", side_effect=self.fail_final_brain):
            Path(placa.ARQ).write_bytes(b"corrupt")
            for _ in range(2):
                with self.assertRaises(OSError):
                    placa.gravar(brain.cer, EPOCH+60)
                self.assertEqual(Path(placa.BAK).read_bytes(), before)
                self.assert_brain("", 223, -29, 1400, EPOCH)
                if Path(placa.ARQ).exists():
                    Path(placa.ARQ).unlink()
        placa.gravar(brain.cer, EPOCH+60)
        self.assertEqual(Path(placa.BAK).read_bytes(), before)
        self.assert_brain("", 223, 19, 1400, EPOCH+60)

    def test_staged_layout_wrong_even_with_recomputed_crc_is_not_published(self):
        brain = self.brain(229, 31, 70)
        placa.gravar(brain.cer, EPOCH)
        before = Path(placa.ARQ).read_bytes()
        verify = placa._valid_on_disk

        def tamper(path, lengths):
            if path == placa.TMP:
                record = bytearray(Path(path).read_bytes())
                record[struct.calcsize(placa.CAB)] ^= 1
                record[-4:] = struct.pack("<I", crc32(record[:-4]))
                Path(path).write_bytes(record)
            return verify(path, lengths)

        with patch.object(placa, "_valid_on_disk", side_effect=tamper):
            with self.assertRaisesRegex(OSError, "staged save verification"):
                placa.gravar(brain.cer, EPOCH+30)
        self.assertEqual(Path(placa.ARQ).read_bytes(), before)

    def test_interrupted_migration_then_real_menu_roundtrip_keeps_both_brains(self):
        self.config()
        Path("capi.json").write_text(json.dumps(dict(PET, fome=63, idade_min=7200, epoch=EPOCH)))
        brain = self.brain(307, 409, 18000)
        placa.gravar(brain.cer, EPOCH-60)
        brain.cer.rede.w_ih[0] = 410
        placa.gravar(brain.cer, EPOCH)
        originals = {name: Path(name).read_bytes() for name in ("config.json", "capi.json", "brain.bin", "brain.bak")}
        replace = pet_slots._replace

        def interrupted(src, dst):
            if dst == "pet_saves/girafa/brain.bin":
                raise OSError("simulated migration interruption")
            return replace(src, dst)

        board = Board()
        with patch.object(pet_slots, "_replace", side_effect=interrupted):
            with self.assertRaisesRegex(RuntimeError, "MedveGoshi data protected"):
                with board.boot():
                    self.fail("half migrated game was opened")
        self.assertTrue(Path("pet_saves/legacy-v1.pending").is_file())
        for name, raw in originals.items():
            self.assertEqual(Path(name).read_bytes(), raw)
        with board.boot() as state:
            self.assertEqual(state["pet"]["fome"], 63)
            ga = pet_slots.brain_dir("girafa")
            self.assertEqual(Path(ga, "brain.bak").read_bytes(), originals["brain.bak"])
            state["ponte"] = placa.Ponte(EPOCH, pasta=ga)
            board.preview(state, "pip")
            board.touch(state, 165, 220)  # actual cancel hitbox
            self.assertEqual(state["cfg"]["personagem"], "girafa")
            self.assertEqual(Path("config.json").read_bytes(), originals["config.json"])
            board.preview(state, "pip")
            board.touch(state, 62, 220)  # actual confirm hitbox
            self.assertEqual(state["cfg"]["personagem"], "pip")
            self.assertEqual(state["fase_vida"](), "ovo")
            self.assertEqual(Path(ga, "brain.bin").read_bytes(), originals["brain.bin"])
            state["pet"].update(fome=23, idade_min=4300)
            pp = pet_slots.brain_dir("pip")
            state["ponte"] = self.brain(311, -55, 25000, pp)
            board.now += 500
            board.preview(state, "girafa")
            board.touch(state, 62, 220)
            self.assertEqual((state["cfg"]["personagem"], state["pet"]["fome"],
                              state["pet"]["idade_min"]), ("girafa", 63, 7200))
            self.assertEqual(pet_slots.load_pet("pip", PET)["fome"], 23)
            self.assert_brain(pp, 311, -55, 25000, board.now)
            self.assert_brain(ga, 307, 410, 18000, EPOCH)
        for name in ("capi.json", "brain.bin", "brain.bak"):
            self.assertEqual(Path(name).read_bytes(), originals[name])

    def test_last_config_rename_failure_keeps_config_and_actual_brains(self):
        config = self.config()
        pet_slots.prepare("girafa")
        pet_slots.save_pet("girafa", dict(PET, fome=44, idade_min=7200))
        pet_slots.save_pet("pip", dict(PET, fome=66, idade_min=6200))
        ga, pp = (pet_slots.brain_dir(p) for p in ("girafa", "pip"))
        girafa, pip = self.brain(613, 20, 24000, ga), self.brain(617, 120, 26000, pp)
        placa.gravar(girafa.cer, EPOCH, ga)
        placa.gravar(pip.cer, EPOCH, pp)
        old_pip = Path(pp, "brain.bin").read_bytes()
        replace = pet_slots._replace

        def fail_config(src, dst):
            if dst == "config.json":
                raise OSError("injected final config rename failure")
            return replace(src, dst)

        board = Board()
        with board.boot() as state:
            state["ponte"] = girafa
            state["pet"]["fome"] = 33
            girafa.cer.rede.w_ih[0] = 89
            board.preview(state, "pip")
            with patch.object(pet_slots, "_replace", side_effect=fail_config):
                board.touch(state, 62, 220)
            self.assertEqual(state["cfg"]["personagem"], "girafa")
            self.assertIs(state["ponte"], girafa)
            self.assertEqual(state["pet"]["fome"], 33)
            self.assertEqual(state["sis_txt"], "Не удалось сменить")
            self.assertEqual(Path("config.json").read_bytes(), config)
            self.assertEqual(Path(pp, "brain.bin").read_bytes(), old_pip)
            self.assert_brain(ga, 613, 89, 24000, EPOCH)
        with board.boot() as state:
            self.assertEqual((state["cfg"]["personagem"], state["pet"]["fome"]), ("girafa", 33))

    def test_legacy_feed_and_real_c_pip_overfeeding_sidecar_survive_reboot(self):
        self.config("pip", pip_native=True)
        pet_slots.prepare("pip")
        pet_slots.save_pet("pip", dict(PET, fome=50, idade_min=7200, epoch=EPOCH))
        path = Path(pet_slots.brain_dir("pip"), pip_game.STATE_NAME)
        with Board().boot() as state:
            state["pip_atualizar"](2000)
            self.assertIsNone(state["pip_snapshot"])
            state["acao_pet"](0)
            self.assertEqual(state["pet"]["fome"], 75)
            self.assertFalse(path.exists())
        with Board(HostNative()).boot() as state:
            state["pip_atualizar"](2000)
            self.assertEqual(round(state["pet"]["fome"]), 90)
            state["acao_pet"](0)
            self.assertEqual(round(state["pet"]["fome"]), 100)
            self.assertEqual(state["pip_reaction"], "nauseous")
            state["acao_pet"](0)
            self.assertEqual(state["pip_reaction"], "disgusted")
            saved = path.read_bytes()
        with Board(HostNative()).boot() as state:
            state["pip_atualizar"](2000)
            self.assertEqual(round(state["pet"]["fome"]), 100)
            self.assertEqual(path.read_bytes(), saved)
            self.assertEqual(state["pip_snapshot"]["now"], EPOCH)
        self.assertFalse(Path("pet_saves/girafa", pip_game.STATE_NAME).exists())


if __name__ == "__main__":
    unittest.main()
