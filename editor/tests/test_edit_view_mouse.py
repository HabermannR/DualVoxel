"""The 3D edit view keeps working after mouse buttons overlap (real Qt mouse events, native window).

PyVistaQt's widget remembers one active button, so a right click during a left drag used to make the
left release arrive as a right release: the stroke never ended and the view no longer orbited. Shift + right
drag pans, for trackpads without a middle button."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

EDITOR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EDITOR))
import sandbox  # noqa: E402,F401  the user's own editor and settings are left alone


def open_window():
    """The editor in its standard layout with the alchemist open; the render dock's engine never starts."""
    from PySide6 import QtCore, QtWidgets
    from PySide6.QtTest import QTest
    from qtui.window import LAYOUT_VERSION, EditorWindow
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)  # noqa: F841
    window = EditorWindow()
    window.settings = QtCore.QSettings(str(Path(tempfile.mkdtemp()) / "layout.ini"),
                                       QtCore.QSettings.Format.IniFormat)  # leave the user's layout alone
    window.closeEvent = lambda e: e.accept()
    window.dock_manager.restoreState(window.default_layout, LAYOUT_VERSION)  # the standard layout
    window.open_path(EDITOR.parent / "assets" / "alchemist.vx2")
    window.show()
    QTest.qWait(400)
    return window


@unittest.skipIf(os.environ.get("SKIP_QT"), "needs a native Qt window")
class EditViewMouseTests(unittest.TestCase):
    def setUp(self):
        from qtui import render_view
        start = render_view.RenderView.start
        render_view.RenderView.start = lambda self: None
        self.addCleanup(setattr, render_view.RenderView, "start", start)

    def test_a_right_click_during_a_box_drag_does_not_stick(self):
        from PySide6 import QtCore, QtWidgets
        from PySide6.QtTest import QTest
        window = open_window()
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

        # Alt + left picks, whatever the brush: VTK's Qt widget never tells VTK about Alt, so it smoothed
        from unittest import mock
        view.brush.set(kind="smooth")
        doc.set_colour(1)
        before = doc.model.colour.copy()
        alt = QtCore.Qt.KeyboardModifier.AltModifier
        with mock.patch.object(QtWidgets.QApplication, "queryKeyboardModifiers", return_value=alt):
            QTest.mousePress(widget, left, alt, centre)
            QTest.mouseRelease(widget, left, alt, centre)
        QTest.qWait(50)
        self.assertTrue((doc.model.colour == before).all())  # nothing smoothed
        self.assertIsNotNone(doc.picked)
        x, y, z = doc.picked
        self.assertEqual(doc.colour, int(before[z, y, x]))  # the colour under the mouse picked
        self.assertNotEqual(doc.colour, 1)
        window.close()

    def test_shift_right_drag_pans_for_trackpads(self):
        """A trackpad has no middle button: Shift + right drag pans in the 3D view, Shift + drag in the render view."""
        import numpy as np
        from PySide6 import QtCore
        from PySide6.QtTest import QTest
        window = open_window()
        right, shift = QtCore.Qt.MouseButton.RightButton, QtCore.Qt.KeyboardModifier.ShiftModifier

        def drag(widget, button, modifier):
            centre = widget.rect().center()
            QTest.mousePress(widget, button, modifier, centre)
            for dx in range(0, 60, 10):
                QTest.mouseMove(widget, centre + QtCore.QPoint(dx, dx // 2))
                QTest.qWait(10)
            QTest.mouseRelease(widget, button, modifier, centre + QtCore.QPoint(60, 30))
            QTest.qWait(50)

        camera = window.edit_view.plotter.camera

        def direction():
            d = np.subtract(camera.GetFocalPoint(), camera.GetPosition())
            return d / np.linalg.norm(d)

        looking, focus = direction(), camera.GetFocalPoint()
        drag(window.edit_view.plotter.interactor, right, shift)
        np.testing.assert_allclose(direction(), looking, atol=1e-6)  # still looking the same way
        self.assertGreater(np.linalg.norm(np.subtract(camera.GetFocalPoint(), focus)), 1)  # moved sideways
        self.assertFalse(window.edit_view.style.orbiting)

        render = window.render_view.camera
        yaw, target = render.yaw, render.target.copy()
        drag(window.render_view, QtCore.Qt.MouseButton.LeftButton, shift)
        self.assertEqual(render.yaw, yaw)  # no orbit
        self.assertFalse(np.allclose(render.target, target))  # a pan
        drag(window.render_view, right, QtCore.Qt.KeyboardModifier.NoModifier)
        self.assertNotEqual(render.yaw, yaw)  # without Shift it still orbits
        window.close()


if __name__ == "__main__":
    unittest.main()
