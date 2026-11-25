"""Рыська / Ryska: a lynx inspired by the family's drawing.

The three hearts, tall ears, rounded head and upright torso come from the
sketch. Only relative, layered game primitives are used: the same pose
works on IPS, native AMOLED, menu thumbnails and the whole-sprite flip.
"""

INK = (65, 42, 40)
RIM = (111, 72, 49)
DARK = (151, 93, 54)
OCHRE = (181, 118, 64)
SAND = (216, 155, 85)
SUN = (242, 183, 105)
GOLD = (251, 202, 133)
CREAM = (255, 223, 172)
MILK = (234, 187, 128)
SPOT = (143, 86, 49)
SPOT_LIGHT = (168, 107, 60)
PINK_SHADOW = (166, 68, 84)
PINK = (224, 110, 128)
PETAL = (250, 155, 151)
PUPIL = (26, 38, 33)
IRIS_SHADE = (64, 113, 75)
IRIS = (130, 191, 119)
GLINT = (213, 230, 177)
SICK_CHEEK = (126, 160, 90)
_HEART = (-7, -1, -7, -4, -4, -6, -1, -5, 0, -3, 1, -5,
          4, -6, 7, -4, 7, -1, 5, 2, 0, 6, -5, 2)
_CHEST = (-13, -2, -13, -8, -8, -11, -4, -10, 0, -6, 4, -10,
          8, -11, 13, -8, 13, -2, 9, 6, 0, 13, -9, 6)
_WALK = (0, 2, 4, 2, 0, -2, -4, -2)


