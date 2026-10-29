"""The line and fill brushes: a line's voxels, its ends and its thickness; a fill that stops at other colours,
in 3D or in one layer, that fills an enclosed hollow but never the space around the model, and that mirrors.
The assistant's flood_fill and draw_line share the same core."""
import os
import sys
import unittest
from pathlib import Path

import numpy as np

EDITOR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EDITOR))
import sandbox  # noqa: E402,F401  the user's own editor and settings are left alone
from core.brushes import flood, line, thick_line  # noqa: E402
from headless_api import VoxelEditor  # noqa: E402
from qtui.brush import Brush, brush_edit  # noqa: E402
from qtui.document import Document  # noqa: E402


def as_set(points):
    return {tuple(int(v) for v in p) for p in points}


class LineTests(unittest.TestCase):
    def test_a_line_has_both_ends_and_a_voxel_per_step(self):
        pts = line((0, 0, 0), (9, 3, 1))
        self.assertEqual(len(pts), 10)
        self.assertEqual(tuple(pts[0]), (0, 0, 0))
        self.assertEqual(tuple(pts[-1]), (9, 3, 1))
        self.assertTrue((np.abs(np.diff(pts, axis=0)) <= 1).all())  # no gaps
        self.assertEqual(len(line((4, 4, 4), (4, 4, 4))), 1)

    def test_thickness_is_the_brush_shape(self):
        self.assertEqual(len(thick_line((2, 5, 5), (12, 5, 5), "cube", 3)), 13 * 9)
        flat = thick_line((2, 5, 5), (12, 5, 5), "square", 3, normal_axis=2)
        self.assertEqual(set(flat[:, 2].tolist()), {5})  # a flat brush lies across the normal

    def test_the_line_brush_between_two_voxels(self):
        doc = Document()
        doc.new(16, 16, 16)
        brush = Brush()
        brush.set(kind="line")
        points, colours, _ = brush_edit(doc, brush, "attach", (12, 3, 0), (0, 0, 1),
                                        box_start=((1, 1, 0), np.array([0, 0, 1])), box_end=(12, 3, 0))
        self.assertIn((1, 1, 0), as_set(points))
        self.assertIn((12, 3, 0), as_set(points))
        self.assertEqual(len(points), 12)
        self.assertTrue((colours == doc.colour).all())
        brush.set(mirror=(True, False, False))  # mirrored as every brush
        points, _, _ = brush_edit(doc, brush, "attach", (3, 3, 0), (0, 0, 1),
                                  box_start=((1, 3, 0), np.array([0, 0, 1])), box_end=(3, 3, 0))
        self.assertEqual(as_set(points), {(1, 3, 0), (2, 3, 0), (3, 3, 0), (14, 3, 0), (13, 3, 0), (12, 3, 0)})

    def test_headless_draw_line_is_unchanged(self):
        editor = VoxelEditor()
        editor.new_model(16, 16, 16)
        self.assertEqual(editor.draw_line([0, 0, 0], [15, 3, 2], 52)["changed_voxels"], 16)


