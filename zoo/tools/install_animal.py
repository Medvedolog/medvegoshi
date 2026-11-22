#!/usr/bin/env python3
"""Install one optional Zoo animal on the ORIGINAL IPS (files-only).

No flashing, no erase_flash, no modification of user pet/brain saves.
Deploy __init__.py, face.py, then manifest.json (last).
Reboot after installation; the registry scans plugins only at startup.
"""
import argparse
import ast
import json
from pathlib import Path
import shlex
import shutil
import subprocess

from zoo import registry


def check_source(folder):
    folder = Path(folder)
    name = folder.name
    if not registry.safe_id(name):
        raise ValueError("unsafe animal directory id")
    paths = [folder / "__init__.py", folder / "face.py",
             folder / "manifest.json"]
    for path in paths:
        if not path.is_file() or path.is_symlink():
            raise ValueError("required regular file missing: " + path.name)
    if paths[2].stat().st_size > registry.MANIFEST_LIMIT:
        raise ValueError("manifest too large")
    with paths[2].open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    registry.validate_manifest(data, name)
    if paths[1].stat().st_size > 48 * 1024:
        raise ValueError("face.py exceeds the 48 KiB per-plugin limit")
    for source in paths[:2]:
        with source.open("r", encoding="utf-8") as f:
            ast.parse(f.read(), filename=str(source))
    return name, paths


def install(folder, port, board="ips", dry_run=False, mpremote="mpremote"):
    if board != "ips":
        raise ValueError("AMOLED V1 installation is blocked until hardware QA")
    if not port or port.startswith("-"):
        raise ValueError("an explicit device serial port is required")
    name, paths = check_source(folder)
    remote = ":zoo/animals/" + name
    commands = [
        [mpremote, "connect", port, "mkdir", ":zoo"],
        [mpremote, "connect", port, "mkdir", ":zoo/animals"],
        [mpremote, "connect", port, "mkdir", remote],
    ]
    for path in paths:  # __init__, face, manifest LAST
        commands.append([mpremote, "connect", port, "cp",
                         str(path), remote + "/" + path.name])
    if dry_run:
        for command in commands:
            print(" ".join(shlex.quote(arg) for arg in command))
        print("Dry run; no serial connection and no saved-game changes.")
        return name
    if shutil.which(mpremote) is None:
        raise RuntimeError("Install mpremote: python -m pip install mpremote")
    # Files-only: existing-dir errors from mkdir are harmless, file-copy
    # failures are fatal; partial transfers are not activated until reboot.
    for command in commands[:3]:
        subprocess.run(command, check=False, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE)
    for command in commands[3:]:
        subprocess.run(command, check=True)
    print("Installed %s. Restart MedveGoshi to rescan animals." % name)
    return name


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path,
                        help="Folder zoo/animals/<id> or another plugin folder")
    parser.add_argument("--port", required=True)
    parser.add_argument("--board", default="ips", choices=("ips", "amoled-v1"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    install(args.source, args.port, args.board, args.dry_run)


if __name__ == "__main__":
    main()
