"""Colours per project: the default table stays as it is, a project saves its own colours file, its parts
follow a changed colour and are restamped, a model opens with the colours it was saved with, and a model
brought from another project's colours is remapped into a copy of its own.

Works on copies of assets/alchemist and skeleton, removed afterwards; the Qt check drives the real window.
"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import sandbox  # noqa: E402,F401  the user's own editor and settings are left alone
from core.colours import default_table  # noqa: E402
from core.model import SAVE_ROOT, Model, vx2  # noqa: E402
from core.scene import SUFFIX, Project  # noqa: E402

PROJECTS = ("_test_colours_a", "_test_colours_b")
COPIES = {m: SAVE_ROOT / f"_test_colours_{m}.vx2" for m in ("alchemist", "skeleton")}


def remove_test_files():
    for path in [*COPIES.values(), *SAVE_ROOT.glob("_test_colours_*")]:
        path.unlink(missing_ok=True)
        (SAVE_ROOT.parent / "export" / f"{path.stem}.vox").unlink(missing_ok=True)


class ColourTableTests(unittest.TestCase):
    def test_the_default_table_never_changes_a_copy_does(self):
        table = default_table()
        self.assertTrue(table.read_only and table.is_default)
        self.assertEqual(table.title, "Default colours")
        with self.assertRaises(ValueError):
            table.set_rgb(5, (1, 2, 3))
        own = table.copy(owner="mine")
        self.assertEqual(own.fingerprint, table.fingerprint)  # the same colours: the same fingerprint
        self.assertTrue(own.set_hex(5, "#123456"))
        self.assertFalse(own.set_hex(5, "123456"))  # already that colour
        self.assertEqual((own.by_id[5]["rgb"], own.changed_slots(), own.modified), ([0x12, 0x34, 0x56], [5], True))
        self.assertNotEqual(own.fingerprint, table.fingerprint)
        self.assertNotEqual(table.by_id[5]["hex"], "#123456")
        self.assertEqual(own.rgb[5].tolist(), [0x12, 0x34, 0x56])
        with self.assertRaises(ValueError):
            own.set_hex(5, "#12345")
        own.revert(5)
        self.assertFalse(own.modified)

    def test_mapping_keeps_equal_slots_and_finds_the_nearest(self):
        own = default_table().copy()
        own.set_rgb(40, default_table().by_id[41]["rgb"])  # 40 now looks exactly like 41
        lut = default_table().mapping_to(own)
        self.assertEqual(lut[0], 0)
        self.assertEqual(lut[41], 41)
        self.assertEqual(lut[40], own.nearest(default_table().by_id[40]["rgb"], 1)[0][0])  # gone: the nearest
        self.assertNotEqual(lut[40], 40)
        self.assertEqual(sum(lut[s] != s for s in range(1, 256)), 1)


class DisplayOrderTests(unittest.TestCase):
    def test_every_order_shows_every_slot_once(self):
        from core.colours import ORDERS, display_order
        table = default_table()
        slots = [c["id"] for c in table.colors]
        self.assertEqual(display_order(table, "Table"), slots)
        for order in ORDERS:
            self.assertEqual(sorted(display_order(table, order)), slots, order)
        steps = [int(table.by_id[s]["lch"][0] // 10) for s in display_order(table, "Lightness")]
        self.assertEqual(steps, sorted(steps))  # dark to light, in steps of L* 10
        hue = display_order(table, "Hue")
        greys = [s for s in hue if table.by_id[s]["lch"][1] < 8]
        self.assertEqual(hue[:len(greys)], greys)  # greys first
        with self.assertRaises(ValueError):
            display_order(table, "Random")

    def test_similar_puts_alike_colours_side_by_side(self):
        from core.colours import display_order
        from colour_math import de2000
        table = default_table()

        def steps(order):
            labs = np.array([table.by_id[s]["lab"] for s in order])
            return float(np.mean(de2000(labs[:-1], labs[1:])))
        self.assertLess(steps(display_order(table, "Similar")), steps(display_order(table, "Table")))


class ProjectColourTests(unittest.TestCase):
    def setUp(self):
        for model, copy in COPIES.items():
            shutil.copyfile(SAVE_ROOT / f"{model}.vx2", copy)

    def tearDown(self):
        remove_test_files()

    def _project(self, name: str) -> Project:
        project = Project()
        part = project.add_model(COPIES["alchemist"])
        project.add_instance(project.add_scene(), part)
        project.save(name)
        return project

    def test_a_project_saves_its_colours_and_its_parts_follow_them(self):
        project = self._project(PROJECTS[0])
        colours = SAVE_ROOT / f"{PROJECTS[0]}.colors.json"
        data = json.loads((SAVE_ROOT / f"{PROJECTS[0]}{SUFFIX}").read_text(encoding="utf-8"))
        self.assertEqual(data["colours"], colours.name)
        self.assertEqual(len(json.loads(colours.read_text(encoding="utf-8"))["colors"]), 255)
        self.assertEqual(project.table.title, f"{PROJECTS[0]} colours")
        part = project.models["_test_colours_alchemist"]
        self.assertIs(part.table, project.table)  # every part on the project's colours, one object

        # change a colour the part uses: unsaved until Save project, which restamps every part
        slot = int(np.unique(part.colour[part.colour > 0])[0])
        project.table.set_hex(slot, "#ff00ff")
        self.assertTrue(project.colours_modified())
        self.assertEqual(part.table.by_id[slot]["hex"], "#ff00ff")
        with self.assertRaises(ValueError):  # the file still names the old colours
            vx2.read_model(COPIES["alchemist"], colors=project.table.colors)
        project.save()
        self.assertFalse(project.colours_modified())
        vx2.read_model(COPIES["alchemist"], colors=project.table.colors)  # restamped

        # reopened: its colours file; the part alone opens with the colours it was saved with
        reopened = Project()
        reopened.load(SAVE_ROOT / f"{PROJECTS[0]}{SUFFIX}")
        self.assertEqual(reopened.table.by_id[slot]["hex"], "#ff00ff")
        self.assertEqual(reopened.notes, [])
        loose = Model()
        loose.open(COPIES["alchemist"])
        self.assertEqual((loose.table.title, loose.table.read_only), (f"{PROJECTS[0]} colours", True))
        info = loose.info()
        self.assertEqual(info["colour_table"], f"{PROJECTS[0]} colours")
        self.assertIn("#ff00ff", [c["hex"] for c in info["colours"]])

    def test_a_model_from_another_projects_colours_becomes_a_remapped_copy(self):
        first = self._project(PROJECTS[0])
        slot = int(np.unique(first.models["_test_colours_alchemist"].colour)[1])
        first.table.set_hex(slot, "#ff00ff")
        first.save()
        before = COPIES["alchemist"].read_bytes()

        second = Project()
        second.add_model(COPIES["skeleton"])
        second.save(PROJECTS[1])
        name = second.add_model(COPIES["alchemist"])
        model = second.models[name]
        self.assertIs(model.table, second.table)
        self.assertNotIn(slot, np.unique(model.colour).tolist())  # magenta is not in the default colours
        self.assertEqual(model.path.name, f"_test_colours_alchemist-{PROJECTS[1]}.vx2")
        self.assertIn(name, second.modified_models())
        self.assertEqual(len(second.notes), 1)
        self.assertIn(f"{PROJECTS[0]} colours", second.notes[0])
        second.save()
        self.assertEqual(COPIES["alchemist"].read_bytes(), before)  # the other project's part as it was
        vx2.read_model(model.path, colors=second.table.colors)

    def test_restamp_keeps_a_project_part_on_its_colours(self):
        project = self._project(PROJECTS[0])
        project.table.set_hex(1, "#010203")
        project.save()
        path = COPIES["alchemist"]
        own = vx2.find_colours(vx2.read_fingerprints(path)[0], [path.parent])
        self.assertEqual(own.name, f"{PROJECTS[0]}.colors.json")
        self.assertIsNone(vx2.find_colours(b"\0" * 8, [path.parent]))

        # colours that are in no file: the model says so instead of opening on the wrong ones
        lost = default_table().copy()
        lost.set_hex(1, "#fedcba")
        colour, material, local = vx2.read_model(path, check_tables=False)
        tmp = Path(tempfile.mkdtemp()) / "lost.vx2"
        vx2.write(tmp, colour, material, local, lost.colors)
        with self.assertRaises(ValueError) as error:
            Model().open(tmp)
        self.assertIn("colours that are not here", str(error.exception))


class QtColourTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6 import QtWidgets
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        for model, copy in COPIES.items():
            shutil.copyfile(SAVE_ROOT / f"{model}.vx2", copy)

    def tearDown(self):
        remove_test_files()

    @staticmethod
    def _window():
        from PySide6 import QtCore
        from PySide6.QtTest import QTest
        from qtui.window import EditorWindow
        window = EditorWindow()
        window._engine_started = True
        window.settings = QtCore.QSettings(str(Path(tempfile.mkdtemp()) / "layout.ini"),
                                           QtCore.QSettings.Format.IniFormat)
        window.confirm_close = lambda: True
        window.show()
        QTest.qWait(200)
        return window

    def test_the_colours_dock_says_whose_colours_and_changes_the_projects(self):
        from PySide6 import QtCore
        from PySide6.QtTest import QTest
        window = self._window()
        doc, panel, pdoc = window.doc, window.palette, window.scenes.project_doc

        # at the start: the new project's colours, not changeable until the project is saved
        self.assertIs(doc.model.table, pdoc.project.table)
        self.assertEqual(panel.table_title.text(), "New project's colours")
        self.assertFalse(panel.change_button.isEnabled())
        self.assertIn("Save the project", panel.table_hint.text())

        # a project saved: its own colours, changed live in its parts and the scene
        name = pdoc.add_model(COPIES["alchemist"])
        pdoc.add_instance(name)
        window.scenes.edit_model(name)
        pdoc.save_project(PROJECTS[0])
        self.assertEqual(panel.table_title.text(), f"{PROJECTS[0]} colours")
        self.assertTrue(panel.change_button.isEnabled())
        part = pdoc.project.models[name]
        slot = int(np.unique(part.colour[part.colour > 0])[0])
        doc.set_colour(slot)
        seen = []
        doc.colours_changed.connect(lambda: seen.append(True))
        panel.hex_box.setText("#00ff00")
        panel.hex_box.editingFinished.emit()
        self.assertEqual(seen, [True])
        self.assertEqual(doc.rgb[slot].tolist(), [0, 255, 0])
        self.assertIn("1 changed, not saved", panel.table_file.text())
        self.assertTrue(panel.revert_button.isEnabled())
        self.assertTrue(any("colours changed" in line for line in window.unsaved()))
        window.save()  # Ctrl+S on a part with changed colours saves the project: colours file and parts
        self.assertFalse(pdoc.project.colours_modified())
        saved = json.loads((SAVE_ROOT / f"{PROJECTS[0]}.colors.json").read_text(encoding="utf-8"))["colors"]
        self.assertEqual(saved[slot - 1]["hex"], "#00ff00")

        # another order lays the grid out differently; a click still picks the slot under it
        panel.order_box.setCurrentText("Lightness")
        grid = panel.grid
        self.assertEqual(grid.order, "Lightness")
        first = grid.slots()[0]
        self.assertEqual(doc.model.table.by_id[first]["lch"][0], min(c["lch"][0] for c in doc.model.colors))
        QTest.mouseClick(grid, QtCore.Qt.MouseButton.LeftButton, pos=QtCore.QPoint(5 + 18, 5))
        self.assertEqual(doc.colour, grid.slots()[1])
        grid.frozen = True  # the colour dialog is open: the order stays while the colour changes
        before = list(grid.slots())
        doc.set_slot_colour(grid.slots()[0], (255, 255, 255))
        self.assertEqual(grid.slots(), before)
        grid.frozen = False
        self.assertNotEqual(grid.slots()[0], before[0])  # re-laid once the dialog closes
        doc.revert_colours()
        panel.order_box.setCurrentText("Table")

        # a model opened alone with the default colours: read-only, and says so
        self._opened_alone_is_read_only(window)
        window.close()

    def test_new_starts_filled_like_magicavoxel(self):
        """File > New starts Filled by default, or with a floor, or empty."""
        window = self._window()
        doc = window.doc
        dialog, read = window.new_model_form()
        self.assertEqual(dialog.start.currentText(), "Filled")
        self.assertFalse(dialog.ground.isEnabled())
        dialog.boxes["x"].setValue(8)
        dialog.boxes["y"].setValue(6)
        dialog.boxes["z"].setValue(5)
        window.new_model(*read())
        self.assertEqual(int((doc.model.colour == doc.colour).sum()), 8 * 6 * 5)
        dialog.start.setCurrentText("Floor")
        self.assertTrue(dialog.ground.isEnabled())
        dialog.ground.setValue(2)
        window.new_model(*read())
        self.assertEqual(int((doc.model.colour > 0).sum()), 8 * 6 * 2)
        dialog.start.setCurrentText("Empty")
        window.new_model(*read())
        self.assertEqual(int((doc.model.colour > 0).sum()), 0)
        dialog.deleteLater()
        window.close()

    def _opened_alone_is_read_only(self, window):
        doc, panel = window.doc, window.palette
        doc.open(COPIES["skeleton"])
        self.assertEqual(panel.table_title.text(), "Default colours")
        self.assertFalse(panel.change_button.isEnabled())
        self.assertIn("palette/colors.json", panel.table_hint.text())
        with self.assertRaises(ValueError):
            doc.set_slot_colour(1, (1, 2, 3))


if __name__ == "__main__":
    unittest.main()
