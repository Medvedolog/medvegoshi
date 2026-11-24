"""Фенек: pixel art from the sketch's oversized ears, shy paws and w-smile."""

OUTLINE = (113, 62, 46)
DEEP = (159, 76, 42)
AMBER = (208, 97, 43)
ORANGE = (237, 126, 51)
TANGERINE = (252, 158, 70)
HONEY = (255, 191, 103)
CREAM_SHADE = (248, 197, 135)
CREAM = (255, 226, 177)
PINK_SHADE = (180, 71, 91)
PINK = (229, 115, 134)
ROSE = (255, 163, 171)
INK = (46, 30, 40)
PUPIL = (29, 22, 32)
AMBER_EYE = (218, 142, 50)
GOLD_EYE = (255, 209, 92)
LUSTRE = (255, 235, 166)
_SIDES = (-1, 1)
_WALK = (0, 2, 4, 2, 0, -2, -4, -2)
_SWISH = (-1, -3, -4, -2, 0, 2, 3, 1)

_EAR = (-3, 7, 0, -5, 10, -17, 25, -28, 39, -42, 44, -44,
        46, -42, 45, -36, 42, -24, 36, -12, 31, -3, 23, 6, 14, 12, 6, 13)
_EAR_IN = (6, 4, 10, -8, 21, -18, 33, -29, 42, -40, 43, -39,
           41, -31, 37, -19, 31, -8, 24, 0, 18, 7, 12, 10)
_EAR_PINK = (10, 3, 15, -7, 23, -16, 32, -25, 39, -34, 39, -29,
             35, -19, 29, -8, 24, -1, 17, 4)
_EAR_LIGHT = (15, -4, 20, -12, 29, -21, 34, -27, 32, -22,
              28, -14, 22, -7, 18, -2)


def _ear(P, side, anchor_y, tilt):
    def patch(color, whole):
        out = []
        for i in range(0, len(whole), 2):
            x, y = whole[i], whole[i+1]
            out.extend(((x + tilt * max(0, -y) / 44) * side, y))
        P(2 * side, anchor_y, out, color)
    patch(OUTLINE, _EAR)
    # Same silhouette inset a little: leaves a crisp darker edge.
    patch(HONEY, tuple((v * .91 if i % 2 == 0 else v * .93 + .5)
                       for i, v in enumerate(_EAR)))
    patch(PINK_SHADE, _EAR_IN)
    patch(PINK, _EAR_PINK)
    patch(ROSE, _EAR_LIGHT)
    P(14 * side, anchor_y + 4, (-5*side, -1, 8*side, -4, 6*side, 2,
                               3*side, 6, -7*side, 7), CREAM_SHADE)


