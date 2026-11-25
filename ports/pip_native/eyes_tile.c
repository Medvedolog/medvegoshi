/* Tile adapter; the upstream MIT rasterizer in zoo/upstream/pip is unchanged. */
#include "eyes_tile.h"
#include <math.h>
#include <string.h>

bool pip_eyes_tile_draw(uint16_t *tile, size_t words, int w, int h,
                        const float pose[PIP_EYE_POSE_SIZE], bool swapped,
                        face_rect_t *bounds)
{
    if (!tile || !pose || !bounds || (uintptr_t)tile % _Alignof(uint16_t) ||
        w < PIP_EYE_MIN_W || w > PIP_EYE_MAX_W ||
        h < PIP_EYE_MIN_H || h > PIP_EYE_MAX_H || words != (size_t)w * (size_t)h) {
        return false;
    }
    for (size_t i = 0; i < PIP_EYE_POSE_SIZE; ++i) {
        float lo = i < 2 || i == 5 ? -1.0f : 0.0f;
        if (!isfinite(pose[i]) || pose[i] < lo || pose[i] > 1.0f) {
            return false;
        }
    }

    face_t face = {
        .color = 0xffbd,
        .pupil_color = 0x0841,  /* dark RGB565, but nonzero for the black key */
        .heart_color = 0xfa2c,
        .blush = pose[7],
        .blush_color = 0xf38c,
        .vein_color = 0xe22b,
        .water_color = 0xa6df,
        .shading = 0.42f,
        .swapped = swapped,
    };
    for (int i = 0; i < 4; ++i) {
        face.drawn[i] = (face_rect_t){0, 0, -1, -1};
    }
    const float ew = fminf(w * 0.35f, h * 0.72f);
    const float eh = fminf(h * 0.67f, ew * 1.16f);
    for (int i = 0; i < 2; ++i) {
        const float sign = i ? 1.0f : -1.0f;
        face.eye[i] = (eye_t) {
            .x = w * 0.5f + sign * w * 0.222f,
            .y = h * 0.45f + sign * pose[5] * h * 0.05f,
            .w = ew, .h = eh, .depth = ew * 0.84f,
            .roll = pose[5] * 0.24f,
            .taper = 0.10f,
            .lid = pose[2 + i],
            .smile = pose[4],
            .look_x = pose[0] * 0.82f,
            .look_y = pose[1] * 0.64f,
            .pw = 0.40f, .ph = 0.42f,
            .heart = pose[6], .glint = 0.9f,
        };
    }
    memset(tile, 0, words * sizeof(*tile));
    *bounds = face_draw(&face, tile, w, h);
    return true;
}
