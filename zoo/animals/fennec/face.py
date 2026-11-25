"""Фенек: expressive pixel fox with a tapered muzzle and grounded paws."""

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
    # Cream bib and long forelegs braced on the ground, like a seated fox.
    P(0, -41, (-16,-7,-9,-12,9,-12,16,-7,13,0,9,4,7,10,0,17,
                -7,10,-10,5,-14,0), CREAM_SHADE)
    P(-1, -42, (-13,-5,-7,-10,7,-10,14,-5,10,0,6,4,0,14,-7,7,-10,0), CREAM)
    for side in _SIDES:
        # A tucked back foot is visible outside the straighter foreleg.
        back = side * 19
        E(back, -5.1, 7.6, 4.75, AMBER, 1)
        E(back-.65, -5.65, 6, 3.1, ORANGE)
        R(back-1.15, -3.8, 1.25, 1.6, DEEP)
    for side in _SIDES:
        x = side * 9.8
        step = max(0, lift * side)
        P(x, 0, (-5*side,-36,4*side,-37,6.8*side,-31,6.5*side,-20,
                 4.9*side,-4-step,3.7*side,1-step,-4*side,1-step,
                 -5.7*side,-6-step,-3.5*side,-20), DEEP)
        P(x, 0, (-3.1*side,-34,3.8*side,-35,5.2*side,-30,4.9*side,-20,
                 3.25*side,-6-step,2.5*side,-1-step,-2.6*side,-1-step,
                 -3.7*side,-6-step,-2*side,-20), ORANGE if side > 0 else HONEY)
        P(x, 0, (-2.6*side,-18,2.6*side,-16,2.8*side,-6-step,2.1*side,-2-step,
                 -2.4*side,-2-step,-3.0*side,-7-step), CREAM_SHADE)
        E(x, -2.1-step, 6.9, 4.35, DEEP)
        E(x-.6, -2.8-step, 5.8, 3.35, CREAM_SHADE)
        E(x-1.15, -3.6-step, 4.4, 1.75, CREAM)
        R(x-2.2, -1.45-step, 1.1, 1.5, AMBER)
        R(x+1.4, -1.45-step, 1.1, 1.5, AMBER)

    # The huge fanned ears are taller than the forehead and visibly pink.
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
    # A small projecting snout with its own shadow and lit plane.
    P(0, -64.1+nod, (-12,0,-8,-5,-4,-8,4,-8,9,-4,12,1,8,7,2,10,
                     -4,9,-9,6), CREAM_SHADE)
    P(-.7, -64.8+nod, (-9,0,-6,-4,-3,-6,4,-6,7,-3,9,1,5,6,1,8,
                      -4,7,-7,5), (255, 235, 195))


    anchors = ((-12.8, -78+nod), (12.8, -78+nod))
    for side, (x, y) in zip(_SIDES, anchors):
        if asleep or eyes == 'fechados':
            A(x, y+.85, 4.6, 2.45, INK, 2, 2)
        elif eyes in ('feliz','alegre'):
            A(x, y+2.8, 5.25, 4.2, INK, 1, 2)
        elif eyes == 'sono':
            A(x, y+.4, 5.15, 3.9, INK, 2, 2)
            E(x, y+1.95, 3.1, 1.4, AMBER_EYE)
        else:
            # Small, rounder eyes, two diagonal sparkles and a tiny lash
            # at each outer corner, as in the hand-drawn close-up.
            wide = eyes in ('susto','assustado')
            E(x, y, 5.65, 5.7 if wide else 5.15, INK)
            E(x, y+.45, 4.4, 4.5 if wide else 4.0, AMBER_EYE)
            E(x, y+.9, 3.7, 3.3, GOLD_EYE)
            E(x, y-.25, 2.95, 3.45 if wide else 3.05, PUPIL)
            P(x, y, (2.7*side,-3.8, 3.6*side,-6.7, 4.4*side,-6.7,
                     4.15*side,-3.8, 6.15*side,-5.3, 6.4*side,-4.1,
                     4.7*side,-2.6), INK)
            R(x-1.95, y-2.85, 1.9, 1.8, LUSTRE)
            R(x+1.45, y+1.2, 1.0, 1.0, LUSTRE)
    for x in (-21, 21):
        E(x, -69.5+nod, 3.85, 2.1, (136,164,102) if sick else (242,155,151))
    for x, y in ((-10,-65), (-13,-64), (10,-65), (13,-64)):
        E(x,y+nod,1,.72,DEEP)
    # Soft triangular black nose, edged by a tiny, warm specular line.
    P(0, -64.5+nod, (-6.2,-1.9,-3.9,-4.2,3.7,-4.2,6.1,-2.3,5.9,.1,
                    3,3.3,0,4.8,-3.1,3.3,-5.9,.4), INK)
    P(0, -64.5+nod, (-4.9,-1.7,-3.1,-3.2,2.9,-3.2,4.8,-1.9,3,.3,
                    -.4,.8,-3.3,-.1), (97, 63, 66))
    R(-2.8, -67.4+nod, 3.05, 1.15, (177, 129, 118))
    R(-.7, -60.25+nod, 1.4, 2.5, INK)
    if mouth in ('o','aberta') or (action=='eating' and (now//170)%2):
        E(0, -56.5+nod, 3.7, 3.05, INK)
        E(0, -55.8+nod, 2.1, 1.15, PINK)
    elif mouth == 'triste':
        A(0, -57.8+nod, 4.1, 2.9, INK, 1, 2)
    elif not asleep:
        A(-2.8, -58.8+nod, 3.4, 2.4, INK, 2, 2)
        A(2.8, -58.8+nod, 3.4, 2.4, INK, 2, 2)
    return anchors
