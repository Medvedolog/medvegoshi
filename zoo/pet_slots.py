"""Per-character save paths and one-time, copy-only legacy migration.

The shared legacy saves are never removed or changed. A pending journal locks
the verified owner and source fingerprints before any slot files are copied;
an interruption can only resume the same plan without replacing other data.
Compatible with MicroPython filesystem APIs. Designed for a single writer.
"""
try:
    import ujson as json
except ImportError:
    import json
import os
import sys

from zoo import recovery
from zoo.registry import safe_id

SAVE_ROOT = "pet_saves"
PET_FILE = "capi.json"
LEGACY_FILES = (PET_FILE, "brain.bin", "brain.bak")
JOURNAL = "legacy-v1.pending"
COMMITTED = "legacy-v1.json"
VERSION = 1
JSON_LIMIT = 16384
FILE_LIMIT = 262144
CHUNK = 1024


class SlotError(recovery.RecoveryRequired):
    pass


def _join(root, suffix):
    return (root.rstrip("/") + "/" if root else "") + suffix


def _absolute(path, cwd):
    parts = []
    target = path if path.startswith("/") else cwd + "/" + path
    for part in target.split("/"):
        if part == "..":
            if parts:
                parts.pop()
        elif part and part != ".":
            parts.append(part)
    return "/" + "/".join(parts)


def _mounted_for(path, mounts):
    best = None
    length = -1
    for volume, mount in mounts:
        prefix = mount.rstrip("/")
        if (not prefix or path == prefix or path.startswith(prefix + "/")) and len(prefix) > length:
            best, length = volume, len(prefix)
    return best


def _require_littlefs(path):
    # FAT rename may delete the old target before retrying internally.
    # Verify the live mount; never guess or reformat a board on update.
    if sys.implementation.name != "micropython":
        return
    try:
        import vfs
        target = _absolute(path, os.getcwd())
        mounted = _mounted_for(target, vfs.mount())
        if isinstance(mounted, vfs.VfsLfs2):
            return
    except (ImportError, AttributeError, OSError, TypeError, ValueError):
        pass
    raise SlotError("slot_filesystem")


def _id(pet_id):
    if not safe_id(pet_id):
        raise SlotError("slot_bad_id")
    return pet_id


def brain_dir(pet_id, root=""):
    """Directory prefix for companion.placa.Ponte, including the final slash."""
    return _join(root, SAVE_ROOT + "/" + _id(pet_id) + "/")


def pet_path(pet_id, root=""):
    return brain_dir(pet_id, root) + PET_FILE


def _errno(error):
    value = getattr(error, "errno", None)
    return value if value is not None else (error.args[0] if error.args else None)


def _stat(path):
    try:
        # MicroPython VFS filesystems do not make symlinks. Reject them if
        # this module is being tested with a host filesystem that does.
        return getattr(os, "lstat", os.stat)(path)
    except OSError as error:
        if _errno(error) == 2:
            return None
        raise


def _is_file(path):
    entry = _stat(path)
    if entry is None:
        return False
    if entry[0] & 0xF000 != 0x8000:
        raise OSError("not a regular save file")
    return True


def _is_dir(path):
    entry = _stat(path)
    if entry is None:
        return False
    if entry[0] & 0xF000 != 0x4000:
        raise OSError("not a save directory")
    return True


def _mkdir(path):
    if not _is_dir(path):
        os.mkdir(path)


def ensure_slot(pet_id, root=""):
    """Create a validated slot directory. Does not write any save contents."""
    target = brain_dir(pet_id, root)
    _require_littlefs(target)
    try:
        _mkdir(_join(root, SAVE_ROOT))
        _mkdir(target[:-1])
    except OSError:
        raise SlotError("slot_io", pet_id)
    return target


def _read_dict(path):
    if not _is_file(path):
        raise ValueError("missing JSON")
    with open(path, "rb") as stream:
        raw = stream.read(JSON_LIMIT + 1)
    if len(raw) > JSON_LIMIT:
        raise ValueError("save JSON too large")
    obj = json.loads(raw.decode('utf-8'))
    if not isinstance(obj, dict):
        raise ValueError("save JSON must be an object")
    return obj


def _flush(stream):
    stream.flush()
    if hasattr(os, "fsync"):
        os.fsync(stream.fileno())


def _sync_vfs():
    if not hasattr(os, "fsync") and hasattr(os, "sync"):
        os.sync()


