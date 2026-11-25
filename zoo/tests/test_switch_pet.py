"""Exercise the same switch transaction used by the firmware menu."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from zoo import pet_slots, switch_pet

PET = {"fome": 80, "alegria": 80, "energia": 80, "saude": 100, "cocos": 0,
       "doente": False, "dormindo": False, "cochilo": False, "epoch": 0,
       "idade_min": 0.0, "vida_adulto": 15, "morto": False}


class SwitchPetTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = temp.name
        self.config = Path(self.root, "config.json")
        self.cfg = {"personagem": "girafa", "som": False}
        self.config.write_text(json.dumps(self.cfg))
        pet_slots.prepare("girafa", self.root)

    def test_switch_round_trip_preserves_both_pets_and_brains(self):
        def flush(data):
            def write(folder):
                Path(folder, "brain.bin").write_bytes(data)
            return write

        girafa = dict(PET, idade_min=750.0, fome=63)
        pip, new = switch_pet.activate(self.cfg, girafa, "pip", PET, 100,
                                       lambda: dict(PET), flush(b"Girafa"), self.root)
        self.assertTrue(new)
        self.assertEqual(Path(pet_slots.brain_dir("girafa", self.root),
                              "brain.bin").read_bytes(), b"Girafa")
        self.cfg["personagem"] = "pip"
        pip["fome"] = 32
        restored, new = switch_pet.activate(self.cfg, pip, "girafa", PET, 150,
                                            lambda: self.fail("reset existing pet"),
                                            flush(b"Pip"), self.root)
        self.assertFalse(new)
        self.assertEqual(restored["idade_min"], 750.0)
        self.assertEqual(restored["fome"], 63)
        self.assertEqual(pet_slots.load_pet("pip", PET, self.root)["fome"], 32)
        self.assertEqual(Path(pet_slots.brain_dir("pip", self.root),
                              "brain.bin").read_bytes(), b"Pip")
        self.assertEqual(json.loads(self.config.read_text())["personagem"], "girafa")

    def test_config_write_failure_keeps_active_selection_and_live_state(self):
        original = pet_slots.save_json
        previous = dict(PET, epoch=22, fome=42)

        def fail_config(path, data):
            if str(path) == str(self.config):
                raise OSError("fault injection")
            return original(path, data)

        with patch.object(pet_slots, "save_json", side_effect=fail_config):
            with self.assertRaises(OSError):
                switch_pet.activate(self.cfg, previous, "pip", PET, 80,
                                    lambda: dict(PET), root=self.root)
        self.assertEqual(self.cfg["personagem"], "girafa")
        self.assertEqual(previous["epoch"], 22)
        self.assertEqual(pet_slots.load_pet("girafa", PET, self.root)["fome"], 42)
        self.assertEqual(json.loads(self.config.read_text())["personagem"], "girafa")

    def test_bad_target_rejected_without_saving_anything(self):
        folder = Path(pet_slots.ensure_slot("pip", self.root))
        (folder / "capi.json").write_text("broken")
        with self.assertRaises(pet_slots.SlotError):
            switch_pet.activate(self.cfg, PET, "pip", PET, 80, lambda: dict(PET),
                                root=self.root)
        self.assertFalse(pet_slots.has_pet("girafa", self.root))
        self.assertEqual((folder / "capi.json").read_text(), "broken")


class SlotFilesystemTests(unittest.TestCase):
    def test_longest_mount_prefix_and_compact_path(self):
        root, child = object(), object()
        mounts = [(child, "/pet_saves"), (root, "/")]
        self.assertIs(pet_slots._mounted_for("/pet_saves/pip/capi.json", mounts), child)
        self.assertIs(pet_slots._mounted_for("/pet_saves_old/capi.json", mounts), root)
        self.assertEqual(pet_slots._absolute("../pip/capi.json", "/pet_saves/girafa"),
                         "/pet_saves/pip/capi.json")

    def test_wrong_micropython_mount_refuses_before_copy(self):
        from types import SimpleNamespace
        class Little:
            pass
        root = Little()
        child = object()
        board = SimpleNamespace(mount=lambda: [(root, "/"), (child, "/pet_saves")],
                                VfsLfs2=Little)
        fake_sys = SimpleNamespace(implementation=SimpleNamespace(name="micropython"))
        with patch.object(pet_slots, "sys", fake_sys), patch.dict("sys.modules", {"vfs": board}):
            pet_slots._require_littlefs("/config.json")
            with self.assertRaises(pet_slots.SlotError) as error:
                pet_slots.prepare("pip", "/")
            self.assertEqual(error.exception.reason, "slot_filesystem")
