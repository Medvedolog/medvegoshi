#!/usr/bin/env python3
"""Show compiled Zoo RGB565+mask frames on a simulated IPS/AMOLED canvas.

This is an offline preview, not a firmware simulator. No sprites or bitmap
fonts from other projects are used.
"""
import argparse
import hashlib
import json
from pathlib import Path

try:
    from PIL import Image, ImageDraw
except ImportError as exc:
    raise SystemExit("Install Pillow on the host: python3 -m pip install Pillow") from exc

SIZES = {"ips": (240, 284), "amoled-v1": (368, 448)}


def decode_frame(pack, name):
    pack = Path(pack)
    meta = json.loads((pack / "manifest.json").read_text(encoding="utf-8"))
    width, height = meta["canvas"]
    frame = next((a for a in meta["frames"] if a["name"] == name), None)
    if frame is None:
        raise ValueError("unknown frame: " + name)
    for key, suffix in (("rgb565", ".rgb565"), ("mask", ".mask")):
        if frame[key] != name + suffix:
            raise ValueError("invalid or unsafe file name")
    raw = (pack / frame["rgb565"]).read_bytes()
    mask = (pack / frame["mask"]).read_bytes()
    if len(raw) != width * height * 2 or len(mask) != (width * height + 7) // 8:
        raise ValueError("wrong frame payload length")
    if hashlib.sha256(raw + mask).hexdigest() != frame["sha256"]:
        raise ValueError("sprite frame checksum failed")
    pixels = bytearray(width * height * 4)
    for i in range(width * height):
        if not (mask[i >> 3] & (0x80 >> (i & 7))):
            continue
        c = (raw[i * 2] << 8) | raw[i * 2 + 1]
        r, g, b = (c >> 11) & 31, (c >> 5) & 63, c & 31
        j = i * 4
        pixels[j:j + 4] = bytes((r * 255 // 31, g * 255 // 63, b * 255 // 31, 255))
    return Image.frombytes("RGBA", (width, height), bytes(pixels)), meta


def preview(pack, out, name="normal", board="ips", scale=None):
    if board not in SIZES:
        raise ValueError("invalid preview target")
    frame, meta = decode_frame(pack, name)
    w, h = SIZES[board]
    # Original game's centre and ground level on each display; AMOLED uses a
    # scaled physical preview, not an assumption that the real port works.
    if scale is None:
        scale = 0.74 if board == "ips" else 1.12
    anchor_x, anchor_y = meta["anchor"]
    target_x = w // 2
    target_y = int(h * 0.72)
    pw = max(1, round(frame.width * scale))
    ph = max(1, round(frame.height * scale))
    scaled = frame.resize((pw, ph), Image.Resampling.NEAREST)
    left = int(target_x - anchor_x * scale + 0.5)
    top = int(target_y - anchor_y * scale + 0.5)
    canvas = Image.new("RGBA", (w, h), (236, 246, 250, 255))
    d = ImageDraw.Draw(canvas)
    d.rectangle((0, int(h * 0.72), w, h), fill=(178, 222, 168, 255))
    d.line((0, target_y, w, target_y), fill=(93, 166, 90, 255), width=2)
    canvas.alpha_composite(scaled, (left, top))
    d.text((6, 6), "%s | %s | %s" % (meta["id"], board, name),
           fill=(40, 60, 75, 255))
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(out)
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--frame", default="normal")
    parser.add_argument("--board", choices=sorted(SIZES), default="ips")
    args = parser.parse_args()
    print(preview(args.pack, args.out, args.frame, args.board))


if __name__ == "__main__":
    main()