def render(E, R, P, A, eyes='normal', mouth='sorriso', sick=False, motion=None):
    action, now = motion or ('still', 0)
    facing = -1 if action == 'walk-left' else 1
    step = 0
    if action in ('walk-left', 'walk-right'):
        step = _WALK[(now // 90) % len(_WALK)]
    elif action in ('jump', 'greeting'):
        step = 3 if (now // 115) % 2 else 1
    asleep = action == 'asleep' or mouth == 'dormindo'
    nod = 2 if asleep or (action == 'eating' and (now // 155) % 2) else 0
    twitch = 1 if not asleep and action != 'still' and 2 <= (now // 90) % 31 <= 3 else 0

    # Short bobtail with the lynx's dark tip. Its broad root is hidden by
    # the haunch. It never grows beyond a little nub, even while twitching.
    tx = 28 * facing
    ty = -25 + (3 if asleep else -2 * twitch)
    P(23 * facing, ty + 1, (-6*facing, 0, 1*facing, -8, 9*facing, -9,
                             13*facing, -5, 12*facing, 0, 6*facing, 5), RIM)
    E(tx + 3*facing, ty - 2, 5.3, 5.4, DARK)
    P(34 * facing, ty - 3, (-2*facing, -4, 2*facing, -4, 3*facing, -1,
                             2*facing, 3, 0, 4, -2*facing, 2), INK)

    E(-17, -19, 13, 16, OCHRE, 1); E(17, -19, 13, 16, DARK, 1)
    E(-19, -20, 9, 11, SAND); E(18, -20, 9, 11, OCHRE)
    E(0, -36, 23, 32, OCHRE, 1)
    E(0, -35, 21, 29.5, DARK)
    E(-1, -40, 19, 24.5, SAND)
    E(-5, -46, 12, 16, SUN)
    # The large heart from the sketch becomes a cream patch in the fur.
    P(0, -33, _CHEST, MILK)
    P(-1, -35, (-11,-2,-11,-7,-6,-9,-3,-8,0,-4,3,-8,7,-9,11,-7,
                 11,-2,7,5,0,10,-8,5), CREAM)
    for x, y, r in ((-23,-23,2.9),(-21,-29,2.1),(-17,-45,2.5),
                     (-14,-50,1.7),(20,-27,2.6),(16,-41,2.7),(13,-48,1.8)):
        E(x, y, r, r*0.66, SPOT)

    for side in (-1, 1):
        x = side * 11
        lift = max(0, step * side)
        E(x, -13 - lift, 9.4, 14, OCHRE, 1)
        E(x - 0.6, -13.8 - lift, 7.4, 11.5, SAND if side > 0 else SUN)
        E(x, -3.4 - lift, 11, 6, OCHRE, 1)
        E(x - .5, -4.2 - lift, 9.1, 4.4, MILK)
        E(x - 1.7, -5.0 - lift, 7.1, 3.0, CREAM)
        R(x - 2.7, -2.9 - lift, 1.2, 2.0, DARK)
        R(x + 2.1, -2.9 - lift, 1.2, 2.0, DARK)
        E(x + side*4, -16 - lift, 1.9, 1.65, SPOT)

    # Pointed ears and ink-black tufts. The tiny asymmetry follows the
    # sketch's uneven tuft heights without changing the head anchor.
    for side in (-1, 1):
        fur_y = -111 + nod + (twitch if side > 0 else 0)
        P(side*20, fur_y, (-9*side, 17, 1*side, -8, 7*side, -7,
                            15*side, 10, 13*side, 19), RIM)
        P(side*20, fur_y, (-6*side, 14, 2*side, -6, 6*side, -5,
                            13*side, 10, 11*side, 15), SAND)
        P(side*20, fur_y, (-2*side, 12, 4*side, 0, 9*side, 11, 7*side, 14), PINK_SHADOW)
        P(side*20, fur_y, (-1*side, 11, 4*side, 3, 7*side, 10, 6*side, 12), PETAL)
        P(side*24, fur_y-5, (-2*side, 5, -3*side, 0, -1*side, -7,
                            0, -7, 1*side, -3, 4*side, -8, 3*side, -1,
                            6*side, -3, 5*side, 3, 3*side, 7), INK)

    # Round face above the pointed lynx cheek ruffs; fur has the same
    # discrete, warm shadow layers as Caramel.
    for side in (-1, 1):
        P(side*25, -78+nod, (-5*side,-10, 8*side,-3, 13*side,2, 9*side,4,
                             12*side,9, 7*side,9, 8*side,14, 1*side,12,
                             -6*side,9), RIM)
        P(side*25, -78+nod, (-4*side,-8, 7*side,-2, 10*side,2, 7*side,4,
                             9*side,7, 5*side,7, 5*side,11, -5*side,7), MILK)
    E(0, -83+nod, 31.2, 25, OCHRE, 1)
    E(0, -82+nod, 29.8, 23.2, DARK)
    E(-1, -85+nod, 28.5, 21.6, SAND)
    E(-3, -88+nod, 25.5, 17.6, SUN)
    E(-10, -95+nod, 14, 8.1, GOLD)
    E(0, -73+nod, 19.7, 11.7, MILK)
    E(-6, -75+nod, 12.4, 8.1, CREAM); E(6, -75+nod, 11.8, 8.0, CREAM)
    for x, y, w, h in ((-18,-99,2.6,1.6),(-10,-102,2.9,1.8),(-2,-104,1.7,1.25),
                        (16,-99,2.6,1.6),(21,-96,1.65,1.15),(8,-103,2,1.4)):
        E(x, y+nod, w, h, SPOT_LIGHT)

    glance = -1 if action == 'walk-left' else (1 if action == 'walk-right' else 0)
    anchors = ((-13.7, -88+nod), (13.7, -88+nod))
    for x, y in anchors:
        if eyes in ('feliz', 'alegre'):
            A(x, y+3.8, 7.2, 5.6, INK, 1, 3)
        elif asleep or eyes == 'fechados':
            A(x, y+.6, 6.6, 3.5, INK, 2, 2)
        else:
            wide = eyes in ('susto', 'assustado')
            E(x, y, 7.7, 8.6 if wide else 7.9, INK)
            E(x, y+.4, 6.2, 6.65, IRIS_SHADE)
            E(x, y+1.45, 5.7, 5.4, IRIS)
            E(x+glance, y-.15, 2.6 if wide else 3.65, 4.25 if wide else 5.25, PUPIL)
            if eyes == 'sono':
                R(x-7.8, y-8, 15.6, 7.4, SUN)
            else:
                R(x+glance-1.7, y-2.35, 1.55, 1.35, GLINT)
    for x in (-22, 22):
        P(x, -76.5+nod, _HEART, SICK_CHEEK if sick else PINK_SHADOW)
        P(x, -77.35+nod, (-6,-1,-6,-3,-3,-5,0,-2,3,-5,6,-3,6,-1,4,2,0,5,-4,2),
          SICK_CHEEK if sick else PINK)
        if not sick:
            E(x-3.4, -79.4+nod, 1.45, .95, PETAL)

    P(0, -76+nod, (-5,-1,-3,-3,3,-3,5,-1,2.5,2.7,0,4,-2.5,2.7), INK)
    R(-.75, -73+nod, 1.5, 4, INK)
    if mouth in ('o','aberta') or (action == 'eating' and (now // 155) % 2):
        E(0, -68+nod, 4.2, 3.8, INK)
        E(.25, -67+nod, 2.25, 1.55, PINK)
    elif mouth == 'triste':
        A(0, -66+nod, 4.9, 3.5, INK, 1, 2)
    elif not asleep:
        A(-3.0, -70+nod, 3.7, 3.0, INK, 2, 2)
        A(3.0, -70+nod, 3.7, 3.0, INK, 2, 2)
        if action == 'greeting':
            E(0, -66+nod, 2, 1.55, PINK)
    return anchors
