"""V1 settings labels: complete glyph data, correct routing, and layout."""
import ast
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
    def __init__(self):
        self.spans = []

    def fill_rect(self, x, y, w, h, color):
        self.spans.append((x, y, w, h, color))


class TestGlyphs(unittest.TestCase):
    def test_ranges_are_valid_and_all_glyphs_visible_except_space(self):
        chars = ''.join(chr(u) for u in range(32, 127)) + RUSSIAN[:-2] + font._EXTRA
        self.assertEqual(len(font._OFFSETS), 2 * (len(chars) + 1))
        self.assertEqual(font._offset(len(chars)), len(font._SPANS))
        for i, ch in enumerate(chars):
            with self.subTest(ch=ch):
                self.assertEqual(font._index(ch), i)
                self.assertTrue(font.supports(ch))
                fb = Recorder()
                font.draw(fb, ch, 0, 0, 5)
                self.assertEqual(font._offset(i + 1) - font._offset(i), 2 * len(fb.spans))
                self.assertEqual(bool(fb.spans), ch != ' ')
                for x, y, w, h, c in fb.spans:
                    self.assertTrue(0 <= x < x + w <= font.ADVANCE)
                    self.assertTrue(0 <= y < y + h <= font.HEIGHT)
                    self.assertEqual((h, c), (1, 5))

    def test_advance_scaling_and_unknown_glyph_handling(self):
        one, both, missing, question = Recorder(), Recorder(), Recorder(), Recorder()
        font.draw(one, 'Ж', 2, 3, 0xABC)
        font.draw(both, 'Ж Ж', 5, 7, 0x123, 2)
        self.assertEqual(both.spans, [
            (5 + offset + (x - 2) * 2, 7 + (y - 3) * 2, w * 2, 2, 0x123)
            for offset in (0, 4 * font.ADVANCE) for x, y, w, _, _ in one.spans
        ])
        self.assertFalse(font.supports('Пип 🐻'))
        self.assertFalse(font.supports('x' * 33))
        font.draw(missing, '🐻', 0, 0, 10)
        font.draw(question, '?', 0, 0, 10)
        self.assertEqual(missing.spans, question.spans)


class TestLabelRouting(unittest.TestCase):
    def setUp(self):
        self.logical = []
        self.captured = []
        self.calls = []
        self.env = {
            'W': 240, 'H': 284, 'MENU_FUNDO': 272,
            'ri': lambda x: int(x + 0.5), 'C': self.wire_color,
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

    def test_only_full_open_labels_captured_and_colors_converted(self):
        self.render(border=271)
        self.assertFalse(self.captured)
        self.assertTrue(self.logical)
        original = self.logical[:]
        self.render(border=271, capture=False)
        self.assertEqual(self.logical, original)
        self.render()
        self.assertFalse(self.logical)
        self.assertIn(('Настройки', 48, 9, self.wire_color(self.env['BRANCO']), 2),
                      self.captured)
        labels = [label[0] for label in self.captured]
        self.assertIn('Часы: только чтение', labels)
        self.assertIn('Сейчас 11:00', labels)
        self.assertNotIn('-1 мин', labels)

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
                for s, x, y, c, scale in self.captured:
                    fb = Recorder()
                    self.assertTrue(font.supports(s), s)
                    origin = VIEWPORT_LARGE.pixel_origin
                    font.draw(fb, s, *origin(x, y), c, scale)
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

    def test_system_notice_keeps_original_order_and_callback_recovers(self):
        stub = SimpleNamespace(
            MENU_FUNDO=272,
            menu=lambda *args: self.calls.append(('menu', args[-1])),
            sistema=lambda text: self.calls.append(('notice', text)),
        )
        callback = self.capture
        env = dict(d=stub, bat_avisou=False, sis_txt='Не удалось сохранить',
                   sis_ate=20, menu_borda=272, tela=SimpleNamespace(menu_text=callback),
                   time=SimpleNamespace(ticks_diff=lambda a, b: a - b),
                   cfg={'modo': 'pet', 'personagem': 'girafa', 'hora': 'real', 'vel': 1, 'som': False},
                   relogio_txt=lambda _: '11:00', hora_real=lambda: 11,
                   menu_pend=None, menu_conf=None, legenda_vida=lambda: '',
                   fase_vida=lambda: 'adulto', runtime_allow_wifi=False,
                   runtime_clock_write=False)
        function_defs('main.py', ('desenhar_sobreposicoes',), env)
        env['desenhar_sobreposicoes'](10)
        env['desenhar_sobreposicoes'](20)
        self.assertEqual(self.calls, [('menu', None), ('notice', 'Не удалось сохранить'),
                                      ('menu', callback)])


if __name__ == '__main__':
    unittest.main()
