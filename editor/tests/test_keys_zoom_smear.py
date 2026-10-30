"""One keymap for every key (one's own in editor.local.json, the guide's table made from it), the slices' zoom and
pan, the smear brush, and 3D strokes without gaps."""
import json
import os
import sys
import unittest
from pathlib import Path

import numpy as np

EDITOR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EDITOR))
import sandbox  # noqa: E402,F401  the user's own editor and settings are left alone
from core.brushes import mirror_images, smear  # noqa: E402


def app():
    from PySide6 import QtWidgets
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)


class SmearTests(unittest.TestCase):
    labs = np.array([[50.0, 0, 0], [50.0, 60, 0], [50.0, -60, 0]] + [[100.0, 0, 0]] * 252)  # slots 1, 2, 3, ...

    def test_the_first_step_carries_and_writes_nothing(self):
        colour = np.zeros((1, 1, 4), dtype=np.uint8)
        colour[0, 0, 0] = 2
        out, carried = smear(colour, np.zeros_like(colour), self.labs, [(0, 0, 0)], None, 0.85)
        self.assertIsNone(out)
        self.assertEqual(carried[0].tolist(), [1.0])

    def test_full_strength_drags_a_voxel_along_and_fades_below(self):
        def drag(strength):
            colour = np.zeros((1, 1, 8), dtype=np.uint8)
            material = np.zeros_like(colour)
            colour[0, 0, 0], material[0, 0, 0] = 2, 7
            carried = None
            for x in range(8):  # a one-voxel brush moved along x
                out, carried = smear(colour, material, self.labs, [(x, 0, 0)], carried, strength)
                if out is not None:
                    (px, py, pz), = out[0]
                    colour[pz, py, px], material[pz, py, px] = out[1][0], out[2][0]
            return colour[0, 0], material[0, 0]
        colour, material = drag(1.0)
        self.assertEqual(colour.tolist(), [2] * 8)  # the voxel, its colour and material, all along the way
        self.assertEqual(material.tolist(), [7] * 8)
        colour, _ = drag(0.85)  # 0.85, 0.72, 0.61, 0.52, then less than half: it fades out
        self.assertEqual(colour.tolist(), [2] * 5 + [0] * 3)

    def test_dragging_air_into_a_solid_carves_it(self):
        colour = np.zeros((1, 1, 4), dtype=np.uint8)
        colour[0, 0, 1:] = 3
        carried = None
        for x in range(4):
            out, carried = smear(colour, np.zeros_like(colour), self.labs, [(x, 0, 0)], carried, 0.85)
            if out is not None:
                colour[0, 0, out[0][:, 0]] = out[1]
        self.assertEqual(colour[0, 0, 1], 0)

    def test_colours_mix_to_the_nearest_table_colour(self):
        colour = np.array([[[2, 3]]], dtype=np.uint8)  # red-ish, then green-ish
        _, carried = smear(colour, np.zeros_like(colour), self.labs, [(0, 0, 0)], None, 0.5)
        out, _ = smear(colour, np.zeros_like(colour), self.labs, [(1, 0, 0)], carried, 0.5)
        self.assertEqual(out[1].tolist(), [1])  # half and half: the grey between them

    def test_mirror_images_once_each_with_the_offsets_turned(self):
        images = mirror_images((2, 5, 5), (10, 10, 10), (True, False, False))
        self.assertEqual([(tuple(a), tuple(f)) for a, f in images], [((2, 5, 5), (1, 1, 1)), ((7, 5, 5), (-1, 1, 1))])
        self.assertEqual(len(mirror_images((5, 5, 5), (11, 10, 10), (True, False, False))), 1)  # on the plane


