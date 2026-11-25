"""Native gameplay text is a large V1 wire overlay, not a logical repaint."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from PIL import ImageChops

from ports import amoled_v1 as v1
from ports import emulate_v1 as panel_sim
from ports import v1_menu_font as font
from ports.v1_full_game_emulate import _framebuffer, _idle, _touch, emulate


FRAMEBUF = SimpleNamespace(FrameBuffer=_framebuffer, RGB565=panel_sim.RGB565)
RED = 0x00F8      # swapped RGB565; actual wire bytes f8 00
WHITE = 0xFFFF
BLUE = 0x1F00
GREEN = 0xE007


class SceneWireTest(unittest.TestCase):
    def screen(self, viewport=v1.VIEWPORT_LARGE):
        panel = panel_sim.Panel(width=v1.PANEL_W, height=v1.PANEL_H)
        return v1.Tela(None, panel, FRAMEBUF, viewport), panel

    def test_scene_interface_and_metrics_only_exist_for_large(self):
        diagnostic, _ = self.screen(v1.VIEWPORT_NATIVE)
        for name in ('scene_text', 'scene_metrics', 'scene_cover'):
            self.assertIsNone(getattr(diagnostic, name))
        large, _ = self.screen()
        for esc in (1, 2):
            with self.subTest(esc=esc):
                s = 'Я в яйце!'
                logical_w, logical_h = large.scene_metrics(s, esc)
                physical_w, physical_h = font.measure(s, esc), font.height(esc)
                view = large.viewport
                self.assertLess((logical_w - 1) * view.width, physical_w * v1.LOGICAL_W)
                self.assertGreaterEqual(logical_w * view.width, physical_w * v1.LOGICAL_W)
                self.assertLess((logical_h - 1) * view.height, physical_h * v1.LOGICAL_H)
                self.assertGreaterEqual(logical_h * view.height, physical_h * v1.LOGICAL_H)
        self.assertIsNone(large.scene_metrics('Игрушка 🧸'))
        self.assertFalse(large.scene_text('Игрушка 🧸', 60, 70, RED))
        self.assertIsNone(large.scene_metrics('Поле 1', 3))
        self.assertFalse(large.scene_text('Поле 1', 60, 70, RED, 3))

    def test_scene_routes_to_qspi_payload_once_without_mutating_logical_buffer(self):
        tela, panel = self.screen()
        view = tela.viewport
        self.assertTrue(tela.scene_text('Поле 1', 20, 42, RED))
        self.assertFalse(any(tela.buf))
        self.assertFalse(any(tela.wire_buf))
        tela.mostrar()
        self.assertFalse(any(tela.buf))
        self.assertEqual(panel.transfers, [(0, 6, 367, 440, view.width * view.height * 2)])
        x, y = view.pixel_origin(20, 42)
        region = panel.image.crop((view.x + x - 2, view.y + y - 2,
                                   view.x + x + font.measure('Поле 1') + 2,
                                   view.y + y + font.height()))
        self.assertIn((255, 0, 0), [color for _, color in region.getcolors()])
        self.assertEqual(panel.image.getbbox(), (
            view.x + x - 2 + region.getbbox()[0],
            view.y + y - 2 + region.getbbox()[1],
            view.x + x - 2 + region.getbbox()[2],
            view.y + y - 2 + region.getbbox()[3],
        ))
        tela.mostrar()
        self.assertIsNone(panel.image.getbbox())

    def test_cover_blocks_whole_overlapping_labels_across_width_then_resets(self):
        tela, panel = self.screen()
        view = tela.viewport
        cover = 100
        # The logical menu already painted over the first 100 rows, before
        # the scaler runs. Keep a distinctive color all the way to both edges.
        row_bytes = v1.LOGICAL_W * 2
        tela.buf[:row_bytes * cover] = b'\x00\x1f' * (v1.LOGICAL_W * cover)
        _, edge = view.pixel_origin(0, cover)
        for pos in ((5, 75), (5, 96), (206, 96), (50, 115)):
            self.assertTrue(tela.scene_text('Я', *pos, RED))
        tela.scene_cover(cover)
        tela.mostrar()
        physical_edge = view.y + edge
        menu = panel.image.crop((0, view.y, view.width, physical_edge))
        self.assertEqual(menu.getcolors(), [(view.width * edge, (0, 0, 255))])
        # A half-clipped character must not leave a second fragment just
        # beneath the panel. The only allowed red label is farther below.
        _, below = view.pixel_origin(0, 115)
        self.assertIsNone(panel.image.crop((0, physical_edge, view.width,
                                             view.y + below - 2)).getbbox())
        lower = panel.image.crop((0, view.y + below - 2, view.width,
                                  view.y + below + font.height()))
        self.assertIn((255, 0, 0), [color for _, color in lower.getcolors()])

        # No cover requested on the following frame. The same top-world
        # anchor can render again, and the prior lower label is gone.
        tela.buf[:] = b'\x00' * len(tela.buf)
        tela.scene_text('Я', 5, 75, RED)
        tela.mostrar()
        self.assertIsNotNone(panel.image.crop((0, view.y, view.width, physical_edge)).getbbox())
        self.assertIsNone(panel.image.crop((0, physical_edge, view.width, 441)).getbbox())

    def test_scene_menu_notice_are_flushed_in_z_order_and_clear_on_transfer_error(self):
        tela, panel = self.screen()
        calls = []
        original = font.draw

        def record(surface, text, *args):
            calls.append(text)
            return original(surface, text, *args)

        # Queue order is intentionally inverted. The native system notice
        # must still cover both text layers, regardless of registration order.
        tela.menu_notice('!', GREEN, WHITE)
        tela.menu_text('М', 120, 36, WHITE)
        tela.scene_text('Я', 120, 36, RED)
        with patch.object(font, 'draw', side_effect=record):
            tela.mostrar()
        self.assertEqual(calls, ['Я', 'М', '!'])
        x, y = tela.viewport.pixel_origin(120, 36)
        self.assertEqual(panel.image.getpixel((x + 7, y + tela.viewport.y + 1)),
                         (0, 255, 0))

        tela.scene_text('Поле 1', 20, 42, RED)
        tela.scene_cover(100)
        tela.menu_text('Настройки', 40, 60, BLUE)
        tela.menu_notice('!', GREEN, WHITE)
        with patch.object(panel, 'tx_color', side_effect=OSError('simulated QSPI loss')):
            with self.assertRaisesRegex(OSError, 'simulated QSPI loss'):
                tela.mostrar()
        tela.scene_text('Я', 5, 42, RED)
        calls.clear()
        with patch.object(font, 'draw', side_effect=record):
            tela.mostrar()
        self.assertEqual(calls, ['Я'])
        self.assertIn((255, 0, 0), [color for _, color in panel.image.getcolors()])


class RealSceneTextTest(unittest.TestCase):
    def test_diagnostic_real_game_still_uses_legacy_rendering(self):
        with patch.object(font, 'draw', side_effect=AssertionError('native font in 1:1')):
            actual, report = emulate(({}, _touch(205, 160)) + _idle(4),
                                     initial_pet='capi', initial_mode='explore',
                                     screen_mode=v1.SCALE_NATIVE)
        self.assertEqual(report['mode'], 'explore')
        self.assertIsNotNone(actual.getbbox())

    def test_capi_egg_and_explore_labels_change_actual_panel_pixels(self):
        for mode, inputs, overrides, label, stage in (
            ('pet', ({}, _touch(48, 259)) + _idle(4), {'idade_min': 0}, 'Я в яйце!', 'ovo'),
            ('explore', ({}, _touch(205, 160)) + _idle(4), {}, 'Поле 1', 'adulto'),
        ):
            with self.subTest(mode=mode):
                kwargs = dict(initial_pet='capi', initial_mode=mode, fixture_state=overrides,
                              screen_mode=v1.SCALE_LARGE)
                frames = []
                original_draw = font.draw
                original_show = v1.Tela.mostrar

                def show(tela):
                    frames.append([])
                    return original_show(tela)

                def record(surface, text, x, y, color, esc=1):
                    frames[-1].append((text, x, y, esc))
                    return original_draw(surface, text, x, y, color, esc)

                with patch.object(v1.Tela, 'mostrar', show), patch.object(font, 'draw', record):
                    actual, report = emulate(inputs, **kwargs)
                self.assertEqual((report['pet'], report['mode'], report['life_stage']),
                                 ('capi', mode, stage))
                self.assertFalse(report['menu_opened'])
                if mode == 'pet':
                    self.assertIn(label, report['speech'].split('|'))
                self.assertEqual(len(frames), report['frames'])
                labels = [(x, y, esc) for text, x, y, esc in frames[-1] if text == label]
                self.assertTrue(labels, frames[-1])

                def without_label(surface, text, *args):
                    if text != label:
                        return original_draw(surface, text, *args)

                with patch.object(font, 'draw', without_label):
                    without, control = emulate(inputs, **kwargs)
                self.assertEqual(control['speech'], report['speech'])
                self.assertEqual(control['native_display_windows'], report['native_display_windows'])
                changed = ImageChops.difference(actual, without).getbbox()
                self.assertIsNotNone(changed, f'{label!r} must be visible on transmitted pixels')
                view = v1.VIEWPORT_LARGE
                left = min(x + view.x - font._X_PAD for x, _, _ in labels)
                top = min(y + view.y for _, y, _ in labels)
                right = max(x + view.x + font.measure(label, esc) + font._X_PAD
                            for x, _, esc in labels)
                bottom = max(y + view.y + font.height(esc) for _, y, esc in labels)
                self.assertTrue(left <= changed[0] < changed[2] <= right and
                                top <= changed[1] < changed[3] <= bottom, changed)


if __name__ == '__main__':
    unittest.main()
