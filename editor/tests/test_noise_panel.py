"""The Noise dock runs the API's noise tools on the open model: on its box, with colours from the Colours dock,
one undo step each, Reroll replacing the last run; and it is a dock of the window."""
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

EDITOR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EDITOR))
import sandbox  # noqa: E402,F401  the user's own editor and settings are left alone


class NoisePanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6 import QtWidgets
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

    def setUp(self):
        from qtui.document import Document
        from qtui.noise_panel import NoisePanel
        self.doc = Document()
        self.doc.new(16, 16, 8, ground=4)  # a floor in the current colour
        self.panel = NoisePanel(self.doc)

    def test_the_box_starts_as_the_whole_model_and_follows_a_new_one(self):
        self.assertEqual(self.panel.box(), ([0, 0, 0], [15, 15, 7]))
        self.doc.new(10, 20, 30)
        self.assertEqual(self.panel.box(), ([0, 0, 0], [9, 19, 29]))
        self.doc.picked = (3, 4, 5)
        self.panel.corner_to_picked("to")
        self.assertEqual(self.panel.box(), ([0, 0, 0], [3, 4, 5]))

    def test_speckle_recolours_only_the_box_in_its_shares_as_one_undo_step(self):
        floor = self.doc.colour
        other = floor % 200 + 7
        self.panel.speckle_colours.add(floor, 0, 1)
        self.panel.speckle_colours.add(other, 0, 1)
        self.panel.speckle_surface.setChecked(False)
        self.panel.set_box((0, 0, 0), (7, 15, 3))  # half the floor
        steps = len(self.doc.model.undo_stack)
        changed = self.panel.apply()
        colour = self.doc.model.colour
        self.assertEqual(changed, 8 * 16 * 4 // 2)  # each colour takes its share exactly
        self.assertEqual(int((colour[:4, :, :8] == other).sum()), changed)
        self.assertFalse((colour[:4, :, 8:] == other).any())  # outside the box: untouched
        self.assertEqual(len(self.doc.model.undo_stack), steps + 1)
        self.doc.undo()
        self.assertFalse((self.doc.model.colour == other).any())

    def test_reroll_replaces_the_last_run_with_a_new_seed(self):
        self.panel.set_tool("erode")
        self.panel.erode_pits.setValue(30)  # percent
        self.panel.apply()
        steps = len(self.doc.model.undo_stack)
        first = self.doc.model.colour.copy()
        self.panel.reroll()
        self.assertEqual(len(self.doc.model.undo_stack), steps)  # replaced, not stacked
        self.assertFalse(np.array_equal(self.doc.model.colour, first))

    def test_terrain_and_scatter_build_ground_with_columns_on_it(self):
        self.doc.new(16, 16, 12)
        grass, flower = self.doc.colour, self.doc.colour % 200 + 9
        self.panel.set_tool("terrain")
        self.panel.terrain_top.add(grass)
        self.panel.set_box((0, 0, 0), (15, 15, 5))
        self.assertGreater(self.panel.apply(), 16 * 16)
        self.assertTrue((self.doc.model.colour[0] > 0).all())  # the floor is ground everywhere
        self.assertFalse(self.doc.model.colour[6:].any())  # nothing above the box
        self.panel.set_tool("scatter")
        self.panel.scatter_tips.add(flower)
        self.panel.scatter_density.setValue(100)
        self.panel.set_box((0, 0, 0), (15, 15, 11))
        self.assertEqual(self.panel.apply(), 16 * 16)  # a dot on every open top voxel
        self.assertEqual(int((self.doc.model.colour == flower).sum()), 16 * 16)

    def test_written_for_people_percentages_one_page_and_what_an_empty_list_means(self):
        self.panel.set_tool("erode")
        self.assertEqual(self.panel.erode_pits.text(), "15.0 %")
        self.assertEqual(self.panel.arguments()[1]["pits"], 0.15)  # the API still takes a fraction
        self.assertEqual(self.panel.erode_scale.text(), "single voxels")
        self.panel.erode_scale.setValue(1)
        self.assertEqual(self.panel.erode_scale.text(), "1 voxel")
        self.panel.erode_scale.setValue(4)
        self.assertEqual(self.panel.erode_scale.text(), "4 voxels")
        self.panel.show()
        self.addCleanup(self.panel.hide)
        visible = [name for name, page in self.panel.page.items() if page.isVisible()]
        self.assertEqual(visible, ["erode"])  # only its own settings: no room kept for a taller page
        self.assertIn("everything in the box", self.panel.about.text())
        self.assertEqual(self.panel.box_size.text(), "16 × 16 × 8 voxels (the whole model)")
        self.panel.set_box((0, 0, 0), (3, 1, 0))
        self.assertEqual(self.panel.box_size.text(), "4 × 2 × 1 voxels")
        self.panel.set_tool("scatter")
        tips = self.panel.scatter_tips
        self.assertTrue(tips.empty.isVisible())
        tips.add_current()
        self.assertFalse(tips.empty.isVisible())
        self.assertEqual(self.panel.arguments()[1]["density"], 0.05)

    def test_a_missing_colour_is_said_not_raised(self):
        steps = len(self.doc.model.undo_stack)
        self.assertIsNone(self.panel.apply())
        self.assertIn("Add a colour", self.panel.status.text())
        self.assertEqual(len(self.doc.model.undo_stack), steps)

    def test_protection_does_not_stop_the_users_own_noise(self):
        self.doc.set_protected(np.argwhere(self.doc.model.colour > 0)[:, ::-1])
        self.panel.set_tool("erode")
        self.panel.erode_pits.setValue(50)
        self.assertGreater(self.panel.apply(), 0)

    def test_the_views_box_follows_the_spin_boxes_and_the_dock_in_sight(self):
        region = self.panel.region
        self.assertEqual((region.start, region.end), ((0, 0, 0), (15, 15, 7)))
        self.panel.set_box((2, 3, 1), (9, 4, 6))
        self.assertEqual((region.start, region.end), ((2, 3, 1), (9, 4, 6)))
        self.panel.corner["to"][0].setValue(1)  # corners in any order: the views see low and high
        self.assertEqual(region.bounds(), ((1, 3, 1), (2, 4, 6)))
        region.set((0, 0, 0), (5, 6, 7))  # a view set it: the spin boxes follow
        self.assertEqual(self.panel.box(), ([0, 0, 0], [5, 6, 7]))
        self.assertFalse(region.shown)
        self.panel.show()
        self.assertTrue(region.shown)
        self.panel.hide()
        self.assertFalse(region.shown)

    def _slice(self, name="Front"):
        """A slice view showing the panel's box, both in sight."""
        from qtui.slice_view import SliceView
        view = SliceView(self.doc, name)
        view.set_region(self.panel.region)
        view.resize(220, 200)
        view.show()
        self.panel.show()
        self.addCleanup(view.close)
        self.addCleanup(self.panel.hide)
        self.app.processEvents()
        return view

    def _mouse(self, view, cells, modifiers=None):
        """A left drag over these (u, v) cells of a slice (one cell: a click)."""
        from PySide6 import QtCore
        from PySide6.QtTest import QTest
        canvas, left = view.canvas, QtCore.Qt.MouseButton.LeftButton
        modifiers = modifiers or QtCore.Qt.KeyboardModifier.NoModifier
        at = [canvas._screen_rect(*cell).center() for cell in cells]
        QTest.mousePress(canvas, left, modifiers, at[0])
        for point in at[1:]:
            QTest.mouseMove(canvas, point)
        QTest.mouseRelease(canvas, left, modifiers, at[-1])

    def test_a_drag_in_a_slice_sets_the_box_in_its_two_axes(self):
        from PySide6 import QtCore
        view = self._slice("Front")  # x right, z up, the layer along y
        self.panel.set_box((0, 3, 0), (15, 12, 7))
        self.panel.drag_button.setChecked(True)
        before, steps = self.doc.model.colour.copy(), len(self.doc.model.undo_stack)
        self._mouse(view, [(9, 5), (6, 3), (2, 1)])  # backwards: the corners come out low and high
        self.assertEqual(self.panel.box(), ([2, 3, 1], [9, 12, 5]))  # y, the slice's depth, stays
        self.assertTrue(np.array_equal(self.doc.model.colour, before))  # it drew nothing
        self.assertEqual(len(self.doc.model.undo_stack), steps)
        self._mouse(self._slice("Top"), [(4, 14), (11, 8)])
        self.assertEqual(self.panel.box(), ([4, 8, 1], [11, 14, 5]))  # x and y now; z stays
        # Alt + left still picks
        self.doc.picked = None
        self._mouse(view, [(3, 2)], QtCore.Qt.KeyboardModifier.AltModifier)
        self.assertEqual(self.doc.picked, (3, view.depth_box.value(), 2))
        self.assertEqual(self.panel.box(), ([4, 8, 1], [11, 14, 5]))

    def test_without_drag_box_or_out_of_sight_a_drag_draws_as_before(self):
        view = self._slice("Front")
        depth = view.depth_box.value()
        self._mouse(view, [(3, 6)])  # attach, the mode, on an empty cell
        self.assertTrue(self.doc.voxel(3, depth, 6))
        self.panel.drag_button.setChecked(True)
        self.panel.hide()  # the dock out of sight: Drag box waits for it
        self.assertFalse(self.panel.region.drags)
        self._mouse(view, [(5, 6)])
        self.assertTrue(self.doc.voxel(5, depth, 6))

    def test_a_slice_outlines_the_box_dashed_when_its_layer_is_outside(self):
        from PySide6 import QtGui
        view = self._slice("Front")
        canvas = view.canvas
        self.panel.set_box((2, 0, 1), (9, 15, 5))
        rect = canvas._screen_rect(2, 1).united(canvas._screen_rect(9, 5))
        colour = QtGui.QColor(*self.panel.region.COLOUR)

        def left_edge():
            """Whether each pixel down the box's left edge is the box's colour."""
            image = canvas.grab().toImage()
            image.setDevicePixelRatio(1)
            scale = canvas.devicePixelRatioF()
            x = round((rect.left() + 1) * scale)
            return [image.pixelColor(x, round(y * scale)) == colour for y in range(rect.top() + 3, rect.bottom() - 2)]

        self.assertTrue(all(left_edge()))
        self.panel.hide()
        self.assertFalse(any(left_edge()))
        self.panel.show()
        self.panel.set_box((2, 0, 1), (9, 3, 5))  # the layer, y = 8, is behind the box: dashed
        along = left_edge()
        self.assertTrue(any(along) and not all(along))

    def test_the_window_has_a_noise_dock(self):
        from PySide6 import QtCore
        from qtui.window import EditorWindow
        window = EditorWindow()
        window._engine_started = True
        window.settings = QtCore.QSettings(str(Path(tempfile.mkdtemp()) / "layout.ini"),
                                           QtCore.QSettings.Format.IniFormat)
        window.confirm_close = lambda: True
        try:
            self.assertIn("Noise", window.docks)
            self.assertIs(window.docks["Noise"].widget(), window.noise_panel)
            from PySide6 import QtWidgets
            view = next(m for m in window.menuBar().findChildren(QtWidgets.QMenu) if m.title() == "&View")
            self.assertIn("Noise", [a.text() for a in view.actions()])
        finally:
            window.close()

    def test_the_window_outlines_the_box_in_every_view_while_the_dock_is_in_sight(self):
        from PySide6 import QtCore
        from PySide6.QtTest import QTest
        from qtui.window import LAYOUT_VERSION, EditorWindow
        window = EditorWindow()
        window._engine_started = True
        window.settings = QtCore.QSettings(str(Path(tempfile.mkdtemp()) / "layout.ini"),
                                           QtCore.QSettings.Format.IniFormat)
        window.confirm_close = lambda: True
        try:
            window.dock_manager.restoreState(window.default_layout, LAYOUT_VERSION)
            window.show()
            QTest.qWait(100)
            panel, plotter = window.noise_panel, window.edit_view.plotter
            for view in window.slices.values():
                self.assertIs(view.canvas.region, panel.region)
            self.assertFalse(panel.region.shown)  # behind the Brush tab
            self.assertNotIn("noise box", plotter.actors)
            window.docks["Noise"].setAsCurrentTab()
            QTest.qWait(50)
            self.assertTrue(panel.region.shown)
            panel.set_box((1, 2, 3), (4, 5, 6))
            bounds = plotter.actors["noise box"].GetBounds()
            self.assertEqual([round(v) for v in bounds], [1, 5, 2, 6, 3, 7])  # the voxels' outer faces
            window.docks["Brush"].setAsCurrentTab()
            QTest.qWait(50)
            self.assertFalse(panel.region.shown)
            self.assertNotIn("noise box", plotter.actors)
        finally:
            window.close()


if __name__ == "__main__":
    unittest.main()
