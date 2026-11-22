"""Original giraffe: PNG art, IPS pack, MicroPython fallback and licensing.

PNG drawings are created from zoo/giraffe/face.py, not third-party art.
No hardware is required for these host-side regressions.
"""
from contextlib import redirect_stdout
import hashlib
import io
from pathlib import Path
import tempfile
import unittest

from PIL import Image

import vida
from zoo import sprites
from zoo.tools.generate_giraffe import (
    SOURCE_SIZE, SOURCE_ANCHOR, SOURCE_COMMIT, POSES,
    make_source, build,
)
from zoo.tools.install_pack import validate, install
from zoo.tools.preview_sprites import decode_frame, preview


class MockIPS:
    def __init__(self):
        self.pixels = {}
    def pixel(self, x, y, value):
        if 0 <= x < 240 and 0 <= y < 284:
            self.pixels[(x, y)] = value


class GiraffeArtTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.pack = self.root / "packs" / "girafa"
        self.pack.parent.mkdir()

    def test_six_expressions_plus_eating_and_blink(self):
        info = make_source(self.source)
        self.assertEqual("girafa", info["id"])
        self.assertEqual("Жирафик", info["name_ru"])
        self.assertEqual("MIT", info["license"])
        self.assertEqual(40, len(SOURCE_COMMIT))
        self.assertTrue(info["rights_confirmed"])
        self.assertEqual(list(SOURCE_ANCHOR), info["source_anchor"])
        self.assertEqual(8, len(POSES))
        hashes = set()
        for name in POSES:
            with Image.open(self.source / (name + ".png")) as png:
                self.assertEqual(SOURCE_SIZE, png.size)
                self.assertEqual("RGBA", png.mode)
                alpha = png.getchannel("A")
                self.assertTrue(alpha.getbbox(), name)
                self.assertEqual(0, alpha.getpixel((0, 0)))
                self.assertEqual(255, alpha.getextrema()[1])
            hashes.add(hashlib.sha256((self.source / (name + ".png")).read_bytes()).hexdigest())
        self.assertEqual(8, len(hashes), "each pose must actually look different")

    def test_source_images_are_byte_reproducible(self):
        make_source(self.source)
        first = {f.name: hashlib.sha256(f.read_bytes()).hexdigest()
                 for f in self.source.iterdir()}
        other = self.root / "other-source"
        make_source(other)
        second = {f.name: hashlib.sha256(f.read_bytes()).hexdigest()
                  for f in other.iterdir()}
        self.assertEqual(first, second)

    def test_refuse_to_overwrite_original_images(self):
        self.source.mkdir()
        important = self.source / "keep.png"
        important.write_bytes(b"do not overwrite")
        with self.assertRaisesRegex(ValueError, "empty directory"):
            make_source(self.source)
        self.assertEqual(important.read_bytes(), b"do not overwrite")

    def test_ips_pack_can_be_installed_and_previewed(self):
        manifest = build(self.source, self.pack)
        self.assertEqual(8, len(manifest["frames"]))
        self.assertEqual((120, 144), tuple(manifest["canvas"]))
        self.assertEqual("ips", manifest["target"])
        self.assertLess(manifest["bytes"], 400 * 1024)
        self.assertEqual("girafa", validate(self.pack)[0])
        frame, _ = decode_frame(self.pack, "normal")
        self.assertEqual(tuple(manifest["canvas"]), frame.size)
        out = self.root / "preview.png"
        preview(self.pack, out, "happy", board="ips")
        with Image.open(out) as image:
            self.assertEqual((240, 284), image.size)

        stdout = io.StringIO()
        with redirect_stdout(stdout):
            install(self.pack, "/dev/ttyACM0", dry_run=True)
        log = stdout.getvalue()
        self.assertIn("girafa/normal.rgb565", log)
        self.assertIn("girafa/manifest.json", log)
        self.assertIn("Dry run", log)

    def test_renderer_loads_real_compiled_frames(self):
        build(self.source, self.pack)
        sprites.clear_cache()
        states = (
            ("normal", "sorriso", False),
            ("feliz", "sorriso", False),
            ("triste", "triste", False),
            ("fechados", "dormindo", False),
            ("susto", "aberta", False),
            ("normal", "triste", True),
        )
        records = []
        for eyes, mouth, sick in states:
            fb = MockIPS()
            metric = sprites.draw(
                fb, "girafa", 110, 205, 0.74,
                eyes, mouth, sick,
                root=str(self.pack.parent), prefer_blit=False)
            self.assertIsNotNone(metric, (eyes, mouth, sick))
            self.assertGreater(len(fb.pixels), 100)
            self.assertTrue(all(0 <= x < 240 and 0 <= y < 284
                                for x, y in fb.pixels))
            records.append(frozenset(fb.pixels.items()))
        self.assertEqual(len(records), len(set(records)))

    def test_amoled_pack_preview_does_not_claim_hardware_support(self):
        meta = build(self.source, self.pack, target="amoled-v1")
        self.assertEqual((192, 224), tuple(meta["canvas"]))
        self.assertEqual("amoled-v1", meta["target"])
        self.assertLessEqual(meta["bytes"], 768 * 1024)
        preview(self.pack, self.root / "amoled-preview.png", board="amoled-v1")
        with Image.open(self.root / "amoled-preview.png") as image:
            self.assertEqual((368, 448), image.size)
        with self.assertRaisesRegex(ValueError, "AMOLED V1"):
            install(self.pack, "/dev/ttyACM0", board="amoled-v1", dry_run=True)
        self.assertIsNone(sprites.draw(
            MockIPS(), "girafa", 110, 205, 0.74, root=str(self.pack.parent),
            target="amoled-v1"))

    def test_character_is_registered_and_speech_fits(self):
        self.assertEqual(vida.NOMES["girafa"], "Жирафик")
        self.assertEqual(vida.HTOP["girafa"], 125)
        self.assertIn("girafa", vida.FRASES_CHAR)
        for lines in vida.FRASES_CHAR["girafa"].values():
            for phrase in lines:
                self.assertLessEqual(len(phrase.split("|")), 2)
                self.assertTrue(all(len(line) <= 14 for line in phrase.split("|")),
                                phrase)
        self.assertEqual(vida.NOMES["cachorro"], "Карамелька")
        self.assertEqual(vida.NOMES["pip"], "Пип")


if __name__ == "__main__":
    unittest.main()
