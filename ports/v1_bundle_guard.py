"""Read-only check of the V1 app against the digest embedded in its firmware."""
import binascii
import hashlib

INDEX = "SHA256SUMS"
MAX_INDEX = 12288
MAX_FILE = 512 * 1024
HEX = "0123456789abcdef"
SEGMENT = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.-"
REQUIRED_PIP = ("reset", "advance", "event", "status", "export_state",
                "import_state", "voice_start", "voice_render_into", "eyes_draw_into")


class BundleMismatch(RuntimeError):
    pass


def _digest(value):
    return (type(value) is str and len(value) == 64 and
            all(ch in HEX for ch in value))


def _hex(digest):
    return binascii.hexlify(digest).decode()


def _safe_path(path):
    return all(part and part[0] not in ".-" and not part.endswith(".")
               and all(ch in SEGMENT for ch in part)
               for part in path.split("/"))


def verify_files(expected, open_file=open):
    """Match each app source to the firmware's index without writing to flash."""
    if not _digest(expected):
        raise BundleMismatch("V1 firmware has no application bundle identity")
    try:
        with open_file(INDEX, "rb") as handle:
            index = handle.read(MAX_INDEX + 1)
        if len(index) > MAX_INDEX or _hex(hashlib.sha256(index).digest()) != expected:
            raise BundleMismatch("V1 application index does not match this firmware")
    except OSError:
        raise BundleMismatch("V1 application index missing or unreadable")
    paths = set()
    for line in index.decode().splitlines():
        parts = line.split("  ", 1)
        if len(parts) != 2:
            raise BundleMismatch("Invalid V1 application index")
        checksum, path = parts
        lower = path.lower()
        if (not _digest(checksum) or not _safe_path(path) or lower in paths or
                lower.rsplit("/", 1)[-1] in ("boot.py", "main.py")):
            raise BundleMismatch("Invalid path in V1 application index")
        paths.add(lower)
        try:
            with open_file(path, "rb") as handle:
                digest = hashlib.sha256()
                count = 0
                while True:
                    data = handle.read(2048)
                    if not data:
                        break
                    count += len(data)
                    if count > MAX_FILE:
                        raise BundleMismatch("Oversized V1 application file: " + path)
                    digest.update(data)
        except OSError:
            raise BundleMismatch("V1 application file missing or unreadable: " + path)
        if _hex(digest.digest()) != checksum:
            raise BundleMismatch("V1 application file differs from bundle: " + path)
    if "v1_game_app.py" not in paths:
        raise BundleMismatch("V1 application entry missing from index")


def verify_modules(pip_native, amoled):
    if (getattr(pip_native, "ABI_VERSION", None) != 1 or
            not all(callable(getattr(pip_native, name, None)) for name in REQUIRED_PIP)):
        raise BundleMismatch("Incompatible V1 Pip native API")
    for module_type, methods in (
            ("QSPIPanel", ("tx_param", "tx_color")),
            ("AMOLED", ("brightness", "reset", "init", "fill", "refresh"))):
        entry = getattr(amoled, module_type, None)
        if not callable(entry) or not all(callable(getattr(entry, name, None)) for name in methods):
            raise BundleMismatch("Incompatible V1 AMOLED native API: " + module_type)


def verify_runtime():
    try:
        import pip_native
        import amoled
    except ImportError:
        raise BundleMismatch("The paired V1 native firmware is required")
    verify_modules(pip_native, amoled)
    verify_files(getattr(pip_native, "APP_INDEX_SHA256", None))
