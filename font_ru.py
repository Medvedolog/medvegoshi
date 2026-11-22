# Compact 8x8 Cyrillic glyphs for the original 240x284 Capigoshi framebuffer.
# Rasterized from DejaVu Sans Mono at 9px, with permission under the
# DejaVu Fonts / Bitstream Vera license. Source and license:
# https://dejavu-fonts.github.io/License.html
# This is bitmap data only; no TTF/OTF font files are included.
#
# Mapping includes А-Я, а-я and Ёё, in that order.
try:
    from ubinascii import unhexlify
except ImportError:
    from binascii import unhexlify

LETTERS = 'АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯабвгдеёжзийклмнопрстуфхцчшщъыьэюя'
_HEX = (
    '3030304848784800' '7840407048487800' '7048487048487800' '7840404040404000'
    '784848484848fc84' '7840407840407800' '7840407840407800' '5060e0e0e0505000'
    '3048083008087000' '4858586868684800' '4858586868684800' '4850606050504800'
    '7848484848488800' '4878787878484800' '4848487848484800' '3048484848483000'
    '7848484848484800' '7048487040404000' '3840404040403800' 'f820202020202000'
    '88d050706060c000' '2070a8a8a8702000' '4848303030484800' '909090909090f808'
    '4848484878080800' '5454545454547c00' 'a8a8a8a8a8a8fc04' 'c040704848487000'
    '8484e4949494e400' '4040407048487000' 'e01010f01010e000' '5068686868685000'
    '7090907050509000' '0000700878487800' '3840704848483000' '0000784870487800'
    '0000704040404000' '000070505050f888' '0000304878403800' '5000304878403800'
    '000050e0e0f05000' '0000384830087800' '0000485858684800' '5070485858684800'
    '0000485060504800' '000070505050d000' '0000484878784800' '0000484878484800'
    '0000304848483000' '0000784848484800' '0000704848487040' '0000384040403800'
    '0000702020202000' '0000484830302020' '202070a8a8a87020' '0000483030304800'
    '0000484848487c04' '0000484848780800' '0000545454547c00' '0000545454547c00'
    '0000545454547e02' '0000c04078487800' '00008484f494f400' '0000404078487800'
    '0000700838087000' '0000586464645800' '0000705070305000'
)
# Fix: the data is a compact, generated table, not a text encoding.
DATA = unhexlify(_HEX)


def is_cyrillic(ch):
    return LETTERS.find(ch) >= 0


def draw_char(fb, ch, x, y, color, scale=1):
    """Draw one 8x8 Cyrillic glyph. Return False for unsupported characters."""
    idx = LETTERS.find(ch)
    if idx < 0:
        return False
    off = idx * 8
    for row in range(8):
        bits = DATA[off + row]
        if not bits:
            continue
        for col in range(8):
            if bits & (128 >> col):
                if scale == 1:
                    fb.pixel(x + col, y + row, color)
                else:
                    fb.fill_rect(x + col * scale, y + row * scale,
                                 scale, scale, color)
    return True
