"""Proof that a thirteenth animal can be installed without core edits.

Constructs a synthetic third-party plugin in a temporary directory. No
MedveGoshi engine file is rewritten, no third-party art is used, and hardware
calls are mocked for the drawing integration test.
"""
import io
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from contextlib import redirect_stdout
import unittest

from zoo import registry
from zoo.tools.install_animal import check_source, install

ROOT = Path(__file__).resolve().parents[2]

FOX = {
    "schema": 1, "id": "testfox", "name_ru": "Лисёнок", "htop": 65,
    "head": -44, "top": -68, "half": 25,
    "eyes": [[-10, -52], [10, -52]], "thermometer": [26, -40],
    "ring": [90, 60, 35], "author": "Original synthetic test",
    "license": "MIT",
    "source_url": "https://example.org/original-test-character",
    "phrases": {
        "ocioso": ["Привет!", "Я тестовый|лисенок!"],
        "carinho": ["Ура!", "Погладь меня!"],
    },
}

FACE = '''def render(E, R, P, A, eyes="normal", mouth="sorriso", sick=False):
    E(0, -40, 25, 28, (238, 130, 65), True)
    E(-10, -52, 5, 5, (255, 255, 255))
    E(10, -52, 5, 5, (255, 255, 255))
    return ((-10, -52), (10, -52))
'''

# Import only in the child process to avoid leaking a mocked ESP32 framebuffer
# or patched package search path into any other Python tests.
BOOT_PROBE = r'''
import sys, types

fbmod = types.ModuleType("framebuf")
fbmod.MONO_HLSB, fbmod.RGB565 = 1, 2
class FB:
    def __init__(self):
        self.draws = 0
    def ellipse(self, *args): self.draws += 1
    def fill_rect(self, *args): self.draws += 1
    def pixel(self, *args): self.draws += 1
    def line(self, *args): self.draws += 1
    def poly(self, *args): self.draws += 1
    def rect(self, *args): self.draws += 1
    def text(self, *args): self.draws += 1
    def fill(self, *args): self.draws += 1
fbmod.FrameBuffer = FB
sys.modules["framebuf"] = fbmod

hw = types.ModuleType("hw")
hw.W, hw.H = 240, 284
hw.cor = lambda r, g, b: ((r & 31) << 11) | ((g & 63) << 5) | (b & 31)
sys.modules["hw"] = hw

from zoo import animals, registry
animals.__path__.append(sys.argv[1])
registry.refresh(sys.argv[1])
import desenho as art
import vida as life

assert len(art.ELENCO) == 11, art.ELENCO  # ten original + testfox
assert art.ELENCO[-1] == "testfox"
assert "testfox" in art.NOMES and "testfox" in life.NOMES
assert life.NOMES["testfox"] == "Лисёнок"
assert life.FRASES_CHAR["testfox"]["ocioso"][0] == "Привет!"
assert art.HTOP["testfox"] == life.HTOP["testfox"] == 65
assert "pip" not in art.ELENCO
assert "girafa" not in art.ELENCO
fb = FB()
art.usar(fb)
head, top, half = art.personagem("testfox", 110, 205)
assert fb.draws > 0 and top < head and half > 0, (fb.draws, head, top, half)
assert art.NOMES["cachorro"] == "Карамелька"
print("external animal imported and rendered without editing core")
'''


class PluginRegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.fox = self.root / "testfox"
        self.fox.mkdir()
        (self.fox / "manifest.json").write_text(
            json.dumps(FOX, ensure_ascii=False), encoding="utf-8")
        (self.fox / "__init__.py").write_text("", encoding="utf-8")
        (self.fox / "face.py").write_text(FACE, encoding="utf-8")

    def test_original_ten_ids_and_two_bundled_plugins(self):
        self.assertEqual(10, len(registry.BUILTINS))
        self.assertEqual(12, len(registry.ELENCO))
        self.assertEqual(("girafa", "pip"), registry.ELENCO[-2:])
        self.assertEqual("Жирафик", registry.NOMES["girafa"])
        self.assertEqual("Пип", registry.NOMES["pip"])
        self.assertEqual(125, registry.HTOP["girafa"])
        self.assertEqual(86, registry.HTOP["pip"])

    def test_metadata_discovery_and_shared_catalogue(self):
        data = registry.discover(str(self.root))
        self.assertEqual(["testfox"], sorted(data))
        cast, names, heights, phrases = registry.make_catalogue(data)
        self.assertEqual(11, len(cast))
        self.assertEqual("testfox", cast[-1])
        self.assertEqual("Лисёнок", names["testfox"])
        self.assertEqual(65, heights["testfox"])
        self.assertEqual(("Привет!", "Я тестовый|лисенок!"),
                         phrases["testfox"]["ocioso"])

    def test_external_plugin_executes_via_shared_engine(self):
        proc = subprocess.run(
            [sys.executable, "-c", BOOT_PROBE, str(self.root)],
            cwd=str(ROOT), capture_output=True, text=True, timeout=25)
        self.assertEqual(proc.returncode, 0, proc.stdout + "\n" + proc.stderr)

    def test_installer_dry_run_uses_manifest_last_and_no_erase(self):
        self.assertEqual("testfox", check_source(self.fox)[0])
        log = io.StringIO()
        with redirect_stdout(log):
            install(self.fox, "/dev/ttyACM0", dry_run=True)
        result = log.getvalue()
        self.assertIn("zoo/animals/testfox/face.py", result)
        self.assertLess(result.index("/face.py"), result.index("/manifest.json"))
        self.assertNotIn("erase", result)
        self.assertNotIn("write_flash", result)

    def test_invalid_plugins_are_skipped_not_published(self):
        bad = json.loads(json.dumps(FOX, ensure_ascii=False))
        bad["phrases"]["carinho"] = ["это слишком длинная реплика без переноса"]
        (self.fox / "manifest.json").write_text(
            json.dumps(bad, ensure_ascii=False), encoding="utf-8")
        self.assertNotIn("testfox", registry.discover(str(self.root)))
        with self.assertRaisesRegex(ValueError, "speech"):
            check_source(self.fox)

    def test_invalid_code_rejected_before_serial_transfer(self):
        (self.fox / "face.py").write_text("def render(:\n", encoding="utf-8")
        with self.assertRaises(SyntaxError):
            check_source(self.fox)

    def test_reserved_id_and_traversal_are_rejected(self):
        self.assertFalse(registry.safe_id("../escape"))
        self.assertFalse(registry.safe_id("Pip"))
        reserved = json.loads(json.dumps(FOX))
        reserved["id"] = "capi"
        with self.assertRaisesRegex(ValueError, "reserved"):
            registry.validate_manifest(reserved, "capi")

    def test_bundled_manifests_are_both_valid(self):
        for pet in ("pip", "girafa"):
            folder = ROOT / "zoo" / "animals" / pet
            with (folder / "manifest.json").open("r", encoding="utf-8") as fd:
                data = json.load(fd)
            self.assertIs(data, registry.validate_manifest(data, pet))
            self.assertTrue((folder / "face.py").is_file())
            self.assertTrue((folder / "__init__.py").is_file())

    def test_installer_rejects_amoled_and_never_changes_saves(self):
        with self.assertRaisesRegex(ValueError, "AMOLED"):
            install(self.fox, "/dev/ttyACM0", board="amoled-v1", dry_run=True)
        self.assertEqual(0, len(list(self.root.glob("*.json"))))

    def test_invalid_manifest_too_large(self):
        with (self.fox / "manifest.json").open("a", encoding="utf-8") as fd:
            fd.write(" " * 10000)
        self.assertEqual({}, registry.discover(str(self.root)))


if __name__ == "__main__":
    unittest.main()
