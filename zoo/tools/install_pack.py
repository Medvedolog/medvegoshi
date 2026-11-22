#!/usr/bin/env python3
"""Install one *verified* Zoo sprite pack onto the original IPS board.

No firmware flashing or erasing; only /zoo/packs/<existing-pet-id>/ files.
The JSON manifest is transferred LAST, so a new pack is not advertised
until its pixel/mask files have been copied successfully.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import shutil
import subprocess

from zoo import registry

ROOT = Path(__file__).resolve().parents[2]
IDENTIFIER = re.compile(r"[a-z][a-z0-9_-]{0,39}\Z")
STEM = re.compile(r"[A-Za-z0-9_-]{1,50}\Z")
FMT = "medvegoshi-rgb565-mask-v1"


def existing_characters(animals_root=None):
    # The device may already hold an optional animal, while its source can
    # live in an external folder not tracked by this repo.
    cast = set(registry.ELENCO)
    if animals_root is not None:
        cast.update(registry.discover(str(animals_root)))
    return cast


def validate(pack, animals_root=None):
    pack = Path(pack)
    meta = json.loads((pack / "manifest.json").read_text(encoding="utf-8"))
    identifier = meta.get("id", "")
    if (not isinstance(identifier, str) or not IDENTIFIER.fullmatch(identifier)
            or identifier not in existing_characters(animals_root)):
        raise ValueError("sprite id must be an existing MedveGoshi character")
    if meta.get("target") != "ips" or meta.get("format") != FMT:
        raise ValueError("installer supports only compiled IPS packs")
    if meta.get("version") != 1:
        raise ValueError("wrong sprite pack version")
    if meta.get("rgb565_endian") != "big" or meta.get("mask_bit_order") != "msb-first":
        raise ValueError("wrong pixel format")
    for field in ("license", "author", "source_url", "source_commit"):
        if not isinstance(meta.get(field), str) or not meta[field]:
            raise ValueError("missing attribution: " + field)
    if meta["license"] not in ("MIT", "CC0-1.0", "CC-BY-4.0"):
        raise ValueError("unapproved license")
    width, height = meta["canvas"]
    if not (8 <= width <= 256 and 8 <= height <= 256):
        raise ValueError("invalid canvas dimensions")
    frames = meta["frames"]
    if not isinstance(frames, list) or not (1 <= len(frames) <= 64):
        raise ValueError("invalid frame list")
    seen = set()
    files = []
    for frame in frames:
        name = frame["name"]
        if not isinstance(name, str) or not STEM.fullmatch(name) or name in seen:
            raise ValueError("invalid/duplicate frame name")
        seen.add(name)
        p, m = name + ".rgb565", name + ".mask"
        if frame["rgb565"] != p or frame["mask"] != m:
            raise ValueError("invalid frame file paths")
        pixels, mask = (pack / p).read_bytes(), (pack / m).read_bytes()
        if len(pixels) != width * height * 2 or len(mask) != (width * height + 7) // 8:
            raise ValueError("truncated sprite: " + name)
        if hashlib.sha256(pixels + mask).hexdigest() != frame.get("sha256"):
            raise ValueError("invalid checksum: " + name)
        files.extend((pack / p, pack / m))
    if "normal" not in seen and "idle" not in seen:
        raise ValueError("sprite needs a normal or idle frame")
    return identifier, files


def install(pack, port, board="ips", dry_run=False, mpremote="mpremote",
            animals_root=None):
    if board != "ips":
        raise ValueError("AMOLED V1 remains blocked until the hardware port is tested")
    if not port or port.startswith("-"):
        raise ValueError("an explicit serial port is required")
    identifier, files = validate(pack, animals_root=animals_root)
    folder = "zoo/packs/" + identifier
    cmds = [
        [mpremote, "connect", port, "mkdir", ":zoo"],
        [mpremote, "connect", port, "mkdir", ":zoo/packs"],
        [mpremote, "connect", port, "mkdir", ":" + folder],
    ]
    for file in files:
        cmds.append([mpremote, "connect", port, "cp",
                     str(file), ":" + folder + "/" + file.name])
    cmds.append([mpremote, "connect", port, "cp",
                 str(Path(pack) / "manifest.json"), ":" + folder + "/manifest.json"])
    if dry_run:
        for cmd in cmds:
            print(" ".join(shlex.quote(word) for word in cmd))
        print("Dry run: no serial connection and no Flash changes.")
        return

    if shutil.which(mpremote) is None:
        raise RuntimeError("mpremote not found; install it with python -m pip install mpremote")
    # The first three mkdir calls may report "already exists", but an actual
    # connection/FS failure will make one of the verified cp calls fail.
    for cmd in cmds[:3]:
        subprocess.run(cmd, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    for cmd in cmds[3:]:
        subprocess.run(cmd, check=True)
    print("Pack installed for %s. Reboot the IPS board to reset the sprite cache." % identifier)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", required=True)
    parser.add_argument("--port", required=True)
    parser.add_argument("--board", choices=("ips", "amoled-v1"), default="ips")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--animals-root", type=Path, default=None,
                        help="Optional external folder containing animal plugin dirs")
    args = parser.parse_args()
    install(args.pack, args.port, args.board, args.dry_run,
            animals_root=args.animals_root)


if __name__ == "__main__":
    main()
