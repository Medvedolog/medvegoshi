"""V1 settings labels: complete glyph data, correct routing, and layout."""
import ast
import math
from pathlib import Path
from types import SimpleNamespace
import unittest

from ports import v1_menu_font as font
from ports.v1_scale import VIEWPORT_LARGE


ROOT = Path(__file__).resolve().parents[1]
RUSSIAN = ''.join(chr(u) for u in range(0x0410, 0x0450)) + 'Ёё'


def function_defs(name, functions, globals_):
    path = ROOT / name
    body = ast.parse(path.read_text(encoding='utf-8')).body
    selected = [n for n in body if isinstance(n, ast.FunctionDef) and n.name in functions]
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(path), 'exec'), globals_)


class Recorder:
    def __init__(self, background=0):
        self.background = background
        self.spans = []

    def fill_rect(self, x, y, w, h, color):
        self.spans.append((x, y, w, h, color))

    def pixel(self, x, y, color=None):
        if color is None:
            return self.background
        self.fill_rect(x, y, 1, 1, color)


class TestGlyphs(unittest.TestCase):
    def test_ranges_are_valid_and_all_glyphs_visible_except_space(self):
        chars = ''.join(chr(u) for u in range(32, 127)) + RUSSIAN[:-2] + font._EXTRA
        for esc, offsets, spans in ((1, font._BODY_OFFSETS, font._BODY_SPANS),
                                    (2, font._HEADING_OFFSETS, font._HEADING_SPANS)):
            self.assertEqual(len(offsets), 2 * (len(chars) + 1))
            self.assertEqual(int.from_bytes(offsets[-2:], 'little'), len(spans))
            for i, ch in enumerate(chars):
                with self.subTest(esc=esc, ch=ch):
                    self.assertEqual(font._index(ch), i)
                    self.assertTrue(font.supports(ch))
                    fb = Recorder()
                    font.draw(fb, ch, 0, 0, 0xFFFF, esc)
                    self.assertEqual(bool(fb.spans), ch != ' ')
                    for x, y, w, h, c in fb.spans:
                        self.assertGreaterEqual(x, -font._X_PAD)
                        self.assertLessEqual(x + w, font.measure(ch, esc) + font._X_PAD)
                        self.assertTrue(0 <= y < y + h <= font.height(esc))
                        self.assertEqual(h, 1)
                        self.assertGreater(c, 0)

    def test_proportional_advances_and_tabular_clock_digits(self):
        for esc in (1, 2):
            self.assertGreater(font.measure('ШШШ', esc), font.measure('шшш', esc))
            self.assertGreater(font.measure('ШШШ', esc), font.measure('111', esc))
            self.assertEqual(len({font.measure(ch, esc) for ch in '0123456789'}), 1)
            self.assertEqual(font.measure('09:00', esc), font.measure('17:59', esc))
        self.assertGreater(font.measure('Настройки', 2), font.measure('Настройки'))
        self.assertLess(font.measure('Настройки', 2), font.measure('Настройки') * 2)

    def test_fixed_baseline_and_rgb565_antialiasing(self):
        for esc in (1, 2):
            plain, accent = Recorder(), Recorder()
            font.draw(plain, 'Е', 0, 0, 0xFFFF, esc)
            font.draw(accent, 'Ё', 0, 0, 0xFFFF, esc)
            self.assertEqual(max(s[1] for s in plain.spans), font.baseline(esc) - 1)
            self.assertEqual(max(s[1] for s in accent.spans), font.baseline(esc) - 1)
            self.assertLess(min(s[1] for s in accent.spans), min(s[1] for s in plain.spans))
        fb = Recorder(background=0x1F00)      # blue background, wire byte order
        font.draw(fb, 'А', 0, 0, 0x00F8)      # red foreground
        self.assertEqual({s[4] for s in fb.spans}, {0x00F8, 0x1550, 0x0AA8})

    def test_unsupported_and_unknown_glyph_handling(self):
        missing, question = Recorder(), Recorder()
        self.assertFalse(font.supports('Пип 🐻'))
        self.assertFalse(font.supports('x' * 33))
        font.draw(missing, '🐻', 0, 0, 0xFFFF)
        font.draw(question, '?', 0, 0, 0xFFFF)
        self.assertEqual(missing.spans, question.spans)
        self.assertEqual(font.measure('🐻'), font.measure('?'))


