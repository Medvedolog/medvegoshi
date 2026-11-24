"""Actual AMOLED V1 menu and state transitions with Bjorni, no device I/O."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
import zipfile

from ports import amoled_v1 as port
from ports.package_amoled_v1_app import package_app
from ports.v1_full_game_emulate import ROOT, _CLOSE, _CONFIRM, _OPEN, _GameRig, _idle, _touch, emulate
from zoo import registry


_SLOTS = {"girafa": 50, "bjorni": 36}
_RIGHT_ANIMAL = _touch(194, 121)
_LEFT_ANIMAL = _touch(44, 121)
_FEED = _touch(48, 259)
_GULYASHKI = _touch(185, 55)
_RIGHT_STEP = _touch(205, 160)
_LEFT_STEP = _touch(40, 160)


def _pick(arrow):
    return _OPEN + (arrow,) + _CONFIRM + _CLOSE


def _pick_explore():
    return _OPEN + (_RIGHT_ANIMAL,) + _CONFIRM + (_GULYASHKI,) + _idle(3) + _CLOSE


def preview(output):
    """Save real large-mode game frames for documentation; no custom painting."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    confirm, check = emulate(
        _OPEN + (_RIGHT_ANIMAL,) + _idle(6), fixtures=_SLOTS, screen_mode=port.SCALE_LARGE)
    if not check["menu_opened"] or check["pet"] != "girafa":
        raise AssertionError("preview must reach the switch confirmation before choosing")
    bjorni, check = emulate(
        _pick(_RIGHT_ANIMAL) + _idle(6), fixtures=_SLOTS, screen_mode=port.SCALE_LARGE)
    if check["pet"] != "bjorni" or not check["menu_closed_after_open"]:
        raise AssertionError("Bjorni preview must use the real pet switch")
    confirm.save(output / "bjorni-switch-confirm.png")
    bjorni.save(output / "bjorni-care.png")


