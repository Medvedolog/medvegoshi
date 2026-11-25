"""Versioned, atomic save slots for the desktop Pip prototype only."""
import hashlib
import hmac
import json
import os
from pathlib import Path
import tempfile

FORMAT = "medvegoshi-pip-host-v1"
MAX_BLOB = 1024
MAX_FILE = 4096


def _path(path):
    path = Path(path)
    if path.name != "pip-state.json" and not path.name.endswith(".pip-state.json"):
        raise ValueError("use a separate pip-state.json or *.pip-state.json slot")
    if path.is_symlink():
        raise ValueError("refuse to follow a save-slot symlink")
    return path


def _encode(blob):
    if not isinstance(blob, bytes) or not 0 < len(blob) <= MAX_BLOB:
        raise ValueError("invalid Pip snapshot size or type")
    return (json.dumps({"format": FORMAT, "payload": blob.hex(),
                        "sha256": hashlib.sha256(blob).hexdigest()},
                       sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")


def load_state(path):
    path = _path(path)
    with path.open("rb") as file:
        raw = file.read(MAX_FILE + 1)
    if len(raw) > MAX_FILE:
        raise ValueError("Pip save exceeds size limit")
    try:
        envelope = json.loads(raw)
        if not isinstance(envelope, dict) or envelope.get("format") != FORMAT:
            raise ValueError("unknown Pip save format")
        data = envelope["payload"]
        if not isinstance(data, str) or len(data) > MAX_BLOB * 2:
            raise ValueError("invalid Pip save payload")
        blob = bytes.fromhex(data)
        if blob.hex() != data:
            raise ValueError("noncanonical Pip save payload")
        digest = envelope["sha256"]
        if (not isinstance(digest, str) or not digest.isascii() or not blob or
                not hmac.compare_digest(digest, hashlib.sha256(blob).hexdigest())):
            raise ValueError("Pip snapshot checksum mismatch")
        return blob
    except (KeyError, UnicodeError, ValueError) as error:
        raise ValueError("invalid Pip save: " + str(error)) from error


def save_state(path, blob):
    """Replace an existing valid Pip slot or create a new one, never other saves."""
    path = _path(path)
    data = _encode(blob)
    if path.exists():
        load_state(path)  # refuse to overwrite unrelated or corrupt data
    dest = None
    try:
        with tempfile.NamedTemporaryFile(prefix=".pip-", dir=path.parent,
                                        delete=False) as file:
            dest = Path(file.name)
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        os.replace(dest, path)
    finally:
        if dest is not None:
            dest.unlink(missing_ok=True)
