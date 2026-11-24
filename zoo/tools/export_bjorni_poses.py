"""Build the crisp game sprite sheet from the original Bjorni animation artwork.

Inputs: the 1536x2288 Bjorni v2 image and the six separate game-state images
from the original project art. This is a host tool (uses Pillow); the device
receives only the bounded generated data in face.py.
"""
import argparse
from pathlib import Path

from PIL import Image

from zoo.tools.build_bjorni_frames import COLS, FRAME_COUNT, H, ROOT, W


# Select coherent source poses without carrying the profile-only gaze rows.
_SELECTION = (
    (0, (0, 1, 4, 5)), (1, (0, 2, 4, 6)), (2, (0, 2, 4, 6)),
    (4, (0, 1, 2, 3, 4)), (3, (0, 1, 2, 3)), (5, (0, 2, 4, 6)),
    (6, (0, 1, 3, 5)), (7, (0, 2, 3, 5)), (8, (0, 2, 3, 5)),
    (0, (2,)),
)
_EXTRA = ('sleepy', 'asleep', 'hungry', 'eating', 'sick', 'surprised')


def export(atlas_path, extra_dir, output):
    with Image.open(atlas_path) as image:
        atlas = image.convert('RGBA')
    if atlas.size != (1536, 2288):
        raise ValueError('unexpected Bjorni source sheet dimensions')
    sources = []
    for row, cols in _SELECTION:
        for col in cols:
            sources.append((atlas.crop((col * 192, row * 208, (col + 1) * 192, (row + 1) * 208)),
                            0.269))
    for state in _EXTRA:
        with Image.open(extra_dir / (state + '.png')) as image:
            if image.size != (342, 513):
                raise ValueError('unexpected state art dimensions: ' + state)
            sources.append((image.convert('RGBA'), 0.102))
    if len(sources) != FRAME_COUNT:
        raise ValueError('unexpected Bjorni frame count')

    sheet = Image.new('RGBA', (COLS * W, ((FRAME_COUNT + COLS - 1) // COLS) * H))
    for i, (image, scale) in enumerate(sources):
        bounds = image.getchannel('A').point(lambda alpha: 255 if alpha >= 130 else 0).getbbox()
        if bounds is None:
            raise ValueError('empty source pose')
        pose = image.crop(bounds)
        ww, hh = round(pose.width * scale), round(pose.height * scale)
        x, y = round(W / 2 + (bounds[0] - image.width / 2) * scale), H - 1 - hh
        if not (0 <= x and x + ww <= W and 0 <= y):
            raise ValueError('source pose does not fit')
        # Never average neighboring colors when shrinking pixel art. The
        # animation system positions feet and handles vertical jump physics.
        pose = pose.resize((ww, hh), Image.Resampling.NEAREST)
        sheet.paste(pose, (i % COLS * W + x, i // COLS * H + y))
    sheet.save(output, optimize=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--atlas', type=Path, required=True)
    parser.add_argument('--extra-dir', type=Path, required=True)
    parser.add_argument('--out', type=Path, default=ROOT / 'zoo/assets/bjorni-poses.png')
    args = parser.parse_args()
    export(args.atlas, args.extra_dir, args.out)


if __name__ == '__main__':
    main()
