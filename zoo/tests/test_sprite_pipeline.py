"""Deterministic host-side sprite compiler regression suite.

All source art in these tests is procedurally created by the test itself.
No third-party PNG files or external downloads are needed.
"""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from PIL import Image, ImageDraw

from zoo.tools.build_sprites import compile_pack, encode_rgb565


SHA = "0123456789abcdef0123456789abcdef01234567"


class SpriteCompilerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.source = self.base / "art"
        self.source.mkdir()
        self.metadata = {
            "id": "test_pet", "name_ru": "Тестовый питомец",
            "author": "Fixture authors (original test art)",
            "license": "CC0-1.0",
            "source_url": "https://example.org/self-created-art",
            "source_commit": SHA,
            "rights_confirmed": True,
            "source_anchor": [6, 11]
        }
        self._write_metadata()
        self._pose("happy", look="right")
        self._pose("sad", look="left")

    def _write_metadata(self):
        (self.source / "pack.json").write_text(
            json.dumps(self.metadata, ensure_ascii=False), encoding="utf-8")

    def _pose(self, name, look="right"):
        im = Image.new("RGBA", (12, 12), (0, 0, 0, 0))
        draw = ImageDraw.Draw(im)
        draw.rectangle((4, 2, 8, 9), fill=(255, 0, 0, 255))
        if look == "right":
            draw.point((8, 3), fill=(0, 0, 255, 255))
        else:
            draw.point((4, 3), fill=(0, 0, 255, 255))
        im.save(self.source / (name + ".png"))

    @staticmethod
    def digest_directory(path):
        return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(path.iterdir()) if p.is_file()}

    def test_deterministic_build_and_sorting(self):
        one, two = self.base / "one", self.base / "two"
        a = compile_pack(self.source, one)
        b = compile_pack(self.source, two)
        self.assertEqual(a, b)
        self.assertEqual(self.digest_directory(one), self.digest_directory(two))
        self.assertEqual([f["name"] for f in a["frames"]], ["happy", "sad"])
        self.assertEqual(a["canvas"], [96, 112])
        self.assertEqual(a["target"], "ips")

    def test_rebuild_with_overwrite_is_byte_identical(self):
        out = self.base / "pack"
        compile_pack(self.source, out)
        first = self.digest_directory(out)
        compile_pack(self.source, out, overwrite=True)
        self.assertEqual(first, self.digest_directory(out))

    def test_full_length_and_sha256(self):
        out = self.base / "out"
        m = compile_pack(self.source, out, size=(48, 56))
        w, h = m["canvas"]
        total = 0
        for item in m["frames"]:
            pixels = (out / item["rgb565"]).read_bytes()
            mask = (out / item["mask"]).read_bytes()
            self.assertEqual(len(pixels), w * h * 2)
            self.assertEqual(len(mask), (w * h + 7) // 8)
            self.assertEqual(item["sha256"],
                             hashlib.sha256(pixels + mask).hexdigest())
            total += len(pixels) + len(mask)
        self.assertEqual(m["bytes"], total)

    def test_canonical_big_endian_rgb565_mask(self):
        im = Image.new("RGBA", (3, 1))
        im.putpixel((0, 0), (255, 0, 0, 255))
        im.putpixel((1, 0), (0, 255, 0, 255))
        im.putpixel((2, 0), (0, 0, 255, 0))
        pixels, mask = encode_rgb565(im)
        self.assertEqual(pixels, bytes.fromhex("f80007e00000"))
        self.assertEqual(mask, b"\xc0")

    def test_pose_registration_does_not_shift_body(self):
        out = self.base / "aligned"
        result = compile_pack(self.source, out, size=(64, 64), margin=4)
        anchor_x, anchor_y = result["anchor"]
        # The anatomical anchor may be just outside the rendered canvas
        # (for example, a foot pivot under a rounded body). Visible pixels
        # must remain inside, while the anchor remains a stable signed offset.
        self.assertIsInstance(anchor_x, int)
        self.assertIsInstance(anchor_y, int)
        for entry in result["frames"]:
            x0, y0, x1, y1 = entry["bounds"]
            self.assertTrue(0 <= x0 < x1 <= 64, entry)
            self.assertTrue(0 <= y0 < y1 <= 64, entry)
        # Same shape / anchor but different eye pixels -> common output
        # bounding boxes and equal mask size.
        self.assertEqual(result["frames"][0]["bounds"],
                         result["frames"][1]["bounds"])

    def test_target_is_explicit_not_hardware_claim(self):
        data = compile_pack(self.source, self.base / "amoled", target="amoled-v1")
        self.assertEqual(data["target"], "amoled-v1")
        self.assertEqual(data["format"], "medvegoshi-rgb565-mask-v1")

    def test_cannot_import_images_without_rights_confirmation(self):
        self.metadata["rights_confirmed"] = False
        self._write_metadata()
        with self.assertRaisesRegex(ValueError, "rights_confirmed"):
            compile_pack(self.source, self.base / "out")
        self.assertFalse((self.base / "out").exists())

    def test_unknown_image_license_is_rejected(self):
        self.metadata["license"] = "Unknown"
        self._write_metadata()
        with self.assertRaisesRegex(ValueError, "license"):
            compile_pack(self.source, self.base / "out")

    def test_invalid_anchor_is_rejected(self):
        self.metadata["source_anchor"] = [200, 10]
        self._write_metadata()
        with self.assertRaisesRegex(ValueError, "anchor outside"):
            compile_pack(self.source, self.base / "out")

    def test_empty_visible_frame_is_rejected(self):
        Image.new("RGBA", (12, 12)).save(self.source / "empty.png")
        with self.assertRaisesRegex(ValueError, "no visible pixels"):
            compile_pack(self.source, self.base / "out")

    def test_output_budget_is_enforced(self):
        with self.assertRaisesRegex(ValueError, "budget"):
            compile_pack(self.source, self.base / "big", size=(256, 256), max_kib=1)
        self.assertFalse((self.base / "big" / "manifest.json").exists())

    def test_dont_overwrite_foreign_directory(self):
        out = self.base / "foreign"
        out.mkdir()
        (out / "important.txt").write_text("KEEP", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "without manifest.json"):
            compile_pack(self.source, out, overwrite=True)
        self.assertEqual((out / "important.txt").read_text(), "KEEP")

    def test_reject_traversal_ids(self):
        self.metadata["id"] = "../escape"
        self._write_metadata()
        with self.assertRaisesRegex(ValueError, "invalid id"):
            compile_pack(self.source, self.base / "out")

    def test_reject_non_sha_source_commit(self):
        self.metadata["source_commit"] = "main"
        self._write_metadata()
        with self.assertRaisesRegex(ValueError, "source_commit"):
            compile_pack(self.source, self.base / "out")

    def test_keep_unrelated_file_in_generated_pack(self):
        out = self.base / "pack"
        compile_pack(self.source, out)
        (out / "notes.txt").write_text("DO NOT DELETE", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "non-generated files"):
            compile_pack(self.source, out, overwrite=True)
        self.assertEqual((out / "notes.txt").read_text(), "DO NOT DELETE")

    def test_source_and_output_cannot_nest(self):
        with self.assertRaisesRegex(ValueError, "separate"):
            compile_pack(self.source, self.source)
        with self.assertRaisesRegex(ValueError, "separate"):
            compile_pack(self.source, self.source / "compiled")
        with self.assertRaisesRegex(ValueError, "separate"):
            compile_pack(self.source, self.base)
        self.assertTrue((self.source / "pack.json").exists())


if __name__ == "__main__":
    unittest.main()
