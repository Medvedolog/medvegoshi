"""Host-side checks for the compact Cyrillic glyph module (no ESP32 needed)."""
import unittest
import font_ru


class FakeFb:
    def __init__(self):
        self.pixels = []
        self.rectangles = []

    def pixel(self, x, y, color):
        self.pixels.append((x, y, color))

    def fill_rect(self, x, y, w, h, color):
        self.rectangles.append((x, y, w, h, color))


class CyrillicFontTests(unittest.TestCase):
    def test_table_is_complete(self):
        self.assertEqual(66, len(font_ru.LETTERS))
        self.assertEqual(66, len(set(font_ru.LETTERS)))
        self.assertEqual(len(font_ru.DATA), len(font_ru.LETTERS) * 8)
        for letter in ('А', 'я', 'Ё', 'ё', 'Ж', 'щ'):
            self.assertTrue(font_ru.is_cyrillic(letter))

    def test_all_letters_have_visible_bitmap(self):
        for letter in font_ru.LETTERS:
            fb = FakeFb()
            self.assertTrue(font_ru.draw_char(fb, letter, 0, 0, 0xffff))
            self.assertTrue(fb.pixels, "empty letter: " + letter)
            self.assertTrue(all(0 <= x < 8 and 0 <= y < 8 for x, y, _ in fb.pixels))

    def test_scaled_letters(self):
        fb = FakeFb()
        self.assertTrue(font_ru.draw_char(fb, 'К', 7, 9, 123, 2))
        self.assertTrue(fb.rectangles)
        self.assertTrue(all(w == h == 2 for _, _, w, h, _ in fb.rectangles))
        self.assertFalse(font_ru.draw_char(fb, '?', 0, 0, 1))


if __name__ == '__main__':
    unittest.main()
