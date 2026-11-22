"""Zoo regression tests: inspired by the invariant-based MIT suites in
Pip-KeyPet, Giraffegotchi and TamaPetchi, but implemented for MedveGoshi.
All tests here run on CPython without a device or additional packages.
"""
from pathlib import Path
import unittest

import vida
from zoo import registry
from zoo.pip.face import render


ROOT = Path(__file__).resolve().parents[2]


class RecordingPrimitives:
    def __init__(self):
        self.ops = []

    def ellipse(self, x, y, rx, ry, color, outside=False):
        self.ops.append(("ellipse", x, y, rx, ry, color, outside))
        if rx <= 0 or ry <= 0:
            raise AssertionError("invalid ellipse radius")
        if not (-50 <= x <= 50 and -125 <= y <= 0):
            raise AssertionError("out-of-range relative drawing coordinate")

    def rect(self, x, y, w, h, color):
        self.ops.append(("rect", x, y, w, h, color))
        if w <= 0 or h <= 0:
            raise AssertionError("invalid rect size")


class PipFaceTests(unittest.TestCase):
    def test_render_all_eye_and_mouth_states(self):
        eye_states = ("normal", "feliz", "fechados", "sono", "susto",
                      "triste", "esquerda", "direita")
        mouth_states = ("sorriso", "aberta", "o", "triste", "dormindo")
        for eyes in eye_states:
            for mouth in mouth_states:
                for sick in (False, True):
                    with self.subTest(eyes=eyes, mouth=mouth, sick=sick):
                        p = RecordingPrimitives()
                        anchors = render(p.ellipse, p.rect, eyes, mouth, sick)
                        self.assertEqual(2, len(anchors))
                        self.assertGreater(len(p.ops), 5)
                        self.assertEqual(2, len([a for a in anchors if a[1] == -80]))

    def test_closed_eyes_have_fewer_shapes_than_open(self):
        a, b = RecordingPrimitives(), RecordingPrimitives()
        render(a.ellipse, a.rect, "normal")
        render(b.ellipse, b.rect, "fechados")
        self.assertGreater(len(a.ops), len(b.ops))

    def test_healthy_and_sick_render_differently(self):
        a, b = RecordingPrimitives(), RecordingPrimitives()
        render(a.ellipse, a.rect, sick=False)
        render(b.ellipse, b.rect, sick=True)
        self.assertNotEqual(a.ops, b.ops)

    def test_pip_pack_does_not_require_hardware(self):
        src = (ROOT / "zoo/pip/face.py").read_text(encoding="utf-8")
        self.assertNotIn("import machine", src)
        self.assertNotIn("import framebuf", src)
        self.assertNotIn("import network", src)


class CatalogueCompatibilityTests(unittest.TestCase):
    def test_pip_is_opt_in_and_original_cast_is_kept(self):
        cast = registry.ELENCO
        self.assertEqual(12, len(cast))
        self.assertEqual("pip", cast[-2])
        self.assertEqual("girafa", cast[-1])
        for original in ("capi", "pato", "elefante", "polvo", "calopsita",
                         "cachorro", "gato", "et", "sapinho", "naufrago"):
            self.assertIn(original, cast)
        self.assertIn("Пип", vida.NOMES.values())
        self.assertIn("Жирафик", vida.NOMES.values())

    def test_character_metadata_match_render_list(self):
        cast = top_constant("desenho.py", "ELENCO")
        art_names = registry.NOMES
        art_heights = registry.HTOP
        self.assertEqual(set(cast), set(art_names))
        self.assertEqual(set(cast), set(art_heights))
        self.assertEqual(set(cast), set(vida.HTOP))
        self.assertEqual(set(cast), set(vida.NOMES))

    def test_all_zoo_phrases_fit_ips_bubble(self):
        phrases = vida.FRASES_CHAR["pip"]
        for group in ("ocioso", "carinho"):
            self.assertTrue(phrases[group])
            for phrase in phrases[group]:
                self.assertLessEqual(len(phrase.split("|")), 2)
                self.assertTrue(all(len(part) <= 14 for part in phrase.split("|")))

    def test_pip_has_no_effect_on_existing_game_ids(self):
        self.assertEqual("Карамелька", vida.NOMES["cachorro"])
        self.assertEqual("Капи", vida.NOMES["capi"])
        self.assertTrue({"comemorar", "andar", "cochilar"} <= set(vida.MOVES))

    def test_runtime_pack_is_deployed_not_reference_tests(self):
        deploy = (ROOT / "deploy.sh").read_text(encoding="utf-8")
        self.assertIn("zoo/pip/face.py", deploy)
        self.assertNotIn("zoo/upstream", deploy)
        self.assertNotIn("zoo/tests", deploy)


class ReferenceSourcesTests(unittest.TestCase):
    def test_each_imported_suite_has_license(self):
        for name in ("pip", "giraffegotchi", "tamapetchi"):
            folder = ROOT / "zoo" / "upstream" / name
            self.assertTrue((folder / "LICENSE").is_file(), name)
            self.assertIn("MIT License", (folder / "LICENSE").read_text(), name)

    def test_reference_tests_are_available(self):
        paths = (
            "pip/sim/face_test.c", "pip/sim/maze_test.c",
            "pip/sim/pet_test.c", "giraffegotchi/test_pet.cpp",
            "giraffegotchi/test_sky.cpp", "tamapetchi/test_backup.cpp",
            "tamapetchi/test_day_night.cpp"
        )
        for path in paths:
            self.assertTrue((ROOT / "zoo/upstream" / path).is_file(), path)


if __name__ == "__main__":
    unittest.main()
