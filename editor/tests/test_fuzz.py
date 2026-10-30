"""Fuzz (group "fuzz", the renderer's kind 9) and the graded fogs: the table, how the renderer reads a fuzz
material, and on the GPU (SKIP_GPU=1 skips) a fuzz body in its colour whose small tufts come out softer
than matte voxels of the same size."""
import json
import os
import sys
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
