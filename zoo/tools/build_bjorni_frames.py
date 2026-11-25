"""Compile the original Bjorni game source sheet to compact device rectangles.

Host-only: python -m zoo.tools.build_bjorni_frames [--check].
The source uses transparent 52x56 cells and an 8-column fixed animation order.
"""
import argparse
from base64 import b64encode
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
W, H = 52, 56
ANIMATIONS = (
    ('idle', 4), ('walk-right', 4), ('walk-left', 4), ('jump', 5),
    ('greeting', 4), ('sad', 4), ('thinking', 4), ('typing', 4), ('happy', 4),
    ('blink', 1), ('sleepy', 1), ('asleep', 1), ('hungry', 1), ('eating', 1),
    ('sick', 1), ('surprised', 1),
)
FRAME_COUNT = sum(n for _, n in ANIMATIONS)
COLS = 8
MARKER = "# Generated device data"


def compile_data(source):
    with Image.open(source) as img:
        img = img.convert('RGBA')
    if img.size != (COLS * W, ((FRAME_COUNT + COLS - 1) // COLS) * H):
        raise ValueError('wrong Bjorni sheet dimensions')
    # Lock the colors that give the original character its identity.
    # A frequency-only palette used to spend most of its places on fur
    # gradients, averaging away the cream muzzle, eye glints and mint key.
    palette = (
        (23, 14, 15), (42, 21, 18), (56, 28, 20), (76, 38, 26),
        (98, 46, 30), (121, 58, 35), (143, 67, 41), (162, 77, 47),
        (175, 86, 49), (186, 93, 54), (199, 104, 60), (222, 126, 72),
        (224, 149, 91), (237, 174, 113), (246, 192, 135), (255, 210, 155),
        (255, 226, 189), (255, 250, 236), (255, 255, 255), (246, 122, 94),
        (13, 31, 31), (22, 47, 46), (32, 66, 65), (45, 92, 89),
        (57, 113, 106), (69, 141, 132), (92, 159, 148),
        (27, 25, 37), (46, 45, 61), (65, 65, 82), (87, 85, 104),
        (113, 112, 131), (102, 242, 154), (71, 183, 118), (163, 183, 124),
        (248, 153, 67), (250, 185, 81),
    )
    lookup = {}

    def color_index(r, g, b):
        rgb = (r, g, b)
        if rgb not in lookup:
            lookup[rgb] = min(range(len(palette)), key=lambda i:
                3 * (r - palette[i][0]) ** 2 + 5 * (g - palette[i][1]) ** 2
                + 2 * (b - palette[i][2]) ** 2)
        return lookup[rgb]

    def rectangles(cell):
        pixels = cell.load()
        active, result = {}, []
        for y in range(H):
            runs = set()
            x = 0
            while x < W:
                r, g, b, a = pixels[x, y]
                if a < 128:
                    x += 1
                    continue
                idx = color_index(r, g, b)
                end = x + 1
                while end < W:
                    rr, gg, bb, aa = pixels[end, y]
                    if aa < 128 or color_index(rr, gg, bb) != idx:
                        break
                    end += 1
                runs.add((x, end - x, idx))
                x = end
            for key in sorted(active.keys() - runs):
                xx, ww, idx = key
                start = active.pop(key)
                result.append((xx, start, ww, y - start, idx))
            for key in runs:
                if key not in active:
                    active[key] = y
        for (xx, ww, idx), start in sorted(active.items()):
            result.append((xx, start, ww, H - start, idx))
        if not result:
            raise ValueError('transparent Bjorni frame')
        return bytes(value for rect in result for value in rect)

    parts = [MARKER, 'PALETTE = ' + repr(palette), 'FRAMES = (']
    for index in range(FRAME_COUNT):
        x, y = index % COLS * W, index // COLS * H
        data = b64encode(rectangles(img.crop((x, y, x + W, y + H))))
        parts.append('    (')
        for i in range(0, len(data), 96):
            parts.append('        ' + repr(data[i:i + 96]))
        parts.append('    ),')
    parts += [')', '']
    return '\n'.join(parts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT / 'zoo/assets/bjorni-poses.png')
    parser.add_argument('--face', type=Path, default=ROOT / 'zoo/animals/bjorni/face.py')
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    before = args.face.read_text(encoding='utf-8')
    head = before.partition(MARKER)[0]
    output = head.rstrip() + '\n\n\n' + compile_data(args.source)
    if args.check:
        if output != before:
            raise SystemExit('Bjorni device sprite data is stale')
    else:
        args.face.write_text(output, encoding='utf-8')


if __name__ == '__main__':
    main()