def _replace(src, dst):
    replace = getattr(os, "replace", os.rename)
    replace(src, dst)
    try:
        _sync_vfs()
    except OSError as error:
        # Rename is the commit point: the new file is already visible.
        # A late sync failure means power-loss durability is uncertain,
        # not that the caller should continue using the old selection.
        print("Zoo save durability unconfirmed after rename:", error)


def save_json(path, data):
    """Publish complete JSON by same-directory rename, never truncating dst.

    CPython uses replace(); the target ESP32 LittleFS VFS uses rename().
    If a VFS refuses replacement, leave the old file intact and report an
    error; never unlink it first. Interrupted .slot-tmp is staging only, not
    a valid save or migration journal, and can be overwritten by a retry.
    """
    _require_littlefs(path)
    tmp = path + ".slot-tmp"
    try:
        if not isinstance(data, dict):
            raise ValueError("save JSON must be an object")
        payload = json.dumps(data).encode('utf-8')
        if len(payload) > JSON_LIMIT:
            raise ValueError("save JSON too large")
        _is_file(path)
        _is_file(tmp)
        with open(tmp, "wb") as stream:
            if stream.write(payload) != len(payload):
                raise OSError("short JSON write")
            _flush(stream)
        _replace(tmp, path)
    except (OSError, ValueError, TypeError, MemoryError):
        raise SlotError("slot_io")


def _identity(data, expected, required=False):
    # Old firmware omitted identity from most capi.json files. Some
    # versions/backups included it; never ignore a conflicting identity.
    supplied = False
    for key in ("personagem", "pet_id", "_pet_id", "animal_id"):
        if key in data:
            supplied = True
            if data[key] != expected:
                raise SlotError("slot_owner_conflict", expected)
    if required and not supplied:
        raise SlotError("slot_owner_unknown", expected)


def _fingerprint(path):
    checksum, size = 2166136261, 0
    with open(path, "rb") as stream:
        while True:
            part = stream.read(CHUNK)
            if not part:
                return [size, checksum]
            size += len(part)
            if size > FILE_LIMIT:
                raise ValueError("legacy file too large")
            for byte in part:
                checksum = ((checksum ^ byte) * 16777619) & 0xFFFFFFFF


def _legacy(root):
    result = {}
    for name in LEGACY_FILES:
        path = _join(root, name)
        if _is_file(path):
            result[name] = _fingerprint(path)
    return result


def _validate_plan(data):
    if type(data.get("version")) is not int or data["version"] != VERSION:
        raise ValueError("bad journal version")
    files = data.get("files")
    owner = data.get("owner")
    if not isinstance(files, dict) or (not safe_id(owner) if files else owner is not None):
        raise ValueError("bad journal owner")
    for name, checksum in files.items():
        if (name not in LEGACY_FILES or not isinstance(checksum, list) or len(checksum) != 2
                or type(checksum[0]) is not int or not 0 <= checksum[0] <= FILE_LIMIT
                or type(checksum[1]) is not int or not 0 <= checksum[1] <= 0xFFFFFFFF):
            raise ValueError("bad journal record")
    return data


def _same(source, dest):
    with open(source, "rb") as first, open(dest, "rb") as second:
        while True:
            part = first.read(CHUNK)
            if part != second.read(CHUNK):
                return False
            if not part:
                return True


def _copy(source, dest, pet_id):
    if _is_file(dest):
        if not _same(source, dest):
            raise SlotError("slot_destination_conflict", pet_id)
        return
    tmp = dest + ".migrating"
    _is_file(tmp)
    with open(source, "rb") as origin, open(tmp, "wb") as target:
        count = 0
        while True:
            part = origin.read(CHUNK)
            if not part:
                break
            count += len(part)
            if count > FILE_LIMIT:
                raise ValueError("legacy file too large")
            if target.write(part) != len(part):
                raise OSError("short save copy")
        _flush(target)
    if not _same(source, tmp):
        raise SlotError("slot_source_changed", pet_id)
    if _is_file(dest):
        if not _same(source, dest):
            raise SlotError("slot_destination_conflict", pet_id)
        return
    _replace(tmp, dest)


def _journal(root, name):
    return _join(root, SAVE_ROOT + "/" + name)


def _confirm_owner(root, pet_id, files):
    config = _join(root, "config.json")
    try:
        persisted = _read_dict(config)
    except (OSError, ValueError, TypeError, MemoryError):
        raise SlotError("slot_owner_unknown", pet_id)
    # Defaults must never be used when assigning old data.
    if "personagem" not in persisted:
        raise SlotError("slot_owner_unknown", pet_id)
    _identity(persisted, pet_id, required=True)
    if PET_FILE in files:
        try:
            data = _read_dict(_join(root, PET_FILE))
        except (OSError, ValueError, TypeError, MemoryError):
            raise SlotError("pet_corrupt", pet_id)
        _identity(data, pet_id)


