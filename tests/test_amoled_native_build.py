"""Pinned native QSPI source prep tests; no downloads, firmware or hardware."""
import hashlib
from pathlib import Path
import tempfile
import unittest

from ports import prepare_firmware as build
from ports.v1_game_demo import show_giraffe


QSPI_TRANSFER_FIXTURE = """/* Unrelated source */
static void hal_lcd_qspi_panel_tx_param(void) {
    mp_hal_pin_od_low(qspi_panel_obj->cs_pin);
    spi_device_polling_transmit(spi_obj->spi, &t);
    mp_hal_pin_od_high(qspi_panel_obj->cs_pin);
}
static void hal_lcd_qspi_panel_tx_color(void) {
    mp_hal_pin_od_low(qspi_panel_obj->cs_pin);
    spi_device_polling_transmit(spi_obj->spi, (spi_transaction_t *)&t);
    do {
        spi_device_polling_transmit(spi_obj->spi, (spi_transaction_t *)&t);
    } while (len > 0);
    mp_hal_pin_od_high(qspi_panel_obj->cs_pin);
}
"""


class FirmwarePreparationTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.mp = self.root / "micropython"
        self.driver = self.root / "upstream"
        board = self.mp / "ports/esp32/boards/ESP32_GENERIC_S3"
        board.mkdir(parents=True)
        (board / "mpconfigboard.cmake").write_text("set(IDF_TARGET esp32s3)\n")
        (board / "sdkconfig.board").write_text(
            "CONFIG_ESPTOOLPY_FLASHMODE_QIO=y\n")
        module = self.driver / "amoled"
        (module / "jpg").mkdir(parents=True)
        (module / "mpfile").mkdir()
        (module / "schrift").mkdir()
        (self.driver / "micropython.cmake").write_text(
            "include(${CMAKE_CURRENT_LIST_DIR}/amoled/micropython.cmake)\n")
        (self.driver / "LICENSE").write_text("MIT License\n")
        (module / "micropython.cmake").write_text(
            " 5 add_library(usermod_amoled INTERFACE)\n"
            " 10 ${CMAKE_CURRENT_LIST_DIR}/amoled_qspi_bus.c\n"
            " 21 # Link the interface library\n")
        for src in ("amoled.c", "amoled_qspi_bus.c", "jpg/tjpgd565.c",
                    "mpfile/mpfile.c", "schrift/schrift.c"):
            (module / src).write_text("/* test stub */\n")
        self.qspi = module / "amoled_qspi_bus.c"
        self.qspi.write_bytes(QSPI_TRANSFER_FIXTURE.replace("\n", "\r\n").encode())

    def test_exact_pinned_sources_and_safe_cmake(self):
        self.assertEqual(len(build.MICROPYTHON_SHA), 40)
        self.assertEqual(len(build.DRIVER_SHA), 40)
        self.assertEqual(build.IDF_TAG, "v5.5.2")
        d = build.prepare(self.mp, self.driver)
        self.assertEqual(d["board"], "ESP32_GENERIC_S3")
        self.assertEqual(d["variant"], "SPIRAM_OCT")
        cmake = (self.driver / "amoled/micropython.cmake").read_text()
        self.assertTrue(cmake.startswith("add_library("))
        self.assertIn("${CMAKE_CURRENT_LIST_DIR}/schrift/schrift.c", cmake)
        self.assertIn("${IDF_PATH}/components/esp_lcd/include", cmake)
        self.assertEqual(cmake.count("target_sources("), 1)
        partitions = self.mp / "ports/esp32/partitions-16MiB.csv"
        self.assertEqual(partitions.read_text(), build.PARTITIONS)
        self.assertIn("0xE00000", partitions.read_text())
        cfg = (self.mp / "ports/esp32/boards/ESP32_GENERIC_S3/sdkconfig.board").read_text()
        self.assertIn("CONFIG_ESPTOOLPY_FLASHSIZE_16MB=y", cfg)
        self.assertIn("CONFIG_PARTITION_TABLE_CUSTOM=y", cfg)
        self.assertEqual((self.driver / "LICENSE").read_text(), "MIT License\n")
        self.assertEqual(d["qspi_sha256"], hashlib.sha256(self.qspi.read_bytes()).hexdigest())

    def test_checked_qspi_covers_param_ramwr_and_payload(self):
        build.prepare(self.mp, self.driver)
        prepared = self.qspi.read_text()
        self.assertEqual(prepared.count("qspi_check_result(qspi_panel_obj, spi_device_polling_transmit("), 3)
        self.assertIn("    qspi_check_result(qspi_panel_obj, spi_device_polling_transmit(spi_obj->spi, &t));", prepared)
        self.assertIn("        qspi_check_result(qspi_panel_obj, spi_device_polling_transmit(", prepared)
        self.assertNotIn("\n    spi_device_polling_transmit(", prepared)
        self.assertNotIn("\n        spi_device_polling_transmit(", prepared)
        self.assertNotIn(b"\n", self.qspi.read_bytes().replace(b"\r\n", b""))
        helper = prepared.split("static void hal_lcd_qspi_panel_tx_param(", 1)[0]
        self.assertIn("if (result != ESP_OK)", helper)
        self.assertLess(helper.index("mp_hal_pin_od_high("), helper.index("mp_raise_msg_varg("))
        self.assertIn("&mp_type_OSError", helper)

    def test_refuse_qspi_transfer_drift_before_writes(self):
        original = self.qspi.read_bytes()
        modified = original.replace(b"spi_device_polling_transmit", b"spi_device_transmit", 1)
        self.qspi.write_bytes(modified)
        cmake = self.driver / "amoled/micropython.cmake"
        expected_cmake = cmake.read_bytes()
        with self.assertRaisesRegex(ValueError, "unexpected pinned QSPI transfer source"):
            build.prepare(self.mp, self.driver)
        self.assertEqual(self.qspi.read_bytes(), modified)
        self.assertEqual(cmake.read_bytes(), expected_cmake)

    def test_refuse_unknown_amoled_upstream(self):
        path = self.driver / "amoled/micropython.cmake"
        path.write_text("add_library(usermod_amoled INTERFACE)\n")
        with self.assertRaises(ValueError):
            build.prepare(self.mp, self.driver)

    def test_refuse_overwrite_existing_partition_file(self):
        part = self.mp / "ports/esp32/partitions-16MiB.csv"
        part.write_text("do not overwrite another partition layout")
        with self.assertRaisesRegex(ValueError, "refusing"):
            build.prepare(self.mp, self.driver)

    def test_refuse_missing_borrowed_license(self):
        (self.driver / "LICENSE").write_text("unknown")
        with self.assertRaisesRegex(ValueError, "license changed"):
            build.prepare(self.mp, self.driver)

    def test_build_script_does_not_flash(self):
        script = (Path(__file__).resolve().parents[1] /
                  "ports/build_amoled_v1.sh").read_text()
        self.assertIn("MICROPYTHON_SHA="+build.MICROPYTHON_SHA, script)
        self.assertIn("AMOLED_SHA="+build.DRIVER_SHA, script)
        self.assertIn("USER_C_MODULES=", script)
        self.assertNotIn("erase_flash", script)
        self.assertNotIn("write_flash", script)
        self.assertNotIn("idf.py flash", script)
        self.assertIn("BUILT_NOT_HARDWARE_TESTED", script)
        self.assertIn("sha256sum", script)


