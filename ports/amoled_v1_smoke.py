"""Opt-in V1 smoke test only. NOT executed by MedveGoshi main.py.

Requires manually selected, compatible native-MicroPython firmware with
amoled.QSPIPanel/AMOLED. Checks V1 I2C addresses before any display writes.
Safe intent: no flash erases, no reads/writes to config.json/capi.json/brain.
Use in an interactive MicroPython REPL only after identifying physical V1.
"""
import time
from ports import amoled_v1


def rgb565_swapped(r, g, b):
    word = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
    return ((word & 0xFF) << 8) | (word >> 8)


def run(i2c=None, confirmed_v1=False):
    if not confirmed_v1:
        raise RuntimeError("Check the board's physical V1 label first; call run(confirmed_v1=True)")
    from machine import Pin, I2C
    if i2c is None:
        i2c = I2C(0, scl=Pin(amoled_v1.I2C_SCL),
                  sda=Pin(amoled_v1.I2C_SDA), freq=400000)
    print("Detecting original Waveshare 1.8 V1 (SH8601/FT3168)...")
    print("I2C:", [hex(x) for x in sorted(i2c.scan())])
    screen, touch = amoled_v1.prepare_v1(i2c, verified_v1=True)
    fb = screen.fb
    colors = ((255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 255))
    for i, rgb in enumerate(colors):
        fb.fill_rect(i * 60, 0, 60, 284, rgb565_swapped(*rgb))
    fb.rect(0, 0, 240, 284, rgb565_swapped(255, 255, 255))
    fb.text("V1 / SH8601", 24, 132, rgb565_swapped(0, 0, 0))
    screen.mostrar()
    print("Colour bars in 240x284 centred viewport; display physical 368x448")
    print("Touch the coloured rectangle within 5 seconds:")
    start = time.ticks_ms()
    readings = []
    while time.ticks_diff(time.ticks_ms(), start) < 5000:
        point = touch.ler()
        if point is not None:
            if not readings or point != readings[-1]:
                readings.append(point)
                print("Game touch:", point)
        time.sleep_ms(40)
    print("Touch samples:", len(readings))
    print("Rendering original MedveGoshi Жирафик through shared desenho.py...")
    from ports.v1_game_demo import show_giraffe
    show_giraffe(screen)
    print("Hardware results are provisional: preserve raw log and photo.")
    return {"touch_samples": len(readings),
            "viewport": (amoled_v1.OFFSET_X, amoled_v1.OFFSET_Y,
                         amoled_v1.LOGICAL_W, amoled_v1.LOGICAL_H)}
