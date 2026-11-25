"""No hardware: disabling Zoo plugins must never destroy an active pet."""
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from zoo import registry
from zoo.tools.disable_animal import disable


class FakeMpremote:
    def __init__(self, active="capi", broken_config=False):
        self.removed = []
        self.commands = []
        config = {"personagem": active, "modo": "pet"}
        text = "{truncated" if broken_config else json.dumps(config)
        pkg = registry.ANIMALS["pip"]
        self.files = {
            "config.json": text.encode(),
            "capi.json": json.dumps({"fome": 65}).encode(),
            "zoo/animals/pip/manifest.json": json.dumps(pkg).encode(),
            "zoo/animals/pip/face.py": b"def render(*args): return ((0,0),(1,1))\n",
            "zoo/animals/pip/__init__.py": b"\n",
            "brain.bin": b"test brain bytes",
            "brain.bak": b"test old brain bytes",
        }

    def run(self, cmd, check=True, **kwargs):
        self.commands.append(cmd)
        if cmd[3] == "cp":
            remote = cmd[4].lstrip(":")
            if remote not in self.files:
                raise subprocess.CalledProcessError(1, cmd)
            Path(cmd[5]).write_bytes(self.files[remote])
        elif cmd[3] == "rm":
            self.removed.append(cmd[4])
        else:
            raise AssertionError("Unexpected mpremote operation: %r" % cmd)
        return subprocess.CompletedProcess(cmd, 0)


class DisableZooTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def run_with_fake(self, fake, backup, active):
        with patch("zoo.tools.disable_animal.shutil.which", return_value="/usr/bin/mpremote"), \
                patch("zoo.tools.disable_animal.subprocess.run", side_effect=fake.run):
            return disable("pip", "/dev/ttyACM0", self.root / backup)

    def test_dry_run_does_not_contact_device_or_write_files(self):
        with patch("zoo.tools.disable_animal.subprocess.run") as mocked:
            output = io.StringIO()
            with redirect_stdout(output):
                result = disable("pip", "/dev/ttyACM0", self.root / "preview",
                                 dry_run=True)
            mocked.assert_not_called()
            self.assertFalse(result)
            self.assertFalse((self.root / "preview").exists())
            self.assertIn("CHECK", output.getvalue())
            self.assertIn("rm :zoo/animals/pip/manifest.json", output.getvalue())

    def test_active_character_never_disabled_and_save_is_backed_up(self):
        fake = FakeMpremote(active="pip")
        with self.assertRaisesRegex(ValueError, "ACTIVE PET"):
            self.run_with_fake(fake, "active", "pip")
        self.assertEqual([], fake.removed)
        self.assertEqual(fake.files["capi.json"],
                         (self.root / "active/capi.json").read_bytes())
        self.assertEqual(fake.files["config.json"],
                         (self.root / "active/config.json").read_bytes())

    def test_inactive_character_disabled_by_manifest_only(self):
        fake = FakeMpremote(active="capi")
        self.assertTrue(self.run_with_fake(fake, "inactive", "capi"))
        self.assertEqual(fake.removed,
                         [":zoo/animals/pip/manifest.json"])
        self.assertFalse(any("capi.json" in q[4] for q in fake.commands
                             if q[3] == "rm"))
        for name in ("config.json", "capi.json", "manifest.json",
                     "face.py", "__init__.py", "brain.bin", "brain.bak"):
            self.assertTrue((self.root / "inactive" / name).exists(), name)
        self.assertEqual(fake.files["brain.bin"],
                         (self.root / "inactive/brain.bin").read_bytes())

    def test_corrupt_config_refuses_disable(self):
        fake = FakeMpremote(broken_config=True)
        with self.assertRaises(ValueError):
            self.run_with_fake(fake, "corrupt", "capi")
        self.assertEqual([], fake.removed)

    def test_missing_existing_plugin_source_refuses_disable(self):
        fake = FakeMpremote()
        del fake.files["zoo/animals/pip/face.py"]
        with self.assertRaises(subprocess.CalledProcessError):
            self.run_with_fake(fake, "incomplete", "capi")
        self.assertEqual([], fake.removed)

    def test_remote_write_failure_preserves_local_backup(self):
        fake = FakeMpremote()
        def error_on_remove(command, **kwargs):
            if command[3] == "rm":
                raise subprocess.CalledProcessError(3, command)
            return fake.run(command, **kwargs)
        with patch("zoo.tools.disable_animal.shutil.which", return_value="/usr/bin/mpremote"), \
                patch("zoo.tools.disable_animal.subprocess.run", side_effect=error_on_remove):
            with self.assertRaises(subprocess.CalledProcessError):
                disable("pip", "/dev/ttyACM0", self.root / "failed")
        self.assertTrue((self.root / "failed/config.json").exists())
        self.assertTrue((self.root / "failed/manifest.json").exists())

    def test_builtins_and_amoled_cannot_be_disabled(self):
        for ident in ("capi", "gato"):
            with self.subTest(ident=ident):
                with self.assertRaisesRegex(ValueError, "built-in"):
                    disable(ident, "/dev/ttyACM0", self.root / ident,
                            dry_run=True)
        with self.assertRaisesRegex(ValueError, "AMOLED"):
            disable("pip", "/dev/ttyACM0", self.root / "amoled",
                    board="amoled-v1", dry_run=True)

    def test_existing_backup_is_never_overwritten(self):
        backup = self.root / "archive"
        backup.mkdir()
        (backup / "config.json").write_bytes(b"KEEP")
        with self.assertRaisesRegex(ValueError, "already exists"):
            disable("pip", "/dev/ttyACM0", backup, dry_run=True)
        self.assertEqual((backup / "config.json").read_bytes(), b"KEEP")


if __name__ == "__main__":
    unittest.main()
