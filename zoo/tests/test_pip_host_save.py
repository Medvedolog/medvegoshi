import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from zoo.pip import host_save


class PipHostSaveTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.slot = self.root / "pip-state.json"

    def test_loop_and_separate_slot(self):
        existing = self.root / "capi.json"
        existing.write_bytes(b"giraffe")
        with self.assertRaises(ValueError):
            host_save.save_state(existing, b"pip one")
        host_save.save_state(self.slot, b"pip one")
        self.assertEqual(host_save.load_state(self.slot), b"pip one")
        host_save.save_state(self.slot, b"pip two")
        self.assertEqual(host_save.load_state(self.slot), b"pip two")
        self.assertEqual(existing.read_bytes(), b"giraffe")

    def test_broken_checksum_never_overwritten(self):
        host_save.save_state(self.slot, b"start")
        data = json.loads(self.slot.read_text())
        data["payload"] = b"other".hex()
        corrupted = json.dumps(data)
        self.slot.write_text(corrupted)
        for operation in (lambda: host_save.load_state(self.slot),
                          lambda: host_save.save_state(self.slot, b"reset")):
            with self.assertRaisesRegex(ValueError, "checksum"):
                operation()
        self.assertEqual(self.slot.read_text(), corrupted)

    def test_interrupted_replace_keeps_previous_data(self):
        host_save.save_state(self.slot, b"before")
        with patch("zoo.pip.host_save.os.replace", side_effect=OSError("simulation")):
            with self.assertRaises(OSError):
                host_save.save_state(self.slot, b"after")
        self.assertEqual(host_save.load_state(self.slot), b"before")
        self.assertEqual(list(self.root.iterdir()), [self.slot])

    def test_oversized_and_symlink(self):
        with self.assertRaises(ValueError):
            host_save.save_state(self.slot, b"x" * (host_save.MAX_BLOB + 1))
        self.slot.write_bytes(b"x" * (host_save.MAX_FILE + 1))
        with self.assertRaises(ValueError):
            host_save.load_state(self.slot)
        target = self.root / "capi.json"
        target.write_bytes(b"leave alone")
        alias = self.root / "linked.pip-state.json"
        alias.symlink_to(target)
        with self.assertRaises(ValueError):
            host_save.save_state(alias, b"pip")
        self.assertEqual(target.read_bytes(), b"leave alone")


if __name__ == "__main__":
    unittest.main()
