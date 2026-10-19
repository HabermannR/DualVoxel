import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from headless_api import VoxelEditor  # noqa: E402
from postprocess import LOOKS, Look, finish  # noqa: E402


def night_scene():
    """A dark blue picture with one bright moon pixel and one glowing red patch."""
    rgb = np.full((120, 100, 3), (10, 12, 30), np.uint8)
    rgb[20, 70] = (240, 245, 250)
    rgb[80:86, 30:36] = (200, 20, 25)
    return rgb


class PostprocessTests(unittest.TestCase):
    def test_none_is_the_picture_as_traced(self):
        rgb = night_scene()
        self.assertIs(finish(rgb, "none"), rgb)

    def test_every_look_keeps_shape_and_type(self):
        rgb = night_scene()
        for name in LOOKS:
            out = finish(rgb, name)
            self.assertEqual(out.shape, rgb.shape, name)
            self.assertEqual(out.dtype, np.uint8, name)

    def test_bloom_spreads_light_around_glows(self):
        rgb = night_scene()
        plain = finish(rgb, Look(tone=True))
        glow = finish(rgb, Look(tone=True, bloom=0.9, bloom_red=0.8))
        self.assertGreater(int(glow[20, 73].sum()), int(plain[20, 73].sum()))   # beside the moon
        self.assertGreater(int(glow[83, 38, 0]), int(plain[83, 38, 0]))         # red bleeds out of the patch

    def test_black_stays_black_under_the_night_grade(self):
        rgb = np.zeros((40, 40, 3), np.uint8)
        out = finish(rgb, Look(tone=True, shadow_tint=(-0.15, 0.0, 0.25), black_crush=0.012))
        self.assertEqual(int(out.max()), 0)

    def test_grain_is_repeatable(self):
        rgb = night_scene()
        np.testing.assert_array_equal(finish(rgb, "night"), finish(rgb, "night"))

    def test_unknown_look(self):
        with self.assertRaises(ValueError):
            finish(night_scene(), "glossy")

    def test_render_rejects_unknown_look_before_the_engine(self):
        editor = VoxelEditor()
        editor.new_model(4, 4, 4)
        editor.paint_box([0, 0, 0], [3, 3, 3], 14)
        with self.assertRaisesRegex(ValueError, "look"):
            editor.render_png(look="glossy")
        self.assertIsNone(editor._engine)


if __name__ == "__main__":
    unittest.main()
