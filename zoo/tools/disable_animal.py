#!/usr/bin/env python3
"""Safely disable an INACTIVE optional Zoo animal on the original IPS.

The operation does NOT recursively delete a plugin or touch capi.json.
Instead it removes only the plugin's manifest.json after downloading a
verifiable local backup of the configuration, pet, and plugin source files.
Boot-time registry discovery then ignores this plugin after reboot.
An ACTIVE animal is strictly protected and cannot be disabled here.

Always use --dry-run first; execution requires --backup-dir.
"""
import argparse
import json
from pathlib import Path
import shlex
import shutil
import subprocess

from zoo import registry


def check_target(identifier, board, port, backup_dir):
    if board != "ips":
        raise ValueError("AMOLED V1 is not supported")
    if not registry.safe_id(identifier):
        raise ValueError("invalid Zoo animal identifier")
    if identifier in (item[0] for item in registry.BUILTINS):
        raise ValueError("cannot disable a built-in animal")
    if not port or port.startswith("-"):
        raise ValueError("serial port must be explicit")
    if backup_dir is None:
        raise ValueError("--backup-dir is required")
    backup = Path(backup_dir)
    if backup.exists():
        raise ValueError("backup directory already exists: refusing overwrite")
    return backup


def _remote_copy(port, path, local_path, mpremote):
    cmd = [mpremote, "connect", port, "cp", ":" + path, str(local_path)]
    subprocess.run(cmd, check=True)
    if not local_path.is_file() or local_path.stat().st_size == 0:
        raise RuntimeError("missing/empty backup: " + str(local_path))


def disable(identifier, port, backup_dir, board="ips",
            dry_run=False, mpremote="mpremote"):
    archive = check_target(identifier, board, port, backup_dir)
    path = "zoo/animals/" + identifier
    needed = {
        "config.json": "config.json",
        "capi.json": "capi.json",
        path + "/manifest.json": "manifest.json",
        path + "/face.py": "face.py",
        path + "/__init__.py": "__init__.py",
    }
    remove_cmd = [mpremote, "connect", port, "rm", ":" + path + "/manifest.json"]
    if dry_run:
        for remote, local in needed.items():
            cmd = [mpremote, "connect", port, "cp", ":" + remote,
                   str(archive / local)]
            print(" ".join(shlex.quote(a) for a in cmd))
        print("CHECK: inspect config.json and refuse if active pet is", identifier)
        print(" ".join(shlex.quote(a) for a in remove_cmd))
        print("Dry run: no device contacted, nothing removed.")
        return False

    if shutil.which(mpremote) is None:
        raise RuntimeError("mpremote is unavailable")
    archive.mkdir(parents=True, exist_ok=False)
    # No changes on device until ALL mandatory backups are complete.
    for remote, local in needed.items():
        _remote_copy(port, remote, archive / local, mpremote)
    with (archive / "config.json").open("r", encoding="utf-8") as fd:
        config = json.load(fd)
    if not isinstance(config, dict) or not isinstance(config.get("personagem"), str):
        raise ValueError("invalid active character in config.json; no changes made")
    if config["personagem"] == identifier:
        raise ValueError("ACTIVE PET: cannot disable %s; no changes made" % identifier)
    with (archive / "capi.json").open("r", encoding="utf-8") as fd:
        pet = json.load(fd)
    if not isinstance(pet, dict):
        raise ValueError("capi.json corrupt; no changes made")
    with (archive / "manifest.json").open("r", encoding="utf-8") as fd:
        manifest = json.load(fd)
    registry.validate_manifest(manifest, identifier)
    # Take extra snapshot of optional companion data if present. An unreadable
    # brain is not a reason to overwrite or remove it.
    for optional in ("brain.bin", "brain.bak"):
        try:
            _remote_copy(port, optional, archive / optional, mpremote)
        except (OSError, subprocess.CalledProcessError, RuntimeError):
            pass
    # This is the ONLY remote mutating operation. The other two module files
    # are intentionally retained on the device for easy rollback.
    subprocess.run(remove_cmd, check=True)
    print("Disabled %s. Backup: %s. Restart to rescan the Zoo." %
          (identifier, archive))
    print("To restore: copy backed-up manifest.json to :" + path + "/manifest.json")
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--id", required=True, help="optional Zoo animal ID")
    parser.add_argument("--port", required=True)
    parser.add_argument("--board", default="ips", choices=("ips", "amoled-v1"))
    parser.add_argument("--backup-dir", required=True, type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    disable(args.id, args.port, args.backup_dir, args.board, args.dry_run)


if __name__ == "__main__":
    main()