def render(E, R, P, A, eyes="normal", mouth="sorriso", sick=False, motion=None):
    action, now = motion or ('still', 0)
    facing = -1 if action == 'walk-left' else 1
    asleep = action == 'asleep' or mouth == 'dormindo'
    happy = action in ('greeting', 'happy', 'jump')
    phase = (now // (105 if happy else 175)) % len(_SWISH)
    swish = (5 if asleep else (_SWISH[phase] if action != 'still' else 0))
    lift = (_WALK[(now//83) % len(_WALK)] if action.startswith('walk-')
            else (2 if happy and phase % 2 else 0))
    nod = 2 if asleep or (action == 'eating' and (now//170) % 2) else 0
    # Large fox brush: stays anchored to the rump while the silky tip sways.
    def tail(PA, col):
        out = []
        for i in range(0, len(PA), 2):
            out.extend((PA[i]*facing, PA[i+1] + swish*max(0, PA[i]-16)/30))
        P(0, 0, out, col)
    tail((13,-19, 20,-29, 29,-34, 36,-40, 42,-53, 48,-46, 51,-38, 50,-30,
          46,-22, 40,-15, 30,-10, 21,-10, 13,-13), OUTLINE)
    tail((15,-19, 22,-27, 31,-32, 39,-41, 42,-49, 46,-44, 49,-37, 48,-30,
          44,-22, 38,-16, 29,-12, 22,-12, 15,-14), AMBER)
    tail((21,-21, 32,-32, 38,-37, 43,-46, 46,-42, 48,-37, 46,-30,
          40,-23, 32,-18, 23,-16), TANGERINE)
    tail((32,-32, 38,-40, 42,-49, 46,-44, 49,-37, 48,-30, 43,-25,
          39,-24, 40,-28, 35,-27, 36,-31), CREAM_SHADE)
    tail((37,-36, 42,-47, 45,-43, 47,-37, 46,-32, 42,-28,
          42,-32, 38,-31), CREAM)

    E(-15, -19, 12, 14.5, AMBER, 1); E(15, -19, 12, 14.5, DEEP, 1)
    E(-17, -20, 8.5, 10.5, TANGERINE); E(17, -20, 8, 10.5, ORANGE)
    E(0, -31, 22.4, 28.2, AMBER, 1)
    E(0, -31, 20.5, 26.1, DEEP); E(-1.4, -35, 18.5, 23.2, ORANGE)
    E(-6, -39, 12.4, 16.6, TANGERINE)
    # Cream bib and little front paws coming together like in the drawing.
    P(0, -41, (-16,-7,-9,-12,9,-12,16,-7,13,0,9,4,7,10,0,17,
                -7,10,-10,5,-14,0), CREAM_SHADE)
    P(-1, -42, (-13,-5,-7,-10,7,-10,14,-5,10,0,6,4,0,14,-7,7,-10,0), CREAM)
    for side in _SIDES:
        step = max(0, lift * side)
        P(side*13, -29-step/2, (-6*side,-3,2*side,-5,6*side,-1,4*side,6,
                                -2*side,12,-7*side,12,-7*side,7), DEEP)
        P(side*13, -30-step/2, (-4*side,-2,2*side,-3,4*side,0,2*side,6,
                                -3*side,10,-6*side,10,-5*side,5), ORANGE)
        E(side*5.8, -18-step/2, 4.7, 3.8, HONEY)
        E(side*10.5, -3.7-step, 10.6, 6.3, AMBER, 1)
        E(side*10.5-.6, -4.7-step, 8.8, 4.5, CREAM_SHADE)
        E(side*10.5-1.3, -5.5-step, 6.6, 2.8, CREAM)
        R(side*10.5-.3, -3.2-step, 1.1, 2, AMBER)

    # The huge rounded ears are taller than the forehead and visibly pink.
    bounce = (-2 if happy else (1 if asleep else 0))
    _ear(P, -1, -84 + nod, bounce + 1)
    _ear(P, 1, -84 + nod, bounce - 1)
    P(0, -70+nod, (-29,-14,-33,-5,-34,1,-30,4,-26,5,-24,10,-16,14,
                   -8,17,1,18,9,17,16,14,24,10,27,5,31,3,34,-1,
                   31,-7,28,-14), OUTLINE)
    E(0, -78+nod, 30.8, 19.8, AMBER, 1)
    E(0, -77+nod, 29.7, 19.3, DEEP)
    E(-1.4, -79.4+nod, 28.4, 18.2, ORANGE)
    E(-2.9, -83.1+nod, 25.2, 14.3, TANGERINE)
    E(-8.4, -88.5+nod, 15.1, 7.2, HONEY)
    # Narrow ivory mask: angled cheekbones and a little projecting muzzle.
    P(0, -73+nod, (-32,-1,-27,-8,-18,-10,-10,-7,-5,0,0,2,5,0,10,-7,
                   18,-10,27,-8,31,-1,29,5,22,9,16,13,10,17,1,19,
                   -8,18,-15,14,-21,10,-28,5), CREAM_SHADE)
    P(0, -74+nod, (-29,0,-25,-7,-18,-9,-11,-7,-6,-1,-1,2,4,0,9,-6,
                   16,-8,24,-6,28,-1,26,4,19,7,11,12,7,16,0,18,
                   -7,16,-11,12,-19,8,-25,5), CREAM)
    E(-.4, -62.9+nod, 10.2, 7.7, CREAM_SHADE)
    E(-1.2, -63.7+nod, 8.3, 6.45, CREAM)

    anchors = ((-12.8, -78+nod), (12.8, -78+nod))
    for side, (x, y) in zip(_SIDES, anchors):
        if asleep or eyes == 'fechados':
            A(x, y+1.1, 5.7, 2.9, INK, 2, 2)
        elif eyes in ('feliz','alegre'):
            A(x, y+3.4, 6.7, 5.0, INK, 1, 3)
        else:
            wide = eyes in ('susto','assustado')
            if eyes == 'sono':
                P(x, y, (-7*side,-1,-2*side,1,3*side,1,7*side,-2,
                         4*side,4,0,5,-4*side,4), INK)
                E(x, y+2.8, 3, 1.35, AMBER_EYE)
            else:
                h = 1.14 if wide else 1.0
                P(x, y, (-7.9*side, .9, -5.7*side,-3.2*h, -2.6*side,-4.9*h,
                         2.6*side,-5.6*h, 8.5*side,-4, 6.6*side,1.8*h,
                         3.3*side,4.5*h, -.4*side,5.25*h, -4.7*side,4.1*h), INK)
                P(x, y, (-5.9*side,.7, -3.9*side,-2.4*h, -.9*side,-3.4*h,
                         3.1*side,-4.45*h, 6.6*side,-3.3, 5.1*side,1.3*h,
                         2*side,3.6*h, -.9*side,4.15*h, -3.4*side,3.2*h), AMBER_EYE)
                E(x+.3*side, y+.45, 4.25, 3.3*h, GOLD_EYE)
                E(x+.45*side, y-.05, 2.8 if wide else 2.35, 3.95*h, PUPIL)
                R(x-1.1, y-1.95, 1.4, 1.4, LUSTRE)
    for x in (-21, 21):
        E(x, -69.5+nod, 3.85, 2.1, (136,164,102) if sick else (242,155,151))
    for x, y in ((-10,-65), (-13,-64), (10,-65), (13,-64)):
        E(x,y+nod,1,.72,DEEP)
    P(0, -64.8+nod, (-4.7,-1.6,-2.3,-3,2.4,-3,4.5,-1.7,3,.6,
                    0,2.7,-2.4,.75), INK)
    R(-.65, -63.3+nod, 1.3, 2.5, INK)
    if mouth in ('o','aberta') or (action=='eating' and (now//170)%2):
        E(0, -59+nod, 3.85, 3.75, INK)
        E(0, -58+nod, 2.2, 1.4, PINK)
    elif mouth == 'triste':
        A(0, -57.8+nod, 4.1, 2.9, INK, 1, 2)
    elif not asleep:
        A(-2.8, -61.4+nod, 3.4, 2.55, INK, 2, 2)
        A(2.8, -61.4+nod, 3.4, 2.55, INK, 2, 2)
    return anchors