class FillTests(unittest.TestCase):
    def setUp(self):
        self.colour = np.zeros((4, 10, 10), dtype=np.uint8)  # z, y, x
        self.material = np.zeros_like(self.colour)
        self.colour[0] = 5  # a floor of colour 5
        self.colour[0, :, 6:] = 7  # its right part colour 7
        self.colour[1, 2, 2] = 5  # a voxel of 5 on top, touching the floor
        self.material[self.colour > 0] = 1

    def test_paint_fill_stops_at_other_colours(self):
        pts = flood(self.colour, self.material, (0, 0, 0), False)
        self.assertEqual(len(pts), 10 * 6 + 1)  # the 5s, and the one above them
        layer = flood(self.colour, self.material, (0, 0, 0), False, "layer", axis=2)
        self.assertEqual(len(layer), 10 * 6)  # only the floor's layer
        self.assertEqual(len(flood(self.colour, self.material, (8, 0, 0), False)), 10 * 4)
        solid = flood(self.colour, self.material, (0, 0, 0), False, match="solid")
        self.assertEqual(len(solid), 101)

    def test_model_scope_and_material_match(self):
        self.colour[3, 9, 9] = 5  # a 5 apart from the rest
        self.assertEqual(len(flood(self.colour, self.material, (0, 0, 0), False)), 61)
        self.assertEqual(len(flood(self.colour, self.material, (0, 0, 0), False, "model")), 62)
        self.material[1, 2, 2] = 2
        self.assertEqual(len(flood(self.colour, self.material, (0, 0, 0), False, match="colour and material")), 60)

    def test_diagonal_neighbours(self):
        self.colour[2, 3, 3] = 5  # touches (2, 2, 1) at an edge only
        self.assertNotIn((3, 3, 2), as_set(flood(self.colour, self.material, (0, 0, 0), False)))
        self.assertIn((3, 3, 2), as_set(flood(self.colour, self.material, (0, 0, 0), False, diagonal=True)))

    def test_tolerance_takes_near_colours(self):
        doc = Document()
        labs = doc.model.table.labs
        near = int(np.argsort(((labs - labs[4]) ** 2).sum(axis=1))[1]) + 1  # the colour nearest to slot 5
        self.colour[0, :, 6:] = near
        exact = flood(self.colour, self.material, (0, 0, 0), False, labs=labs)
        loose = flood(self.colour, self.material, (0, 0, 0), False, labs=labs, tolerance=50)
        self.assertEqual(len(exact), 61)
        self.assertEqual(len(loose), 101)

    def test_attach_fills_a_hollow_but_never_the_outside(self):
        colour = np.zeros((6, 8, 8), dtype=np.uint8)
        colour[0:5, 1:7, 1:7] = 3
        colour[1:4, 2:6, 2:6] = 0  # a closed box with a hollow inside
        material = np.zeros_like(colour)
        hollow = flood(colour, material, (3, 3, 2), True)
        self.assertEqual(len(hollow), 3 * 4 * 4)
        self.assertEqual(len(flood(colour, material, (0, 0, 3), True)), 0)  # the outside: refused
        colour[4, 3, 3] = 0  # a hole in the lid: the hollow is open now
        self.assertEqual(len(flood(colour, material, (3, 3, 2), True)), 0)
        ring = np.zeros((4, 8, 8), dtype=np.uint8)  # a ring on the floor: its inside fills in its layer
        ring[0, 2:6, 2:6] = 3
        ring[0, 3:5, 3:5] = 0
        self.assertEqual(len(flood(ring, np.zeros_like(ring), (3, 3, 0), True, "layer", axis=2)), 4)
        self.assertEqual(len(flood(ring, np.zeros_like(ring), (3, 3, 0), True)), 0)  # 3D: open at the top

    def test_the_fill_brush_mirrors_and_erases(self):
        doc = Document()
        doc.new(8, 8, 8)
        doc.model.colour[0, 0:2, 0:2] = 5
        doc.model.colour[0, 0:2, 6:8] = 5
        doc.model.material[doc.model.colour > 0] = 0
        brush = Brush()
        brush.set(kind="fill")
        points, colours, _ = brush_edit(doc, brush, "erase", (0, 0, 0), (0, 0, 1), hit=(0, 0, 0))
        self.assertEqual(len(points), 4)
        self.assertTrue((colours == 0).all())
        brush.set(mirror=(True, False, False))
        points, _, _ = brush_edit(doc, brush, "erase", (0, 0, 0), (0, 0, 1), hit=(0, 0, 0))
        self.assertEqual(len(points), 8)
        self.assertIsNone(brush_edit(doc, brush, "attach", (4, 4, 0), (0, 0, 1)))  # open space: nothing

    def test_headless_flood_fill(self):
        editor = VoxelEditor()
        editor.new_model(8, 8, 8)
        editor.paint_box([0, 0, 0], [7, 7, 0], 54)
        editor.paint_box([4, 0, 0], [7, 7, 0], 60)
        self.assertEqual(editor.flood_fill([0, 0, 0], 61)["changed_voxels"], 32)
        self.assertEqual(editor.model.colour[0, 0, 3], 61)
        self.assertEqual(editor.model.colour[0, 0, 4], 60)
        self.assertEqual(editor.flood_fill([5, 5, 0], 0)["changed_voxels"], 32)  # colour 0 erases
        with self.assertRaises(ValueError):
            editor.flood_fill([3, 3, 3], 54)  # open space
        editor.paint_box([1, 1, 2], [5, 5, 2], 54)
        editor.erase_box([2, 2, 2], [4, 4, 2])
        self.assertEqual(editor.flood_fill([3, 3, 2], 54, reach="layer")["changed_voxels"], 9)


@unittest.skipIf(os.environ.get("SKIP_QT"), "needs Qt")
class SliceLineTests(unittest.TestCase):
    def test_a_line_dragged_in_a_slice(self):
        from PySide6 import QtWidgets
        from qtui.slice_view import SliceView
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)  # noqa: F841
        doc = Document()
        doc.new(16, 16, 16)
        view = SliceView(doc, "Top")
        brush = Brush()
        brush.set(kind="line")
        view.set_brush(brush)
        view.depth_box.setValue(0)
        doc.begin_stroke()
        view.draw_box((1, 1), (9, 5), "attach")
        doc.end_stroke()
        solid = np.argwhere(doc.model.colour[0] > 0)
        self.assertEqual(len(solid), 9)
        self.assertEqual(doc.model.colour[0, 1, 1] > 0 and doc.model.colour[0, 5, 9] > 0, True)
        view.canvas.box_start, view.canvas.last = (1, 1), (9, 5)
        view.canvas.grab()  # paints the dragged line without failing

    def test_a_huge_fill_previews_as_an_outline(self):
        from PySide6 import QtWidgets
        from qtui import render_view
        from qtui.edit_view import PREVIEW_LIMIT
        start = render_view.RenderView.start
        render_view.RenderView.start = lambda self: None
        self.addCleanup(setattr, render_view.RenderView, "start", start)
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)  # noqa: F841
        from qtui.window import EditorWindow
        window = EditorWindow()
        window.confirm_close = lambda: True
        self.addCleanup(window.close)
        window.new_model(64, 64, 64, "Filled")  # 262 144 voxels, one colour
        view, doc = window.edit_view, window.doc
        view.brush.set(kind="fill")
        doc.set_tool("paint")
        texts = []
        doc.hover_changed.connect(texts.append)
        view._show_preview((3, 3, 63), (3, 3, 64), (3, 3, 63))
        self.assertGreater(64 ** 3, PREVIEW_LIMIT)
        self.assertTrue(texts[-1].endswith(f"{64 ** 3} voxels (outlined)"), texts[-1])
        self.assertIsNotNone(view.preview_actor)
        doc.begin_stroke()
        view.apply((3, 3, 63), (3, 3, 64))
        doc.end_stroke()
        self.assertTrue((doc.model.colour == doc.colour).all())  # painted its own colour: nothing changed
        doc.set_colour(doc.colour % 200 + 1)
        doc.begin_stroke()
        self.assertEqual(view.apply((3, 3, 63), (3, 3, 64)), 64 ** 3)
        doc.end_stroke()
        doc.undo()
        self.assertTrue((doc.model.colour != doc.colour).all())


if __name__ == "__main__":
    unittest.main()
