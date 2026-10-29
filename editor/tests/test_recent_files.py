"""File > Open recent: models and projects opened or saved, newest first, each once, at most RECENT_MAX; a
file gone since can be taken off the list, and Clear list empties it."""
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
class RecentFilesTests(unittest.TestCase):
    def setUp(self):
        from PySide6 import QtWidgets
        from qtui import render_view
        start = render_view.RenderView.start
        render_view.RenderView.start = lambda self: None
        self.addCleanup(setattr, render_view.RenderView, "start", start)
        self.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
        from qtui.window import EditorWindow
        self.window = EditorWindow()  # its settings are a fresh temporary file (sandbox)
        self.window.confirm_close = lambda: True
        self.addCleanup(self.window.close)
        self.folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.folder, True)

    def copy(self, name: str, as_name: str | None = None) -> Path:
        target = self.folder / (as_name or name)
        shutil.copy(ASSETS / name, target)
        return target

    def test_opened_and_saved_files_come_first_once(self):
        w = self.window
        self.assertEqual(w.recent_files(), [])
        a, b = self.copy("alchemist.vx2"), self.copy("alchemist.vx2", "second.vx2")
        w.open_path(a)
        w.open_path(b)
        self.assertEqual(w.recent_files(), [str(b.resolve()), str(a.resolve())])
        w.open_path(a)  # again: to the top, not twice
        self.assertEqual(w.recent_files(), [str(a.resolve()), str(b.resolve())])
        saved = self.folder / "saved.vx2"
        w._save_to(saved)
        self.assertEqual(w.recent_files()[0], str(saved.resolve()))

    def test_a_file_that_fails_to_open_is_not_listed(self):
        from PySide6 import QtWidgets
        from unittest import mock
        broken = self.folder / "broken.vx2"
        broken.write_bytes(b"not a model")
        with mock.patch.object(QtWidgets.QMessageBox, "warning"):
            self.window.open_path(broken)
        self.assertEqual(self.window.recent_files(), [])

    def test_at_most_ten_and_clear(self):
        from qtui.window import RECENT_MAX
        w = self.window
        for i in range(RECENT_MAX + 3):
            w.remember_recent(self.folder / f"m{i}.vx2")
        files = w.recent_files()
        self.assertEqual(len(files), RECENT_MAX)
        self.assertTrue(files[0].endswith(f"m{RECENT_MAX + 2}.vx2"))
        w.forget_recent()
        self.assertEqual(w.recent_files(), [])

    def test_the_menu_names_files_and_marks_missing_ones(self):
        from PySide6 import QtWidgets
        from unittest import mock
        w = self.window
        there = self.copy("alchemist.vx2")
        gone = self.folder / "gone.vx2"
        w.remember_recent(gone)
        w.remember_recent(there)
        w.rebuild_recent_menu()
        texts = [a.text() for a in w.recent_menu.actions() if not a.isSeparator()]
        self.assertEqual(texts[0], f"alchemist.vx2 — {self.folder.name}")
        self.assertEqual(texts[1], f"gone.vx2 — {self.folder.name}  (missing)")
        self.assertEqual(texts[-1], "Clear list")
        self.assertEqual(w.recent_menu.actions()[0].toolTip(), str(there.resolve()))
        Button = QtWidgets.QMessageBox.StandardButton
        with mock.patch.object(QtWidgets.QMessageBox, "question", return_value=Button.Yes):
            w.recent_menu.actions()[1].trigger()  # the missing one: taken off
        self.assertEqual(w.recent_files(), [str(there.resolve())])
        w.recent_menu.actions()[0].trigger()  # opens it
        self.assertEqual(Path(w.doc.model.path).resolve(), there.resolve())

    def test_opening_a_recent_model_asks_about_unsaved_edits(self):
        from PySide6 import QtWidgets
        from unittest import mock
        w = self.window
        first, second = self.copy("alchemist.vx2"), self.copy("alchemist.vx2", "other.vx2")
        w.open_path(first)
        w.doc.set_voxels([[0, 0, 0]], colour=3)
        Button = QtWidgets.QMessageBox.StandardButton
        with mock.patch.object(QtWidgets.QMessageBox, "warning", return_value=Button.Cancel) as ask:
            w.open_recent(second)
        ask.assert_called_once()
        self.assertEqual(Path(w.doc.model.path).resolve(), first.resolve())  # cancelled: still the first
        with mock.patch.object(QtWidgets.QMessageBox, "warning", return_value=Button.Discard):
            w.open_recent(second)
        self.assertEqual(Path(w.doc.model.path).resolve(), second.resolve())

    def test_projects_are_listed_too(self):
        project = next(ASSETS.glob("*.project.json"), None)
        if project is None:
            self.skipTest("no project in assets/")
        self.window.open_path(project)
        self.assertEqual(self.window.recent_files()[0], str(project.resolve()))


if __name__ == "__main__":
    unittest.main()
