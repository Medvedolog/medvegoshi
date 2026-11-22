"""Use the SAME MedveGoshi game artist on AMOLED V1 without cloning main.py.

Preview only: all real sensors/game save management remain disabled until
the full HAL is verified on physical Waveshare V1. No filesystem writes.
"""
def show_giraffe(screen, art=None):
    if art is None:
        import desenho as art  # Shared original game renderer, no duplicate
    art.usar(screen.fb)
    screen.fb.fill(art.C(art.CREME))
    art.centro("MedveGoshi", 12, art.INK, 1)
    art.centro("Жирафик", 38, art.TEXTO, 1)
    art.personagem("girafa", 120, 218,
                   olhos="feliz", boca="sorriso", fase="adulto")
    art.centro("SH8601 / V1", 252, art.INK, 1)
    screen.mostrar()
