"""High-resolution pictures: save_render (and the MCP render_file) take print sizes that a picture handed back
may not; the Render dock draws a still of any size in steps and saves it finished; File > Render picture… and
the Light dock's button ask for it. Orbit animations (animation.py, File > Export orbit animation…) draw
their frames the same way. No GPU here: a stand-in engine draws."""
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

EDITOR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EDITOR))
import sandbox  # noqa: E402,F401  the user's own editor and settings are left alone
from headless_api import VoxelEditor  # noqa: E402


class FakeRenderer:
    """Fills the picture with one colour, `step` samples a call, as render_frame does in capture mode."""
    reconstruction = 1
    centre = (0.0, 0.0, 0.0)
    has_projection = True

    def __init__(self, step=100):
        self.step, self.done, self.captures, self.views, self.times = step, 0, [], [], []
        self.projections = []

    def projection(self, ortho, half_height=1.0):
        self.projections.append((ortho, half_height))

    def capture_time(self, seconds):
        self.times.append(seconds)

    def capture(self, samples):
        self.captures.append(samples)
        self.done = 0

    def frame(self, out, eye, forward, right, up, moving):
        self.views.append((tuple(eye), out.shape))
        out[...] = (200, 40, 30, 255)
        self.done += self.step
        return self.done


class FakeEngine:
    def __init__(self):
        self.renderer = FakeRenderer()
        self.samples, self.last_frame, self.shown_version = 0, 0.0, 0
        self.synced = 0

    def sync(self, model, camera, force=False):
        self.synced += 1


class HeadlessLimitTests(unittest.TestCase):
    def setUp(self):
        self.editor = VoxelEditor()
        self.editor.new_model(4, 4, 4)
        self.editor.paint_box([0, 0, 0], [3, 3, 3], 14)

    def test_a_picture_handed_back_stays_screen_sized(self):
        with self.assertRaisesRegex(ValueError, "1080"):
            self.editor.render_png(width=2160, height=2700)
        self.assertIsNone(self.editor._engine)

    def test_a_saved_picture_may_be_print_sized_up_to_its_own_limit(self):
        with self.assertRaisesRegex(ValueError, "8192"):
            self.editor.save_render("too_big.png", width=9000, height=9000)
        with self.assertRaisesRegex(ValueError, "4096"):
            self.editor.save_render("too_many.png", width=2160, height=2700, samples=5000)
        self.assertIsNone(self.editor._engine)  # refused before the engine starts

    def test_an_orbit_is_checked_before_the_engine_starts(self):
        with self.assertRaisesRegex(ValueError, "frames 2-"):
            self.editor.save_orbit("one.gif", frames=1)
        with self.assertRaisesRegex(ValueError, ".gif"):
            self.editor.save_orbit("orbit.avi")
        self.assertIsNone(self.editor._engine)


class AnimationTests(unittest.TestCase):
    def test_a_full_turn_starts_at_the_view_and_loops_an_arc_is_centred_and_a_swing_goes_out_and_back(self):
        from animation import orbit_angles
        np.testing.assert_allclose(orbit_angles(4, 360), [0, 90, 180, 270])
        np.testing.assert_allclose(orbit_angles(3, 90), [-45, 0, 45])
        np.testing.assert_allclose(orbit_angles(3, -90), [45, 0, -45])
        np.testing.assert_allclose(orbit_angles(4, 90, swing=True), [0, 45, 0, -45], atol=1e-9)

    def test_views_turn_about_the_centre_keeping_height_and_distance(self):
        from animation import orbit_views
        views = orbit_views((0, -2, 1), (0, 1, 0), (1, 0, 0), (0, 0, 1), (0, 0, 0), 4, 360)
        np.testing.assert_allclose(views[1][0], (2, 0, 1), atol=1e-9)  # a quarter turn counter-clockwise
        np.testing.assert_allclose(views[1][1], (-1, 0, 0), atol=1e-9)  # still looking at the centre
        for eye, *_ in views:
            self.assertAlmostEqual(float(np.hypot(eye[0], eye[1])), 2)
            self.assertAlmostEqual(float(eye[2]), 1)

    def test_gif_and_webp_need_nothing_more_and_other_files_are_refused(self):
        from PIL import Image
        from animation import FrameWriter
        folder = Path(tempfile.mkdtemp())
        for name in ("a.gif", "a.webp"):
            writer = FrameWriter(folder / name, 8, 6, fps=10)
            for shade in (0, 120, 240):
                writer.add(np.full((6, 8, 3), shade, np.uint8))
            with Image.open(writer.close()) as picture:
                self.assertEqual((picture.size, picture.n_frames), ((8, 6), 3))
        with self.assertRaisesRegex(ValueError, "orbit is saved as"):
            FrameWriter(folder / "a.avi", 8, 6, fps=10)
        writer = FrameWriter(folder / "b.gif", 8, 6, fps=10)
        writer.add(np.zeros((6, 8, 3), np.uint8))
        writer.abort()
        self.assertFalse((folder / "b.gif").exists())
        with self.assertRaisesRegex(ValueError, "GB"):  # held in memory: refused before it starts
            FrameWriter(folder / "c.webp", 1080, 1350, fps=30, frames=300)
        self.assertFalse((folder / "c.webp").exists())


