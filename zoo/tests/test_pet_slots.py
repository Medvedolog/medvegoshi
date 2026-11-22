"""Host regressions for the MicroPython-compatible pet save format."""
import errno
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from zoo import pet_slots as slots
from zoo import recovery

DEFAULTS = {"fome": 80, "alegria": 80, "energia": 80, "saude": 100, "cocos": 0,
            "doente": False, "dormindo": False, "cochilo": False, "morto": False,
            "epoch": 0, "idade_min": 0., "vida_adulto": 15}


class PetSlotTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.root_s = str(self.root)
        self.saves = self.root / slots.SAVE_ROOT

    def _json(self, path, data):
        (self.root / path).write_text(json.dumps(data), encoding="utf-8")

    def _legacy(self, identity=None, config=True):
        if config:
            self._json("config.json", {"personagem": "girafa"})
        data = dict(DEFAULTS, fome=31, epoch=1234)
        if identity is not None:
            data["personagem"] = identity
        self._json("capi.json", data)
        # Deliberately opaque: the companion subsystem owns brain validation.
        (self.root / "brain.bin").write_bytes(bytes(range(256)) * 6)
        (self.root / "brain.bak").write_bytes(b"restorable backup")
        (self.root / "brain.tmp").write_bytes(b"old interrupted write")
        return {f: (self.root / f).read_bytes() for f in (*slots.LEGACY_FILES, "brain.tmp")}

    def _assert_originals(self, originals):
        for name, payload in originals.items():
            self.assertEqual((self.root / name).read_bytes(), payload)

    def test_fresh_boot_and_distinct_independent_slots(self):
        folder = Path(slots.prepare("capi", self.root_s))
        self.assertEqual(folder, self.saves / "capi")
        self.assertTrue(slots.brain_dir("capi", self.root_s).endswith("/"))
        self.assertFalse(slots.has_pet("capi", self.root_s))
        self.assertFalse(slots.has_pet("girafa", self.root_s))
        self.assertEqual(slots.load_pet("girafa", DEFAULTS, self.root_s), DEFAULTS)
        given = dict(DEFAULTS, fome=22)
        untouched = given.copy()
        slots.save_pet("capi", given, self.root_s)
        self.assertEqual(given, untouched)
        slots.save_pet("girafa", dict(DEFAULTS, fome=65), self.root_s)
        self.assertTrue(slots.has_pet("capi", self.root_s))
        self.assertEqual(slots.load_pet("capi", DEFAULTS, self.root_s)["fome"], 22)
        self.assertEqual(slots.load_pet("girafa", DEFAULTS, self.root_s)["fome"], 65)
        self.assertEqual(slots.load_pet("girafa", DEFAULTS, self.root_s)["pet_id"], "girafa")

    def test_exact_copy_capi_brain_and_backup_once(self):
        originals = self._legacy(identity="girafa")
        folder = Path(slots.prepare("girafa", self.root_s))
        self._assert_originals(originals)
        for name in slots.LEGACY_FILES:
            self.assertEqual((folder / name).read_bytes(), originals[name])
        self.assertFalse((folder / "brain.tmp").exists())
        journal = json.loads((self.saves / slots.COMMITTED).read_text())
        self.assertEqual(journal["owner"], "girafa")
        self.assertFalse((self.saves / slots.JOURNAL).exists())
        evolved = dict(slots.load_pet("girafa", DEFAULTS, self.root_s), fome=45)
        slots.save_pet("girafa", evolved, self.root_s)
        self._json("config.json", {"personagem": "pip"})
        secondary = Path(slots.prepare("pip", self.root_s))
        self.assertEqual(list(secondary.iterdir()), [])
        self.assertEqual(slots.load_pet("girafa", DEFAULTS, self.root_s)["fome"], 45)
        self._assert_originals(originals)

    def test_no_owner_is_never_guessed_from_default_or_embedded_id(self):
        originals = self._legacy(identity="girafa", config=False)
        for missing in (True, False):
            if not missing:
                self._json("config.json", {"modo": "pet"})
            with self.assertRaises(slots.SlotError) as error:
                slots.prepare("girafa", self.root_s)
            self.assertEqual(error.exception.reason, "slot_owner_unknown")
            self.assertFalse(self.saves.exists())
            self._assert_originals(originals)

    def test_conflicting_legacy_identity_and_selection_stop(self):
        originals = self._legacy(identity="capi")
        for selection in ("girafa", "pip"):
            with self.assertRaises(slots.SlotError) as error:
                slots.prepare(selection, self.root_s)
            self.assertEqual(error.exception.reason, "slot_owner_conflict")
            self.assertFalse(self.saves.exists())
            self._assert_originals(originals)

    def test_partial_copy_retries_only_same_owner_after_power_loss(self):
        originals = self._legacy()
        real_replace = slots._replace

        def power_loss(src, dest):
            if dest.endswith("/brain.bin"):
                raise OSError(errno.EIO, "simulated power loss")
            return real_replace(src, dest)

        with patch.object(slots, "_replace", side_effect=power_loss):
            with self.assertRaises(slots.SlotError):
                slots.prepare("girafa", self.root_s)
        self.assertTrue((self.saves / slots.JOURNAL).exists())
        self.assertFalse((self.saves / slots.COMMITTED).exists())
        self.assertEqual((self.saves / "girafa" / "capi.json").read_bytes(),
                         originals["capi.json"])
        self.assertFalse((self.saves / "girafa" / "brain.bin").exists())
        with self.assertRaises(slots.SlotError):
            slots.has_pet("girafa", self.root_s)
        self._json("config.json", {"personagem": "pip"})
        with self.assertRaises(slots.SlotError) as error:
            slots.prepare("pip", self.root_s)
        self.assertEqual(error.exception.reason, "slot_owner_conflict")
        self.assertFalse((self.saves / "pip").exists())
        self._json("config.json", {"personagem": "girafa"})
        folder = Path(slots.prepare("girafa", self.root_s))
        self._assert_originals(originals)
        self.assertEqual((folder / "brain.bin").read_bytes(), originals["brain.bin"])
        self.assertEqual((folder / "brain.bak").read_bytes(), originals["brain.bak"])

    def test_changed_source_cannot_resume_interrupted_migration(self):
        originals = self._legacy()
        with patch.object(slots, "_copy", side_effect=OSError(errno.EIO, "disk")):
            with self.assertRaises(slots.SlotError):
                slots.prepare("girafa", self.root_s)
        (self.root / "brain.bin").write_bytes(b"changed since pending")
        with self.assertRaises(slots.SlotError) as error:
            slots.prepare("girafa", self.root_s)
        self.assertEqual(error.exception.reason, "slot_source_changed")
        self.assertFalse((self.saves / "girafa" / "brain.bin").exists())
        self.assertEqual((self.root / "capi.json").read_bytes(), originals["capi.json"])

    def test_differing_existing_slot_stops_before_any_other_copy(self):
        originals = self._legacy()
        folder = Path(slots.ensure_slot("girafa", self.root_s))
        (folder / "brain.bak").write_bytes(b"important existing data")
        with self.assertRaises(slots.SlotError) as error:
            slots.prepare("girafa", self.root_s)
        self.assertEqual(error.exception.reason, "slot_destination_conflict")
        self.assertFalse((folder / "capi.json").exists())
        self.assertFalse((folder / "brain.bin").exists())
        self.assertFalse((self.saves / slots.JOURNAL).exists())
        self.assertEqual((folder / "brain.bak").read_bytes(), b"important existing data")
        self._assert_originals(originals)

    def test_save_rename_failure_preserves_existing_primary(self):
        slots.prepare("girafa", self.root_s)
        slots.save_pet("girafa", dict(DEFAULTS, fome=32), self.root_s)
        current = Path(slots.pet_path("girafa", self.root_s))
        raw = current.read_bytes()
        with patch.object(slots, "_replace", side_effect=OSError(errno.EIO, "disk")):
            with self.assertRaises(slots.SlotError):
                slots.save_pet("girafa", dict(DEFAULTS, fome=91), self.root_s)
        self.assertEqual(current.read_bytes(), raw)
        self.assertEqual(slots.load_pet("girafa", DEFAULTS, self.root_s)["fome"], 32)
        slots.save_pet("girafa", dict(DEFAULTS, fome=91), self.root_s)
        self.assertEqual(slots.load_pet("girafa", DEFAULTS, self.root_s)["fome"], 91)

    def test_has_pet_refuses_IO_and_invalid_slot_never_defaults(self):
        slots.prepare("girafa", self.root_s)
        with patch.object(slots, "_stat", side_effect=OSError(errno.EACCES, "read")):
            with self.assertRaises(slots.SlotError):
                slots.has_pet("girafa", self.root_s)
        folder = Path(slots.brain_dir("girafa", self.root_s))
        bad = folder / "capi.json"
        bad.write_text('{"fome":', encoding="utf-8")
        self.assertTrue(slots.has_pet("girafa", self.root_s))
        with self.assertRaises(recovery.RecoveryRequired):
            slots.load_pet("girafa", DEFAULTS, self.root_s)

    def test_existing_embedded_owner_for_another_slot_is_refused(self):
        slots.prepare("girafa", self.root_s)
        path = Path(slots.pet_path("girafa", self.root_s))
        self._json(path, dict(DEFAULTS, pet_id="capi"))
        with self.assertRaises(slots.SlotError) as error:
            slots.load_pet("girafa", DEFAULTS, self.root_s)
        self.assertEqual(error.exception.reason, "slot_owner_conflict")

    def test_bad_id_refused_before_creating_any_directories(self):
        for value in ("../capi", "/capi", "", "Capí", "capi\\pip", "x" * 41, None):
            with self.subTest(value=value), self.assertRaises(slots.SlotError):
                slots.prepare(value, self.root_s)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_host_symlink_is_not_used_as_slot_or_destination(self):
        slots.prepare("girafa", self.root_s)
        victim = self.root / "external"
        victim.mkdir()
        victim_file = victim / "capi.json"
        victim_file.write_text("unchanged", encoding="utf-8")
        (self.saves / "pip").symlink_to(victim, target_is_directory=True)
        with self.assertRaises(slots.SlotError):
            slots.save_pet("pip", DEFAULTS, self.root_s)
        with self.assertRaises(slots.SlotError):
            slots.has_pet("pip", self.root_s)
        self.assertEqual(victim_file.read_text(encoding="utf-8"), "unchanged")


if __name__ == "__main__":
    unittest.main()
