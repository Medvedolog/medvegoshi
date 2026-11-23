"""Pin and minimally repair the upstream MicroPython AMOLED C build.

Host-only. Clones are fetched by build_amoled_v1.sh, which calls prepare().
No flashing, no bundled borrowed C sources. Keep the upstream LICENSE intact.
"""
import hashlib
from pathlib import Path

MICROPYTHON_SHA = "e0e9fbb17ed6fd06bb76e266ae554784c9c80804"
DRIVER_SHA = "97934b7c35b1720a14fd69e4e1322bb5684b9b2c"
MICROPYTHON_TAG = "v1.28.0"
IDF_TAG = "v5.5.2"
BOARD = "ESP32_GENERIC_S3"
VARIANT = "SPIRAM_OCT"
# Based on MIT-licensed upstream 16MiB partition layout.
PARTITIONS = (
    "# Name,   Type, SubType, Offset,  Size, Flags\n"
    "nvs,      data, nvs,     0x9000,  0x6000,\n"
    "phy_init, data, phy,    0xf000,  0x1000,\n"
    "factory,  app,  factory, 0x10000, 0x1F0000,\n"
    "vfs,      data, fat,    0x200000, 0xE00000,\n"
)


def _ensure(path, marker):
    if marker not in path.read_text():
        raise ValueError("unexpected pinned upstream layout: " + str(path))


def _checked_qspi_source(source):
    # dobodu holds CS low across RAMWR and every color chunk. A failed
    # transfer must release CS before MicroPython unwinds, not continue with
    # later chunks. The successful command/payload format is unchanged.
    helper = """static void qspi_check_result(amoled_qspi_bus_obj_t *panel, esp_err_t result)
{
    if (result != ESP_OK) {
        mp_hal_pin_od_high(panel->cs_pin);
        mp_raise_msg_varg(&mp_type_OSError, MP_ERROR_TEXT("%d(spi_device_polling_transmit)"), result);
    }
}

"""
    marker = "\nstatic void hal_lcd_qspi_panel_tx_param("
    replacements = [(marker, "\n" + helper + marker[1:])]
    for indent, transaction in (("    ", "&t"),
                                ("    ", "(spi_transaction_t *)&t"),
                                ("        ", "(spi_transaction_t *)&t")):
        call = "spi_device_polling_transmit(spi_obj->spi, " + transaction + ")"
        replacements.append((
            "\n" + indent + call + ";\n",
            "\n" + indent + "qspi_check_result(qspi_panel_obj, " + call + ");\n",
        ))
    for original, patched in replacements:
        if source.count(original) != 1:
            raise ValueError("unexpected pinned QSPI transfer source; re-review upstream")
        source = source.replace(original, patched, 1)
    return source


def prepare(micropython, driver):
    micropython, driver = Path(micropython), Path(driver)
    board_dir = micropython / "ports/esp32/boards/ESP32_GENERIC_S3"
    config = board_dir / "sdkconfig.board"
    board_cmake = board_dir / "mpconfigboard.cmake"
    module = driver / "amoled/micropython.cmake"
    root_cmake = driver / "micropython.cmake"
    license_file = driver / "LICENSE"
    for file in (config, board_cmake, module, root_cmake, license_file):
        if not file.is_file():
            raise ValueError("missing pinned source file: " + str(file))
    _ensure(board_cmake, "IDF_TARGET esp32s3")
    _ensure(root_cmake, "amoled/micropython.cmake")
    _ensure(config, "CONFIG_ESPTOOLPY_FLASHMODE_QIO=y")
    _ensure(module, "amoled_qspi_bus.c")
    _ensure(module, "usermod_amoled")
    if "MIT License" not in license_file.read_text():
        raise ValueError("upstream driver license changed: manual review required")
    source_files = (
        "amoled.c", "amoled_qspi_bus.c", "mpfile/mpfile.c",
        "jpg/tjpgd565.c", "schrift/schrift.c",
    )
    for src in source_files:
        if not (driver / "amoled" / src).is_file():
            raise ValueError("missing upstream C dependency: " + src)

    # Pinned upstream file contains pasted line numbers before CMake commands.
    # Fail if upstream changes, rather than silently patching arbitrary code.
    orig = module.read_text()
    if "5 add_library" not in orig or "21 # Link" not in orig:
        raise ValueError("CMake recipe changed; re-review upstream manually")
    qspi = driver / "amoled/amoled_qspi_bus.c"
    # Preserve the source checkout's line endings (the pinned blob uses CRLF).
    qspi_original = qspi.read_bytes()
    qspi_source = _checked_qspi_source(qspi_original.decode("utf-8").replace("\r\n", "\n"))
    if b"\r\n" in qspi_original:
        qspi_source = qspi_source.replace("\n", "\r\n")
    qspi_bytes = qspi_source.encode("utf-8")
    cmake = (
        "add_library(usermod_amoled INTERFACE)\n"
        "target_sources(usermod_amoled INTERFACE\n"
        + "".join("  ${CMAKE_CURRENT_LIST_DIR}/" + s + "\n" for s in source_files)
        + ")\n"
        "target_include_directories(usermod_amoled INTERFACE\n"
        "  ${IDF_PATH}/components/esp_lcd/include\n"
        "  ${CMAKE_CURRENT_LIST_DIR}\n"
        ")\n"
        "target_link_libraries(usermod INTERFACE usermod_amoled)\n"
    )
    partitions = micropython / "ports/esp32/partitions-16MiB.csv"
    if partitions.exists() and partitions.read_text() != PARTITIONS:
        raise ValueError("refusing to replace existing partitions")
    module.write_text(cmake)
    qspi.write_bytes(qspi_bytes)
    current = config.read_text()
    if "CONFIG_ESPTOOLPY_FLASHSIZE_16MB=y" not in current:
        config.write_text(current.rstrip() +
                          "\nCONFIG_ESPTOOLPY_FLASHSIZE_16MB=y\n"
                          "CONFIG_PARTITION_TABLE_CUSTOM=y\n"
                          'CONFIG_PARTITION_TABLE_CUSTOM_FILENAME="partitions-16MiB.csv"\n')
    partitions.write_text(PARTITIONS)
    return {
        "upstream": DRIVER_SHA, "micropython": MICROPYTHON_SHA,
        "board": BOARD, "variant": VARIANT,
        "cmake_sha256": hashlib.sha256(cmake.encode()).hexdigest(),
        "qspi_sha256": hashlib.sha256(qspi_bytes).hexdigest(),
        "partition_sha256": hashlib.sha256(PARTITIONS.encode()).hexdigest(),
    }


if __name__ == "__main__":
    import json
    import sys
    if len(sys.argv) != 3:
        raise SystemExit("usage: python prepare_firmware.py MICRO_PY_REPO NATIVE_DRIVER_REPO")
    print(json.dumps(prepare(sys.argv[1], sys.argv[2]), sort_keys=True))