class RenderStillTests(unittest.TestCase):
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
        self.ended = []
        self.view.still_finished.connect(lambda path, message: self.ended.append((path, message)))

    def run_still(self):
        for _ in range(100):
            if self.view.still is None:
                return
            self.view.tick()
        self.fail("the still never finished")

    def test_without_the_renderer_it_says_so(self):
        self.assertEqual(self.view.render_still(self.path, 640, 480, 64), "The renderer is not running.")

    def test_sizes_samples_and_finish_are_checked(self):
        self.view.engine = FakeEngine()
        self.assertIn("8192", self.view.render_still(self.path, 9000, 480, 64))
        self.assertIn("4096", self.view.render_still(self.path, 640, 480, 9999))
        self.assertIn("finish", self.view.render_still(self.path, 640, 480, 64, look="glossy"))
        self.assertIsNone(self.view.still)

    def test_a_still_draws_in_steps_at_its_own_size_and_saves_finished(self):
        from PIL import Image
        engine = self.view.engine = FakeEngine()
        self.view.camera.pos = np.array([1.0, 2.0, 3.0])
        self.assertIsNone(self.view.render_still(self.path, 2160, 2700, 300, look="none"))
        self.assertEqual(self.view.render_still(self.path, 640, 480, 64), "A picture is already rendering.")
        self.view.camera.pos = np.array([9.0, 9.0, 9.0])  # moving the camera meanwhile leaves the picture alone
        self.run_still()
        self.assertEqual(len(engine.renderer.views), 3)  # 300 samples, 100 a step
        self.assertTrue(all(view == ((1.0, 2.0, 3.0), (2700, 2160, 4)) for view in engine.renderer.views))
        self.assertEqual(engine.renderer.captures, [300, 0])  # back to live frames after
        self.assertEqual(engine.shown_version, -1)  # the live view catches up with edits made meanwhile
        self.assertEqual(self.ended, [(str(self.path), f"Saved a 2160 x 2700 picture (300 spp) to {self.path}")])
        picture = Image.open(self.path)
        self.assertEqual(picture.size, (2160, 2700))
        self.assertEqual(picture.getpixel((5, 5)), (200, 40, 30))

    def test_the_finish_is_applied(self):
        from PIL import Image
        self.view.engine = FakeEngine()
        self.view.render_still(self.path, 64, 64, 100, look="night")
        self.run_still()
        self.assertNotEqual(Image.open(self.path).getpixel((32, 32)), (200, 40, 30))

    def test_a_picture_is_taken_from_the_view_not_from_the_swinging_preview(self):
        self.view.engine = FakeEngine()
        yaw = self.view.camera.yaw
        self.view.preview_orbit({"degrees": 60, "swing": True, "seconds": 4})
        self.view.preview["start"] -= 1
        self.view._preview_step()
        self.view.render_still(self.path, 64, 64, 100)
        self.assertIsNone(self.view.preview)
        self.assertEqual(self.view.camera.yaw, yaw)

    def test_cancel_saves_nothing_and_goes_back_to_live_frames(self):
        engine = self.view.engine = FakeEngine()
        self.view.render_still(self.path, 640, 480, 1000)
        self.view.tick()
        self.view.cancel_still()
        self.assertIsNone(self.view.still)
        self.assertFalse(self.path.exists())
        self.assertEqual(engine.renderer.captures, [1000, 0])
        self.assertEqual(self.ended, [("", "Picture cancelled.")])

    def test_an_orbit_draws_each_frame_at_its_angle_and_moment_and_writes_them(self):
        from PIL import Image
        class Shaded(FakeRenderer):  # a shade of its own a frame: a GIF merges repeated frames
            def frame(self, out, *view):
                done = super().frame(out, *view)
                out[..., 0] = 40 * len(self.views)
                return done

        engine = self.view.engine = FakeEngine()
        engine.renderer = Shaded()
        self.view.camera.pos = np.array([0.0, -2.0, 1.0])
        path = self.path.with_suffix(".gif")
        self.assertIsNone(self.view.render_orbit(path, 32, 24, 100, frames=4, fps=8, degrees=90))
        self.run_still()
        angles = [round(float(np.degrees(np.arctan2(eye[1], eye[0]))), 6) for eye, _ in engine.renderer.views]
        self.assertEqual(angles, [-135, -105, -75, -45])  # an arc of 90 degrees centred on the view
        self.assertEqual(engine.renderer.times, [0, 0.125, 0.25, 0.375, 0])  # each frame's moment, then back
        self.assertEqual(engine.renderer.captures, [100, 100, 100, 100, 0])
        with Image.open(path) as gif:
            self.assertEqual((gif.size, gif.n_frames), ((32, 24), 4))
        self.assertEqual(self.ended, [(str(path), f"Saved a 32 x 24 orbit, 4 frames (0.5 s), to {path}")])

    def test_a_cancelled_orbit_leaves_no_file(self):
        self.view.engine = FakeEngine()
        path = self.path.with_suffix(".webp")
        self.view.render_orbit(path, 32, 24, 100, frames=6, fps=8)
        self.view.tick()
        self.view.cancel_still()
        self.assertFalse(path.exists())
        self.assertEqual(self.ended, [("", "Animation cancelled.")])

    def test_the_preview_swings_the_live_camera_and_puts_it_back(self):
        camera = self.view.camera
        yaw = camera.yaw
        states = []
        self.view.preview_changed.connect(states.append)
        self.view.preview_orbit({"degrees": 60, "swing": True, "seconds": 4})
        self.view.preview["start"] -= 1  # a quarter of the way: out at one end of the arc
        self.view._preview_step()
        self.assertAlmostEqual(camera.yaw, yaw - np.radians(30), places=4)
        self.view.preview_orbit(None)
        self.assertEqual(camera.yaw, yaw)
        self.assertEqual(states, [True, False])

    def test_a_gpu_the_renderer_cannot_use_stops_the_dock_with_its_message(self):
        class FailingEngine(FakeEngine):
            closed = False

            def frame(self, camera, moving):  # the first frame makes the Vulkan device
                raise RuntimeError("No GPU here can run the path tracer")

            def close(self):
                self.closed = True

        engine = self.view.engine = FailingEngine()
        self.view.isVisible = lambda: True
        self.view._tick.start()
        self.view.tick()
        self.view.tick()  # one already queued: the message stays
        self.assertIsNone(self.view.engine)
        self.assertTrue(engine.closed)
        self.assertFalse(self.view._tick.isActive())
        self.assertEqual(self.view.message, "Renderer unavailable:\nNo GPU here can run the path tracer")


class WindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6 import QtWidgets
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

    def test_file_menu_and_light_dock_ask_for_a_picture_in_the_render_docks_shape(self):
        from PySide6 import QtCore, QtWidgets
        from qtui.window import EditorWindow
        window = EditorWindow()
        window._engine_started = True
        window.settings = QtCore.QSettings(str(Path(tempfile.mkdtemp()) / "layout.ini"),
                                           QtCore.QSettings.Format.IniFormat)
        window.confirm_close = lambda: True
        try:
            file = next(m for m in window.menuBar().findChildren(QtWidgets.QMenu) if m.title() == "&File")
            self.assertIn("Render picture…", [a.text() for a in file.actions()])
            self.assertIn("Render video…", [a.text() for a in file.actions()])
            self.assertEqual({"Light", "Render setup", "Export"} - set(window.docks), set())
            view = next(m for m in window.menuBar().findChildren(QtWidgets.QMenu) if m.title() == "&View")
            listed = [a.text() for a in view.actions() if not a.isSeparator()]
            self.assertEqual(set(window.docks) - set(listed), set())  # every dock can be shown again
            self.assertEqual(len(listed), len(set(listed)))
            export = window.export_panel
            self.assertEqual(export.picture_button.text(), "Render picture…")
            window.render_view.resize(400, 500)
            export.width_box.setValue(800)
            settings = export.orbit_settings()
            self.assertEqual(settings["height"], 1000)  # the dock's 4:5 kept
            self.assertEqual((settings["degrees"], settings["swing"], settings["frames"], settings["fps"]),
                             (60, True, 300, 30))  # an arc swung out and back over 10 s, not a full turn
            export.seconds_box.setValue(4)
            self.assertEqual(export.frames_label.text(), "120 frames")
            window.render_view.resize(400, 500)
            dialog, read = window.picture_form()
            boxes = dialog.widgets
            boxes["width"].setValue(2000)
            self.assertEqual(boxes["height"].value(), 2500)  # the dock's 4:5 kept
            boxes["height"].setValue(1000)
            self.assertFalse(boxes["keep"].isChecked())  # a height of one's own
            boxes["look"].setCurrentText("night")
            boxes["path"].setText(str(Path(tempfile.mkdtemp()) / "shot"))
            self.assertFalse(boxes["ortho"].isChecked())  # as the Render dock draws
            boxes["ortho"].setChecked(True)
            path, width, height, samples, look, ortho = read()
            self.assertTrue(path.endswith("shot.png"))
            self.assertEqual((width, height, samples, look, ortho), (2000, 1000, 512, "night", True))
            self.assertIn("Ortho", [b.text() for b in window.setup_panel.findChildren(QtWidgets.QCheckBox)])
            window.render_view.still = {"rgba": np.zeros((4, 4, 4), np.uint8), "done": 0, "samples": 1}
            window.render_view.still_changed.emit(True)
            self.assertEqual(export.picture_button.text(), "Cancel picture")
            self.assertFalse(export.video_button.isEnabled())
            window.render_view.still["orbit"] = {}
            window.render_view.still_changed.emit(True)
            self.assertEqual(export.video_button.text(), "Cancel video")
            self.assertFalse(export.picture_button.isEnabled())
            window.render_view.still = None
            window.render_view.still_changed.emit(False)
            self.assertEqual((export.video_button.text(), export.picture_button.isEnabled()), ("Render video…", True))
        finally:
            window.close()


if __name__ == "__main__":
    unittest.main()
