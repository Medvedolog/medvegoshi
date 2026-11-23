"""Host only: rasterize the native body and heading from Noto Sans Bold.

Run from the root:
  python -m ports.gen_v1_menu_font /usr/share/fonts/truetype/noto/NotoSans-Bold.ttf

Pinned input: Google Noto Sans Bold v2.004 from Debian fonts-noto-core.
SHA-256 e83493c945848ecd4a9ad0f6d19164541a0d3e23a9c952304a00a46e00272ac5.
The checked-in output used Pillow 13.0.0 / FreeType 2.14.3.
"""
import argparse
from hashlib import sha256
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from ports import v1_menu_font as target

MARKER = '# Generated font spans below. Do not edit by hand.\n'
FONT_SHA = 'e83493c945848ecd4a9ad0f6d19164541a0d3e23a9c952304a00a46e00272ac5'


def rasterize(font, size_index):
    offsets = bytearray(b'\0\0')
    widths, spans = bytearray(), bytearray()
    chars = ''.join(chr(u) for u in range(32, 127))
    chars += ''.join(chr(u) for u in range(0x0410, 0x0450)) + target._EXTRA
    height, baseline, pad = target.height(size_index), target.baseline(size_index), target._X_PAD
    assert len({font.getlength(c) for c in '0123456789'}) == 1, 'digits should be tabular'
    for ch in chars:
        left, top, right, bottom = font.getbbox(ch, anchor='ls')
        if not (-pad <= left and top + baseline >= 0 and bottom + baseline <= height):
            raise ValueError('glyph would be cropped: ' + repr(ch))
        width = right + pad
        image = Image.new('L', (width, height))
        ImageDraw.Draw(image).text((pad, baseline), ch, font=font, fill=255, anchor='ls')
        coverage = image.point([(pixel * 3 + 127) // 255 for pixel in range(256)])
        for y in range(height):
            x = 0
            while x < width:
                alpha = coverage.getpixel((x, y))
                if not alpha:
                    x += 1
                    continue
                start = x
                while x < width and x < start + 16 and coverage.getpixel((x, y)) == alpha:
                    x += 1
                if not (y < 32 and start < 32):
                    raise ValueError('span would overflow: ' + repr(ch))
                spans.extend(((y << 3) | (alpha << 1) | (start >> 4),
                              ((start & 15) << 4) | (x - start - 1)))
        widths.append(round(font.getlength(ch) * 4))
        offsets.extend(len(spans).to_bytes(2, byteorder='little'))
    return widths, offsets, spans


def literals(name, data):
    # No decoding or per-glyph allocations on device. repr keeps ASCII runs
    # compact while escaping all bytes that would be unsafe in Python source.
    lines = [name + ' = (']
    for i in range(0, len(data), 24):
        lines.append('    ' + repr(bytes(data[i:i + 24])))
    return '\n'.join(lines + [')', ''])


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('font', type=Path)
    args = p.parse_args()
    if sha256(args.font.read_bytes()).hexdigest() != FONT_SHA:
        p.error('expected the pinned Noto Sans Bold asset')
    output = Path(target.__file__)
    header, found, _ = output.read_text(encoding='utf-8').partition(MARKER)
    if not found:
        p.error('expected the generated data marker')
    font_tables = []
    for size, index, name in ((16, 1, 'BODY'), (25, 2, 'HEADING')):
        font = ImageFont.truetype(str(args.font), size)
        for field, data in zip(('WIDTHS', 'OFFSETS', 'SPANS'), rasterize(font, index)):
            font_tables.append(literals('_%s_%s' % (name, field), data))
    output.write_text(header + MARKER + '\n'.join(font_tables), encoding='utf-8')


if __name__ == '__main__':
    main()
