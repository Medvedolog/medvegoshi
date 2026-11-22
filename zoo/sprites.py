# On-device optional sprite renderer for MedveGoshi / MicroPython.
# The original procedural drawing remains the fallback for every pet.
#
# Loads the deterministic files built by zoo/tools/build_sprites.py:
# RGB565 network/big-endian bytes + MSB-first 1-bit transparency mask.
# Reads only ONE pixel row and ONE frame mask at a time (no Pillow, no PNG).
# The IPS framebuffer stores byte-swapped RGB565 (see hw.cor).
try:
    import ujson as json
except ImportError:
    import json
try:
    import uhashlib as hashlib
except ImportError:
    import hashlib
try:
    from ubinascii import hexlify
except ImportError:
    from binascii import hexlify
import os

PACK_ROOT = "/zoo/packs"
FORMAT = "medvegoshi-rgb565-mask-v1"
FRAME_LIMIT = 64
MANIFEST_LIMIT = 48 * 1024
CANVAS_LIMIT = 256
_PACKS = {}


def clear_cache():
    """Re-read packs after copying new files; also called on reboot."""
    _PACKS.clear()


def _safe(name):
    if not isinstance(name, str) or not (1 <= len(name) <= 50):
        return False
    for ch in name:
        if not ('a' <= ch <= 'z' or 'A' <= ch <= 'Z'
                or '0' <= ch <= '9' or ch in "_-"):
            return False
    return True


def _number(v, low, high):
    # MicroPython bool is a subclass of int, exclude it explicitly.
    return type(v) is int and low <= v <= high


def _pair(v):
    return isinstance(v, (tuple, list)) and len(v) == 2 and all(
        _number(n, -256, 512) for n in v)


def _rect(v, w, h):
    return isinstance(v, (tuple, list)) and len(v) == 4 and all(
        type(n) is int for n in v) and 0 <= v[0] < v[2] <= w and 0 <= v[1] < v[3] <= h


def _stat_size(path):
    return os.stat(path)[6]