class FakeScreen:
    def __init__(self):
        self.fb = type("FB", (), {"fill": lambda self, c: None})()
        self.frames = 0
    def mostrar(self):
        self.frames += 1


class SharedDrawingSpy:
    CREME = (255, 247, 232)
    INK = (40, 30, 40)
    TEXTO = (58, 42, 16)
    def __init__(self):
        self.commands = []
    def usar(self, fb):
        self.commands.append(("usar", fb))
    def C(self, color):
        return color
    def centro(self, *args):
        self.commands.append(("centro", args))
    def personagem(self, *args, **kwargs):
        self.commands.append(("personagem", args, kwargs))


class SharedGameBridgeTests(unittest.TestCase):
    def test_same_character_artist_can_render_on_amoled_screen(self):
        screen = FakeScreen()
        artist = SharedDrawingSpy()
        show_giraffe(screen, art=artist)
        self.assertEqual(screen.frames, 1)
        names = [x[0] for x in artist.commands]
        self.assertEqual(names.count("personagem"), 1)
        self.assertEqual(names.count("usar"), 1)
        pet = next(x for x in artist.commands if x[0] == "personagem")
        self.assertEqual(pet[1][:3], ("girafa", 120, 218))
        self.assertEqual(pet[2]["fase"], "adulto")


if __name__ == "__main__":
    unittest.main()
