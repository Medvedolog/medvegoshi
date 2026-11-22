# MedveGoshi Zoo — optional face pack.
#
# An original lightweight MicroPython reinterpretation of the *idea* of Pip's
# expressive, eye-led design. Not a translation of the Pip-KeyPet 3D C renderer.
# Inspired by David Novikov's MIT project:
# https://github.com/NovikovVisuals/Pip-KeyPet
#
# Signature: ellipse(dx, dy, rx, ry, rgb, outside=False) and
# rect(dx, dy, width, height, rgb). Coordinates are relative to the
# feet origin and get scaled by the caller's existing _rel() helpers.
# No files, dynamic allocations or hardware imports are needed per frame.

BODY = (39, 40, 83)
BODY_RIM = (21, 23, 58)
BODY_HIGHLIGHT = (67, 72, 132)
EYE = (249, 251, 250)
PUPIL = (35, 45, 89)
SHINE = (255, 255, 255)
CHEEK = (245, 131, 176)
SICK = (132, 167, 153)


def render(ellipse, rect, eyes='normal', mouth='sorriso', sick=False, draw_eyes=True):
    """Draw a small Pip-style creature with expressions. Returns eye anchors.

    This is a deterministic vector character, not a sprite or the official
    Pip-KeyPet renderer. Suitable for the original IPS framebuffer; the same
    primitives can later be used by the AMOLED V1 platform layer.
    """
    E, R = ellipse, rect
    E(0, -42, 35, 43, BODY_RIM, True)
    E(0, -44, 33, 42, BODY, True)
    E(-10, -72, 18, 9, BODY_HIGHLIGHT)
    E(-17, -58, 6, 3, SICK if sick else CHEEK)
    E(17, -58, 6, 3, SICK if sick else CHEEK)

    closed = eyes in ('fechados', 'sono', 'dormindo')
    pleased = eyes in ('feliz', 'alegre')
    scared = eyes in ('susto', 'assustado')
    sad = eyes in ('triste', 'chorando')
    shift = (-4 if eyes in ('esquerda', 'olhar_esq') else
             4 if eyes in ('direita', 'olhar_dir') else 0)

    if draw_eyes:
        for x in (-15, 15):
            if closed:
                E(x, -79, 11, 3, EYE)
            elif pleased:
                E(x, -79, 12, 8, EYE)
                E(x, -82, 8, 4, BODY)
            else:
                E(x, -80, 12, 16 if scared else 14, EYE)
                E(x + shift, -79 + (3 if sad else 0), 5 if scared else 7, 8, PUPIL)
                E(x + shift - 2, -82 + (3 if sad else 0), 2, 3, SHINE)

    # Mouth drawn only with existing ellipse/rect primitives (low CPU cost).
    if mouth in ('dormindo', 'triste') or sad:
        E(0, -45, 10, 3, PUPIL)
        R(-8, -46, 16, 3, BODY)
    elif mouth in ('aberta', 'o', 'surpresa') or scared:
        E(0, -47, 6, 9, PUPIL)
        E(0, -43, 3, 3, CHEEK)
    else:
        E(0, -47, 10, 5, PUPIL)
        R(-11, -51, 22, 5, BODY)

    return ((-15, -80), (15, -80))

