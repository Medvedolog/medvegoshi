#!/usr/bin/env python3
"""Build 8 ORIGINAL giraffe PNG poses from our procedural MedveGoshi drawing.

No sprites, images or animal designs are copied from Giraffegotchi. We reuse
the project's own MIT-licensed zoo/giraffe/face.py renderer, then feed the
result through the existing deterministic PNG -> RGB565 compiler.

Run from the repository root:
  python3 -m zoo.tools.generate_giraffe --source-out /tmp/giraffe-src \
      --pack-out /tmp/giraffe-ips
  python3 -m zoo.tools.preview_sprites --pack /tmp/giraffe-ips \
      --out /tmp/giraffe-preview.png --frame happy --board ips
"""
import argparse
import json
from pathlib import Path

try:
    from PIL import Image, ImageDraw
except ImportError as exc:
    raise SystemExit("Pillow is required on the host: pip install Pillow") from exc

from zoo.giraffe.face import render
from zoo.tools.build_sprites import compile_pack

# The first authored source file for Жирафик, not Giraffegotchi artwork.
SOURCE_COMMIT = "73788e25b273da5f6bf444c19ecee697781598dd"
SOURCE_URL = (
    "https://github.com/Medvedolog/medvegoshi/blob/"
    + SOURCE_COMMIT + "/zoo/giraffe/face.py"
)
SOURCE_SIZE = (160, 168)
SOURCE_ANCHOR = (80, 160)
SUPERSAMPLE = 3
# The names match the states consumed by zoo/sprites.py::_select().
POSES = {
    "normal": ("normal", "sorriso", False),
    "happy": ("feliz", "sorriso", False),
    "sad": ("triste", "triste", False),
    "sleeping": ("fechados", "dormindo", False),
    "sick": ("normal", "triste", True),
    "surprised": ("susto", "aberta", False),
    "eating": ("normal", "aberta", False),
    "blink": ("fechados", "sorriso", False),
}
OUTPUT_SIZE = (120, 144)


def pose_image(eyes, mouth, sick=False):
    """Draw using the same declarative geometric primitives as the IPS game."""
    k = SUPERSAMPLE
    w, h = SOURCE_SIZE
    ox, oy = SOURCE_ANCHOR
    image = Image.new("RGBA", (w * k, h * k), (0, 0, 0, 0))
    ctx = ImageDraw.Draw(image)

    def coords(cx, cy):
        return ((cx + ox) * k, (cy + oy) * k)

    def circle(x, y, rx, ry, fill, outline=False):
        cx, cy = coords(x, y)
        rx, ry = rx * k, ry * k
        if outline:
            border = tuple(max(0, int(z * 0.68)) for z in fill)
            ctx.ellipse((round(cx-rx-k), round(cy-ry-k),
                         round(cx+rx+k), round(cy+ry+k)), fill=border + (255,))
        ctx.ellipse((round(cx-rx), round(cy-ry),
                     round(cx+rx), round(cy+ry)), fill=tuple(fill)+(255,))

    def rectangle(x, y, width, height, fill):
        cx, cy = coords(x, y)
        ctx.rectangle((round(cx), round(cy),
                       round(cx + width * k - 1),
                       round(cy + height * k - 1)),
                      fill=tuple(fill)+(255,))

    def polygon(x, y, points, fill):
        cx, cy = coords(x, y)
        ctx.polygon([(round(cx+points[i]*k), round(cy+points[i+1]*k))
                     for i in range(0, len(points), 2)],
                    fill=tuple(fill)+(255,))

    def arc(x, y, rx, ry, fill, half, thickness=2):
        cx, cy = coords(x, y)
        # The game's upper-half arc is represented with PIL's upper half.
        start, end = (180, 360) if half == 1 else (0, 180)
        for i in range(thickness):
            dx, dy = (rx-i)*k, (ry-i)*k
            if dx <= 0 or dy <= 0:
                continue
            ctx.arc((round(cx-dx), round(cy-dy),
                     round(cx+dx), round(cy+dy)),
                    start, end, fill=tuple(fill)+(255,), width=k)

    render(circle, rectangle, polygon, arc, eyes, mouth, sick)
    # Single step of antialiasing, same bounding box for every expression.
    return image.resize(SOURCE_SIZE, Image.Resampling.LANCZOS)


def make_source(out):
    """Create the original PNG poses and a rights-checked metadata manifest.

    Refuse to overwrite existing user art. The builder operates only inside an
    explicitly empty output directory, so accidental deletion is impossible.
    """
    out = Path(out)
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise ValueError("source output must be an empty directory")
    out.mkdir(parents=True, exist_ok=True)
    metadata = {
        "id": "girafa",
        "name_ru": "Жирафик",
        "author": "MedveGoshi contributors (original procedural giraffe)",
        "license": "MIT",
        "source_url": SOURCE_URL,
        "source_commit": SOURCE_COMMIT,
        "rights_confirmed": True,
        "source_anchor": list(SOURCE_ANCHOR),
        "generator": "zoo/tools/generate_giraffe.py",
    }
    (out / "pack.json").write_text(
        json.dumps(metadata, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8")
    for name, args in POSES.items():
        pose_image(*args).save(out / (name + ".png"))
    return metadata


def build(source_out, pack_out, target="ips"):
    make_source(source_out)
    size = OUTPUT_SIZE if target == "ips" else (192, 224)
    return compile_pack(source_out, pack_out, size=size, target=target,
                        margin=4, fps=4, max_kib=768)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-out", required=True, type=Path)
    parser.add_argument("--pack-out", required=True, type=Path)
    parser.add_argument("--target", choices=("ips", "amoled-v1"), default="ips")
    args = parser.parse_args()
    meta = build(args.source_out, args.pack_out, args.target)
    print("Built %d original giraffe poses for %s (%d bytes)." % (
        len(meta["frames"]), args.target, meta["bytes"]))


if __name__ == "__main__":
    main()
