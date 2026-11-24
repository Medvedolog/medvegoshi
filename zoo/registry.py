"""MedveGoshi Zoo: one boot-time registry for optional animal plugins.

The nine retained Capigoshi animals stay in their original order.
An additional animal is a self-contained directory:
  /zoo/animals/<id>/__init__.py
  /zoo/animals/<id>/manifest.json
  /zoo/animals/<id>/face.py

No project-core source edit is needed for further *procedural* animals.
Scan only on boot (reload/reboot after installation), never every frame.
No Pillow, CPython-only modules, network, or remote code execution.
"""
try:
    import ujson as json
except ImportError:
    import json
import os

# Immutable baseline. Do not rename or reorder these IDs: saved games and
# ESP-NOW payloads use them. Names are Russian, engine keys remain Portuguese.
BUILTINS = (
    ("capi", "Капи", 77),
    ("elefante", "Слон", 75),
    ("pato", "Утка", 95),
    ("polvo", "Осьминог", 71),
    ("calopsita", "Попугай", 84),
    ("cachorro", "Карамелька", 75),
    ("gato", "Кот", 75),
    ("et", "Пришелец", 81),
    ("sapinho", "Лягушонок", 65),
)
RETIRED = ("naufrago",)  # keep the legacy save ID reserved, not playable
ROOT = __file__.rsplit("/", 1)[0] + "/animals"
MANIFEST_LIMIT = 4096
MAX_PLUGINS = 12
APPROVED_LICENSES = ("MIT", "CC0-1.0", "CC-BY-4.0")
ANIMALS = {}
ELENCO = ()
NOMES = {}
HTOP = {}
EXTRA_PHRASES = {}
_RENDERERS = {}     # one import per animal, never on every frame


def safe_id(value):
    if not isinstance(value, str) or not (1 <= len(value) <= 40):
        return False
    if not ("a" <= value[0] <= "z"):
        return False
    for letter in value:
        if not (("a" <= letter <= "z") or ("0" <= letter <= "9")
                or letter == "_"):
            return False
    return True


def _integer(value, low, high):
    return type(value) is int and low <= value <= high


def _pair(value, low=-180, high=180):
    return (isinstance(value, (list, tuple)) and len(value) == 2
            and all(_integer(v, low, high) for v in value))


def _lines(value):
    if not isinstance(value, (list, tuple)) or not 1 <= len(value) <= 10:
        return False
    for phrase in value:
        if not isinstance(phrase, str) or len(phrase) > 29 or not phrase:
            return False
        parts = phrase.split("|")
        if len(parts) > 2 or not all(0 < len(s) <= 14 for s in parts):
            return False
    return True


def validate_manifest(info, folder_id):
    """Validate metadata with fixed-size fields before accepting a plugin."""
    if not isinstance(info, dict) or not safe_id(folder_id):
        raise ValueError("invalid plugin directory / manifest")
    if info.get("schema") != 1 or info.get("id") != folder_id:
        raise ValueError("plugin manifest schema/id mismatch")
    if folder_id in RETIRED or folder_id in (x[0] for x in BUILTINS):
        raise ValueError("built-in character id is reserved")
    name = info.get("name_ru")
    if not isinstance(name, str) or not 1 <= len(name) <= 14:
        raise ValueError("name_ru must fit IPS menu")
    if not _integer(info.get("htop"), 40, 170):
        raise ValueError("invalid htop")
    if not _integer(info.get("head"), -170, -5):
        raise ValueError("invalid head offset")
    if not _integer(info.get("top"), -180, -10):
        raise ValueError("invalid top offset")
    if info["top"] >= info["head"]:
        raise ValueError("top must be above head")
    if not _integer(info.get("half"), 5, 90):
        raise ValueError("invalid half width")
    eyes = info.get("eyes")
    if (not isinstance(eyes, (tuple, list)) or len(eyes) != 2
            or not all(_pair(p) for p in eyes)):
        raise ValueError("invalid eye anchor positions")
    if info.get("thermometer") is not None and not _pair(info["thermometer"]):
        raise ValueError("invalid thermometer position")
    ring = info.get("ring")
    if ring is not None and (not isinstance(ring, (list, tuple))
                            or len(ring) != 3
                            or not all(_integer(v, 0, 255) for v in ring)):
        raise ValueError("invalid outline RGB color")
    phrases = info.get("phrases")
    if not isinstance(phrases, dict) or set(phrases) != {"ocioso", "carinho"}:
        raise ValueError("phrases must define ocioso and carinho")
    if not all(_lines(phrases[k]) for k in ("ocioso", "carinho")):
        raise ValueError("speech must fit 2 x 14 characters")
    if "animated" in info and type(info["animated"]) is not bool:
        raise ValueError("animated must be boolean")
    if info.get("license") not in APPROVED_LICENSES:
        raise ValueError("unknown or unsuitable license")
    if (not isinstance(info.get("author"), str)
            or not 1 <= len(info["author"]) <= 160):
        raise ValueError("author credit is required")
    url = info.get("source_url")
    if (not isinstance(url, str) or len(url) > 300
            or not url.startswith("https://")):
        raise ValueError("HTTPS source attribution is required")
    return info


