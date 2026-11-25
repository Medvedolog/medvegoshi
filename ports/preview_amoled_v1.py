#!/usr/bin/env python3
"""Host-only pixel-accurate preview of V1's initial centered game viewport.

Conservatively copies the 240x284 IPS framebuffer without any scaling into
the 368x448 AMOLED frame. This is a layout preview, not an SH8601 emulator.
"""
import argparse
from pathlib import Path

from PIL import Image

from ports import amoled_v1


def render(source, destination):
    source = Path(source)
    destination = Path(destination)
    if source.resolve() == destination.resolve():
        raise ValueError("refuse to overwrite source image")
    with Image.open(source) as orig:
        if orig.size != (amoled_v1.LOGICAL_W, amoled_v1.LOGICAL_H):
            raise ValueError("expected input 240x284 RGB preview")
        image = Image.new("RGB", (amoled_v1.PANEL_W, amoled_v1.PANEL_H),
                          (0, 0, 0))
        image.paste(orig.convert("RGB"), (amoled_v1.OFFSET_X,
                                         amoled_v1.OFFSET_Y))
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise ValueError("refuse to overwrite existing destination")
    image.save(destination)
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    print(render(args.source, args.out))


if __name__ == "__main__":
    main()
