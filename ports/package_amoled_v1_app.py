"""Build a review-only application ZIP on the host; never connects to a board."""
import argparse
import hashlib
import io
import os
from pathlib import Path
import re
import stat
import zipfile


# A new runtime dependency or animal must be reviewed and added explicitly.
# No recursive discovery: untracked files, build output and device data are excluded.
UNCHANGED_PATHS = (
    'LICENSE',
    'desenho.py', 'font_ru.py', 'hw.py', 'portal.py', 'rede.py', 'vida.py',
    'companion/__init__.py', 'companion/actions.py', 'companion/cerebro.py',
    'companion/clima.py', 'companion/config.py', 'companion/drives.py',
    'companion/encoder.py', 'companion/expressao.py', 'companion/learn.py',
    'companion/nucleo.py', 'companion/nucleo_viper.py', 'companion/placa.py',
    'companion/relogio.py', 'companion/reward.py', 'companion/snn.py',
    'ports/__init__.py', 'ports/amoled_v1.py', 'ports/amoled_v1_audio.py',
    'ports/amoled_v1_launch.py', 'ports/amoled_v1_runtime.py',
    'ports/runtime_handoff.py', 'ports/v1_bundle_guard.py', 'ports/v1_bringup.py',
    'ports/v1_game_hal.py', 'ports/v1_menu_font.py', 'ports/v1_native_canvas.py',
    'ports/v1_scale.py',
    'zoo/__init__.py', 'zoo/pet_slots.py', 'zoo/recovery.py', 'zoo/registry.py',
    'zoo/sprites.py', 'zoo/switch_pet.py',
    'zoo/animals/__init__.py',
    'zoo/animals/bjorni/__init__.py', 'zoo/animals/bjorni/face.py',
    'zoo/animals/bjorni/manifest.json',
    'zoo/animals/girafa/__init__.py', 'zoo/animals/girafa/face.py',
    'zoo/animals/girafa/manifest.json',
    'zoo/animals/pip/__init__.py', 'zoo/animals/pip/face.py',
    'zoo/animals/pip/manifest.json',
    'zoo/animals/ryska/__init__.py', 'zoo/animals/ryska/face.py',
    'zoo/animals/ryska/manifest.json',
    'zoo/animals/fennec/__init__.py', 'zoo/animals/fennec/face.py',
    'zoo/animals/fennec/manifest.json',
    'zoo/giraffe/__init__.py', 'zoo/giraffe/face.py',
    'zoo/pip/__init__.py', 'zoo/pip/eyes.py', 'zoo/pip/face.py', 'zoo/pip/game.py',
)
APP_FILES = tuple((path, path) for path in UNCHANGED_PATHS) + (
    ('main.py', 'v1_game_app.py'),
    ('companion/raiox.html', 'raiox.html'),
    ('zoo/upstream/pip/LICENSE', 'LICENSE-Pip-KeyPet.txt'),
)
STATUS_NAME = 'UNTESTED.txt'
SUMS_NAME = 'SHA256SUMS'
STATUS = (
    'MedveGoshi | AMOLED 1.8 V1 | UNTESTED ON HARDWARE\n'
    'Application source only. Review the files and SHA256SUMS on the host.\n'
    'This is not firmware, a backup, an installer, or a bootable image.\n'
    'Contains no main.py or boot.py entry point. Do not rename v1_game_app.py.\n'
    'Requires compatible experimental MicroPython with native display support.\n'
    'Do not use this ZIP to replace the factory firmware.\n'
)
MAX_FILE_BYTES = 512 * 1024
MAX_PAYLOAD_BYTES = 4 * 1024 * 1024
SAFE_PART = re.compile(r'[a-zA-Z0-9_][a-zA-Z0-9_.-]*\Z')
TEXT_SUFFIXES = ('.py', '.html', '.json', '.txt')
MANIFEST_DIRS = {
    'zoo/animals/bjorni', 'zoo/animals/girafa', 'zoo/animals/pip', 'zoo/animals/ryska',
    'zoo/animals/fennec',
}


class PackageError(ValueError):
    """The tree or requested output cannot be packaged as a V1 application."""


