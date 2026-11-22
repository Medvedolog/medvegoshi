#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include "face.h"

#define PIP_EYE_MIN_W 16
#define PIP_EYE_MIN_H 12
#define PIP_EYE_MAX_W 160
#define PIP_EYE_MAX_H 96
#define PIP_EYE_POSE_SIZE 8

/* Draw only in an exclusively owned, aligned tile of exactly words pixels.
 * pose: gaze x/y (-1..1), lid L/R (0..1), smile (0..1), roll (-1..1),
 * heart (0..1), blush (0..1). Zero is a transparent blit key.
 * Bounds conservative and inclusive, not a validity mask.
 * Must be called by one thread: upstream face_draw uses static scratch.
 */
bool pip_eyes_tile_draw(uint16_t *tile, size_t words, int w, int h,
                        const float pose[PIP_EYE_POSE_SIZE], bool swapped,
                        face_rect_t *bounds);
