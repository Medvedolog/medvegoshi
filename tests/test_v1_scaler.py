"""Shared touch/paint scale and endian invariants on the host."""
import unittest

from ports.v1_scale import (LOGICAL_W, LOGICAL_H, VIEWPORT_LARGE, VIEWPORT_NATIVE,
                            Scaler, viewport_for)


class V1ScalerTests(unittest.TestCase):
    def test_all_logical_pixels_roundtrip_through_both_viewports(self):
        for viewport in (VIEWPORT_NATIVE, VIEWPORT_LARGE):
            for y in range(LOGICAL_H):
                for x in range(LOGICAL_W):
                    p = viewport.logical_to_physical(x, y)
                    if viewport.physical_to_logical(*p) != (x, y):
                        self.fail((p, x, y))

    def test_scaled_pixels_use_the_same_mapping_as_touch_at_every_position(self):
        v = VIEWPORT_LARGE
        scaler = Scaler(v)
        source = bytearray(scaler.input_bytes)
        for i in range(0, len(source), 2):
            source[i] = i // 2 % 251
            source[i + 1] = i // (2 * LOGICAL_W) % 239
        wire = bytearray(scaler.output_bytes)
        scaler.copy(source, wire)
        self.assertEqual(len(wire), 320160)
        for y in range(v.height):
            for x in range(v.width):
                lx, ly = v.physical_to_logical(x + v.x, y + v.y)
                dst, src = (y * v.width + x) * 2, (ly * LOGICAL_W + lx) * 2
                if (wire[dst], wire[dst + 1]) != (source[src], source[src + 1]):
                    self.fail((x, y, lx, ly))
        for p in ((-1, 6), (368, 6), (0, 5), (367, 441), (0, 448)):
            self.assertIsNone(v.physical_to_logical(*p))

    def test_short_or_shared_buffer_and_unknown_mode_fail(self):
        scaler = Scaler(VIEWPORT_LARGE)
        good = bytearray(scaler.input_bytes)
        for output in (bytearray(1), good):
            with self.assertRaises(ValueError):
                scaler.copy(good, output)
        with self.assertRaises(ValueError):
            viewport_for('stretch')


if __name__ == '__main__':
    unittest.main()
