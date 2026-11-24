"""Pixel-level host coverage for the directly drawn large-viewport canvas."""
from array import array
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from ports.emulate_v1 import FrameBuffer, MONO_HLSB, RGB565, decode
from ports.v1_native_canvas import NativeCanvas
from ports.v1_scale import VIEWPORT_LARGE

MOD = SimpleNamespace(FrameBuffer=FrameBuffer, RGB565=RGB565, MONO_HLSB=MONO_HLSB)
V = VIEWPORT_LARGE
# Native halfwords for common panel RGB565 colors.
BLACK, RED, GREEN, BLUE = 0, 0x00F8, 0xE007, 0x1F00


class NativeCanvasTests(TestCase):
    def setUp(self):
        self.buf = bytearray(V.width * V.height * 2)
        self.canvas = NativeCanvas(self.buf, MOD, V)

    def test_maps_every_integer_endpoint_like_touch_viewport_and_is_local(self):
        c = self.canvas
        self.assertEqual((c.width, c.height), (368, 435))
        self.assertEqual((c.map_x(0), c.map_y(0)), (0, 0))
        self.assertTrue(c.native_art)
        for n in range(-17, 285):
            self.assertEqual((c.map_x(n), c.map_y(n)), V.pixel_origin(n, n))
        self.assertEqual(c.map_x(-1.5), -2)
        self.assertEqual(c.map_y(10.2), 16)
        self.assertEqual(c.map_x(1.5), 3)
        self.assertEqual(c.map_x(15 + 1e-8), c.map_x(15))
        self.assertEqual(c.map_y(284 + 1e-8), c.map_y(284))
        with self.assertRaises(ValueError):
            NativeCanvas(bytearray(5), MOD, V)

    def test_fill_and_shared_fractional_edges_take_the_real_wire_path(self):
        c = self.canvas
        c.fill(BLUE)
        c.fill_rect(-2.0, 4.5, 3.5, 2.0, RED)
        c.fill_rect(1.5, 4.5, 3.5, 2.0, GREEN)
        y = c.map_y(4.5)
        boundary = c.map_x(1.5)
        self.assertEqual(c.fb.image.getpixel((boundary - 1, y)), decode(0xF800))
        self.assertEqual(c.fb.image.getpixel((boundary, y)), decode(0x07E0))
        self.assertEqual(c.fb.image.getpixel((boundary, y - 1)), decode(0x001F))
        c.flush()
        i = (y * c.width + boundary) * 2
        self.assertEqual(self.buf[i:i+2], b'\x07\xe0')

    def test_shapes_compose_in_game_order_and_raw_native_detail_survives(self):
        c = self.canvas
        c.fill(BLACK)
        c.ellipse(20, 20, 7, 6, RED, True)
        x, y = c.map_x(20), c.map_y(20)
        self.assertEqual(c.fb.image.getpixel((x, y)), decode(0xF800))
        c.fb.pixel(x, y, GREEN)
        self.assertEqual(c.pixel(20, 20), GREEN)
        c.poly(18, 18, array("h", [0, 0, 6, 0, 0, 6]), BLUE, True)
        self.assertEqual(c.pixel(20, 20), BLUE)
        c.rect(35, 15, 5, 5, RED)
        self.assertEqual(c.pixel(35, 15), RED)
        self.assertEqual(c.pixel(37, 17), BLACK)
        c.line(37, 14, 37, 20, GREEN)
        self.assertEqual(c.pixel(37, 17), GREEN)

    def test_subpixel_half_ellipse_still_has_nonempty_quadrants(self):
        c = self.canvas
        c.fill(BLACK)
        c.ellipse(20.25, 20.75, 0.15, 0.15, RED, True, 3)
        self.assertEqual(c.fb.image.getpixel((c.map_x(20.25), c.map_y(20.75))),
                         decode(0xF800))

    def test_transparent_blit_can_read_unlabelled_logical_framebuffer_and_clip(self):
        c = self.canvas
        c.fill(BLUE)
        raw = FrameBuffer(bytearray(4 * 3 * 2), 4, 3, RGB565)
        raw.fill(BLACK)
        raw.pixel(1, 1, RED)
        raw.pixel(3, 1, GREEN)
        c.blit(raw, -1, 0, BLACK)
        self.assertEqual(c.pixel(0, 1), RED)
        self.assertEqual(c.pixel(1, 1), BLUE)
        self.assertEqual(c.pixel(2, 1), GREEN)
        self.assertEqual(c.pixel(3, 1), BLUE)
        self.assertIsNone(c.pixel(-1, 1))
        self.assertIsNone(c.pixel(c.logical_width, 1))

    def test_tile_uses_parent_scale_but_independent_backing(self):
        c = self.canvas
        tile = c.new_tile(60, 80)
        self.assertEqual((tile.width, tile.height), (92, 123))
        self.assertEqual((tile.sx, tile.sy), (c.sx, c.sy))
        self.assertIsNot(tile.buf, c.buf)
        tile.fill(GREEN)
        self.assertEqual(c.pixel(1, 1), BLACK)
        c.blit(tile, 1, 1, GREEN)
        self.assertEqual(c.pixel(1, 1), BLACK)
        c.blit(tile, 1, 1)
        self.assertEqual(c.pixel(60, 80), GREEN)
        self.assertEqual(c.pixel(61, 80), BLACK)

    def test_legacy_text_draws_and_reuses_tiny_glyph_buffer(self):
        c = self.canvas
        c.fill(BLACK)
        c.text("Wi", 12, 15, RED)
        area = c.fb.image.crop((c.map_x(12), c.map_y(15), c.map_x(28), c.map_y(23)))
        self.assertIn(decode(0xF800), set(area.get_flattened_data() if hasattr(area, "get_flattened_data")
                                            else area.getdata()))
        glyph = c._glyph
        c.text("Fi", -8, 15, GREEN)
        self.assertIs(c._glyph, glyph)


    def test_game_pip_eyes_go_to_raw_surface_at_native_dimensions(self):
        from zoo.pip import eyes

        # Load the actual game renderer privately with host framebuf shims.
        filename = Path(__file__).resolve().parents[1] / "desenho.py"
        spec = importlib.util.spec_from_file_location("native_canvas_eyes_probe", filename)
        renderer = importlib.util.module_from_spec(spec)
        cor = lambda r, g, b: ((r & 248) | ((g & 224) >> 5)
                               | (((g & 28) << 3 | (b >> 3)) << 8))
        hw = SimpleNamespace(cor=cor, W=240, H=284)
        with patch.dict(sys.modules, {"hw": hw, "framebuf": MOD}):
            spec.loader.exec_module(renderer)
        c = self.canvas
        renderer.usar(c)
        c.fb.blit = Mock()
        tile = object()
        point_x, point_y, scale = 120, 205, 0.74
        with patch.object(eyes, "try_tile", return_value=tile) as render_tile:
            renderer.personagem("pip", point_x, point_y, pip_state=("neutral", 1200))
        x = c.map_x(point_x - 27 * scale)
        y = c.map_y(point_y - 94 * scale)
        w = c.map_x(point_x + 27 * scale) - x
        h = c.map_y(point_y - 62 * scale) - y
        render_tile.assert_called_once_with(c.fb, x, y, w, h, "normal",
                                            "neutral", 1200, 368, 435)
        c.fb.blit.assert_called_once_with(tile, x, y, 0)
        self.assertGreater(w, round(54 * scale))
        self.assertGreater(h, round(32 * scale))
