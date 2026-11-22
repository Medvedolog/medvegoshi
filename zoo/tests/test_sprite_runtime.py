"""ESP32-compatible streaming sprite loader regressions (host CPython).

Tests generate original tiny PNGs at runtime. Nothing is downloaded or
copied from Giraffegotchi/Pip; artwork is strictly synthetic.
"""
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest

from PIL import Image, ImageDraw
from zoo import sprites
from zoo.tools.build_sprites import compile_pack

SHA = "0123456789abcdef0123456789abcdef01234567"


class PixelFB:
    def __init__(self, w=240, h=284):
        self.w, self.h = w, h
        self.pixels = {}
        self.blit_calls = 0

    def pixel(self, x, y, color):
        if 0 <= x < self.w and 0 <= y < self.h:
            self.pixels[(x, y)] = color

    def fill_rect(self, x, y, w, h, color):
        for yy in range(max(0, y), min(self.h, y + h)):
            for xx in range(max(0, x), min(self.w, x + w)):
                self.pixel(xx, yy, color)


class FrameBufferStub:
    def __init__(self, buf, width, height, fmt):
        self.buf = buf
        self.width = width
        self.height = height


class BlittingFB(PixelFB):
    def blit(self, source, x, y, key):
        self.blit_calls += 1
        for xx in range(source.width):
            p = xx * 2
            val = source.buf[p] | (source.buf[p + 1] << 8)
            if val != key:
                self.pixel(x + xx, y, val)


