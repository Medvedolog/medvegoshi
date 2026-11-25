"""Board-free visual QA: tests compiled resources and honest hardware status."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from PIL import Image

from zoo.tools.generate_giraffe import build
from zoo.tools.offline_qa import analyze, create_bundle, EXPECTED_GIRAFFE


class OfflineQATests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        cls.pack = cls.root / "ips"
        build(cls.root / "source", cls.pack)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_all_eight_expressions_and_explicit_hardware_status(self):
        result = analyze(self.pack, "ips")
        self.assertEqual(result["status"], "host_pass")
        self.assertEqual(result["hardware_status"], "NOT_TESTED")
        self.assertEqual(result["frame_count"], 8)
        self.assertEqual([x["name"] for x in result["frame_reports"]],
                         list(EXPECTED_GIRAFFE))
        self.assertEqual(len({x["sha256"] for x in result["frame_reports"]}), 8)
        self.assertEqual(result["board_pixels"], [240, 284])
        self.assertEqual(result["limits"]["framebuffer_bytes_theoretical"],
                         240 * 284 * 2)

    def test_creates_contact_sheet_and_readable_report(self):
        out = self.root / "qa-ips"
        result = create_bundle(self.pack, out, "ips")
        self.assertEqual(result, json.loads((out / "report.json").read_text()))
        self.assertEqual(8, len(list(out.glob("*.png")))-1)
        with Image.open(out / "all_expressions.png") as sheet:
            self.assertEqual(sheet.size, (4 * 240, 2 * (284 + 22)))
        report = (out / "report.md").read_text(encoding="utf-8")
        self.assertIn("НЕ ВЫПОЛНЕНА", report)
        self.assertIn("теоретические", report)
        self.assertIn("Жирафика", report)

    def test_damaged_pack_fails_before_producing_report(self):
        cloned = self.root / "damaged"
        shutil.copytree(self.pack, cloned)
        path = cloned / "normal.rgb565"
        corrupted = bytearray(path.read_bytes())
        corrupted[4] ^= 0x80
        path.write_bytes(corrupted)
        out = self.root / "should-not-exist"
        with self.assertRaisesRegex(ValueError, "checksum"):
            create_bundle(cloned, out, "ips")
        self.assertFalse(out.exists())

    def test_report_does_not_overwrite_other_files(self):
        out = self.root / "preexisting"
        out.mkdir()
        (out / "user-notes.txt").write_text("DO NOT DELETE")
        with self.assertRaisesRegex(ValueError, "overwrite"):
            create_bundle(self.pack, out, "ips")
        self.assertEqual((out / "user-notes.txt").read_text(), "DO NOT DELETE")

    def test_reject_wrong_board_target(self):
        with self.assertRaisesRegex(ValueError, "target mismatch"):
            analyze(self.pack, "amoled-v1")

    def test_amoled_is_only_an_image_preview_not_a_claim_of_hardware(self):
        src = self.root / "source-amoled"
        pack = self.root / "amoled"
        build(src, pack, target="amoled-v1")
        result = create_bundle(pack, self.root / "qa-amoled", "amoled-v1")
        self.assertEqual(result["board_pixels"], [368, 448])
        self.assertEqual(result["hardware_status"], "NOT_TESTED")
        with Image.open(self.root / "qa-amoled/all_expressions.png") as img:
            self.assertEqual(img.size, (4 * 368, 2 * (448 + 22)))


if __name__ == "__main__":
    unittest.main()
