"""Mirroring across a plane of one's own: through a voxel's centre (an even doubled sum) or between two voxels
(an odd one), anywhere on the axis; the model's centre stays the default, and images outside the box drop."""
import os
import sys
import unittest
from pathlib import Path

import numpy as np

EDITOR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EDITOR))
import sandbox  # noqa: E402,F401  the user's own editor and settings are left alone
from core.brushes import mirror_sum, mirrored  # noqa: E402
from headless_api import VoxelEditor  # noqa: E402
from qtui.brush import Brush, brush_edit  # noqa: E402
from qtui.document import Document  # noqa: E402


class MirrorPlaneTests(unittest.TestCase):
    def test_the_centre_is_the_default(self):
        size = (8, 6, 4)
        pts, source = mirrored([[1, 2, 3]], size, (True, True, True))
        self.assertEqual(sorted(map(tuple, pts)), sorted({(x, y, z) for x in (1, 6) for y in (2, 3)
                                                          for z in (3, 0)}))
        same, _ = mirrored([[1, 2, 3]], size, (True, True, True), (None, None, None))
        np.testing.assert_array_equal(pts, same)
        self.assertEqual(mirror_sum(size, None, 0), 7)

    def test_a_plane_through_a_voxel_and_between_two(self):
        size = (32, 32, 32)
        through, _ = mirrored([[10, 0, 0]], size, (True, False, False), (24, None, None))  # through voxel 12
        self.assertEqual(sorted(through[:, 0].tolist()), [10, 14])
        on, _ = mirrored([[12, 0, 0]], size, (True, False, False), (24, None, None))  # its own image: once
        self.assertEqual(on[:, 0].tolist(), [12])
        between, _ = mirrored([[10, 0, 0]], size, (True, False, False), (25, None, None))  # between 12 and 13
        self.assertEqual(sorted(between[:, 0].tolist()), [10, 15])

    def test_the_brush_mirrors_off_centre_and_drops_what_falls_outside(self):
        doc = Document()
        doc.new(16, 16, 16)
        brush = Brush()
        brush.set(mirror=(True, False, False), mirror_plane=(2 * 3, None, None))  # through x = 3
        points, _, _ = brush_edit(doc, brush, "attach", (5, 4, 0), (0, 0, 1))
        self.assertEqual(sorted(points[:, 0].tolist()), [1, 5])
        far = brush_edit(doc, brush, "attach", (9, 4, 0), (0, 0, 1))[0]  # its image, x = -3, is outside
        self.assertEqual(far[:, 0].tolist(), [9])
        brush.set(mirror_plane=(None, None, None))  # back to the centre: 15 - 5
        points, _, _ = brush_edit(doc, brush, "attach", (5, 4, 0), (0, 0, 1))
        self.assertEqual(sorted(points[:, 0].tolist()), [5, 10])

    def test_headless_mirror_across_a_plane(self):
        editor = VoxelEditor()
        editor.new_model(16, 4, 4)
        editor.paint_box([0, 0, 0], [2, 0, 0], 54)  # x 0..2
        editor.mirror("x", plane=4)  # through voxel 4: 0..2 -> 8..6
        row = (editor.model.colour[0, 0] > 0).nonzero()[0].tolist()
        self.assertEqual(row, [0, 1, 2, 6, 7, 8])
        editor.undo()
        editor.mirror("x", plane=2.5)  # between 2 and 3: 0..2 -> 5..3
        self.assertEqual((editor.model.colour[0, 0] > 0).nonzero()[0].tolist(), [0, 1, 2, 3, 4, 5])
        editor.undo()
        editor.paint_box([14, 1, 0], [14, 1, 0], 54)
        editor.mirror("x", keep="high", plane=13)  # 14 -> 12; 0..2 mirror 26..24, outside the model: kept
        self.assertEqual((editor.model.colour[0, 1] > 0).nonzero()[0].tolist(), [12, 14])
        self.assertEqual((editor.model.colour[0, 0] > 0).nonzero()[0].tolist(), [0, 1, 2])
        for bad in (2.25, -1, 15.5, True, "3"):
            with self.assertRaises(ValueError):
                editor.mirror("x", plane=bad)


@unittest.skipIf(os.environ.get("SKIP_QT"), "needs Qt")
class MirrorPlaneWindowTests(unittest.TestCase):
    def test_the_brush_dock_sets_a_plane_and_the_views_show_it(self):
        from PySide6 import QtWidgets
        from qtui import render_view
        start = render_view.RenderView.start
        render_view.RenderView.start = lambda self: None
        self.addCleanup(setattr, render_view.RenderView, "start", start)
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)  # noqa: F841
        from qtui.window import EditorWindow
        window = EditorWindow()
        window.confirm_close = lambda: True
        self.addCleanup(window.close)
        window.new_model(16, 16, 16, "Floor", 1)
        panel, brush = window.brush_panel, window.edit_view.brush
        self.assertFalse(panel.plane_pick_buttons[0].isEnabled())  # nothing picked yet
        window.doc.pick(5, 2, 0)
        panel.plane_to_picked(0)
        self.assertEqual(brush.mirror, (True, False, False))
        self.assertEqual(brush.mirror_plane, (10, None, None))
        self.assertEqual(panel.plane_boxes[0].text(), "5")
        panel.plane_boxes[0].setValue(5.5)
        self.assertEqual(brush.mirror_plane, (11, None, None))
        self.assertIn("mirror x", window.edit_view.plotter.actors)
        window.slices["Top"].canvas.grab()  # paints the dashed line without failing
        panel.plane_boxes[0].setValue(-0.5)
        self.assertEqual(panel.plane_boxes[0].text(), "centre")
        self.assertEqual(brush.mirror_plane, (None, None, None))
        brush.set(mirror=(False, False, False))
        self.assertNotIn("mirror x", window.edit_view.plotter.actors)


if __name__ == "__main__":
    unittest.main()
