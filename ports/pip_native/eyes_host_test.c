/* Desktop test against the exact vendored rasterizer; no MicroPython needed. */
#include "eyes_tile.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

static uint16_t guarded[(size_t)PIP_EYE_MAX_W * PIP_EYE_MAX_H + 2];
static uint16_t baseline[(size_t)PIP_EYE_MAX_W * PIP_EYE_MAX_H];

static size_t visible(const uint16_t *data, size_t n)
{
    size_t nonzero = 0;
    for (size_t i = 0; i < n; ++i) nonzero += data[i] != 0;
    return nonzero;
}

static void render_case(int w, int h, const float pose[8], bool swapped, face_rect_t *r)
{
    uint16_t *tile = guarded + 1;
    const size_t pixels = (size_t)w * (size_t)h;
    guarded[0] = guarded[pixels + 1] = 0x93ec;
    assert(pip_eyes_tile_draw(tile, pixels, w, h, pose, swapped, r));
    assert(guarded[0] == 0x93ec && guarded[pixels + 1] == 0x93ec);
    assert(!tile[0] && !tile[w - 1] && !tile[pixels - 1] && !tile[pixels - w]);
    if (r->x2 >= r->x1) {
        assert(r->x1 >= 0 && r->y1 >= 0 && r->x2 < w && r->y2 < h);
    }
    for (int y = 0; y < h; ++y) {
        for (int x = 0; x < w; ++x) {
            if (tile[y * w + x] != 0) {
                assert(x >= r->x1 && x <= r->x2 && y >= r->y1 && y <= r->y2);
            }
        }
    }
}

int main(void)
{
    const float neutral[8] = {0};
    const float shut[8] = {0, 0, 1, 1, 0, 0, 0, 0};
    const float smile[8] = {0.8f, -0.3f, 0, 0.4f, 0.6f, 0.7f, 0.9f, 0.6f};
    uint16_t *tile = guarded + 1;
    face_rect_t r;
    const size_t n = 72 * 36;
    render_case(72, 36, neutral, false, &r);
    const size_t normal_pixels = visible(tile, n);
    assert(normal_pixels > 100 && normal_pixels < n / 2);
    memcpy(baseline, tile, n * 2);
    size_t pupils = 0;
    for (size_t i = 0; i < n; ++i) pupils += baseline[i] == 0x0841;
    assert(pupils > 0);
    render_case(72, 36, neutral, true, &r);
    for (size_t i = 0; i < n; ++i) {
        assert(tile[i] == (uint16_t)((baseline[i] << 8) | (baseline[i] >> 8)));
    }
    render_case(72, 36, shut, false, &r);
    assert(visible(tile, n) < normal_pixels / 4);
    render_case(72, 36, smile, false, &r);
    assert(memcmp(tile, baseline, n * 2));
    render_case(16, 12, neutral, true, &r);
    render_case(16, 96, smile, false, &r);
    render_case(160, 12, smile, false, &r);
    render_case(160, 96, smile, true, &r);
    float bad[8] = {NAN};
    tile[0] = 0x4421;
    assert(!pip_eyes_tile_draw(tile, n, 72, 36, bad, true, &r));
    assert(!pip_eyes_tile_draw(tile, n - 1, 72, 36, neutral, true, &r));
    assert(!pip_eyes_tile_draw(tile, n, 161, 36, neutral, true, &r));
    assert(tile[0] == 0x4421);
    puts("Pip upstream C eye tile passed");
}
