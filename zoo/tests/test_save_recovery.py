"""No-write boot recovery for missing Zoo plugins and corrupted saves."""
import json
from pathlib import Path
import tempfile
import unittest

from zoo import recovery

ROOT = Path(__file__).resolve().parents[2]


class FakeFrame:
    def __init__(self):
        self.clears = []
    def fill(self, color):
        self.clears.append(color)


class FakeScreen:
    def __init__(self):
        self.fb = FakeFrame()
        self.shown = 0
    def mostrar(self):
        self.shown += 1


class FakeDrawing:
    def __init__(self):
        self.labels = []
    @staticmethod
    def C(color):
        return tuple(color)
    def centro(self, message, y, color, esc=1):
        self.labels.append((message, y))


CFG = {"modo": "pet", "som": True, "personagem": "capi",
       "hora": "real", "vel": 2, "casa": "pet"}

PET = {"fome": 80, "alegria": 80, "energia": 80, "saude": 100, "cocos": 0,
       "doente": False, "dormindo": False, "cochilo": False, "epoch": 0,
       "idade_min": 0.0, "vida_adulto": 15, "morto": False}


class ZooRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.config = root / "config.json"
        self.save = root / "capi.json"

    def test_initial_install_without_files_is_valid(self):
        self.assertEqual(CFG, recovery.load_config(str(self.config), CFG, ("capi",)))
        self.assertEqual(PET, recovery.load_pet(str(self.save), PET))
        self.assertFalse(self.config.exists())
        self.assertFalse(self.save.exists())

    def test_valid_plugin_save_preserved_exactly(self):
        saved = dict(CFG, personagem="girafa", stars=["one"])
        self.config.write_text(json.dumps(saved), encoding="utf-8")
        original = self.config.read_bytes()
        got = recovery.load_config(str(self.config), CFG, ("capi", "girafa"))
        self.assertEqual("girafa", got["personagem"])
        self.assertEqual(original, self.config.read_bytes())

    def test_missing_plugin_is_not_silently_replaced_by_capi(self):
        saved = dict(CFG, personagem="girafa")
        self.config.write_text(json.dumps(saved), encoding="utf-8")
        self.save.write_text(json.dumps(PET), encoding="utf-8")
        cfg_bytes, pet_bytes = self.config.read_bytes(), self.save.read_bytes()
        with self.assertRaises(recovery.RecoveryRequired) as ctx:
            recovery.load_config(str(self.config), CFG, ("capi", "pip"))
        self.assertEqual("pet_missing", ctx.exception.reason)
        self.assertEqual("girafa", ctx.exception.pet_id)
        self.assertEqual(cfg_bytes, self.config.read_bytes())
        self.assertEqual(pet_bytes, self.save.read_bytes())

    def test_restoring_plugin_recovers_same_selected_animal(self):
        saved = dict(CFG, personagem="girafa")
        self.config.write_text(json.dumps(saved), encoding="utf-8")
        with self.assertRaises(recovery.RecoveryRequired):
            recovery.load_config(str(self.config), CFG, ("capi",))
        loaded = recovery.load_config(str(self.config), CFG, ("capi", "girafa"))
        self.assertEqual("girafa", loaded["personagem"])

    def test_truncated_config_and_non_dict_config_stop_boot(self):
        for body in ('{"personagem":', '[]', '"string"'):
            with self.subTest(body=body):
                self.config.write_text(body, encoding="utf-8")
                before = self.config.read_bytes()
                with self.assertRaises(recovery.RecoveryRequired):
                    recovery.load_config(str(self.config), CFG, ("capi",))
                self.assertEqual(before, self.config.read_bytes())

    def test_invalid_type_for_saved_id_stops_boot(self):
        self.config.write_text('{"personagem": 123}', encoding="utf-8")
        with self.assertRaises(recovery.RecoveryRequired):
            recovery.load_config(str(self.config), CFG, ("capi",))

    def test_invalid_pet_and_truncated_pet_stop_boot(self):
        for body in ('{"idade_min":', '[]', '{"fome": "high"}',
                     '{"morto": 1}', '{"energia": false}'):
            with self.subTest(body=body):
                self.save.write_text(body, encoding="utf-8")
                original = self.save.read_bytes()
                with self.assertRaises(recovery.RecoveryRequired) as ctx:
                    recovery.load_pet(str(self.save), PET)
                self.assertEqual("pet_corrupt", ctx.exception.reason)
                self.assertEqual(original, self.save.read_bytes())

    def test_valid_shared_save_no_schema_migration(self):
        old = dict(PET, idade_min=1450.5, vida_adulto=22, energia=36)
        self.save.write_text(json.dumps(old), encoding="utf-8")
        before = self.save.read_bytes()
        self.assertEqual(old, recovery.load_pet(str(self.save), PET))
        self.assertEqual(before, self.save.read_bytes())

    def test_error_screen_is_russian_and_shows_saved_id(self):
        screen, drawing = FakeScreen(), FakeDrawing()
        error = recovery.RecoveryRequired("pet_missing", "girafa")
        recovery.show_recovery(screen, drawing, error)
        labels = [item[0] for item in drawing.labels]
        self.assertIn("НЕТ ПИТОМЦА", labels)
        self.assertIn("girafa", labels)
        self.assertIn("Данные не изменены", labels)
        self.assertEqual(screen.shown, 1)

    def test_boot_guard_raises_without_save_mutation(self):
        saved = dict(CFG, personagem="girafa")
        self.config.write_text(json.dumps(saved), encoding="utf-8")
        self.save.write_text(json.dumps(PET), encoding="utf-8")
        before_config, before_pet = self.config.read_bytes(), self.save.read_bytes()
        screen, drawing = FakeScreen(), FakeDrawing()
        with self.assertRaisesRegex(RuntimeError, "data protected"):
            recovery.require_config(str(self.config), CFG, ("capi",),
                                    screen, drawing)
        self.assertEqual(self.config.read_bytes(), before_config)
        self.assertEqual(self.save.read_bytes(), before_pet)
        self.assertEqual(screen.shown, 1)

    def test_main_checks_config_before_loading_pet(self):
        src = (ROOT / "main.py").read_text(encoding="utf-8")
        self.assertIn("zoo_recovery.require_config", src)
        self.assertIn("zoo_recovery.require_pet", src)
        self.assertNotIn("cfg['personagem'] = 'capi'", src)
        self.assertLess(src.index("zoo_recovery.require_config"),
                        src.index("zoo_recovery.require_pet"))
        self.assertLess(src.index("zoo_recovery.require_pet"),
                        src.index("vt = 0"))

    def test_software_update_copies_main_last(self):
        script = (ROOT / "deploy.sh").read_text(encoding="utf-8")
        self.assertIn('cp "$DIR/zoo/recovery.py"', script)
        self.assertIn('cp "$DIR/main.py"', script)
        self.assertLess(script.index('cp "$DIR/zoo/recovery.py"'),
                        script.index('cp "$DIR/main.py"'))
        self.assertLess(script.index('cp "$DIR/zoo/registry.py"'),
                        script.index('cp "$DIR/main.py"'))


if __name__ == "__main__":
    unittest.main()
