"""Host RGB565 regression: compose once and turn the complete pet."""
import importlib.util
import math
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from ports.emulate_v1 import FrameBuffer, MONO_HLSB, RGB565

ROOT = Path(__file__).resolve().parents[1]
W, H = 240, 284
GREEN = (0, 255, 0)


def wire_color(r, g, b):
    word = ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)
    return ((word & 255) << 8) | (word >> 8)


def load_art():
    spec = importlib.util.spec_from_file_location('art_for_rotation', ROOT / 'desenho.py')
    module = importlib.util.module_from_spec(spec)
    kit = {
        'hw': SimpleNamespace(W=W, H=H, cor=wire_color),
        'framebuf': SimpleNamespace(FrameBuffer=FrameBuffer, RGB565=RGB565, MONO_HLSB=MONO_HLSB),
    }
    with patch.dict(sys.modules, kit):
        spec.loader.exec_module(module)
    return module


def paint(art, pet, angle, flip=1, zoom=(1, 1), x=120, y=188):
    fb = FrameBuffer(bytearray(W * H * 2), W, H, RGB565)
    fb.fill(wire_color(*GREEN))
    art.usar(fb)
    p = art.personagem_vivo(pet, x, y, {
        'rot': angle, 'flip': flip, 'sx': zoom[0], 'sy': zoom[1],
    }, {'grama_e': GREEN}, 310, 'normal', 'sorriso')
    return fb.image, p


def largest_component(points):
    todo = set(points)
    largest = 0
    while todo:
        q = [todo.pop()]
        size = 0
        while q:
            x, y = q.pop()
            size += 1
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    p = x + dx, y + dy
                    if p in todo:
                        todo.remove(p)
                        q.append(p)
        largest = max(largest, size)
    return largest


def occupied(image):
    return {(x, y) for y in range(H) for x in range(W) if image.getpixel((x, y)) != GREEN}


class SpriteCohesionTests(unittest.TestCase):
    def setUp(self):
        self.art = load_art()

    def test_turn_keeps_each_silhouette_in_one_piece(self):
        for name in ('capi', 'gato', 'elefante', 'bjorni'):
            for angle in (math.pi / 5, math.pi / 2, math.pi, -math.pi / 3):
                with self.subTest(pet=name, angle=angle):
                    im, pose = paint(self.art, name, angle, zoom=(0.94, 1.04))
                    points = occupied(im)
                    self.assertGreater(len(points), 1000)
                    self.assertGreaterEqual(largest_component(points), len(points) * 0.993)
                    self.assertEqual(len(pose['eyes']), 2)
                    self.assertIsNone(self.art._T)

    def test_full_turn_returns_all_twelve_pets_to_exact_resting_pixels(self):
        self.assertEqual(len(self.art.ELENCO), 12)
        for pet in self.art.ELENCO:
            with self.subTest(pet=pet):
                upright, start = paint(self.art, pet, 0)
                rotated, end = paint(self.art, pet, math.tau)
                self.assertEqual(upright.tobytes(), rotated.tobytes())
                for (x0, y0), (x1, y1) in zip(start['eyes'], end['eyes']):
                    self.assertAlmostEqual(x0, x1, places=4)
                    self.assertAlmostEqual(y0, y1, places=4)

    def test_mirror_preserves_pose_and_keeps_outside_panel_clipped(self):
        im, a = paint(self.art, 'gato', math.pi / 2)
        mirror, b = paint(self.art, 'gato', math.pi / 2, flip=-1)
        self.assertNotEqual(im.tobytes(), mirror.tobytes())
        for i in range(2):
            self.assertAlmostEqual(a['eyes'][i][0] + b['eyes'][i][0], 240, places=4)
            self.assertAlmostEqual(a['eyes'][i][1], b['eyes'][i][1], places=4)
        x = 5
        edge, _ = paint(self.art, 'elefante', math.pi / 3, x=x, y=44)
        self.assertGreater(len(occupied(edge)), 100)
        size = self.art._roll_buf
        paint(self.art, 'capi', -math.pi / 2)
        self.assertIs(self.art._roll_buf, size)
        self.assertLessEqual(len(size), 34 * 1024)

    def test_no_tile_never_falls_back_to_mixed_primitive_rotation(self):
        with patch.object(self.art, '_personagem_rolado', return_value=None):
            on, _ = paint(self.art, 'gato', math.pi / 2, zoom=(0.9, 1.1))
        off, _ = paint(self.art, 'gato', 0, zoom=(0.9, 1.1))
        self.assertEqual(on.tobytes(), off.tobytes())


