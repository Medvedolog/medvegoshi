"""Verify Bjorni's generated sprite data and state priorities."""
from binascii import a2b_base64
from pathlib import Path
from unittest import TestCase

from zoo.animals.bjorni import face
from zoo.tools.build_bjorni_frames import H, W, compile_data

ROOT = Path(__file__).resolve().parents[2]


class BjorniFramesTest(TestCase):
    def test_generated_frame_bytes_match_original_source(self):
        module = (ROOT / 'zoo/animals/bjorni/face.py').read_text(encoding='utf-8')
        generated = compile_data(ROOT / 'zoo/assets/bjorni-poses.png')
        self.assertTrue(module.endswith(generated))
        self.assertEqual(len(face.FRAMES), 44)
        self.assertLess((ROOT / 'zoo/animals/bjorni/face.py').stat().st_size, 234 * 1024)
        self.assertEqual(len(set(face.FRAMES)), len(face.FRAMES))
        for frame in face.FRAMES:
            data = a2b_base64(frame)
            self.assertTrue(data and len(data) % 5 == 0)
            for x, y, w, h, c in zip(data[0::5], data[1::5], data[2::5], data[3::5], data[4::5]):
                self.assertTrue(0 <= x < x+w <= W and 0 <= y < y+h <= H and c < len(face.PALETTE))

    def test_readable_face_and_keyboard_colors_survive_compilation(self):
        colors = {face.PALETTE[i] for i in a2b_base64(face.FRAMES[0])[4::5]}
        self.assertTrue(any(r > 245 and g > 230 and b > 225 for r, g, b in colors))
        self.assertTrue(any(g >= 220 and r < 130 and b >= 130 for r, g, b in colors))
        self.assertTrue(any(r >= 245 and 175 < g < 234 and b < 190 for r, g, b in colors))
        self.assertTrue(any(r < 39 and g < 34 and b < 30 for r, g, b in colors))

    def test_game_poses_are_distinct(self):
        frame = face.select_frame
        self.assertEqual(frame('fechados', 'dormindo', True), 39)
        self.assertEqual(frame('sono', 'triste', True), 42)
        self.assertEqual(frame('susto', 'o', False, ('walk-left', 500)), 43)
        self.assertEqual(frame('sono', 'sorriso'), 38)
        self.assertEqual(frame('fechados', 'sorriso'), 37)
        self.assertEqual(frame('normal', 'triste', False, ('hungry', 0)), 40)
        self.assertEqual(frame('normal', 'aberta', False, ('eating', 0)), 41)
        self.assertNotEqual(frame('normal', 'meia', False, ('eating', 180)), 41)
        for action in ('walk-right', 'walk-left', 'typing', 'greeting', 'thinking'):
            self.assertNotEqual(frame('normal', 'sorriso', False, (action, 0)),
                                frame('normal', 'sorriso', False, (action, 280)), action)
        self.assertEqual(frame('normal', 'sorriso', False, ('jump', 0)), 12)
        self.assertEqual(frame('normal', 'sorriso', False, ('jump', 500)), 16)
        self.assertEqual(frame('normal', 'sorriso', False, ('jump', 900)), 16)

    def test_render_does_not_depend_on_files_or_game_state(self):
        operations = []
        rect = lambda *args: operations.append(args)
        eye = face.render(None, rect, None, None, motion=('typing', 140))
        self.assertEqual(eye, ((-17, -83), (17, -83)))
        self.assertGreater(len(operations), 200)
        self.assertLess(len(operations), 780)