@unittest.skipIf(os.environ.get("SKIP_QT"), "needs Qt")
class KeymapTests(unittest.TestCase):
    def setUp(self):
        import local_config
        from qtui import keymap
        app()
        self.keymap, self.config = keymap, local_config.CONFIG
        before = self.config.read_text(encoding="utf-8") if self.config.exists() else None
        self.addCleanup(lambda: (self.config.write_text(before, encoding="utf-8") if before is not None
                                 else self.config.unlink(missing_ok=True), keymap.reload()))
        local_config.update("keys", None)
        keymap.reload()

    def test_the_defaults_have_no_clashes(self):
        self.assertEqual(self.keymap.conflicts(), [])

    def test_a_shared_key_clashes_only_where_both_work(self):
        km = self.keymap
        bindings = dict(km.current())
        bindings["view_front"] = ("M",)  # the 3D view's, and the Scene view has M: different views
        self.assertEqual(km.conflicts(bindings), [])
        bindings["view_back"] = ("Shift+R",)  # the 3D view's stamp key: the same view
        self.assertEqual([(a, b) for _, a, b in km.conflicts(bindings)], [("view_back", "stamp_turn_back")])
        bindings["view_back"] = ("Ctrl+1",)
        bindings["round"] = ("M",)  # anywhere: it clashes with both
        self.assertEqual({(a, b) for _, a, b in km.conflicts(bindings)},
                         {("round", "view_front"), ("round", "instance_mirror")})

    def test_own_keys_come_from_editor_local_json_and_only_changes_are_saved(self):
        km = self.keymap
        km.save({**km.current(), "size_up": ("+",), "redo": ("Ctrl+Y", "Ctrl+Shift+Z")})
        saved = json.loads(self.config.read_text(encoding="utf-8"))
        self.assertEqual(saved["keys"], {"size_up": ["+"]})  # redo as it was: left out
        self.assertEqual(km.keys("size_up"), ("+",))
        km.save(dict((a.name, a.keys) for a in km.ACTIONS))
        self.assertNotIn("keys", json.loads(self.config.read_text(encoding="utf-8")))

    def test_the_dialog_marks_a_clash_and_keeps_ok_off(self):
        from PySide6 import QtGui
        dialog = self.keymap.KeysDialog()
        self.assertTrue(dialog.ok.isEnabled())
        dialog.edits["brush_voxel"][0].setKeySequence(QtGui.QKeySequence("A"))  # Attach's key
        self.assertFalse(dialog.ok.isEnabled())
        self.assertIn("Attach", dialog.warning.text())
        dialog.defaults()
        self.assertTrue(dialog.ok.isEnabled())

    def test_the_guide_has_the_table(self):
        guide = (EDITOR / "docs" / "guide.md").read_text(encoding="utf-8")
        self.assertIn(self.keymap.guide_table(), guide, "run docs/keys_table.py")


