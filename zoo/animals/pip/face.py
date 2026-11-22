"""Pip: adapt the existing tiny renderer to the universal Zoo ABI."""
from zoo.pip.face import render as _render

def render(E, R, P, A, eyes='normal', mouth='sorriso', sick=False, draw_eyes=True):
    return _render(E, R, eyes, mouth, sick, draw_eyes)