def prepare(active_id, root=""):
    """Migrate once, then return the current animal's directory prefix.

    Existing config must explicitly name the selected owner if any legacy
    save exists. Conflicting identity, source changes and differing
    pre-existing destination bytes all stop instead of creating a fresh pet.
    The caller can show a recovery message and keep the legacy files intact.
    """
    _id(active_id)
    _require_littlefs(_join(root, "config.json"))
    _require_littlefs(_join(root, SAVE_ROOT))
    _require_littlefs(brain_dir(active_id, root))
    done, pending = _journal(root, COMMITTED), _journal(root, JOURNAL)
    try:
        # Inspect the parent before children and do not create anything
        # until ownership checks pass (no guessed migration from defaults).
        parent_exists = _is_dir(_join(root, SAVE_ROOT))
        has_done = parent_exists and _is_file(done)
        has_pending = parent_exists and _is_file(pending)
        if has_done:
            _validate_plan(_read_dict(done))
            if has_pending:
                raise SlotError("slot_journal_conflict", active_id)
            return ensure_slot(active_id, root)
        files = _legacy(root)
        if has_pending:
            plan = _validate_plan(_read_dict(pending))
            if plan["owner"] is not None and plan["owner"] != active_id:
                raise SlotError("slot_owner_conflict", active_id)
            if files != plan["files"]:
                raise SlotError("slot_source_changed", active_id)
        else:
            plan = {"version": VERSION, "owner": active_id if files else None, "files": files}
        if files:
            _confirm_owner(root, active_id, files)
        folder = ensure_slot(active_id, root)
        # Preflight every destination before copying any part of a mismatch.
        for name in files:
            dest, source = folder + name, _join(root, name)
            if _is_file(dest) and not _same(source, dest):
                raise SlotError("slot_destination_conflict", active_id)
        if not has_pending:
            save_json(pending, plan)
        for name in files:
            _copy(_join(root, name), folder + name, active_id)
        if files != _legacy(root):
            raise SlotError("slot_source_changed", active_id)
        _replace(pending, done)
        return folder
    except SlotError:
        raise
    except (OSError, ValueError, TypeError, MemoryError):
        raise SlotError("slot_io", active_id)


def load_selection(config, defaults, retired=(), fallback="capi", root=""):
    """Resolve a retired selection without relabeling or deleting its data.

    Finish the copy-only legacy migration with the old on-disk owner first.
    Only after loading the independent fallback slot publish the new setting.
    """
    selected = config["personagem"]
    prepare(selected, root)
    if selected not in retired:
        return load_pet(selected, defaults, root)
    prepare(fallback, root)
    pet = load_pet(fallback, defaults, root)
    updated = dict(config)
    updated["personagem"] = fallback
    for key in ("pet_id", "_pet_id", "animal_id"):
        if updated.get(key) == selected:
            updated[key] = fallback
    save_json(_join(root, "config.json"), updated)
    config.update(updated)
    return pet


def _require_prepared(root, pet_id):
    try:
        if (not _is_dir(_join(root, SAVE_ROOT)) or
                not _is_file(_journal(root, COMMITTED)) or
                _is_file(_journal(root, JOURNAL))):
            raise SlotError("slot_not_ready", pet_id)
    except OSError:
        raise SlotError("slot_io", pet_id)


def has_pet(pet_id, root=""):
    """Strict primary-save existence; only ENOENT means no pet."""
    folder = brain_dir(pet_id, root)
    _require_prepared(root, pet_id)
    try:
        return _is_dir(folder[:-1]) and _is_file(folder + PET_FILE)
    except OSError:
        raise SlotError("slot_io", pet_id)


def load_pet(pet_id, defaults, root=""):
    present = has_pet(pet_id, root)
    if present:
        try:
            result = recovery.load_pet(pet_path(pet_id, root), defaults)
        except recovery.RecoveryRequired as error:
            raise SlotError(error.reason, pet_id)
    else:
        result = dict(defaults)
    _identity(result, pet_id)
    return result


def save_pet(pet_id, data, root=""):
    _id(pet_id)
    _require_prepared(root, pet_id)
    if not isinstance(data, dict):
        raise SlotError("pet_corrupt", pet_id)
    _identity(data, pet_id)
    payload = dict(data)
    payload["pet_id"] = pet_id
    folder = ensure_slot(pet_id, root)
    save_json(folder + PET_FILE, payload)
