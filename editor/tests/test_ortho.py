"""The orthographic view: the Render dock's camera can draw with parallel rays (renderer_set_projection),
the wheel then narrowing the view instead of bringing the eye nearer; the Render setup dock's Ortho box and the
Render picture dialog switch it, greyed out with a renderer from before it. The renderer part runs on the GPU
unless SKIP_GPU=1: two equal cubes, one near and one far, come out the same size only without perspective."""
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path

import numpy as np

EDITOR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EDITOR))
sys.path.insert(0, str(EDITOR.parent / "engine"))
sys.path.insert(0, str(EDITOR / "tests"))
import sandbox  # noqa: E402,F401  the user's own editor and settings are left alone
from core.camera import FOV_TAN, OrbitCamera  # noqa: E402
from test_render_picture import FakeEngine, FakeRenderer  # noqa: E402

SKIP_GPU = os.environ.get("SKIP_GPU") == "1"


class CameraTests(unittest.TestCase):
    def test_framing_sets_both_views_to_show_the_model_alike(self):
        camera = OrbitCamera()
        camera.frame((0, 0, 0), 2.0)
        self.assertAlmostEqual(camera.distance, 2.9)
        self.assertAlmostEqual(camera.ortho_height, 2.9 * FOV_TAN)  # the perspective view's height at the target

    def test_switching_keeps_the_model_as_large_and_stands_the_eye_clear_of_it(self):
        camera = OrbitCamera()
        camera.frame((0, 0, 0), 2.0)
        camera.zoom(5)  # a perspective eye brought close
        near = camera.distance
        camera.set_ortho(True)
        self.assertAlmostEqual(camera.ortho_height, near * FOV_TAN, places=5)
        self.assertAlmostEqual(float(np.linalg.norm(camera.pos)), 4.0, places=4)  # twice the model: none behind it
        np.testing.assert_allclose(camera.fwd, -camera.pos / np.linalg.norm(camera.pos), atol=1e-6)
        camera.set_ortho(False)
        self.assertAlmostEqual(camera.distance, near, places=5)
        self.assertAlmostEqual(float(np.linalg.norm(camera.pos)), near, places=4)

    def test_the_wheel_narrows_an_orthographic_view_and_panning_follows_its_size(self):
        camera = OrbitCamera()
        camera.frame((0, 0, 0), 2.0)
        camera.set_ortho(True)
        distance, height = camera.distance, camera.ortho_height
        camera.zoom(2)
        self.assertEqual(camera.distance, distance)
        self.assertAlmostEqual(camera.ortho_height, height * 0.81, places=5)
        camera.pan(100, 0)
        self.assertAlmostEqual(float(np.linalg.norm(camera.target)), 100 * 0.0015 * camera.ortho_height / FOV_TAN,
                               places=5)


class OlderRendererTests(unittest.TestCase):
    def test_a_renderer_from_before_draws_perspective_and_refuses_ortho(self):
        from voxel_renderer import VoxelRenderer
        renderer = object.__new__(VoxelRenderer)
        renderer.dll = types.SimpleNamespace()  # none of the new calls
        self.assertFalse(renderer.has_projection)
        renderer.projection(False)
        renderer.fov(60)
        with self.assertRaisesRegex(RuntimeError, "newer one"):
            renderer.projection(True, 1.0)

    def test_a_newer_one_gets_the_calls(self):
        from voxel_renderer import VoxelRenderer
        calls = []
        renderer = object.__new__(VoxelRenderer)
        renderer.dll = types.SimpleNamespace(renderer_set_projection=lambda *a: calls.append(("projection", *a)),
                                             renderer_set_fov=lambda *a: calls.append(("fov", *a)))
        renderer.projection(True, 1.5)
        renderer.fov(30)
        self.assertEqual(calls, [("projection", 1, 1.5), ("fov", 30.0)])

    def test_each_live_frame_sends_the_cameras_projection(self):
        from engine_view import EngineView
        engine = object.__new__(EngineView)
        engine.renderer = FakeRenderer()
        engine.rgba = np.zeros((4, 4, 4), np.uint8)
        engine.samples, engine.animated, engine.last_frame = 0, False, 0.0
        camera = OrbitCamera()
        camera.set_ortho(True)
        engine.frame(camera, False)
        self.assertEqual(engine.renderer.projections, [(True, camera.ortho_height)])


class RenderDockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6 import QtWidgets
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

    def setUp(self):
        from qtui.document import Document
        from qtui.render_view import RenderView
        self.doc = Document()
        self.doc.new(8, 8, 8, ground=2)
        self.view = RenderView(self.doc)
        self.view.resize(300, 200)
        self.path = Path(tempfile.mkdtemp()) / "still.png"

    def run_still(self):
        for _ in range(100):
            if self.view.still is None:
                return
            self.view.tick()
        self.fail("the still never finished")

    def test_the_ortho_box_switches_the_dock_and_shows_what_it_draws(self):
        from qtui.render_setup_panel import RenderSetupPanel
        engine = self.view.engine = FakeEngine()
        panel = RenderSetupPanel(self.view)
        self.assertTrue(panel.ortho_box.isEnabled())
        engine.samples = 99
        panel.ortho_box.setChecked(True)
        self.assertTrue(self.view.camera.ortho)
        self.assertEqual(engine.samples, 0)  # the new picture draws even when the old one had settled
        self.view.set_ortho(False)  # from elsewhere: the box follows
        self.assertFalse(panel.ortho_box.isChecked())

    def test_with_an_older_renderer_the_box_is_greyed_out_and_says_why(self):
        from qtui.render_setup_panel import RenderSetupPanel
        engine = self.view.engine = FakeEngine()
        engine.renderer.has_projection = False
        panel = RenderSetupPanel(self.view)
        self.assertFalse(panel.ortho_box.isEnabled())
        self.assertIn("needs a newer renderer", panel.ortho_box.toolTip())
        self.assertIn("perspective only", self.view.render_still(self.path, 64, 64, 100, ortho=True))

    def test_a_picture_may_be_orthographic_while_the_dock_stays_perspective(self):
        engine = self.view.engine = FakeEngine()
        camera = self.view.camera
        camera.frame((0, 0, 0), 1.0)
        self.assertIsNone(self.view.render_still(self.path, 64, 64, 300, ortho=True))
        self.run_still()
        self.assertEqual(engine.renderer.projections, [(True, camera.distance * FOV_TAN)] * 3)  # each step
        self.assertFalse(camera.ortho)
        eye = engine.renderer.views[0][0]
        self.assertAlmostEqual(float(np.linalg.norm(eye)), 2.0, places=4)  # stood clear of the model

    def test_a_picture_as_the_dock_draws_and_an_orbit_keep_its_projection(self):
        engine = self.view.engine = FakeEngine()
        self.view.set_ortho(True)
        height = self.view.camera.ortho_height
        self.view.render_still(self.path, 64, 64, 100)
        self.run_still()
        self.view.render_orbit(self.path.with_suffix(".gif"), 32, 24, 100, frames=2, fps=8)
        self.run_still()
        self.assertEqual(set(engine.renderer.projections), {(True, height)})


@unittest.skipIf(SKIP_GPU, "SKIP_GPU=1")
class RendererTests(unittest.TestCase):
    """Two equal red cubes on the table, one near the eye and one far behind it, seen from the front and above."""

    def setUp(self):
        from headless_api import VoxelEditor
        self.editor = e = VoxelEditor()
        self.addCleanup(e.close)
        e.new_model(48, 96, 16)
        red = e.model.nearest_slot((220, 20, 20))
        e.paint_box([4, 4, 0], [15, 15, 11], red)  # left and near (yaw 0 looks from -y)
        e.paint_box([32, 80, 0], [43, 91, 11], red)  # right and far
        e.render_png(0, 20, 64, 64, 1, "Day")  # starts the engine with the model and the light
        self.engine = e._engine
        if not self.engine.has_projection:
            self.skipTest("this renderer build is from before the orthographic view")

    def cubes(self, ortho):
        width, height = 480, 320
        size = max(self.engine.size)
        self.engine.projection(ortho, 1.45 * size * FOV_TAN)
        rgba = self.engine.render(width, height, 0, 20, samples=32).astype(int)
        red = (rgba[..., 0] > rgba[..., 1] + 60) & (rgba[..., 0] > rgba[..., 2] + 60)
        return red[:, :width // 2].sum(), red[:, width // 2:].sum()

    def test_without_perspective_near_and_far_cubes_are_the_same_size(self):
        near, far = self.cubes(False)
        self.assertGreater(near, 2 * far, (near, far))  # perspective: the near one much larger
        near, far = self.cubes(True)
        self.assertGreater(far, 500)
        self.assertAlmostEqual(near / far, 1, delta=0.06)
        again = self.cubes(False)  # and back: the perspective view as before
        self.assertGreater(again[0], 2 * again[1])


if __name__ == "__main__":
    unittest.main()
