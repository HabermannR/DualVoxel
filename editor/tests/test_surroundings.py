"""Surroundings (core/lights.py): an HDR environment, any OpenEXR from a folder of one's own or a path,
lighting the model instead of the sun and sky, and the floor under it. The renderer part runs on the GPU
unless SKIP_GPU=1 (and only with a renderer build that has them)."""
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

EDITOR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EDITOR))
sys.path.insert(0, str(EDITOR.parent / "engine"))
import sandbox  # noqa: E402,F401  the user's own editor and settings are left alone
from core import lights  # noqa: E402
from voxel_renderer import FLOORS, environment_texels, load_environment  # noqa: E402

SKIP_GPU = os.environ.get("SKIP_GPU") == "1"


def write_exr(path, rgb):
    import OpenEXR
    header = {"compression": OpenEXR.ZIP_COMPRESSION, "type": OpenEXR.scanlineimage}
    OpenEXR.File(header, {"RGB": np.ascontiguousarray(rgb, dtype=np.float32)}).write(str(path))


class FakeRenderer:
    def __init__(self):
        self.calls = []

    def environment(self, rgb, strength=1.0, rotation=0.0):
        self.calls.append(("environment", None if rgb is None else rgb.shape, strength, rotation))

    def environment_light(self, strength=1.0, rotation=0.0):
        self.calls.append(("light", strength, rotation))

    def floor(self, preset="wood", colour=None, roughness=None):
        self.calls.append(("floor", preset, colour, roughness))


class SurroundingsTests(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        rgb = np.full((8, 16, 3), 0.2, np.float32)
        rgb[2, 5] = 400  # a small, bright sun
        write_exr(self.folder / "yard.exr", rgb)
        self.second = Path(tempfile.mkdtemp())
        write_exr(self.second / "dusk.exr", np.full((4, 8, 3), 0.1, np.float32))
        write_exr(self.second / "yard.exr", np.zeros((4, 8, 3), np.float32))  # the first folder's wins
        patcher = mock.patch.object(lights, "environment_folders", lambda: [self.folder, self.second])
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_any_exr_by_its_name_in_the_folder_or_by_a_path(self):
        self.assertIsNone(lights.environment_path("sky"))
        self.assertEqual(lights.environment_path("yard"), self.folder / "yard.exr")
        self.assertEqual(lights.environment_path("yard.exr"), self.folder / "yard.exr")
        self.assertEqual(lights.environment_path(str(self.folder / "yard.exr")), self.folder / "yard.exr")
        self.assertEqual(lights.environment_files(), [self.second / "dusk.exr", self.folder / "yard.exr"])
        self.assertEqual(lights.environment_path("dusk"), self.second / "dusk.exr")
        with self.assertRaisesRegex(ValueError, "No HDR environment"):
            lights.environment_path("studio")  # nothing comes with the editor
        with self.assertRaisesRegex(ValueError, "floor"):
            lights.check_surroundings({"floor": "marble"})

    def test_a_wide_map_is_halved_keeping_its_light_and_sampling_follows_brightness(self):
        rgb = load_environment(self.folder / "yard.exr", max_width=4)
        self.assertEqual(rgb.shape, (2, 4, 3))
        np.testing.assert_allclose(rgb.mean(), load_environment(self.folder / "yard.exr").mean(), rtol=1e-5)
        texels = environment_texels(load_environment(self.folder / "yard.exr"))
        cdf = texels[..., 3].ravel()
        self.assertTrue((np.diff(cdf) >= 0).all())
        self.assertEqual(cdf[-1], 1)
        mass = np.diff(np.concatenate([[0], cdf])).reshape(8, 16)
        self.assertGreater(mass[2, 5], 0.9)  # the sun is drawn nearly always
        even = environment_texels(np.zeros((4, 8, 3), np.float32))[..., 3]
        self.assertAlmostEqual(float(even[1, -1]), 0.5, places=5)  # a dark map: drawn from evenly

    def test_an_environment_is_read_and_sent_once_then_only_its_strength_and_turn(self):
        renderer = FakeRenderer()
        lights.apply_surroundings(renderer, {"environment": "yard", "strength": 2, "rotation": 30, "floor": "mirror"})
        lights.apply_surroundings(renderer, {"environment": "yard", "strength": 0.5, "rotation": 90, "floor": "mirror"})
        lights.apply_surroundings(renderer, None)  # back to the sun and sky on the table
        self.assertEqual(renderer.calls, [
            ("environment", (8, 16, 3), 2.0, 30.0), ("floor", "mirror", None, None),
            ("light", 0.5, 90.0),
            ("environment", None, 1.0, 0.0), ("floor", "wood", None, None)])

    def test_the_render_dock_says_its_surroundings_and_refuses_one_it_cannot_have(self):
        from PySide6 import QtWidgets
        from qtui.document import Document
        from qtui.render_view import RenderView
        QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
        view = RenderView(Document())
        view.set_surroundings(environment="yard", floor="cloth", floor_colour=[0.2, 0.3, 0.4])
        self.assertEqual((view.surroundings["environment"], view.surroundings["floor"]), ("yard", "cloth"))
        with self.assertRaises(ValueError):
            view.set_surroundings(environment="nowhere")
        self.assertEqual(view.surroundings["environment"], "yard")  # the old ones stay

    @unittest.skipIf(SKIP_GPU, "SKIP_GPU=1")
    def test_the_renderer_draws_in_an_environment_on_each_floor(self):
        from PIL import Image
        from headless_api import VoxelEditor
        editor = VoxelEditor()
        try:
            editor.new_model(6, 6, 6)
            editor.paint_box([1, 1, 0], [4, 4, 3], 144)
            plain = np.asarray(Image.open(io.BytesIO(editor.render_png(width=64, height=64, samples=8))))
            if not hasattr(editor._engine.dll, "renderer_set_floor"):
                self.skipTest("this renderer build has no floors or HDR environments")
            for floor in FLOORS:
                lit = np.asarray(Image.open(io.BytesIO(editor.render_png(
                    width=64, height=64, samples=8, surroundings={"environment": "yard", "floor": floor}))))
                self.assertEqual(lit.shape, plain.shape)
                self.assertGreater(np.abs(lit.astype(int) - plain.astype(int)).mean(), 1, floor)
        finally:
            editor.close()


if __name__ == "__main__":
    unittest.main()
