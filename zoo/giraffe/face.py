# MedveGoshi Zoo — original procedural giraffe ("Жирафик").
# Clean-room artwork: no Giraffegotchi sprite files are copied.
# Inspired by its optional-animal architecture, not by an external character.
#
# The same drawing primitives as the original Capigoshi are used.
YELLOW = (250, 198, 82)
SHADE = (197, 137, 64)
LIGHT = (255, 225, 135)
DARK = (113, 72, 38)
SPOT = (175, 112, 47)
HOOF = (111, 81, 61)
BLUSH = (240, 142, 138)
SICK = (164, 185, 136)
WHITE = (255, 250, 233)


def render(E, R, P, A, eyes='normal', mouth='sorriso', sick=False):
    """Draw a gentle spotted giraffe relative to its hoof/ground anchor.

    E: ellipse(dx,dy,rx,ry,color,outside)
    R: rectangle(dx,dy,w,h,color)
    P: polygon(dx,dy,tuple_coords,color)
    A: arc(dx,dy,rx,ry,color,half,...)
    Returns two eye positions relative to the anchor.
    """
    # Four small hoofs below the oval body and a long neck on the right.
    for x in (-26, -12, 15, 26):
        R(x - 4, -21, 8, 19, YELLOW)
        E(x, -3, 7, 4, HOOF, True)
    E(-2, -31, 39, 25, SHADE, True)
    E(-2, -32, 37, 23, YELLOW)
    E(13, -66, 14, 38, SHADE, True)
    E(13, -66, 12, 37, YELLOW)

    # Giraffe's characteristic irregular neck/body patches.
    for x, y, rx, ry in ((-24, -37, 8, 7), (-2, -28, 9, 8),
                         (22, -34, 8, 6), (10, -54, 6, 8),
                         (19, -73, 5, 7), (8, -85, 4, 4)):
        E(x, y, rx, ry, SPOT)
    # Little tail with brown tuft.
    R(-42, -40, 14, 3, SHADE)
    E(-46, -40, 5, 7, SPOT)
    # Ossicones, ears and tufts.
    R(-3, -122, 5, 15, YELLOW)
    R(25, -122, 5, 15, YELLOW)
    E(0, -123, 6, 5, SPOT)
    E(28, -123, 6, 5, SPOT)
    E(-13, -108, 16, 7, SHADE, True)
    E(-13, -108, 14, 6, YELLOW)
    E(41, -108, 16, 7, SHADE, True)
    E(41, -108, 14, 6, YELLOW)

    # Head and snout.
    E(14, -102, 32, 22, SHADE, True)
    E(14, -102, 30, 21, YELLOW)
    E(15, -91, 25, 14, LIGHT)
    E(7, -94, 3, 2, DARK)
    E(27, -94, 3, 2, DARK)

    if eyes in ('fechados', 'sono', 'dormindo'):
        E(-2, -107, 8, 2, DARK)
        E(24, -107, 8, 2, DARK)
    elif eyes in ('feliz', 'alegre'):
        A(-2, -108, 8, 6, DARK, 1, 2)
        A(24, -108, 8, 6, DARK, 1, 2)
    else:
        for xx in (-2, 24):
            E(xx, -108, 8, 9, WHITE)
            E(xx, -107 + (3 if eyes in ('triste', 'chorando') else 0), 4, 6, DARK)
            E(xx - 2, -110, 1, 2, WHITE)

    if mouth in ('triste', 'dormindo') or eyes in ('triste', 'chorando'):
        E(16, -88, 8, 2, DARK)
        R(8, -90, 16, 3, LIGHT)
    elif mouth in ('aberta', 'o', 'surpresa') or eyes in ('susto', 'assustado'):
        E(16, -88, 5, 7, DARK)
    else:
        E(16, -88, 9, 4, DARK)
        R(6, -92, 20, 5, LIGHT)

    if sick:
        E(-12, -95, 6, 3, SICK)
        E(37, -95, 6, 3, SICK)
    elif eyes not in ('fechados', 'sono', 'dormindo'):
        E(-12, -95, 5, 3, BLUSH)
        E(37, -95, 5, 3, BLUSH)
    return ((-2, -108), (24, -108))
