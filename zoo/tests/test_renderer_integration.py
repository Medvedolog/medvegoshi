"""Render the actual desenho.py character entrypoint without ESP32 hardware.

Uses a tiny host-only mock of framebuf and hw in a subprocess, so it cannot
alter other tests' module imports. Based on face drawing invariants in the
Pip-KeyPet MIT test suite.
"""
import subprocess
import sys
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]

PROBE = r'''
import sys, types

class FB:
    draws = 0
    def __init__(self, *args):
        self.width, self.height = 240, 284
    def ellipse(self, *args): self.draws += 1
    def fill_rect(self, *args): self.draws += 1
    def pixel(self, *args): self.draws += 1
    def line(self, *args): self.draws += 1
    def poly(self, *args): self.draws += 1
    def rect(self, *args): self.draws += 1
    def text(self, *args): self.draws += 1
    def fill(self, *args): self.draws += 1

framebuf = types.ModuleType("framebuf")
framebuf.FrameBuffer = FB
framebuf.MONO_HLSB = 1
framebuf.RGB565 = 2
sys.modules["framebuf"] = framebuf
hw = types.ModuleType("hw")
hw.W, hw.H = 240, 284
hw.cor = lambda r, g, b: ((r & 31) << 11) | ((g & 63) << 5) | (b & 31)
sys.modules["hw"] = hw

import desenho as d

for hero in d.ELENCO:
    for eyes, mouth, sick in (
        ("normal", "sorriso", False),
        ("fechados", "dormindo", False),
        ("susto", "o", False),
        ("triste", "triste", True),
    ):
        fb = FB()
        d.usar(fb)
        head, top, half = d.personagem(hero, 110, 205, eyes, mouth, sick)
        assert fb.draws > 0, (hero, "did not draw")
        assert half > 0 and top < head, (hero, head, top, half)
    print("ok", hero)
assert len(d.ELENCO) == 14
assert 'naufrago' not in d.ELENCO
'''


class FullRendererIntegration(unittest.TestCase):
    def test_all_characters_render_with_actual_dispatcher(self):
        proc = subprocess.run(
            [sys.executable, "-c", PROBE],
            cwd=str(ROOT), capture_output=True, text=True, timeout=25)
        self.assertEqual(proc.returncode, 0, proc.stdout + "\n" + proc.stderr)
        self.assertEqual(proc.stdout.count("ok "), 14)

    def test_existing_dispatcher_uses_sprite_then_falls_back(self):
        code = PROBE + r'''
seen = []
def simulated_sprite(fb, hero, cx, feet, scale, eyes, mouth, sick, **options):
    seen.append(hero)
    return (100, 50, 40, [(99, 82), (121, 82)])
d.zoo_sprites.draw = simulated_sprite
sprite_fb = FB()
d.usar(sprite_fb)
metrics = d.personagem("cachorro", 110, 205)
assert metrics == (100, 50, 40), metrics
assert seen == ["cachorro"], seen
assert sprite_fb.draws == 0, "the procedural renderer should be skipped"

d.zoo_sprites.draw = lambda *args, **kwargs: None
procedural_fb = FB()
d.usar(procedural_fb)
metrics = d.personagem("cachorro", 110, 205)
assert procedural_fb.draws > 0, "procedural fallback was not called"
assert metrics[2] > 0
'''
        proc = subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(ROOT), capture_output=True, text=True, timeout=25)
        self.assertEqual(proc.returncode, 0, proc.stdout + "\\n" + proc.stderr)


if __name__ == "__main__":
    unittest.main()
