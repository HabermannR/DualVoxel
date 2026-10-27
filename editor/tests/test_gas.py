"""Gas in the renderer, on synthetic scenes (the GPU; SKIP_GPU=1 skips): a thick body of white steam stays
white instead of greying to black, and where two gases touch, each keeps its own look."""
import io
import os
import sys
import unittest
from pathlib import Path

import numpy as np

EDITOR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EDITOR))
import sandbox  # noqa: E402,F401  the user's own editor and settings are left alone
from headless_api import VoxelEditor  # noqa: E402

STEAM, MIST, GLOWING_GAS = 35, 36, 37


def picture(editor, yaw, pitch, light, width=800, height=400, samples=256):
    from PIL import Image
    png = editor.render_png(yaw, pitch, width, height, samples, light)
    return np.asarray(Image.open(io.BytesIO(png)).convert("RGB")).astype(float) / 255


def patch(editor, rgb, yaw, pitch, voxel):
    """The mean colour of a 7 x 7 patch around where a voxel position shows in the picture."""
    engine = editor._engine
    eye, forward, right, up = engine.orbit_camera(yaw, pitch)
    point = np.asarray(engine.origin[:3]) + np.asarray(voxel) / 32 - eye
    depth = point @ forward
    height, width = rgb.shape[:2]
    fov = np.tan(np.radians(22.5))
    u = (point @ right) / (depth * fov * width / height)
    v = (point @ up) / (depth * fov)
    x, y = int((u + 1) / 2 * width), int((1 - v) / 2 * height)
    return rgb[y - 3:y + 4, x - 3:x + 4].reshape(-1, 3).mean(axis=0)


@unittest.skipIf(os.environ.get("SKIP_GPU") == "1", "SKIP_GPU=1")
class GasTests(unittest.TestCase):
    def setUp(self):
        self.editor = VoxelEditor()
        self.addCleanup(self.editor.close)

    def renders_gas(self):
        if not hasattr(self.editor._engine.dll, "renderer_set_floor"):
            self.skipTest("this renderer build is from before gas could be thick")

    def test_thick_steam_stays_white_seen_from_its_shadow_side(self):
        e = self.editor
        e.new_model(48, 30, 28)
        white = e.model.nearest_slot((240, 242, 245))
        e.paint_box([0, 0, 0], [47, 29, 0], e.model.nearest_slot((110, 120, 90)))
        e.paint_box([4, 4, 1], [7, 7, 4], white, STEAM)  # 4 voxels: two scatters deep
        e.paint_box([16, 2, 1], [39, 25, 24], white, STEAM)  # 24: twelve deep
        rgb = picture(e, 180, 5, "Day")  # from behind: what shows has scattered many times
        self.renders_gas()
        thin = patch(e, rgb, 180, 5, (6, 6, 3)).mean()
        thick = patch(e, rgb, 180, 5, (28, 14, 13)).mean()
        self.assertGreater(thick, 0.85 * thin, (thin, thick))  # was 0.46 before

    def test_touching_gases_each_keep_their_own_look(self):
        e = self.editor
        e.new_model(24, 30, 16)
        e.paint_box([0, 0, 0], [23, 29, 0], e.model.nearest_slot((110, 120, 90)))
        e.paint_box([4, 6, 1], [19, 9, 12], e.model.nearest_slot((220, 226, 235)), MIST)  # a sheet of mist in front
        e.paint_box([4, 10, 1], [19, 25, 12], e.model.nearest_slot((120, 235, 90)), GLOWING_GAS)  # glowing behind it
        rgb = picture(e, 0, 5, "Night")  # from the front, at night: only the glow behind can be green
        self.renders_gas()
        r, g, b = patch(e, rgb, 0, 5, (12, 6, 7))
        # the glow's green (bright, so red rises through the tone curve); it was mist all through, a grey
        self.assertGreater(g, 1.25 * r, (r, g, b))
        self.assertGreater(g, 1.8 * b, (r, g, b))


if __name__ == "__main__":
    unittest.main()