@unittest.skipIf(os.environ.get("SKIP_QT"), "needs a native Qt window")
class SliceZoomTests(unittest.TestCase):
    def setUp(self):
        app()
        from qtui.brush import Brush
        from qtui.document import Document
        from qtui.slice_view import SliceView
        self.doc = Document()
        self.doc.new(256, 32, 64, ground=4)
        self.view = SliceView(self.doc, "Front")
        self.view.set_brush(Brush())
        self.view.resize(200, 300)
        self.view.show()
        self.addCleanup(self.view.close)
        from PySide6.QtTest import QTest
        QTest.qWait(50)
        self.canvas = self.view.canvas

    def test_a_wide_layer_fits_a_narrow_slice(self):
        cell, ox, oy = self.canvas._layout()
        self.assertLess(cell, 1)
        self.assertLessEqual(cell * 256, self.canvas.width())  # once it overflowed and was cut off
        self.assertGreaterEqual(ox, 0)

    def test_zoom_keeps_the_cell_under_the_cursor_and_fits_again(self):
        from PySide6 import QtCore
        at = QtCore.QPointF(90, 150)
        under = self.canvas.cell_at(at)
        for _ in range(12):
            self.canvas.zoom_at(at, 1)
            self.assertEqual(self.canvas.cell_at(at), under)
        self.assertGreaterEqual(self.canvas._layout()[0], 6)  # close enough for the grid
        self.canvas.zoom_at(at, -40)
        self.assertIsNone(self.canvas.zoom)

    def test_keys_and_mouse(self):
        from PySide6 import QtCore
        from PySide6.QtTest import QTest
        Key, Button = QtCore.Qt.Key, QtCore.Qt.MouseButton
        depth = self.view.depth_box.value()
        QTest.keyClick(self.canvas, Key.Key_PageUp)
        QTest.keyClick(self.canvas, Key.Key_Period)
        QTest.keyClick(self.canvas, Key.Key_Comma)
        self.assertEqual(self.view.depth_box.value(), depth + 1)
        self.canvas.zoom_at(QtCore.QPointF(100, 150), 8)
        pan = QtCore.QPointF(self.canvas.pan)
        QTest.mousePress(self.canvas, Button.MiddleButton, pos=QtCore.QPoint(100, 150))
        QTest.mouseMove(self.canvas, QtCore.QPoint(130, 140))
        QTest.mouseRelease(self.canvas, Button.MiddleButton, pos=QtCore.QPoint(130, 140))
        self.assertEqual(self.canvas.pan - pan, QtCore.QPointF(30, -10))
        QTest.keyClick(self.canvas, Key.Key_Home)
        self.assertIsNone(self.canvas.zoom)

    def test_a_stroke_stops_at_the_edge_and_pans_along(self):
        from PySide6 import QtCore
        from PySide6.QtTest import QTest
        self.doc.set_tool("attach")
        self.view.depth_box.setValue(10)
        # the fitted layer is a thin band across the canvas's middle: a fixed row (150) lay just below it where
        # the canvas came out a little lower (250 pixels on Linux and macOS), so no stroke began
        y = self.canvas.height() // 2
        self.canvas.zoom_at(QtCore.QPointF(10, y), 10)
        start = QtCore.QPoint(20, y)
        QTest.mousePress(self.canvas, QtCore.Qt.MouseButton.LeftButton, pos=start)
        self.assertIsNotNone(self.canvas.stroke_button)
        before = QtCore.QPointF(self.canvas.pan)
        QTest.mouseMove(self.canvas, QtCore.QPoint(self.canvas.width() + 80, y))
        QTest.qWait(200)
        self.assertLess(self.canvas.pan.x(), before.x())  # panned towards the cursor
        QTest.mouseRelease(self.canvas, QtCore.Qt.MouseButton.LeftButton,
                           pos=QtCore.QPoint(self.canvas.width() + 80, y))
        u, v = self.canvas.cell_at(QtCore.QPointF(self.canvas.width() - 1, y))
        self.assertTrue(self.doc.model.colour[v, 10, :u + 1].all() or self.doc.model.colour[:, 10, u].any())

    def test_leaving_clears_the_status_bar(self):
        from PySide6 import QtCore
        texts = []
        self.doc.hover_changed.connect(texts.append)
        self.canvas._move_to(QtCore.QPointF(100, 150))
        self.canvas.leaveEvent(None)
        self.assertEqual(texts[-1], "")