def discover(root=None):
    """Read valid optional animals in deterministic ID order, skipping bad ones.

    No Python module imports during discovery: large renderers are imported
    lazily by renderer(). Invalid or unfinished manifests never reach the
    selection menu. For device discovery, use the module ROOT, not CWD.
    """
    if root is None:
        root = ROOT
    found = {}
    try:
        entries = sorted(os.listdir(root))
    except OSError:
        return found
    if len(entries) > 200:  # avoid pathological/accidental filesystem scans
        return found
    for item in entries:
        if len(found) >= MAX_PLUGINS:
            break
        if not safe_id(item):
            continue
        base = root.rstrip("/") + "/" + item
        try:
            manifest_path = base + "/manifest.json"
            if os.stat(manifest_path)[6] > MANIFEST_LIMIT:
                continue
            # Require a usable procedural renderer, not just a sprite folder.
            os.stat(base + "/__init__.py")
            os.stat(base + "/face.py")
            with open(manifest_path, "r") as handle:
                metadata = json.loads(handle.read())
            validate_manifest(metadata, item)
        except (OSError, ValueError, TypeError, KeyError, MemoryError):
            continue
        found[item] = metadata
    return found


def make_catalogue(found):
    ids = [item[0] for item in BUILTINS]
    names = {x[0]: x[1] for x in BUILTINS}
    heights = {x[0]: x[2] for x in BUILTINS}
    phrases = {}
    # Preserve bundled menu positions when external Zoo animals are added.
    # Other IDs are sorted for reproducible menu order.
    bundled = ("pip", "girafa", "bjorni")
    ordered = [x for x in bundled if x in found]
    ordered += [x for x in sorted(found) if x not in bundled]
    for key in ordered:
        if key in names or key in RETIRED:
            continue
        data = found[key]
        ids.append(key)
        names[key] = data["name_ru"]
        heights[key] = data["htop"]
        phrases[key] = {
            "ocioso": tuple(data["phrases"]["ocioso"]),
            "carinho": tuple(data["phrases"]["carinho"]),
        }
    return tuple(ids), names, heights, phrases


def refresh(root=None):
    """Replace registry snapshot. Use at startup or before reloading the game."""
    global ANIMALS, ELENCO, NOMES, HTOP, EXTRA_PHRASES
    ANIMALS = discover(root)
    ELENCO, NOMES, HTOP, EXTRA_PHRASES = make_catalogue(ANIMALS)
    _RENDERERS.clear()
    return ELENCO


def renderer(character_id):
    """Lazy-load optional animal renderer, returning None on broken plugins."""
    if character_id not in ANIMALS:
        return None
    if character_id in _RENDERERS:
        fn = _RENDERERS[character_id]
        return fn if fn is not False else None
    try:
        module_name = "zoo.animals." + character_id + ".face"
        module = __import__(module_name, None, None, ("render",))
        fn = getattr(module, "render", None)
        if not callable(fn):
            fn = False
    except (ImportError, AttributeError, ValueError, MemoryError, SyntaxError):
        fn = False
    _RENDERERS[character_id] = fn
    return fn if fn is not False else None


# Startup snapshot: imports in desenho.py and vida.py see the same cast.
refresh()
