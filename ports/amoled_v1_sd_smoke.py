"""Explicit read-only microSD check for Waveshare AMOLED 1.8 V1."""
from ports.amoled_v1 import validate_v1_bus


def probe(i2c, *, enabled=False, confirmed_v1=False, machine_module=None):
    """Read the card geometry and its first block. No mount, format or write."""
    if enabled is not True or confirmed_v1 is not True:
        raise ValueError("explicit V1 confirmation and opt-in required")
    validate_v1_bus(i2c)
    if machine_module is None:
        import machine as machine_module
    # First-party Arduino V1 pin_config.h / 14_LVGL_SD_Test; native SDMMC.
    card = machine_module.SDCard(slot=1, width=1, sck=2, cmd=1, data=(3,),
                                freq=10_000_000)
    try:
        blocks, size = card.ioctl(4, 0), card.ioctl(5, 0)
        if type(blocks) is not int or blocks <= 0 or size != 512:
            raise OSError("unexpected SD card geometry")
        if card.readblocks(0, bytearray(size)) is not True:
            raise OSError("SD sector zero could not be read")
        return {"blocks": blocks, "block_bytes": size, "bytes": blocks * size}
    finally:
        card.deinit()
