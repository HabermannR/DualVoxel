"""The 3D edit view's orthographic camera and view snaps: no perspective, picking and Frame still work, the
keys (5, 1 / 3 / 7 / 0 with Ctrl for the other side) and the setting is remembered."""
import os
import sys
import unittest
from pathlib import Path

import numpy as np

EDITOR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EDITOR))
import sandbox  # noqa: E402,F401  the user's own editor and settings are left alone


@unittest.skipIf(os.environ.get("SKIP_QT"), "needs a Qt window")
class OrthoViewTests(unittest.TestCase):
    def setUp(self):
        from PySide6 import QtWidgets
        from PySide6.QtTest import QTest
        from qtui import render_view
        start = render_view.RenderView.start
        render_view.RenderView.start = lambda self: None
        self.addCleanup(setattr, render_view.RenderView, "start", start)
        self.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
        from qtui.window import EditorWindow
        self.window = EditorWindow()
        self.window.confirm_close = lambda: True
        self.addCleanup(self.window.close)
        self.window.new_model(16, 16, 16, "Floor", 1)
        self.window.show()
        QTest.qWait(200)
        self.view = self.window.edit_view
        self.camera = self.view.plotter.renderer.GetActiveCamera()

    def test_ortho_frames_and_picks_straight_down(self):
        view = self.view
        view.snap_view("top")
        view.set_ortho(True)
        self.assertTrue(view.ortho_box.isChecked())
        self.assertTrue(self.camera.GetParallelProjection())
        view.frame()
        self.assertTrue(self.camera.GetParallelProjection())
        self.assertGreater(self.camera.GetParallelScale(), 7)  # the 16-wide model fits
        view.snap_view("top")
        w, h = view.plotter.renderer.GetSize()
        hit, attach = view._pick((w // 2, h // 2))
        self.assertIsNotNone(hit)
        self.assertEqual(hit[2], 0)  # the floor layer, seen from straight above
        self.assertEqual(tuple(np.subtract(attach, hit)), (0, 0, 1))
        self.assertTrue(all(6 <= c <= 9 for c in hit[:2]))
        self.assertTrue(self.window.settings.value("edit_ortho", type=bool))
        view.set_ortho(False)
        self.assertFalse(self.camera.GetParallelProjection())
        self.assertFalse(self.window.settings.value("edit_ortho", type=bool))

    def test_the_keys(self):
        from PySide6 import QtCore
        from PySide6.QtTest import QTest
        view, widget = self.view, self.view.plotter.interactor
        widget.setFocus()
        QTest.keyClick(widget, QtCore.Qt.Key.Key_5)
        self.assertTrue(self.camera.GetParallelProjection())
        QTest.keyClick(widget, QtCore.Qt.Key.Key_1)  # front: from -y
        direction = np.subtract(self.camera.GetPosition(), self.camera.GetFocalPoint())
        self.assertAlmostEqual(direction[0], 0)
        self.assertLess(direction[1], 0)
        QTest.keyClick(widget, QtCore.Qt.Key.Key_3, QtCore.Qt.KeyboardModifier.ControlModifier)  # left: from -x
        direction = np.subtract(self.camera.GetPosition(), self.camera.GetFocalPoint())
        self.assertLess(direction[0], 0)
        self.assertAlmostEqual(direction[1], 0)
        QTest.keyClick(widget, QtCore.Qt.Key.Key_0)  # isometric 2:1: 30 degrees up
        direction = np.subtract(self.camera.GetPosition(), self.camera.GetFocalPoint())
        self.assertAlmostEqual(np.degrees(np.arcsin(direction[2] / np.linalg.norm(direction))), 30, places=3)
        QTest.keyClick(widget, QtCore.Qt.Key.Key_5)
        self.assertFalse(self.camera.GetParallelProjection())


if __name__ == "__main__":
    unittest.main()
