"""The 3D edit view keeps working after mouse buttons overlap (real Qt mouse events, native window).

PyVistaQt's widget remembers one active button, so a right click during a left drag used to make the
left release arrive as a right release: the stroke never ended and the view no longer orbited."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

EDITOR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EDITOR))
os.environ.setdefault("DUALVOXEL_LINK_FILE", str(Path(tempfile.mkdtemp()) / "live_link.json"))  # the window's link


@unittest.skipIf(os.environ.get("SKIP_QT"), "needs a native Qt window")
class EditViewMouseTests(unittest.TestCase):
    def test_a_right_click_during_a_box_drag_does_not_stick(self):
        from PySide6 import QtCore, QtWidgets
        from PySide6.QtTest import QTest
        from qtui import render_view
        start, render_view.RenderView.start = render_view.RenderView.start, lambda self: None
        try:
            from qtui.window import LAYOUT_VERSION, EditorWindow
            app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
            window = EditorWindow()
            window.settings = QtCore.QSettings(str(Path(tempfile.mkdtemp()) / "layout.ini"),
                                               QtCore.QSettings.Format.IniFormat)  # leave the user's layout alone
            window.closeEvent = lambda e: e.accept()
            window.dock_manager.restoreState(window.default_layout, LAYOUT_VERSION)  # the standard layout
            window.open_path(EDITOR.parent / "assets" / "alchemist.vx2")
            window.show()
            QTest.qWait(400)
            view, doc = window.edit_view, window.doc
            widget = view.plotter.interactor
            centre = widget.rect().center()
            left, right, none = QtCore.Qt.MouseButton.LeftButton, QtCore.Qt.MouseButton.RightButton, \
                QtCore.Qt.KeyboardModifier.NoModifier
            view.brush.kind = "box"
            doc.set_tool("attach")

            def orbits():
                before = view.plotter.camera.GetPosition()
                QTest.mousePress(widget, right, none, centre)
                for dx in range(0, 60, 10):
                    QTest.mouseMove(widget, centre + QtCore.QPoint(dx, 0))
                    QTest.qWait(10)
                QTest.mouseRelease(widget, right, none, centre + QtCore.QPoint(60, 0))
                QTest.qWait(50)
                return view.plotter.camera.GetPosition() != before

            self.assertTrue(orbits())
            QTest.mousePress(widget, left, none, centre)
            QTest.mouseMove(widget, centre + QtCore.QPoint(20, 10))
            QTest.mousePress(widget, right, none, centre + QtCore.QPoint(20, 10))
            QTest.mouseRelease(widget, right, none, centre + QtCore.QPoint(20, 10))
            QTest.mouseMove(widget, centre + QtCore.QPoint(40, 20))
            QTest.mouseRelease(widget, left, none, centre + QtCore.QPoint(40, 20))
            QTest.qWait(50)
            self.assertFalse(view.style.stroking)
            self.assertTrue(orbits())
            window.close()
        finally:
            render_view.RenderView.start = start


if __name__ == "__main__":
    unittest.main()
