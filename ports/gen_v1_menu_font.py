"""Host only: regenerate the bitmap font using Pillow and DejaVu Sans Mono Bold.

Run from the root:
  python -m ports.gen_v1_menu_font /path/to/DejaVuSansMono-Bold.ttf

The checked-in data used Pillow 13.0.0 / FreeType 2.14.3 and a font with
SHA-256 0d3c03d1b667192f91223660a3163325cf83132662fe4d9f7d6e596bf7a995c2.
"""
import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from ports import v1_menu_font as target

MARKER = '# Generated font spans below. Do not edit by hand.\n'
SIZE, BASELINE, THRESHOLD = 15, 11, 96


def rasterize(font):
    offsets, spans = bytearray(b'\0\0'), bytearray()
    chars = ''.join(chr(u) for u in range(32, 127))
    chars += ''.join(chr(u) for u in range(0x0410, 0x0450)) + target._EXTRA
    for ch in chars:
        left, top, right, bottom = font.getbbox(ch, anchor='ls')
        baseline = max(BASELINE, -top)  # make room for accents in this glyph
        x = (target.ADVANCE - round(font.getlength(ch))) // 2
        if not (bottom + baseline <= target.HEIGHT and 0 <= x + left <= x + right <= target.ADVANCE):
            raise ValueError('glyph would be cropped: ' + repr(ch))
        image = Image.new('L', (target.ADVANCE, target.HEIGHT))
        ImageDraw.Draw(image).text((x, baseline), ch, font=font, fill=255, anchor='ls')
        for y in range(target.HEIGHT):
            x = 0
            while x < target.ADVANCE:
                if image.getpixel((x, y)) < THRESHOLD:
                    x += 1
                    continue
                start = x
                while x < target.ADVANCE and image.getpixel((x, y)) >= THRESHOLD:
                    x += 1
                spans.extend(((y << 4) | start, x - start))
        offsets.extend(len(spans).to_bytes(2, byteorder='little'))
    return offsets, spans


def literals(name, data):
    # Avoid runtime hex decoding and intermediate glyph/row containers.
    lines = [name + ' = (']
    for i in range(0, len(data), 18):
        lines.append("    b'" + ''.join('\\x%02x' % n for n in data[i:i + 18]) + "'")
    return '\n'.join(lines + [')', ''])


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('font', type=Path)
    args = p.parse_args()
    font = ImageFont.truetype(str(args.font), SIZE)
    if font.getname() != ('DejaVu Sans Mono', 'Bold'):
        p.error('expected DejaVu Sans Mono Bold')
    offsets, spans = rasterize(font)
    output = Path(target.__file__)
    header, _, _ = output.read_text(encoding='utf-8').partition(MARKER)
    output.write_text(header + MARKER + literals('_OFFSETS', offsets) + '\n'
                      + literals('_SPANS', spans), encoding='utf-8')


if __name__ == '__main__':
    main()