class SpriteRuntimeTests(unittest.TestCase):
    def setUp(self):
        sprites.clear_cache()
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.base = Path(self.td.name)
        self.source = self.base / "art"
        self.source.mkdir()
        self.root = self.base / "packs"
        self.root.mkdir()
        self.hero = "cachorro"
        self.meta = {
            "id": self.hero, "name_ru": "Карамелька",
            "author": "Test suite", "license": "CC0-1.0",
            "source_url": "https://example.org/test-only",
            "source_commit": SHA, "rights_confirmed": True,
            "source_anchor": [8, 15]
        }
        self._write_meta()
        self._make_pose("normal", (255, 0, 0, 255))
        self._make_pose("happy", (0, 255, 0, 255))
        self._make_pose("sleeping", (0, 0, 255, 255))
        self._make_pose("sick", (255, 255, 0, 255))

    def _write_meta(self):
        (self.source / "pack.json").write_text(
            json.dumps(self.meta, ensure_ascii=False), encoding="utf-8")

    def _make_pose(self, name, color):
        im = Image.new("RGBA", (16, 16))
        d = ImageDraw.Draw(im)
        d.rectangle((3, 3, 12, 12), fill=color)
        d.point((5, 5), fill=(255, 0, 255, 255))
        im.save(self.source / (name + ".png"))

    def _build(self, target="ips", size=(32, 40)):
        folder = self.root / self.hero
        compile_pack(self.source, folder, target=target, size=size, margin=2)
        sprites.clear_cache()
        return folder

    def _draw(self, fb, eyes="normal", mouth="sorriso", sick=False,
              prefer_blit=False, target="ips"):
        return sprites.draw(
            fb, self.hero, 95, 160, 1, eyes, mouth, sick,
            root=str(self.root), target=target, disp_w=240, disp_h=284,
            prefer_blit=prefer_blit)

    def test_no_pack_falls_back_without_mutating_framebuffer(self):
        fb = PixelFB()
        self.assertIsNone(self._draw(fb))
        self.assertEqual(fb.pixels, {})

    def test_registered_normal_sprite_draws_without_black_rectangle(self):
        self._build()
        fb = PixelFB()
        info = self._draw(fb)
        self.assertIsNotNone(info)
        self.assertEqual(len(info), 4)
        self.assertEqual(len(info[3]), 2)
        self.assertGreater(len(fb.pixels), 25)
        self.assertIn(0x00F8, fb.pixels.values())  # opaque red, native little-endian
        self.assertNotIn((79, 117), fb.pixels)  # transparent corner remains untouched

    def test_happy_sleep_and_sick_select_different_frames(self):
        self._build()
        colors = {}
        for eyes, sick in (("normal", False), ("feliz", False),
                           ("fechados", False), ("normal", True)):
            fb = PixelFB()
            self.assertIsNotNone(self._draw(fb, eyes, sick=sick))
            colors[(eyes, sick)] = set(fb.pixels.values())
        self.assertIn(0x00F8, colors[("normal", False)])
        self.assertIn(0xE007, colors[("feliz", False)])   # RGB565 green, swapped
        self.assertIn(0x1F00, colors[("fechados", False)])  # blue
        self.assertIn(0xE0FF, colors[("normal", True)])  # yellow (FFE0 -> E0FF)

    def test_real_framebuf_blit_path_and_opaque_key_collision(self):
        self._build()
        stub = types.ModuleType("framebuf")
        stub.FrameBuffer = FrameBufferStub
        stub.RGB565 = 2
        previous = sys.modules.get("framebuf")
        sys.modules["framebuf"] = stub
        try:
            fb = BlittingFB()
            self.assertIsNotNone(self._draw(fb, prefer_blit=True))
            self.assertGreater(fb.blit_calls, 0)
            self.assertIn(0x1FF8, fb.pixels.values())  # opaque magenta must NOT disappear
            self.assertIn(0x00F8, fb.pixels.values())
        finally:
            if previous is None:
                sys.modules.pop("framebuf", None)
            else:
                sys.modules["framebuf"] = previous

    def test_wrong_target_uses_procedural_fallback(self):
        self._build(target="amoled-v1")
        self.assertIsNone(self._draw(PixelFB()))
        self.assertIsNone(self._draw(PixelFB(), target="amoled-v1"))

    def test_corrupt_data_with_same_length_falls_back_before_drawing(self):
        pack = self._build()
        file = pack / "normal.rgb565"
        raw = bytearray(file.read_bytes())
        raw[30] ^= 0x80
        file.write_bytes(raw)
        fb = PixelFB()
        self.assertIsNone(self._draw(fb))
        self.assertEqual({}, fb.pixels)

    def test_truncated_file_is_rejected_by_manifest_validation(self):
        pack = self._build()
        file = pack / "normal.rgb565"
        file.write_bytes(file.read_bytes()[:-1])
        self.assertIsNone(self._draw(PixelFB()))

    def test_corrupt_path_falls_back(self):
        pack = self._build()
        file = pack / "manifest.json"
        m = json.loads(file.read_text(encoding="utf-8"))
        m["frames"][0]["rgb565"] = "../invalid.rgb565"
        file.write_text(json.dumps(m), encoding="utf-8")
        self.assertIsNone(self._draw(PixelFB()))

    def test_missing_idle_falls_back(self):
        pack = self._build()
        file = pack / "manifest.json"
        m = json.loads(file.read_text(encoding="utf-8"))
        m["frames"] = [x for x in m["frames"] if x["name"] != "normal"]
        file.write_text(json.dumps(m), encoding="utf-8")
        self.assertIsNone(self._draw(PixelFB()))

    def test_missing_emotion_frame_uses_normal_sprite(self):
        self.source.joinpath("happy.png").unlink()
        self.source.joinpath("sleeping.png").unlink()
        self.source.joinpath("sick.png").unlink()
        self._build()
        fb = PixelFB()
        self.assertIsNotNone(self._draw(fb, eyes="feliz"))
        self.assertIn(0x00F8, fb.pixels.values())

    def test_negative_cache_requires_reset_after_pack_install(self):
        fb = PixelFB()
        self.assertIsNone(self._draw(fb))
        self._build()
        # Build helper clears cache; explicitly restore negative-cache scenario.
        sprites.clear_cache()
        self.root.joinpath(self.hero, "manifest.json").rename(
            self.root.joinpath(self.hero, "later.json"))
        self.assertIsNone(self._draw(PixelFB()))
        self.root.joinpath(self.hero, "later.json").rename(
            self.root.joinpath(self.hero, "manifest.json"))
        self.assertIsNone(self._draw(PixelFB()))
        sprites.clear_cache()
        self.assertIsNotNone(self._draw(PixelFB()))

    def test_scale_down_and_screen_clipping(self):
        self._build()
        fb = PixelFB()
        result = sprites.draw(fb, self.hero, 0, 0, 0.5,
                              root=str(self.root), disp_w=240, disp_h=284,
                              prefer_blit=False)
        self.assertIsNotNone(result)
        self.assertTrue(all(0 <= x < 240 and 0 <= y < 284 for x, y in fb.pixels))

    def test_no_png_pillow_or_runtime_file_imports(self):
        runtime = (Path(__file__).resolve().parents[1] / "sprites.py").read_text()
        self.assertNotIn("from PIL", runtime)
        self.assertNotIn("import machine", runtime)
        self.assertNotIn("pngdec", runtime)

    def test_manifest_header_mismatch_falls_back(self):
        pack = self._build()
        filename = pack / "manifest.json"
        manifest = json.loads(filename.read_text(encoding="utf-8"))
        manifest["mask_bit_order"] = "lsb-first"
        filename.write_text(json.dumps(manifest), encoding="utf-8")
        self.assertIsNone(self._draw(PixelFB()))


if __name__ == "__main__":
    unittest.main()
