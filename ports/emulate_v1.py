"""Host-only AMOLED V1 contract simulator. Does not run ESP32/MicroPython."""
import argparse
import json
import struct
import sys
from pathlib import Path
from types import SimpleNamespace

from PIL import Image, ImageDraw, ImageFont
from ports import amoled_v1 as port
from ports import v1_bringup

RGB565, MONO_HLSB = 1, 2


def decode(word):
    return (((word >> 11) & 31) * 255 // 31,
            ((word >> 5) & 63) * 255 // 63, (word & 31) * 255 // 31)


def image_from_wire(data, size):
    rgb = bytearray()
    for (word,) in struct.iter_unpack(">H", data):
        rgb.extend(decode(word))
    return Image.frombytes("RGB", size, bytes(rgb))


class FrameBuffer:
    def __init__(self, buf, width, height, fmt):
        self.buf, self.fmt = buf, fmt
        self.image = Image.new("RGB" if fmt == RGB565 else "1", (width, height))
        self.draw = ImageDraw.Draw(self.image)

    def color(self, c):
        if self.fmt == MONO_HLSB:
            return 1 if c else 0
        return decode(((c & 255) << 8) | (c >> 8))

    def flush(self):
        if self.fmt == RGB565:
            pixels = getattr(self.image, "get_flattened_data", self.image.getdata)
            for i, (r, g, b) in enumerate(pixels()):
                struct.pack_into(">H", self.buf, i * 2,
                                 (r >> 3) << 11 | (g >> 2) << 5 | (b >> 3))

    def fill(self, c):
        self.image.paste(self.color(c), (0, 0, *self.image.size))

    def pixel(self, x, y, c=None):
        if not (0 <= x < self.image.width and 0 <= y < self.image.height):
            return None
        if c is None:
            return self.image.getpixel((x, y))
        self.draw.point((x, y), fill=self.color(c))

    def rect(self, x, y, w, h, c, fill=False):
        if w > 0 and h > 0:
            col = self.color(c)
            self.draw.rectangle((x, y, x + w - 1, y + h - 1),
                                outline=col, fill=col if fill else None)

    def fill_rect(self, x, y, w, h, c):
        self.rect(x, y, w, h, c, True)

    def line(self, x, y, x1, y1, c):
        self.draw.line((x, y, x1, y1), fill=self.color(c))

    def hline(self, x, y, w, c):
        self.fill_rect(x, y, w, 1, c)

    def vline(self, x, y, h, c):
        self.fill_rect(x, y, 1, h, c)

    def ellipse(self, x, y, rx, ry, c, fill=False, mask=15):
        shape = Image.new("1", (rx * 2 + 1, ry * 2 + 1))
        draw = ImageDraw.Draw(shape)
        draw.ellipse((0, 0, rx * 2, ry * 2), outline=1, fill=1 if fill else None)
        if not (mask & 3):
            draw.rectangle((0, 0, rx * 2, ry - 1), fill=0)
        if not (mask & 12):
            draw.rectangle((0, ry + 1, rx * 2, ry * 2), fill=0)
        self.image.paste(self.color(c), (x - rx, y - ry, x + rx + 1, y + ry + 1), shape)

    def poly(self, x, y, coords, c, fill=False):
        points = [(x + px, y + py) for px, py in zip(coords[::2], coords[1::2])]
        if len(points) >= 3:
            col = self.color(c)
            self.draw.polygon(points, outline=col, fill=col if fill else None)

    def text(self, text, x, y, c):
        for i, ch in enumerate(text):
            self.draw.text((x + 8 * i, y - 1), ch, font=ImageFont.load_default(),
                           fill=self.color(c))


class Panel:
    def __init__(self, **params):
        self.image = Image.new("RGB", (params["width"], params["height"]))
        self.window = {}
        self.transfers = []

    def tx_param(self, command, data):
        if command not in (0x2A, 0x2B):
            raise AssertionError("unexpected simulated QSPI command")
        self.window[command] = struct.unpack(">HH", data)

    def tx_color(self, command, data):
        assert command == 0
        (x0, x1), (y0, y1) = self.window[0x2A], self.window[0x2B]
        w, h = x1 - x0 + 1, y1 - y0 + 1
        if not (0 <= x0 <= x1 < self.image.width and 0 <= y0 <= y1 < self.image.height):
            raise AssertionError("invalid panel window")
        if len(data) != w * h * 2:
            raise AssertionError("panel window/payload mismatch")
        self.image.paste(image_from_wire(data, (w, h)), (x0, y0))
        self.transfers.append((x0, y0, x1, y1, len(data)))
        self.window.clear()


class AMOLED:
    def __init__(self, panel, **kwargs):
        self.panel = panel

    def brightness(self, value):
        if not 0 <= value <= 255:
            raise AssertionError("native brightness range")

    def reset(self):
        pass

    def init(self):
        pass

    def fill(self, value):
        if value != 0:
            raise AssertionError("unexpected full panel fill")
        self.panel.image.paste((0, 0, 0), (0, 0, *self.panel.image.size))

    def refresh(self):
        if self.panel.transfers:
            raise AssertionError("full native refresh after direct frame")


# Physical panel coordinates, including a deliberate hit in the black margin.
SCRIPT = ({}, {"touch": (10, 20)}, {}, {"touch": (184, 230)},
          {"touch": (185, 231)}, {}, {"boot": 1}, {"boot": 1}, {},
          {"power": 1}, {}, {})


class Rig:
    def __init__(self, inputs=SCRIPT, revision="v1"):
        self.inputs, self.revision, self.frame = inputs, revision, 0
        self.expander = {1: 0xFF, 3: 0xFF}
        self.power = 0
        self.writes = []
        self.panel = None

    def event(self):
        return self.inputs[self.frame] if self.frame < len(self.inputs) else {}

    def sleep_ms(self, _duration):
        self.frame += 1
        self.power |= 8 if self.event().get("power") else 0

    def scan(self):
        return [0x20, 0x34, 0x38 if self.revision == "v1" else 0x15]

    def readfrom_mem(self, address, register, size):
        if address == 0x20 and size == 1:
            return bytes((self.expander[register],))
        if address == 0x34 and size == 1:
            return bytes(({3: 0x4A, 0x41: 8, 0x49: self.power}[register],))
        if (address, register, size) == (0x38, 2, 5) and self.event().get("touch"):
            x, y = self.event()["touch"]
            return bytes((1, x >> 8, x & 255, y >> 8, y & 255))
        raise OSError("simulated I2C NACK")

    def writeto_mem(self, address, register, data):
        self.writes.append((address, register, bytes(data)))
        if (address, register) == (0x34, 0x49) and data == b"\x08":
            self.power &= ~8
        elif address == 0x20 and register in self.expander and len(data) == 1:
            self.expander[register] = data[0]
        else:
            raise AssertionError("unexpected I2C write")

    def machine(self):
        rig = self

        class Pin:
            OUT, IN, PULL_UP = 1, 0, 2

            def __init__(self, number, *_a, **_kw):
                allowed = (0, 4, 5, 6, 7, 11, 12, 14, 15, 21)
                if number not in allowed:
                    raise AssertionError("unexpected pin: %d" % number)
                self.number = number

            def value(self):
                field = {0: "boot", 21: "touch"}.get(self.number)
                return 0 if rig.event().get(field) else 1

        return SimpleNamespace(Pin=Pin, SPI=lambda *_a, **_kw: None,
                               PWM=object, I2S=object)

    def native_panel(self, **kwargs):
        self.panel = Panel(**kwargs)
        return self.panel


def emulate(inputs=SCRIPT, revision="v1", wifi=False):
    """Run the real V1 bridge + bringup using deterministic scripted stimuli."""
    rig = Rig(inputs, revision)
    machine = rig.machine()
    framebuf = SimpleNamespace(FrameBuffer=FrameBuffer, RGB565=RGB565,
                               MONO_HLSB=MONO_HLSB)
    native = SimpleNamespace(QSPIPanel=rig.native_panel, AMOLED=AMOLED)

    def prepare(bus, **kwargs):
        screen, touch = port.prepare_v1(
            bus, machine_module=machine, amoled_module=native,
            framebuffer_module=framebuf, verified_v1=kwargs["verified_v1"])
        output = screen.mostrar

        def flush():
            screen.fb.flush()
            output()

        screen.mostrar = flush
        return screen, touch

    # Scope the host shims to this call; do not replace hardware in imports
    # that survive the simulation. Use the real shared procedural renderer.
    names = ("machine", "framebuf", "hw", "desenho")
    originals = {name: sys.modules.get(name) for name in names}
    try:
        sys.modules.update(machine=machine, framebuf=framebuf)
        for name in ("hw", "desenho"):
            sys.modules.pop(name, None)
        result = v1_bringup.run(
            confirmed_v1=True, frames=len(inputs), i2c=rig,
            machine_module=machine, prepare=prepare, clock=rig,
            wifi_status=(lambda: "WIFI: SIMULATED") if wifi else None)
    finally:
        for name, module in originals.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module
    return rig, result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--wifi", action="store_true", help="fake Wi-Fi status")
    args = parser.parse_args()
    rig, result = emulate(wifi=args.wifi)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("xb") as f:
        rig.panel.image.save(f, format="PNG")
    print(json.dumps({"status": "HOST_ONLY", **result}, sort_keys=True))


if __name__ == "__main__":
    main()