def image_pixels(im):
    return getattr(im, 'get_flattened_data', im.getdata)()


class NativeSpriteTests(unittest.TestCase):
    def setUp(self):
        from ports.v1_native_canvas import NativeCanvas
        from ports.v1_scale import VIEWPORT_LARGE
        self.art = load_art()
        self.canvas = NativeCanvas(
            bytearray(VIEWPORT_LARGE.width * VIEWPORT_LARGE.height * 2),
            SimpleNamespace(FrameBuffer=FrameBuffer, RGB565=RGB565, MONO_HLSB=MONO_HLSB),
            VIEWPORT_LARGE)

    def draw(self, pet, angle, x=120, flip=1):
        self.canvas.fill(wire_color(*GREEN))
        self.art.usar(self.canvas)
        return self.art.personagem_vivo(pet, x, 196,
            {'rot': angle, 'flip': flip}, {'grama_e': GREEN}, 310, 'normal', 'sorriso')

    def mask(self):
        return {(i % self.canvas.width, i // self.canvas.width)
                for i, color in enumerate(image_pixels(self.canvas.fb.image)) if color != GREEN}

    def test_all_twelve_can_turn_and_land_exactly_on_native_canvas(self):
        self.assertEqual(len(self.art.ELENCO), 12)
        for pet in self.art.ELENCO:
            with self.subTest(pet=pet):
                p = self.draw(pet, 0)
                start = self.canvas.fb.image.tobytes()
                self.draw(pet, -math.pi / 3)
                self.assertGreater(len(self.mask()), 3000)
                self.assertNotEqual(start, self.canvas.fb.image.tobytes())
                q = self.draw(pet, -math.tau)
                self.assertEqual(p['eyes'], q['eyes'])
                self.assertEqual(start, self.canvas.fb.image.tobytes())
        self.assertLess(len(self.art._roll_native.buf), 76 * 1024)
        self.assertIsNone(self.art._roll_buf)

    def test_caramel_puppy_rotates_as_single_layer_and_terrain_can_cover_it(self):
        for a in (-math.pi / 3, math.pi / 2, math.pi):
            with self.subTest(angle=a):
                self.draw('cachorro', a)
                points = self.mask()
                self.assertGreater(largest_component(points), 0.99 * len(points))
        self.draw('cachorro', math.pi / 4, x=7, flip=-1)
        self.assertGreater(len(self.mask()), 300)
        self.draw('cachorro', math.pi / 3)
        self.canvas.fill_rect(0, 0, W, H, wire_color(*GREEN))
        self.assertFalse(self.mask())

    def test_native_fine_detail_is_not_a_scaled_legacy_frame(self):
        self.draw('cachorro', 0)
        dst = self.canvas.fb.image
        low, _ = paint(self.art, 'cachorro', 0, y=196)
        # More native color transitions and independently positioned edges
        # persist even after dropping the native-only palette highlights.
        glint = self.canvas.fb.color(wire_color(255, 226, 169))
        self.assertIn(glint, set(image_pixels(dst)))
        self.assertNotIn(glint, set(image_pixels(low)))
        up = low.resize(dst.size, resample=0)
        self.assertGreater(sum(a != b for a, b in zip(image_pixels(dst), image_pixels(up))), 1000)

    def test_caramel_eyes_keep_blue_irises_dark_pupils_and_tiny_catchlights(self):
        images = []
        color = lambda rgb: self.canvas.fb.color(wire_color(*rgb))
        for mood in ('normal', 'feliz', 'susto', 'sono', 'fechados'):
            self.canvas.fill(wire_color(*GREEN))
            self.art.usar(self.canvas)
            self.art.personagem('cachorro', 120, 196, mood)
            eyes = []
            for x, y in self.art.olhos_ult:
                cx, cy = self.canvas.map_x(x), self.canvas.map_y(y)
                eye = self.canvas.fb.image.crop((cx - 8, cy - 8, cx + 9, cy + 9))
                pixels = list(image_pixels(eye))
                self.assertNotIn((255, 255, 255), pixels)
                self.assertIn(color((62, 35, 29)), pixels)
                blink = pixels.count(color((207, 232, 241)))
                if mood in ('normal', 'susto'):
                    self.assertGreaterEqual(pixels.count(color((26, 29, 36))), 12)
                    self.assertGreaterEqual(pixels.count(color((115, 188, 215))), 12)
                    self.assertIn(blink, range(1, 5))
                else:
                    self.assertEqual(blink, 0)
                eyes.append(eye.tobytes())
            images.append(tuple(eyes))
        self.assertEqual(len(set(images)), 5)