@unittest.skipIf(os.environ.get("SKIP_QT"), "needs a native Qt window")
class WindowKeysTests(unittest.TestCase):
    def setUp(self):
        from qtui import render_view
        start = render_view.RenderView.start
        render_view.RenderView.start = lambda self: None
        self.addCleanup(setattr, render_view.RenderView, "start", start)
        app()
        from qtui.window import EditorWindow
        self.window = EditorWindow()
        self.window.confirm_close = lambda: True
        self.addCleanup(self.window.close)
        self.window.new_model(16, 16, 16, "Floor", 2)
        self.window.show()
        self.window.activateWindow()
        from PySide6.QtTest import QTest
        if not QTest.qWaitForWindowActive(self.window):  # menu keys work only while a window of the editor is
            self.skipTest("the window did not get the focus")

    def press(self, key, mods=None, widget=None):
        from PySide6 import QtCore
        from PySide6.QtTest import QTest
        QTest.keyClick(widget or self.window.slices["Top"].canvas, key, mods or QtCore.Qt.KeyboardModifier.NoModifier)

    def test_brush_keys_work_from_a_slice(self):
        from PySide6 import QtCore
        Key, Mod = QtCore.Qt.Key, QtCore.Qt.KeyboardModifier
        brush = self.window.edit_view.brush
        self.window.slices["Top"].canvas.setFocus()
        size = brush.size
        self.press(Key.Key_BracketRight)
        self.press(Key.Key_Plus)
        self.assertEqual(brush.size, size + 2)
        self.press(Key.Key_Minus, Mod.KeypadModifier)  # the number pad's minus too
        self.assertEqual(brush.size, size + 1)
        self.press(Key.Key_U)
        self.assertEqual(brush.kind, "smear")
        self.press(Key.Key_V)
        self.assertEqual(brush.kind, "voxel")
        self.press(Key.Key_X, Mod.AltModifier)
        self.assertEqual(brush.mirror, (True, False, False))
        self.press(Key.Key_C)
        self.assertTrue(brush.round)
        self.press(Key.Key_B, Mod.ControlModifier)
        self.assertFalse(self.window.slices["Side"].ghost_box.isChecked())

    def test_ctrl_shift_z_redoes(self):
        from PySide6 import QtCore
        Key, Mod = QtCore.Qt.Key, QtCore.Qt.KeyboardModifier
        doc = self.window.doc
        doc.set_voxels([(3, 3, 5)], colour=4)
        doc.undo()
        self.assertEqual(doc.voxel(3, 3, 5), 0)
        self.press(Key.Key_Z, Mod.ControlModifier | Mod.ShiftModifier)
        self.assertEqual(doc.voxel(3, 3, 5), 4)


@unittest.skipIf(os.environ.get("SKIP_QT"), "needs Qt")
class SliceSmearTests(unittest.TestCase):
    def test_a_slice_stroke_drags_voxels_mirrored_in_one_undo_step(self):
        app()
        from qtui.brush import Brush
        from qtui.document import Document
        from qtui.slice_view import SliceView
        doc = Document()
        doc.new(20, 8, 8)
        doc.set_voxels([(2, 4, 4), (17, 4, 4)], colour=5)  # a voxel and its mirror image across x
        view = SliceView(doc, "Top")
        brush = Brush()
        brush.set(kind="smear", size=1, smear_strength=1.0, mirror=(True, False, False))
        view.set_brush(brush)
        view.depth_box.setValue(4)
        view.begin_stroke()
        view.draw([(2, 4)], "attach")
        view.draw([(3, 4), (4, 4), (5, 4)], "attach")  # the mode does not matter: smear is a sculpting brush
        view.end_stroke()
        self.assertEqual(doc.model.colour[4, 4, 2:6].tolist(), [5] * 4)
        self.assertEqual(doc.model.colour[4, 4, 14:18].tolist(), [5] * 4)  # the mirror image dragged its own
        doc.undo()
        self.assertEqual(int((doc.model.colour > 0).sum()), 2)


@unittest.skipIf(os.environ.get("SKIP_QT"), "needs a native Qt window")
class StrokeGapTests(unittest.TestCase):
    def test_a_fast_3d_drag_leaves_no_gaps(self):
        from qtui import render_view
        start = render_view.RenderView.start
        render_view.RenderView.start = lambda self: None
        self.addCleanup(setattr, render_view.RenderView, "start", start)
        app()
        from qtui.window import EditorWindow
        window = EditorWindow()
        window.confirm_close = lambda: True
        self.addCleanup(window.close)
        window.new_model(40, 8, 8, "Floor", 2)
        view, doc = window.edit_view, window.doc
        view._pick = lambda pos: ((pos[0] // 10, 3, 1), (pos[0] // 10, 3, 2))  # ten pixels a voxel along x
        doc.set_tool("paint")
        doc.set_colour(9)
        view.begin_stroke((5, 0), "paint")
        view.continue_stroke((385, 0))  # one mouse event across 38 voxels
        view.end_stroke()
        self.assertTrue((doc.model.colour[1, 3, 0:39] == 9).all())


if __name__ == "__main__":
    unittest.main()
