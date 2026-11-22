"""Adapter contracts exercised with a fake of the on-device C API."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from zoo import pet_slots
from zoo.pip import game

NOW = 1_785_000_000


class Native:
    def __init__(self):
        self.calls = []
        self.now = self.tz = 0
        self.mood = "curious"

    def reset(self, seed, now, tz):
        self.calls.append(("reset", seed, now, tz))
        self.now, self.tz = now, tz

    def advance(self, now):
        self.calls.append(("advance", now))
        if now < self.now:
            raise ValueError("native clock went back")
        self.now = now

    def event(self, name):
        self.calls.append(("event", name))
        self.mood = "nauseous" if name == "feed" else "happy"
        return self.mood

    def status(self):
        return {"mood": self.mood, "reason": {"kind": "palette"},
                "needs": {name: .9 for name in game.NEEDS}, "asleep": False,
                "now": self.now, "tz_min": self.tz, "valence": .5}

    def export_state(self):
        self.calls.append(("export",))
        return json.dumps([self.now, self.tz, self.mood]).encode("ascii")

    def import_state(self, data):
        self.calls.append(("import", data))
        try:
            self.now, self.tz, self.mood = json.loads(data.decode("ascii"))
        except (ValueError, TypeError):
            raise ValueError("bad native payload")


class GameAdapterTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.addCleanup(self.close)
        self.root = temp.name
        self.native = Native()
        pet_slots.prepare("capi", self.root)
        self.pip_path = Path(pet_slots.brain_dir("pip", self.root)) / game.STATE_NAME

    def close(self):
        if game._active is not None:
            game._active.close()

    def start(self, native=None, rtc=NOW, enabled=True, **opts):
        return game.open_pip("pip", rtc, native=native or self.native, enabled=enabled,
                             root=self.root, **opts)

    def test_clock_normalization_on_both_documented_epochs(self):
        self.assertEqual(game.unix_from_rtc(NOW, 60, 1970), NOW - 3600)
        self.assertEqual(game.unix_from_rtc(NOW - game.EPOCH_2000_OFFSET, -30, 2000),
                         NOW + 1800)
        for raw, tz, epoch in ((0, 0, 1970), (NOW, 0, 1980), (NOW, True, 1970),
                               (NOW, 900, 1970), (True, 0, 1970)):
            with self.assertRaises(ValueError):
                game.unix_from_rtc(raw, tz, epoch)

    def test_only_explicit_pip_session_can_import_or_touch_saves(self):
        before = set(Path(self.root).rglob("*"))
        for selected, enabled in (("capi", True), ("girafa", True), ("pip", False),
                                   ("pip", 1)):
            self.assertIsNone(game.open_pip(selected, NOW, enabled=enabled,
                                           native=self.native, root=self.root))
        self.assertIsNone(self.start(native=object()))
        with patch.dict("sys.modules", {"pip_native": None}):
            self.assertIsNone(game.open_pip("pip", NOW, enabled=True, root=self.root))
        self.assertEqual(self.native.calls, [])
        self.assertEqual(set(Path(self.root).rglob("*")), before)

    def test_lazy_sidecar_uses_only_pip_and_resumes_explicitly(self):
        other = Path(pet_slots.ensure_slot("capi", self.root))
        (other / "brain.bin").write_bytes(b"other brain")
        (other / "capi.json").write_bytes(b"other game")
        session = self.start(epoch_year=2000, rtc=NOW - game.EPOCH_2000_OFFSET)
        self.assertIsNotNone(session)
        self.assertTrue(session.tick(NOW - game.EPOCH_2000_OFFSET)["needs"]["food"])
        self.assertEqual(session.event("comida"), "nauseous")
        self.assertIsNone(session.event("unrecognized"))
        self.assertFalse(self.pip_path.exists())
        self.assertTrue(session.flush())
        self.assertTrue(self.pip_path.exists())
        self.assertEqual(json.loads(self.pip_path.read_text())["pet_id"], "pip")
        session.close()
        outgoing = Native()
        restored = self.start(native=outgoing, rtc=NOW + 3)
        self.assertIsNotNone(restored)
        self.assertEqual(restored.status()["mood"], "nauseous")
        self.assertEqual(restored.status()["now"], NOW + 3)
        self.assertEqual([action[0] for action in outgoing.calls], ["import", "advance"])
        self.assertFalse(session.flush())
        self.assertEqual((other / "brain.bin").read_bytes(), b"other brain")
        self.assertEqual((other / "capi.json").read_bytes(), b"other game")

    def test_broken_or_incompatible_state_can_never_be_replaced(self):
        self.pip_path.parent.mkdir()
        valid_envelope = {"schema": 1, "engine": "pip_native", "pet_id": "pip",
                          "state_hex": "9876"}
        artifacts = [b"", b"{", json.dumps(dict(valid_envelope, schema=2)).encode(),
                     json.dumps(dict(valid_envelope, pet_id="capi")).encode(),
                     json.dumps(dict(valid_envelope, state_hex="ff" * 283)).encode(),
                     json.dumps(dict(valid_envelope, state_hex="ÿ")).encode(),
                     json.dumps(valid_envelope).encode()]
        for original in artifacts:
            with self.subTest(artifact=original[:30]):
                self.native.calls.clear()
                self.pip_path.write_bytes(original)
                self.assertIsNone(self.start())
                self.assertEqual(self.pip_path.read_bytes(), original)
                self.assertNotIn("reset", [action[0] for action in self.native.calls])

    def test_externally_replaced_sidecar_disables_writes(self):
        session = self.start()
        self.assertTrue(session.flush())
        self.pip_path.write_bytes(b"external replacement")
        self.assertEqual(session.event("comida"), "nauseous")
        self.assertFalse(session.flush())
        self.assertIsNone(session.tick(NOW + 1))
        self.assertEqual(self.pip_path.read_bytes(), b"external replacement")

    def test_missing_or_backward_clock_ignores_events_until_caught_up(self):
        session = self.start()
        self.assertEqual(session.tick(NOW - 150)["now"], NOW)
        self.assertIsNone(session.event("comida"))
        self.assertIsNone(session.event("stroke", 0))
        self.assertEqual(self.native.calls, [("reset", 1, NOW, 0)])
        self.assertEqual(session.tick(NOW + 1)["now"], NOW + 1)
        self.assertEqual(session.event("comida"), "nauseous")

    def test_second_unrelated_session_cannot_steal_native_state(self):
        first = self.start()
        other = Native()
        self.assertIsNone(self.start(native=other))
        self.assertIs(first, self.start())
        self.assertEqual(other.calls, [])
        self.assertEqual(first.event("comida"), "nauseous")

    def test_restore_with_clock_or_timezone_disagreement_is_read_only(self):
        session = self.start()
        self.assertTrue(session.flush())
        session.close()
        previous = self.pip_path.read_bytes()
        self.assertIsNone(self.start(rtc=NOW - 1))
        self.assertIsNone(self.start(tz_min=15))
        self.assertEqual(self.pip_path.read_bytes(), previous)

    def test_device_fs_failure_keeps_legacy_game_and_prior_sidecar(self):
        session = self.start()
        self.assertTrue(session.flush())
        previous = self.pip_path.read_bytes()
        session.event("comida")
        with patch.object(pet_slots, "save_json", side_effect=OSError("no space")):
            self.assertFalse(session.flush())
        self.assertIsNone(session.status())
        self.assertEqual(self.pip_path.read_bytes(), previous)


if __name__ == "__main__":
    unittest.main()
