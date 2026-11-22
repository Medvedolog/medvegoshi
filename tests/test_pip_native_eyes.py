"""Bounded RGB565 native Pip eyes, tested as original compiled C and Python glue."""
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from zoo.pip import eyes, face

ROOT = Path(__file__).resolve().parents[1]


class NativePipEyesTest(unittest.TestCase):
    def test_original_c_rasterizer_clip_key_and_byte_order(self):
        source = ROOT / "ports/pip_native"
        upstream = ROOT / "zoo/upstream/pip/ui"
        with tempfile.TemporaryDirectory() as temp:
            executable = str(Path(temp) / "eyes")
            subprocess.run(shlex.split(os.getenv("CC", "cc")) + [
                "-std=c11", "-Wall", "-Wextra", "-Werror", "-I", str(upstream),
                str(source / "eyes_host_test.c"), str(source / "eyes_tile.c"),
                str(upstream / "face.c"), "-lm", "-o", executable],
                check=True, timeout=30)
            subprocess.run([executable], check=True, timeout=10)

    def test_same_pose_reuses_cache_and_stays_in_its_own_tile(self):
        calls = []
        native = SimpleNamespace(eyes_draw_into=lambda *args: calls.append(args))
        module = SimpleNamespace(FrameBuffer=lambda data, w, h, fmt: (id(data), w, h, fmt), RGB565=1)
        c = eyes.Eyes(native, module)
        neutral = eyes.pose_for("normal", "neutral", 0)
        closed = eyes.pose_for("fechados", "asleep", 0)
        tile = c.prepare(60, 36, neutral)
        self.assertEqual(c.prepare(60, 36, neutral), tile)
        self.assertEqual(c.prepare(60, 36, closed), tile)
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(calls[0][0]), 60 * 36 * 2)
        self.assertEqual(calls[1][3][2:4], (1., 1.))
        self.assertIsNone(c.prepare(85, 36, neutral))
        screen = SimpleNamespace(blit=lambda *_: None)
        with patch.object(eyes, "_TRIED", True), patch.object(eyes, "_CACHE", c):
            self.assertIsNone(eyes.try_tile(screen, 205, 30, 60, 36, "normal", "neutral", 0))

    def test_lightweight_face_keeps_body_when_native_eyes_replace_only_eyes(self):
        legacy, native = [], []
        def ellipse(target):
            return lambda *a: target.append(a)
        rect = lambda *_: None
        self.assertEqual(face.render(ellipse(legacy), rect),
                         face.render(ellipse(native), rect, draw_eyes=False))
        self.assertGreater(len(legacy), len(native))
        self.assertEqual(legacy[:5], native[:5])
        self.assertTrue(all(t[4] != face.EYE for t in native))
