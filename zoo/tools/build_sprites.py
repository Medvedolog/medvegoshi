#!/usr/bin/env python3
"""Deterministic, host-only PNG -> RGB565 + 1-bit-alpha sprite compiler.

Inspired by the *workflow*, not copied code, of Giraffegotchi:
https://github.com/elliotboney/giraffegotchi (MIT).

Usage:
  python3 zoo/tools/build_sprites.py --source /path/to/own-art --out /tmp/pack \
      --size 96x112 --target ips
Requires Pillow on the DEVELOPMENT COMPUTER only; never upload this script
or Pillow to the microcontroller.

Input is a directory containing pack.json and one or more pose PNGs. Every
pose is registered to a common reference origin (source_anchor or anchors),
and every pose uses the same scale and placement.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil

try:
    from PIL import Image
except ImportError as exc:
    raise SystemExit("Pillow is required on the host: python3 -m pip install Pillow") from exc

ALLOWED_LICENSES = frozenset(("MIT", "CC0-1.0", "CC-BY-4.0"))
ALLOWED_TARGETS = frozenset(("ips", "amoled-v1"))
MAX_FRAMES = 64
MAX_SOURCE_PX = 1024
ID_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,39}$")
FRAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,50}$")


def check_anchor(value, image, label):
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError("%s: anchor must be [x, y]" % label)
    if any(isinstance(i, bool) or not isinstance(i, int) for i in value):
        raise ValueError("%s: anchor must contain integers" % label)
    if not (0 <= value[0] < image.width and 0 <= value[1] < image.height):
        raise ValueError("%s: anchor outside image" % label)
    return tuple(value)


def load_source(folder):
    with (folder / "pack.json").open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    mandatory = ("id", "name_ru", "author", "license", "source_url", "source_commit")
    for key in mandatory:
        if not isinstance(data.get(key), str) or not data[key].strip():
            raise ValueError("pack.json: non-empty %s is required" % key)
    if not ID_PATTERN.fullmatch(data["id"]):
        raise ValueError("pack.json: invalid id")
    if data.get("rights_confirmed") is not True:
        raise ValueError("pack.json: rights_confirmed must be true after manual asset review")
    if data["license"] not in ALLOWED_LICENSES:
        raise ValueError("pack.json: license not approved for this prototype")
    if not data["source_url"].startswith(("https://", "http://")):
        raise ValueError("pack.json: source_url must be a URL")
    if not re.fullmatch(r"[a-fA-F0-9]{40}", data["source_commit"]):
        raise ValueError("pack.json: source_commit must be a 40-character Git SHA")
    pics = sorted(folder.glob("*.png"), key=lambda x: x.name)
    if not (1 <= len(pics) <= MAX_FRAMES):
        raise ValueError("provide between 1 and %d PNG poses" % MAX_FRAMES)
    if any(not FRAME_PATTERN.fullmatch(p.stem) for p in pics):
        raise ValueError("unsafe frame filename")
    if "anchors" in data:
        if not isinstance(data["anchors"], dict):
            raise ValueError("anchors must be a mapping")
        if set(data["anchors"]) - {p.stem for p in pics}:
            raise ValueError("anchors contains unknown pose")
    images = []
    for file in pics:
        with Image.open(file) as opened:
            if (not 1 <= opened.width <= MAX_SOURCE_PX
                    or not 1 <= opened.height <= MAX_SOURCE_PX):
                raise ValueError("source dimensions outside supported range")
            rgba = opened.convert("RGBA")
        anchor = data.get("anchors", {}).get(
            file.stem, data.get("source_anchor", [rgba.width // 2, rgba.height - 1]))
        anchor = check_anchor(anchor, rgba, file.name)
        alpha = rgba.getchannel("A")
        bbox = alpha.point(lambda a: 255 if a >= 128 else 0).getbbox()
        if bbox is None:
            raise ValueError("%s has no visible pixels" % file.name)
        images.append((file.stem, rgba, anchor, bbox))
    return data, images


def common_transform(images, width, height, margin):
    left = min(box[0] - anchor[0] for _, _, anchor, box in images)
    top = min(box[1] - anchor[1] for _, _, anchor, box in images)
    right = max(box[2] - anchor[0] for _, _, anchor, box in images)
    bottom = max(box[3] - anchor[1] for _, _, anchor, box in images)
    size_x, size_y = right - left, bottom - top
    scale = min((width - 2 * margin) / size_x, (height - 2 * margin) / size_y)
    if scale <= 0:
        raise ValueError("invalid scale")
    # Keep the registered bottom edge near the ground, not the centre.
    anchor_x = (width - round(size_x * scale)) // 2 - round(left * scale)
    anchor_y = height - margin - round(bottom * scale)
    return scale, (anchor_x, anchor_y)


def encode_rgb565(image):
    """Network/big-endian RGB565; opaque black fills transparent pixels."""
    raw = bytearray()
    bits = bytearray((image.width * image.height + 7) // 8)
    pix = image.load()
    for y in range(image.height):
        for x in range(image.width):
            r, g, b, alpha = pix[x, y]
            i = y * image.width + x
            if alpha >= 128:
                bits[i // 8] |= 0x80 >> (i % 8)  # MSB-first packed transparency mask
                value = ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)
            else:
                value = 0
            raw.extend((value >> 8, value & 0xff))
    return bytes(raw), bytes(bits)


def assemble_frame(image, source_anchor, scale, target_anchor, width, height):
    scaled = image.resize(
        (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
        resample=Image.Resampling.LANCZOS)
    # Binary alpha: anti-aliased semi-transparency must not create coloured fringes.
    alpha = scaled.getchannel("A").point(lambda a: 255 if a >= 128 else 0)
    scaled.putalpha(alpha)
    x = target_anchor[0] - round(source_anchor[0] * scale)
    y = target_anchor[1] - round(source_anchor[1] * scale)
    dest = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    dest.paste(scaled, (x, y), scaled.getchannel("A"))
    # PIL paste+mask can create intermediate alpha on antialias edges; harden again.
    dest.putalpha(dest.getchannel("A").point(lambda a: 255 if a >= 128 else 0))
    return dest


def compile_pack(source, output, size=(96, 112), target="ips",
                 margin=4, fps=4, max_kib=768, overwrite=False):
    source, output = Path(source), Path(output)
    # Protect the input art and its parents from accidental --overwrite.
    s, o = source.resolve(), output.resolve()
    if s == o or s in o.parents or o in s.parents:
        raise ValueError("source and output must be separate, non-nested directories")
    width, height = size
    if target not in ALLOWED_TARGETS:
        raise ValueError("unknown target")
    if not (8 <= width <= 256 and 8 <= height <= 256):
        raise ValueError("invalid output size")
    if not (0 <= margin <= min(width, height) // 4):
        raise ValueError("invalid margin")
    if not (1 <= fps <= 30):
        raise ValueError("invalid fps")
    if not (1 <= max_kib <= 8192):
        raise ValueError("invalid pack limit")

    data, poses = load_source(source)  # perform validation before touching output
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        if not overwrite:
            raise ValueError("output must be empty (use --overwrite for a generated directory)")
        if not output.is_dir():
            raise ValueError("output path is not a directory")
        # Never remove unrelated content: generated outputs must carry our manifest.
        marker = output / "manifest.json"
        if not marker.is_file():
            raise ValueError("refusing to overwrite a directory without manifest.json")
        with marker.open("r", encoding="utf-8") as handle:
            old = json.load(handle)
        if old.get("format") != "medvegoshi-rgb565-mask-v1":
            raise ValueError("refusing to overwrite foreign directory")
        if old.get("id") != data["id"]:
            raise ValueError("refusing to overwrite a different pack")
        expected = {"manifest.json"}
        for frame in old.get("frames", []):
            expected.update((frame.get("rgb565"), frame.get("mask")))
        if any(p.is_symlink() or not p.is_file() or p.name not in expected
               for p in output.iterdir()):
            raise ValueError("refusing to overwrite non-generated files")
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)

    scale, out_anchor = common_transform(poses, width, height, margin)
    manifest = {
        "format": "medvegoshi-rgb565-mask-v1",
        "id": data["id"], "name_ru": data["name_ru"],
        "version": 1, "author": data["author"], "license": data["license"],
        "source_url": data["source_url"], "source_commit": data["source_commit"],
        "target": target, "canvas": [width, height],
        "anchor": list(out_anchor), "fps": fps,
        "rgb565_endian": "big", "mask_bit_order": "msb-first",
        "frames": []
    }
    total = 0
    for stem, image, source_anchor, _ in poses:
        frame = assemble_frame(image, source_anchor, scale, out_anchor, width, height)
        pixels, mask = encode_rgb565(frame)
        total += len(pixels) + len(mask)
        if total > max_kib * 1024:
            # Remove only the assets we created, leaving no apparently complete pack.
            for f in output.glob("*.rgb565"):
                f.unlink()
            for f in output.glob("*.mask"):
                f.unlink()
            raise ValueError("pack exceeds %d KiB budget" % max_kib)
        pixel_path, mask_path = stem + ".rgb565", stem + ".mask"
        (output / pixel_path).write_bytes(pixels)
        (output / mask_path).write_bytes(mask)
        manifest["frames"].append({
            "name": stem, "rgb565": pixel_path, "mask": mask_path,
            "sha256": hashlib.sha256(pixels + mask).hexdigest(),
            "bytes": len(pixels) + len(mask),
            "bounds": list(frame.getchannel("A").getbbox() or (0, 0, 0, 0))
        })
    manifest["bytes"] = total
    with (output / "manifest.json").open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(manifest, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--size", default="96x112", help="WxH pixel canvas")
    parser.add_argument("--target", choices=sorted(ALLOWED_TARGETS), default="ips")
    parser.add_argument("--fps", type=int, default=4)
    parser.add_argument("--margin", type=int, default=4)
    parser.add_argument("--max-kib", type=int, default=768)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    m = re.fullmatch(r"(\d+)x(\d+)", args.size)
    if not m:
        parser.error("--size must be WxH (for example, 96x112)")
    info = compile_pack(args.source, args.out,
                        size=(int(m.group(1)), int(m.group(2))),
                        target=args.target, margin=args.margin, fps=args.fps,
                        max_kib=args.max_kib, overwrite=args.overwrite)
    print("Built %s: %d frames, %d bytes for %s" %
          (info["id"], len(info["frames"]), info["bytes"], info["target"]))


if __name__ == "__main__":
    main()
