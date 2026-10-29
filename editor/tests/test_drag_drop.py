"""A .vx2, .vox or project dropped on the window opens, as File > Open recent would; other files are refused."""
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

EDITOR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EDITOR))
import sandbox  # noqa: E402,F401  the user's own editor and settings are left alone

ASSETS = EDITOR.parent / "assets"


@unittest.skipIf(os.environ.get("SKIP_QT"), "needs Qt")
class DragDropTests(unittest.TestCase):
    def setUp(self):
        from PySide6 import QtWidgets
        from qtui import render_view
        start = render_view.RenderView.start
        render_view.RenderView.start = lambda self: None
        self.addCleanup(setattr, render_view.RenderView, "start", start)
        self.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
        from qtui.window import EditorWindow
        self.window = EditorWindow()
        self.window.confirm_close = lambda: True
        self.asked = []
        self.window.ask_save = lambda lines, question, **_: self.asked.append(question) or True
        self.addCleanup(self.window.close)
        self.folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.folder, True)

    def mime(self, *paths):
        from PySide6 import QtCore
        mime = QtCore.QMimeData()
        mime.setUrls([QtCore.QUrl.fromLocalFile(str(p)) for p in paths])
        return mime

    def drag(self, mime) -> bool:
        from PySide6 import QtCore, QtGui
        event = QtGui.QDragEnterEvent(QtCore.QPoint(20, 20), QtCore.Qt.DropAction.CopyAction, mime,
                                      QtCore.Qt.MouseButton.LeftButton, QtCore.Qt.KeyboardModifier.NoModifier)
        event.ignore()
        self.window.dragEnterEvent(event)
        return event.isAccepted()

    def drop(self, mime):
        from PySide6 import QtCore, QtGui
        from PySide6.QtTest import QTest
        event = QtGui.QDropEvent(QtCore.QPointF(20, 20), QtCore.Qt.DropAction.CopyAction, mime,
                                 QtCore.Qt.MouseButton.LeftButton, QtCore.Qt.KeyboardModifier.NoModifier)
        self.window.dropEvent(event)
        QTest.qWait(50)  # the file opens after the drop has finished

    def test_a_dropped_model_opens(self):
        model = self.folder / "dropped.vx2"
        shutil.copy(ASSETS / "alchemist.vx2", model)
        self.assertTrue(self.drag(self.mime(model)))
        self.drop(self.mime(model))
        self.assertEqual(Path(self.window.doc.model.path).resolve(), model.resolve())
        self.assertEqual(self.window.recent_files()[0], str(model.resolve()))
        self.assertEqual(len(self.asked), 1)  # asked about unsaved work first, as Open recent does

    def test_other_files_are_refused_and_the_first_of_several_opens(self):
        text = self.folder / "notes.txt"
        text.write_text("not a model")
        self.assertFalse(self.drag(self.mime(text)))
        before = self.window.doc.model.path
        self.drop(self.mime(text))
        self.assertEqual(self.window.doc.model.path, before)
        first, second = self.folder / "first.vx2", self.folder / "second.vx2"
        for target in (first, second):
            shutil.copy(ASSETS / "alchemist.vx2", target)
        self.assertTrue(self.drag(self.mime(text, first, second)))
        self.drop(self.mime(text, first, second))
        self.assertEqual(Path(self.window.doc.model.path).resolve(), first.resolve())


if __name__ == "__main__":
    unittest.main()