def _parts(name):
    parts = name.split('/')
    if any(not SAFE_PART.fullmatch(part) or part.endswith('.') for part in parts):
        raise PackageError('unsafe relative path: ' + name)
    return parts


def _validate_entry(source, target):
    for name in (source, target):
        parts = _parts(name)
        if parts[-1] != 'LICENSE' and not parts[-1].endswith(TEXT_SUFFIXES):
            raise PackageError('non-source path: ' + name)
        if parts[-1].endswith('.json') and (
                parts[-1] != 'manifest.json' or '/'.join(parts[:-1]) not in MANIFEST_DIRS):
            raise PackageError('only allowlisted animal manifests may use JSON: ' + name)
    if target in (STATUS_NAME, SUMS_NAME) or _parts(target)[-1].lower() in ('main.py', 'boot.py'):
        raise PackageError('reserved application archive path: ' + target)


def _regular_file(root, relative):
    parts = _parts(relative)
    path = root
    for part in parts[:-1]:
        path /= part
        if not stat.S_ISDIR(path.lstat().st_mode):
            raise PackageError('expected a real directory: ' + str(path))
    path /= parts[-1]
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode):
        raise PackageError('expected a regular file: ' + relative)
    if metadata.st_size > MAX_FILE_BYTES:
        raise PackageError('file exceeds per-file size limit: ' + relative)
    return path


def _read(root, relative):
    try:
        path = _regular_file(root, relative)
        # O_NOFOLLOW is available on common Unix hosts; lstat above also
        # rejects static symlinks on hosts that do not expose this flag.
        flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
        flags |= getattr(os, 'O_BINARY', 0)
        with os.fdopen(os.open(path, flags), 'rb') as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                raise PackageError('expected a regular file: ' + relative)
            data = handle.read(MAX_FILE_BYTES + 1)
    except FileNotFoundError as exc:
        raise PackageError('missing required application input: ' + relative) from exc
    if len(data) > MAX_FILE_BYTES:
        raise PackageError('file exceeds per-file size limit: ' + relative)
    try:
        decoded = data.decode('utf-8')
    except UnicodeDecodeError as exc:
        raise PackageError('expected UTF-8 source: ' + relative) from exc
    if any(ord(char) < 32 and char not in '\n\r\t' for char in decoded):
        raise PackageError('unexpected control bytes in source: ' + relative)
    return data


def _archive(entries):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_STORED) as archive:
        for name, data in sorted(entries.items()):
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.create_system = 3  # stable Unix permissions, regardless of host
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(info, data)
    return stream.getvalue()


def package_app(source, output):
    """Build a deterministic ZIP from a trusted checkout and return its SHA256.

    The destination must be a new .zip file in an existing directory. All
    source validation runs before any output file is created.
    """
    source = Path(source).resolve(strict=True)
    output = Path(output)
    if not source.is_dir():
        raise PackageError('source must be the project checkout directory')
    if output.suffix.lower() != '.zip':
        raise PackageError('output must have a .zip suffix')
    if os.path.lexists(output):
        raise FileExistsError(str(output))

    contents, names, total = {}, set(), 0
    for relative, name in APP_FILES:
        _validate_entry(relative, name)
        if name.casefold() in names:
            raise PackageError('duplicate application archive path: ' + name)
        names.add(name.casefold())
        data = _read(source, relative)
        total += len(data)
        if total > MAX_PAYLOAD_BYTES:
            raise PackageError('application exceeds total size limit')
        contents[name] = data
    contents[STATUS_NAME] = STATUS.encode('utf-8')
    contents[SUMS_NAME] = ''.join(
        hashlib.sha256(contents[name]).hexdigest() + '  ' + name + '\n'
        for name in sorted(contents)
    ).encode('ascii')
    data = _archive(contents)
    with output.open('xb') as handle:
        handle.write(data)
    return hashlib.sha256(data).hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', default=Path(__file__).resolve().parents[1],
                        help='MedveGoshi checkout (default: checkout containing this tool)')
    parser.add_argument('--output', required=True, help='new application .zip path')
    args = parser.parse_args(argv)
    try:
        checksum = package_app(args.source, args.output)
    except (OSError, PackageError) as exc:
        parser.exit(1, 'Packaging failed: ' + str(exc) + '\n')
    print(checksum + '  ' + args.output)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