def preview_walk(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    walking, check = emulate(
        _pick_explore() + (_RIGHT_STEP,) * 12, fixtures=_SLOTS, screen_mode=port.SCALE_LARGE)
    if (check["pet"], check["mode"]) != ("bjorni", "explore"):
        raise AssertionError("must reach Bjorni in Гуляшки before rendering")
    walking.save(output / "bjorni-gulyashki.png")


def preview_actions(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    # The first feed frame always selects the mouth/paws food pose at tick 0.
    feeding, check = emulate(
        _pick(_RIGHT_ANIMAL) + (_FEED,) + _idle(2),
        fixtures=_SLOTS, screen_mode=port.SCALE_LARGE)
    if check["pet"] != "bjorni" or check["food_after"] != 61:
        raise AssertionError("feeding screenshot must follow a real care action")
    feeding.save(output / "bjorni-feeding.png")
    with patch.object(_GameRig, "epoch_start", _GameRig.epoch_start + 12 * 3600):
        sleeping, check = emulate(_pick_explore(), fixtures=_SLOTS, screen_mode=port.SCALE_LARGE)
    if (check["pet"], check["mode"]) != ("bjorni", "explore"):
        raise AssertionError("sleeping screenshot must enter Bjorni's night scene")
    sleeping.save(output / "bjorni-sleeping.png")


def _record_selection(face, selection):
    pick_frame = face.select_frame

    def observe(eyes, mouth, sick, motion=None):
        index = pick_frame(eyes, mouth, sick, motion)
        if motion is not None:
            action, stamp = motion
            selection.setdefault(action, []).append((stamp, index))
        return index

    return patch.object(face, "select_frame", side_effect=observe)


class BjorniV1Test(TestCase):
    def test_bjorni_is_added_after_existing_zoo_pets(self):
        self.assertEqual(registry.ELENCO[-3:], ("pip", "girafa", "bjorni"))
        self.assertEqual(registry.NOMES["bjorni"], "Бйорни")
        self.assertEqual(len(registry.ELENCO), 12)
        self.assertIsNotNone(registry.renderer("bjorni"))

    def test_roster_boundary_skips_retired_slot_in_both_directions(self):
        initial = {"sapinho": 45, "pip": 72}
        _, check = emulate(_pick(_RIGHT_ANIMAL) + _pick(_LEFT_ANIMAL),
                           fixtures=initial, initial_pet="sapinho",
                           screen_mode=port.SCALE_LARGE)
        self.assertEqual([item["pet"] for item in check["pet_trace"]],
                         ["sapinho", "pip", "sapinho"])
        self.assertEqual(check["saved_food"], initial)

    def test_switch_and_feed_bjorni_without_touching_giraffe_save(self):
        from zoo.animals.bjorni import face

        pictures, selection = {}, {}
        frames = (_pick(_RIGHT_ANIMAL) + (_FEED,) + _idle(6)
                  + _pick(_LEFT_ANIMAL))
        with _record_selection(face, selection):
            final, check = emulate(
                frames, fixtures=_SLOTS, pet_images=pictures, screen_mode=port.SCALE_LARGE)
        self.assertIn("eating", selection)
        self.assertGreaterEqual(len({index for _, index in selection["eating"]}), 2)
        self.assertNotEqual(selection["eating"][0][1], selection["idle"][0][1])
        self.assertEqual([item["pet"] for item in check["pet_trace"]],
                         ["girafa", "bjorni", "girafa"])
        self.assertTrue(all(item["life_stage"] == "adulto" for item in check["pet_trace"]))
        self.assertEqual(check["saved_food"], {"girafa": 50, "bjorni": 61})
        self.assertTrue(check["menu_closed_after_open"])
        self.assertTrue(check["offline_forced"])
        self.assertEqual(check["saves"], "temporary")
        self.assertEqual(check["native_display_windows"], [(0, 6, 367, 440, 320160)] * len(frames))
        self.assertEqual(final.size, (368, 448))
        self.assertEqual(set(pictures), {"girafa", "bjorni"})
        self.assertNotEqual(pictures["girafa"].tobytes(), pictures["bjorni"].tobytes())

    def test_gulyashki_sends_distinct_walk_and_jump_frames_from_touch(self):
        from zoo.animals.bjorni import face

        selection = {}
        # Hold right >200 ms, release, then hold left while there is room
        # before the map edge. A separate brief tap triggers an actual jump.
        sequence = (_pick_explore() + (_RIGHT_STEP,) * 12 + _idle(2)
                    + (_LEFT_STEP,) * 12 + _idle(2) + (_RIGHT_STEP,) + _idle(22))
        with _record_selection(face, selection):
            _, check = emulate(sequence, fixtures=_SLOTS, screen_mode=port.SCALE_LARGE)
        self.assertEqual((check["pet"], check["mode"]), ("bjorni", "explore"))
        self.assertEqual(check["fake_sound_events"].count("pulo"), 1)
        names = ("walk-right", "walk-left", "jump")
        frames = []
        for name in names:
            self.assertIn(name, selection)
            values = {index for _, index in selection[name]}
            self.assertGreaterEqual(len(values), 2, name)
            frames.append(values)
        for index, group in enumerate(frames):
            self.assertTrue(all(group.isdisjoint(others) for others in frames[index + 1:]))

    def test_offline_v1_archive_reaches_bjorni_from_actual_launcher(self):
        with TemporaryDirectory(prefix="medve-bjorni-app-test-") as directory:
            root = Path(directory)
            package = root / "app.zip"
            package_app(ROOT, package)
            staged = root / "staged"
            with zipfile.ZipFile(package) as handle:
                paths = set(handle.namelist())
                prefix = "zoo/animals/bjorni/"
                self.assertTrue({prefix + name for name in (
                    "__init__.py", "manifest.json", "face.py",
                )} <= paths)
                self.assertNotIn("main.py", paths)
                self.assertNotIn("boot.py", paths)
                handle.extractall(staged)
            _, check = emulate(
                _pick(_RIGHT_ANIMAL), fixtures=_SLOTS,
                app_path=staged / "v1_game_app.py", screen_mode=port.SCALE_NATIVE)
            self.assertTrue(check["packaged_entry"])
            self.assertTrue(check["rtc_write_enabled"] is False and check["offline_forced"])
            self.assertEqual(check["runtime_profile"], "amoled_1_8_v1")
            self.assertEqual(check["pet"], "bjorni")
            self.assertEqual(check["saved_food"], _SLOTS)
