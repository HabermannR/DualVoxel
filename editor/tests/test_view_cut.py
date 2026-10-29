"""The 3D edit view's cut: planes that keep whole voxels on one side, the section showing what they lay bare."""
import os
import sys
import unittest
from pathlib import Path

import numpy as np

EDITOR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EDITOR))


class KeptTests(unittest.TestCase):
    def test_a_cut_keeps_one_side_and_two_keep_a_band(self):
        from qtui.view_cut import Cut, kept
        shape = (8, 4, 6)  # z, y, x
        self.assertIsNone(kept(shape, []))
        below = kept(shape, [Cut(2, 3)])
        self.assertTrue(below[:3].all() and not below[3:].any())
        above = kept(shape, [Cut(2, 3, keep_above=True)])
        np.testing.assert_array_equal(above, ~below)
        band = kept(shape, [Cut(2, 2, keep_above=True), Cut(2, 5)])
        self.assertEqual([bool(band[z].all()) for z in range(8)], [False, False, True, True, True, False, False, False])
        x_cut = kept(shape, [Cut(0, 4)])
        self.assertTrue(x_cut[:, :, :4].all() and not x_cut[:, :, 4:].any())
        self.assertEqual(Cut(2, 3).text(), "z < 3")
        self.assertEqual(Cut(0, 1, True).text(), "x ≥ 1")
        self.assertEqual(Cut(1, 99).clamped((6, 4, 8)).at, 4)


@unittest.skipIf(os.environ.get("SKIP_QT"), "needs a native Qt window")
class EditViewCutTests(unittest.TestCase):
    def test_the_view_shows_the_section_and_the_model_stays(self):
        from PySide6 import QtWidgets
        from PySide6.QtTest import QTest
        from qtui.document import Document
        from qtui.edit_view import EditView
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)  # noqa: F841
        doc = Document()
        doc.new(8, 8, 8, ground=0)
        block = [(x, y, z) for x in range(2, 6) for y in range(2, 6) for z in range(2, 6)]
        doc.set_voxels(block, colour=3)
        doc.set_voxels([(3, 3, 3)], colour=5)  # inside the block: only a cut shows it
        view = EditView(doc)
        view.resize(500, 500)
        view.show()
        QTest.qWait(150)

        def shown_voxels():
            rows = [faces[3] for _, faces, *_ in view.chunks.values()]
            return {tuple(v) for v in np.concatenate(rows)} if rows else set()

        whole = doc.model.colour.copy()
        self.assertNotIn((3, 3, 3), shown_voxels())
        view.cut_box.setChecked(True)  # the first cut: the X-Y plane through the middle, the lower half kept
        QTest.qWait(80)
        self.assertEqual(len(view.cut_panel.cuts), 1)
        self.assertEqual(view.cut_panel.cuts[0].text(), "z < 4")
        self.assertFalse(any(z >= 4 for _, _, z in shown_voxels()))
        self.assertIn((3, 3, 3), shown_voxels())  # the section lays the inside bare
        np.testing.assert_array_equal(doc.model.colour, whole)  # the model itself is untouched
        self.assertIn("cut 0", view.plotter.actors)

        # an edit while cut: the section voxel is painted, and the cut stays in force
        doc.set_voxels([(3, 3, 3)], colour=7)
        QTest.qWait(80)
        self.assertEqual(doc.model.colour[3, 3, 3], 7)
        self.assertFalse(any(z >= 4 for _, _, z in shown_voxels()))

        view.cut_panel._edit(flip=True)  # keep the upper half
        QTest.qWait(50)
        self.assertEqual(view.cut_panel.cuts[0].text(), "z ≥ 4")
        self.assertFalse(any(z < 4 for _, _, z in shown_voxels()))

        view.cut_box.setChecked(False)  # off: the whole model again, the cut kept for next time
        QTest.qWait(50)
        self.assertTrue(any(z < 4 for _, _, z in shown_voxels()) and any(z >= 4 for _, _, z in shown_voxels()))
        self.assertNotIn("cut 0", view.plotter.actors)
        self.assertEqual(len(view.cut_panel.cuts), 1)
        view.close()


@unittest.skipIf(os.environ.get("SKIP_QT"), "needs a native Qt window")
class BackgroundTests(unittest.TestCase):
    def test_the_background_switches_and_says_so(self):
        from PySide6 import QtWidgets
        from qtui.document import Document
        from qtui.edit_view import BACKGROUNDS, EditView
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)  # noqa: F841
        doc = Document()
        doc.new(4, 4, 4)
        view = EditView(doc)
        told = []
        view.background_changed.connect(told.append)
        renderer = view.plotter.renderer
        self.assertEqual(view.background, "Dark")
        self.assertTrue(renderer.GetGradientBackground())
        view.set_background("White")
        self.assertFalse(renderer.GetGradientBackground())
        np.testing.assert_allclose(renderer.GetBackground(), BACKGROUNDS["White"][0])
        view.set_background("Light")
        self.assertTrue(renderer.GetGradientBackground())
        view.set_background("an old name")  # ignored
        self.assertEqual(view.background, "Light")
        self.assertEqual(told, ["White", "Light"])
        self.assertEqual([a.text() for a in view.background_actions.actions() if a.isChecked()], ["Light"])
        view.close()


if __name__ == "__main__":
    unittest.main()
