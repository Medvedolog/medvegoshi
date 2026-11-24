"""Compile the original Bjorni game source sheet to compact device rectangles.

Host-only: python -m zoo.tools.build_bjorni_frames [--check].
The source uses transparent 44x48 cells and an 8-column fixed animation order.
"""
import argparse
from base64 import b64encode
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
W, H = 44, 48
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
    used = [(r, g, b) for r, g, b, alpha in img.getdata() if alpha > 127]
    if not used:
        raise ValueError('empty Bjorni sheet')
    colors = Image.new('RGB', (len(used), 1))
    colors.putdata(used)
    quant = colors.quantize(colors=16, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    c = quant.getpalette()
    palette = tuple(tuple(c[i:i+3]) for i in range(0, 48, 3))
    lookup = {}
    mapped = iter(quant.getdata())
    for rgb in used:
        lookup[rgb] = next(mapped)

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
                idx = lookup[(r, g, b)]
                end = x + 1
                while end < W:
                    rr, gg, bb, aa = pixels[end, y]
                    if aa < 128 or lookup[(rr, gg, bb)] != idx:
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