def _load(root, hero, target):
    if not _safe(hero) or target != "ips":
        return None  # AMOLED hardware backend is not enabled yet.
    base = root.rstrip("/") + "/" + hero
    name = base + "/manifest.json"
    try:
        if _stat_size(name) > MANIFEST_LIMIT:
            return None
        with open(name, "r") as fd:
            meta = json.loads(fd.read())
        if (meta.get("format") != FORMAT or meta.get("id") != hero
                or meta.get("target") != "ips" or meta.get("version") != 1
                or meta.get("rgb565_endian") != "big"
                or meta.get("mask_bit_order") != "msb-first"):
            return None
        wh = meta.get("canvas")
        if not _pair(wh):
            return None
        w, h = wh
        if not (8 <= w <= CANVAS_LIMIT and 8 <= h <= CANVAS_LIMIT):
            return None
        anchor = meta.get("anchor")
        if not _pair(anchor):
            return None
        frames = meta.get("frames")
        if not isinstance(frames, list) or not (1 <= len(frames) <= FRAME_LIMIT):
            return None
        by_name = {}
        for item in frames:
            if not isinstance(item, dict):
                return None
            stem = item.get("name")
            if not _safe(stem) or stem in by_name:
                return None
            if item.get("rgb565") != stem + ".rgb565" or item.get("mask") != stem + ".mask":
                return None
            digest = item.get("sha256")
            if not isinstance(digest, str) or len(digest) != 64 or any(
                    c not in "0123456789abcdef" for c in digest):
                return None
            nbytes = w * h * 2 + (w * h + 7) // 8
            if item.get("bytes") != nbytes or not _rect(item.get("bounds"), w, h):
                return None
            if (_stat_size(base + "/" + stem + ".rgb565") != 2 * w * h
                    or _stat_size(base + "/" + stem + ".mask") != (w * h + 7) // 8):
                return None
            by_name[stem] = item
        if "idle" not in by_name and "normal" not in by_name:
            # Avoid silently assigning a sad or sleeping picture to all moods.
            return None
        return {
            "base": base, "canvas": (w, h), "anchor": tuple(anchor),
            "frames": by_name, "verified": {},
            "active": None, "mask": None,
        }
    except (OSError, ValueError, TypeError, KeyError, MemoryError):
        return None


def _pack(root, hero, target):
    key = root + ":" + hero + ":" + target
    if key not in _PACKS:
        _PACKS[key] = _load(root, hero, target) or False
    pack = _PACKS[key]
    return pack if pack is not False else None


def _select(pack, eyes, mouth, sick):
    frames = pack["frames"]
    names = []
    if sick:
        names.extend(("sick", "ill", "doente"))
    if eyes in ("fechados", "sono", "dormindo"):
        names.extend(("sleeping", "asleep", "closed"))
    elif eyes in ("susto", "assustado"):
        names.extend(("surprised", "scared"))
    elif eyes in ("feliz", "alegre"):
        names.extend(("happy", "smile"))
    elif eyes in ("triste", "chorando"):
        names.extend(("sad",))
    if mouth == "triste":
        names.append("sad")
    elif mouth in ("aberta", "o", "meia"):
        names.extend(("eating", "open"))
    names.extend(("normal", "idle"))
    for key in names:
        if key in frames:
            return frames[key]
    return None


def _check_frame(pack, frame):
    name = frame["name"]
    if pack["verified"].get(name):
        return True
    path = pack["base"] + "/" + name
    h = hashlib.sha256()
    for suffix in (".rgb565", ".mask"):
        with open(path + suffix, "rb") as fd:
            while True:
                piece = fd.read(512)
                if not piece:
                    break
                h.update(piece)
    if hexlify(h.digest()).decode("ascii") != frame["sha256"]:
        return False
    pack["verified"][name] = True
    return True


def _mask_for(pack, frame):
    if pack["active"] == frame["name"] and pack["mask"] is not None:
        return pack["mask"]
    path = pack["base"] + "/" + frame["name"] + ".mask"
    with open(path, "rb") as fd:
        bits = fd.read()
    w, h = pack["canvas"]
    if len(bits) != (w * h + 7) // 8:
        raise ValueError("wrong mask length")
    # Keep only the most recently requested frame mask (~1-8 KiB).
    pack["active"], pack["mask"] = frame["name"], bits
    return bits


def _paint(fb, pack, frame, cx, feet, scale, disp_w, disp_h, prefer_blit=True):
    w, h = pack["canvas"]
    ax, ay = pack["anchor"]
    dw = max(1, int(w * scale + 0.5))
    dh = max(1, int(h * scale + 0.5))
    x0 = int(cx - ax * scale + 0.5)
    y0 = int(feet - ay * scale + 0.5)
    if dw > disp_w * 2 or dh > disp_h * 2:
        return None
    mask = _mask_for(pack, frame)
    inrow = bytearray(w * 2)
    outrow = bytearray(dw * 2)
    use_blit = False
    if prefer_blit and hasattr(fb, "blit"):
        try:
            import framebuf
            row_fb = framebuf.FrameBuffer(outrow, dw, 1, framebuf.RGB565)
            use_blit = True
        except (ImportError, AttributeError, ValueError):
            pass

    path = pack["base"] + "/" + frame["rgb565"]
    last_sy = -1
    with open(path, "rb") as fd:
        for yy in range(dh):
            screen_y = y0 + yy
            if screen_y < 0 or screen_y >= disp_h:
                continue
            sy = min(h - 1, (yy * h) // dh)
            if sy != last_sy:
                fd.seek(sy * w * 2)
                if fd.readinto(inrow) != len(inrow):
                    raise OSError("truncated sprite frame")
                last_sy = sy

            # The IPS FB is 16-bit little-endian; each RGB565 file word is
            # big-endian. Writing raw byte pairs yields hw.cor() values.
            # Key F81F has native numeric value 1FF8 on this framebuffer.
            collisions = [] if use_blit else None
            for xx in range(dw):
                sx = min(w - 1, xx * w // dw)
                index = sy * w + sx
                masked = mask[index >> 3] & (0x80 >> (index & 7))
                dest_pos, src_pos = xx * 2, sx * 2
                if masked:
                    b0, b1 = inrow[src_pos], inrow[src_pos + 1]
                    if use_blit and b0 == 0xF8 and b1 == 0x1F:
                        collisions.append(xx)
                else:
                    b0, b1 = 0xF8, 0x1F
                outrow[dest_pos], outrow[dest_pos + 1] = b0, b1
            if use_blit:
                fb.blit(row_fb, x0, screen_y, 0x1FF8)
                for xx in collisions:
                    tx = x0 + xx
                    if 0 <= tx < disp_w:
                        fb.pixel(tx, screen_y, 0x1FF8)
            else:
                # Correct-but-slower fallback for preview framebuffer mocks.
                for xx in range(dw):
                    tx = x0 + xx
                    if not 0 <= tx < disp_w:
                        continue
                    sx = min(w - 1, xx * w // dw)
                    index = sy * w + sx
                    if mask[index >> 3] & (0x80 >> (index & 7)):
                        a = outrow[xx * 2]
                        b = outrow[xx * 2 + 1]
                        fb.pixel(tx, screen_y, a | (b << 8))

    l, t, r, b = frame["bounds"]
    left = x0 + l * scale
    right = x0 + r * scale
    top = y0 + t * scale
    bottom = y0 + b * scale
    half = max(4, int((right - left) * 0.48))
    head_y = top + (bottom - top) * 0.27
    eye_y = top + (bottom - top) * 0.3
    eyes = [(left + (right - left) * 0.32, eye_y),
            (left + (right - left) * 0.68, eye_y)]
    return head_y, top, half, eyes


def draw(fb, hero, cx, feet, scale, eyes="normal", mouth="sorriso",
         sick=False, root=PACK_ROOT, target="ips",
         disp_w=240, disp_h=284, prefer_blit=True):
    """Optional sprite. Return drawing metrics or None for procedural fallback.

    No pack is installed by default. A pack must match the selected character
    id and IPS target. The original character rendering is always available.
    """
    if fb is None or not 0.1 <= scale <= 3 or not _safe(hero):
        return None
    pack = _pack(root, hero, target)
    if pack is None:
        return None
    frame = _select(pack, eyes, mouth, sick)
    if frame is None:
        return None
    try:
        if not _check_frame(pack, frame):
            pack["verified"].pop(frame["name"], None)
            return None
        return _paint(fb, pack, frame, cx, feet, scale,
                      disp_w, disp_h, prefer_blit)
    except (OSError, ValueError, TypeError, IndexError, MemoryError):
        # A missing/corrupt optional art resource must never prevent play.
        pack["verified"].pop(frame["name"], None)
        return None
