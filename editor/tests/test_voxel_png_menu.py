"""File > Export voxel PNG… and Import voxel PNG…: views painted and read back as one undo step, a slice sheet
opened as a new model, the pictures to look at refused."""
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
from PIL import Image

EDITOR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EDITOR))
import sandbox  # noqa: E402,F401  the user's own editor and settings are left alone

ASSETS = EDITOR.parent / "assets"


@unittest.skipIf(os.environ.get("SKIP_QT"), "needs Qt")
class VoxelPngMenuTests(unittest.TestCase):
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
        self.addCleanup(self.window.close)
        self.folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.window.open_path(ASSETS / "corpse.vx2")

    def test_menu_entries_sit_under_save_as(self):
        file = next(m for m in self.window.menuBar().findChildren(type(self.window.recent_menu))
                    if m.title() == "&File")
        texts = [a.text() for a in file.actions()]  # separators are ""
        at = texts.index("Save as…")
        self.assertEqual(texts[at + 1:at + 5], ["", "Export voxel PNG…", "Import voxel PNG…", ""])

    def test_paint_a_view_and_undo(self):
        menu, doc = self.window.voxel_png, self.window.doc
        files = menu.export(0, 4, ["front"], self.folder / "corpse")
        self.assertEqual([f.name for f in files], ["corpse.front.colour.png", "corpse.front.material.png",
                                                   "corpse.front.shaded.png"])
        before = doc.model.colour.copy()
        front = self.folder / "corpse.front.colour.png"
        image = Image.open(front)
        pixels, palette = np.asarray(image).copy(), image.getpalette()
        solid = np.argwhere(pixels > 0)[0]  # a block on the figure
        r, c = (solid // 4) * 4
        pixels[r:r + 4, c:c + 4] = 99
        painted = Image.fromarray(pixels, "P")
        painted.putpalette(palette)
        painted.save(front, transparency=0)
        report = menu.import_paths([front, self.folder / "corpse.front.shaded.png"])  # the shaded one is skipped
        self.assertEqual(report["changed_voxels"], 1)
        self.assertEqual(int((doc.model.colour == 99).sum() - (before == 99).sum()), 1)
        doc.undo()
        np.testing.assert_array_equal(doc.model.colour, before)

    def test_slices_open_as_a_new_model(self):
        menu, doc = self.window.voxel_png, self.window.doc
        colour, material = doc.model.colour.copy(), doc.model.material.copy()
        sheet = menu.export(1, 1, [], self.folder / "corpse")[0]
        doc.new(4, 4, 4)
        with mock.patch.object(self.window, "ask_save", return_value=True):
            report = menu.import_paths([sheet])
        self.assertEqual(report["size"], [33, 21, 64])
        np.testing.assert_array_equal(doc.model.colour, colour)
        np.testing.assert_array_equal(doc.model.material, material)
        self.assertIsNone(doc.model.path)

    def test_only_pictures_to_look_at_are_refused(self):
        from PySide6 import QtWidgets
        menu = self.window.voxel_png
        menu.export(0, 2, ["top"], self.folder / "corpse")
        with mock.patch.object(QtWidgets.QMessageBox, "warning") as warning:
            self.assertIsNone(menu.import_paths([self.folder / "corpse.top.shaded.png"]))
        self.assertIn("only to look at", warning.call_args[0][2])


if __name__ == "__main__":
    unittest.main()
