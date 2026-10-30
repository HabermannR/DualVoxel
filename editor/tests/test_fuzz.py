"""Fuzz (group "fuzz", the renderer's kind 9) and the graded fogs: the table, how the renderer reads a fuzz
material, and on the GPU (SKIP_GPU=1 skips) a fuzz body in its colour whose small tufts come out softer
than matte voxels of the same size."""
import json
import os
import sys
import unittest
from pathlib import Path

import numpy as np

EDITOR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EDITOR))
import sandbox  # noqa: E402,F401  the user's own editor and settings are left alone
from headless_api import VoxelEditor  # noqa: E402
from test_gas import patch, picture  # noqa: E402

TABLE = json.loads((EDITOR.parent / "palette" / "materials.json").read_text(encoding="utf-8"))["materials"]
BY_NAME = {m["name"]: m for m in TABLE}


class FuzzTableTests(unittest.TestCase):
    def test_the_fuzz_materials_and_fog_levels(self):
        fuzz = [m["name"] for m in TABLE if m["group"] == "fuzz"]
        self.assertEqual(fuzz[:5], ["moss", "felt", "fur", "wool", "dust"])
        self.assertEqual(len(fuzz), 16)
        fogs = ["faintest haze", "faint haze", "thin haze", "haze", "light mist", "mist", "heavy mist", "fog",
                "thick fog", "dense fog"]  # the guide's ladder, thinnest first
        self.assertEqual({BY_NAME[n]["group"] for n in fogs}, {"gas"})
        densities = [BY_NAME[n]["density"] for n in fogs]
        self.assertEqual(densities, sorted(densities, reverse=True))  # thinnest first

    def test_the_renderer_reads_fuzz_as_its_own_kind(self):
        from voxel_renderer import FUZZ_STYLE, material_fields, style_of
        from qtui.material_rules import USED, reading
        fur = BY_NAME["fur"]
        self.assertEqual(style_of(fur), FUZZ_STYLE)
        what, fields = reading(fur)
        self.assertTrue(what.startswith("fuzz (kind 9)"), what)
        self.assertEqual({f for f, (status, _) in fields.items() if status == USED},
                         {"density", "sss", "roughness", "sheen"})
        self.assertEqual(material_fields(fur)[5], fur["sss"])  # the reach goes in sss's place


@unittest.skipIf(os.environ.get("SKIP_GPU") == "1", "SKIP_GPU=1")
class FuzzRenderTests(unittest.TestCase):
    def test_a_fuzz_body_in_its_colour_and_its_tufts_softer_than_matte(self):
        e = VoxelEditor()
        self.addCleanup(e.close)
        e.new_model(48, 24, 14)
        floor, red = e.model.nearest_slot((90, 110, 140)), e.model.nearest_slot((200, 40, 40))
        e.paint_box([0, 0, 0], [47, 23, 0], floor)
        e.paint_box([6, 8, 1], [7, 9, 2], red, 0)  # a 2 x 2 x 2 matte tuft
        e.paint_box([18, 8, 1], [19, 9, 2], red, BY_NAME["fur"]["id"])  # the same in fur
        e.paint_box([30, 6, 1], [39, 15, 10], red, BY_NAME["felt"]["id"])  # a felt block
        rgb = picture(e, 0, 35, "Day", samples=384)
        if not hasattr(e._engine.dll, "renderer_set_floor"):
            self.skipTest("this renderer build is older than gas")
        r, g, b = patch(e, rgb, 0, 35, (35, 6, 6))  # the felt block's front: red, not see-through
        self.assertGreater(r, 1.6 * b, (r, g, b))
        redness = lambda x: (lambda p: p[0] - p[2])(patch(e, rgb, 0, 35, (x, 8, 2)))
        self.assertLess(redness(19), 0.8 * redness(7), "a fur tuft should be softer, its edge thinner, than matte")

    def test_a_ledge_seen_edge_on_shows_no_slit(self):
        """A step of plush seen level with its ledge: a ray skimming the ledge meets the pile under the next step
        up (the fuzz field), not the sky behind the block, which once showed as a white slit along the ledge."""
        e = VoxelEditor()
        self.addCleanup(e.close)
        e.new_model(40, 24, 16)
        red, plush = e.model.nearest_slot((200, 40, 40)), BY_NAME["plush"]["id"]
        e.paint_box([6, 4, 0], [33, 19, 5], red, plush)  # the lower step
        e.paint_box([6, 11, 6], [33, 19, 11], red, plush)  # the upper step, set back
        # the eye half a voxel above the ledge (the orbit's centre is 8 voxels up, the camera 1.45 x 40 voxels
        # off), so rays come in through the ledge's top at a glance
        pitch = -np.degrees(np.arcsin(1.5 / (1.45 * 40)))
        rgb = picture(e, 0, pitch, "Day", samples=256)
        engine = e._engine
        eye, forward, right, up = engine.orbit_camera(0, pitch)
        point = np.asarray(engine.origin[:3]) + np.asarray((20, 11, 6)) / 32 - eye  # the ledge's back edge
        height, width = rgb.shape[:2]
        fov = np.tan(np.radians(22.5))
        x = int(((point @ right) / ((point @ forward) * fov * width / height) + 1) / 2 * width)
        y = int((1 - (point @ up) / ((point @ forward) * fov)) / 2 * height)
        band = rgb[y - 6:y + 7, x - 40:x + 41]  # rows across the ledge line, over the middle of the block
        rows = band[..., 0].mean(axis=1) - band[..., 2].mean(axis=1)
        self.assertGreater(rows.min(), 0.15, f"a row along the ledge is not red but sky: {rows.round(2)}")


if __name__ == "__main__":
    unittest.main()
