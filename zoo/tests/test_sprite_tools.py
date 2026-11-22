"""Host preview + safe mpremote pack installer; no device required."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest

from PIL import Image, ImageDraw
from zoo.tools.build_sprites import compile_pack
from zoo.tools.preview_sprites import decode_frame, preview
from zoo.tools.install_pack import existing_characters, install, validate

SHA = "0123456789abcdef0123456789abcdef01234567"


class SpriteHostToolsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        src = self.root / "art"
        src.mkdir()
        meta = {
            "id": "cachorro", "name_ru": "Карамелька",
            "author": "Original synthetic fixture", "license": "CC0-1.0",
            "source_url": "https://example.org/synthetic", "source_commit": SHA,
            "rights_confirmed": True, "source_anchor": [8, 15]
        }
        (src / "pack.json").write_text(json.dumps(meta), encoding="utf-8")
        im = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.rectangle((4, 3, 11, 12), fill=(255, 0, 0, 255))
        im.save(src / "normal.png")
        self.pack = self.root / "pack"
        compile_pack(src, self.pack, size=(32, 40), margin=2)

    def test_decode_frame_has_transparent_border(self):
        im, meta = decode_frame(self.pack, "normal")
        self.assertEqual((32, 40), im.size)
        self.assertEqual("cachorro", meta["id"])
        self.assertEqual(0, im.getpixel((0, 0))[3])
        self.assertEqual(255, max(im.getchannel("A").getdata()))

    def test_host_previews_both_canvas_sizes(self):
        for board, size in (("ips", (240, 284)),
                            ("amoled-v1", (368, 448))):
            with self.subTest(board=board):
                output = self.root / (board + ".png")
                self.assertEqual(output, preview(self.pack, output,
                                                 "normal", board=board))
                with Image.open(output) as image:
                    self.assertEqual(size, image.size)

    def test_validated_dry_run_does_not_require_mpremote(self):
        self.assertIn("cachorro", existing_characters())
        name, paths = validate(self.pack)
        self.assertEqual(name, "cachorro")
        self.assertEqual(2, len(paths))
        output = io.StringIO()
        with redirect_stdout(output):
            install(self.pack, "/dev/ttyACM0", dry_run=True)
        commands = output.getvalue()
        self.assertIn("cp", commands)
        self.assertIn("zoo/packs/cachorro/normal.rgb565", commands)
        self.assertLess(commands.index("normal.rgb565"), commands.index("manifest.json"))
        self.assertIn("no serial connection", commands)

    def test_no_amoled_flash_or_install(self):
        with self.assertRaisesRegex(ValueError, "AMOLED V1"):
            install(self.pack, "/dev/ttyACM0", board="amoled-v1", dry_run=True)

    def test_no_invalid_serial_port(self):
        with self.assertRaisesRegex(ValueError, "explicit serial"):
            install(self.pack, "", dry_run=True)

    def test_installer_refuses_corruption(self):
        data = self.pack / "normal.rgb565"
        d = bytearray(data.read_bytes())
        d[0] ^= 1
        data.write_bytes(d)
        with self.assertRaisesRegex(ValueError, "checksum"):
            validate(self.pack)

    def test_not_registered_character_cannot_be_installed(self):
        manifest = self.pack / "manifest.json"
        d = json.loads(manifest.read_text())
        d["id"] = "surprise"
        manifest.write_text(json.dumps(d))
        with self.assertRaisesRegex(ValueError, "existing"):
            validate(self.pack)


if __name__ == "__main__":
    unittest.main()