class TestLabelRouting(unittest.TestCase):
    def setUp(self):
        self.logical = []
        self.captured = []
        self.calls = []
        self.env = {
            'W': 240, 'H': 284, 'MENU_FUNDO': 272,
            'ri': lambda x: int(math.floor(x + 0.5)), 'C': self.wire_color,
            'ELENCO': ('girafa', 'pip'), 'NOMES': {'girafa': 'Жирафик', 'pip': 'Пип'},
            'MODOS': (('pet', 'Уход'), ('companion', 'Жизнь'), ('explore', 'Гулять')),
            'AJUSTES_ROT': ('-1 мин', '-1 ч', '+1 ч', '+1 мин'),
            'MENU_CLOCK_X': 16, 'MENU_CLOCK_STEP': 53, 'MENU_CLOCK_W': 49,
            'VEL_MIN': {1: 30, 2: 15, 3: 10},
            'texto': lambda *args: self.logical.append(args),
        }
        for i, c in enumerate(('INK', 'CREME', 'ACC', 'MUTEDM', 'TRAY',
                               'TRAY_BTN', 'BRANCO', 'VERMELHO')):
            self.env[c] = (i, 2, 3)
        for fn in ('rrect', 'rect', 'linha', 'poly', 'personagem', 'ovo', 'hl'):
            self.env[fn] = lambda *_args, **_kw: None
        function_defs('desenho.py', ('centro', '_seg', 'menu'), self.env)

    @staticmethod
    def wire_color(c):
        return c[0] + 0x1234

    def capture(self, *args):
        self.captured.append(args)
        return font.supports(args[0])

    def render(self, border=272, clock='real', mode='pet', clock_write=False,
               pending=None, confirm=None, legenda='', capture=True):
        self.logical.clear()
        self.captured.clear()
        self.env['menu'](border, mode, 'girafa', clock, 1, '11:00', False,
                         pending, confirm, legenda, 'adulto', 0, clock_write,
                         self.capture if capture else None)

    def test_labels_keep_one_font_through_animation_and_preserve_legacy_fallback(self):
        positions = []
        for border in (180, 260, 271, 272):
            self.render(border=border)
            self.assertFalse(self.logical)
            label = next(args for args in self.captured if args[0] == 'Настройки')
            self.assertEqual(label[1:5], (48, border - 263,
                                           self.wire_color(self.env['BRANCO']), 2))
            self.assertEqual(label[5], (0, border - 263, 240, 0))
            positions.append(label[2])
        self.assertEqual(positions, [-83, -3, 8, 9])
        self.render(border=271, capture=False)
        self.assertFalse(self.captured)
        self.assertTrue(self.logical)

    def test_all_russian_label_modes_fit_and_keep_original_known_areas(self):
        for clock, pending, confirm, clock_write, expected in (
            ('real', None, None, True, ('+1 мин', 'Сейчас 11:00')),
            ('real', 'pip', 'trocar', False, ('Пип?', 'Прогресс сохранится')),
            ('real', None, 'zerar', False, ('Сбросить прогресс?', 'Этот друг начнёт с яйца')),
            ('sim', None, None, False, ('2x', 'сутки за 30 мин')),
        ):
            with self.subTest(clock=clock, confirm=confirm):
                self.render(clock=clock, pending=pending, confirm=confirm, clock_write=clock_write)
                self.assertFalse(self.logical)
                areas = {
                    'Настройки': (49 - 1, 9, 192, 29),
                    'Сменить друга': (116, 73, 224, 87),
                    'Прогресс сохранится': (16, 168, 224, 206),
                    'Этот друг начнёт с яйца': (16, 168, 224, 206),
                    '+1 мин': (175, 214, 224, 236)
                }
                for s, x, y, c, scale, *aligned in self.captured:
                    fb = Recorder()
                    self.assertTrue(font.supports(s), s)
                    origin = VIEWPORT_LARGE.pixel_origin
                    px, py = origin(x, y)
                    py -= 2
                    if aligned:
                        bx, by, bw, bh = aligned[0]
                        left, top = origin(bx, by)
                        right, bottom = origin(bx + bw, by + bh)
                        px = (left + right - font.measure(s, scale)) // 2
                        if bh:
                            py = (top + bottom - font.height(scale)) // 2
                    font.draw(fb, s, px, py, c, scale)
                    x0, y0, x1, y1 = areas.get(s, (0, 0, 240, 272))
                    left, top = origin(x0, y0)
                    right, bottom = origin(x1, y1)
                    self.assertTrue(fb.spans)
                    self.assertTrue(all(left <= px and px + pw <= right
                                        and top <= py and py + ph <= bottom
                                        for px, py, pw, ph, _ in fb.spans), s)
                self.assertTrue(set(expected).issubset({label[0] for label in self.captured}))

    def test_unsupported_label_still_draws_logically(self):
        self.render(legenda='Пип 🐻')
        self.assertIn('Пип 🐻', [args[0] for args in self.captured])
        self.assertEqual([args[0] for args in self.logical], ['Пип 🐻'])

    def test_system_notice_does_not_change_menu_font_and_is_queued_after_it(self):
        stub = SimpleNamespace(
            MENU_FUNDO=272,
            menu=lambda *args: self.calls.append(('menu', args[-1])),
            sistema=lambda text, fn: self.calls.append(('notice', text, fn)),
        )
        callback = self.capture
        notice = lambda *_: None
        env = dict(d=stub, bat_avisou=False, sis_txt='Не удалось сохранить',
                   sis_ate=20, menu_borda=272, tela=SimpleNamespace(menu_text=callback, menu_notice=notice),
                   time=SimpleNamespace(ticks_diff=lambda a, b: a - b),
                   cfg={'modo': 'pet', 'personagem': 'girafa', 'hora': 'real', 'vel': 1, 'som': False},
                   relogio_txt=lambda _: '11:00', hora_real=lambda: 11,
                   menu_pend=None, menu_conf=None, legenda_vida=lambda: '',
                   fase_vida=lambda: 'adulto', runtime_allow_wifi=False,
                   runtime_clock_write=False)
        function_defs('main.py', ('desenhar_sobreposicoes',), env)
        env['desenhar_sobreposicoes'](10)
        env['desenhar_sobreposicoes'](20)
        self.assertEqual(self.calls, [('menu', callback), ('notice', 'Не удалось сохранить', notice),
                                      ('menu', callback)])


if __name__ == '__main__':
    unittest.main()
