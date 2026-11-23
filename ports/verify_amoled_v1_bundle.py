"""Verify V1 archive membership, content and target compilation on the host."""
import argparse
import hashlib
from pathlib import Path
import subprocess
import tempfile
import zipfile

from ports.package_amoled_v1_app import (APP_FILES, MAX_FILE_BYTES,
                                        STATUS_NAME, SUMS_NAME)
from ports.v1_bundle_guard import verify_files


def verify_archive(path, *, mpy_cross=None):
    expected = {name for _, name in APP_FILES} | {SUMS_NAME, STATUS_NAME}
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        if (len(infos) != len(expected) or {i.filename for i in infos} != expected
                or any(i.file_size > MAX_FILE_BYTES for i in infos)):
            raise ValueError("unexpected V1 archive members or sizes")
        index = archive.read(SUMS_NAME)
        digest = hashlib.sha256(index).hexdigest()
        lines = index.decode("ascii").splitlines()
        paths = [line.split("  ", 1)[-1] for line in lines]
        if len(paths) != len(expected) - 1 or set(paths) != expected - {SUMS_NAME}:
            raise ValueError("incomplete V1 application index")
        verify_files(digest, lambda name, mode: archive.open(name, "r"))
        if mpy_cross is not None:
            compiler = Path(mpy_cross).resolve(strict=True)
            with tempfile.TemporaryDirectory(prefix="v1-cross-") as directory:
                root = Path(directory)
                for name in sorted(expected):
                    if name.endswith(".py"):
                        target = root / name
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(archive.read(name))
                        subprocess.run([str(compiler), "-march=xtensawin", "-s", name,
                                        "-o", str(root / "check.mpy"), str(target)], check=True)
    return digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive")
    parser.add_argument("--mpy-cross")
    parser.add_argument("--firmware", type=Path)
    args = parser.parse_args()
    digest = verify_archive(args.archive, mpy_cross=args.mpy_cross)
    if args.firmware is not None and digest.encode("ascii") not in args.firmware.read_bytes():
        raise SystemExit("Paired application digest not found in firmware image")
    print(digest)


if __name__ == "__main__":
    main()
