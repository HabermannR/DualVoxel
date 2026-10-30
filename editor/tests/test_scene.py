"""Models placed in scenes: orientations, arrays, the project file, and the Qt editor's outliner, scene view
and transform panel.

The Qt check drives the real window (it needs the native platform); it works on
copies of assets/alchemist, skeleton and corpse, removed afterwards.
"""
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import sandbox  # noqa: E402,F401  the user's own editor and settings are left alone
from core.model import SAVE_ROOT  # noqa: E402
from core.scene import (IDENTITY, SUFFIX, Project, mirrored, orient_from_text, orient_text,  # noqa: E402
                        place_plane, place_point, placed_size, rotated)

MODELS = ("alchemist", "skeleton", "corpse")
COPIES = {m: SAVE_ROOT / f"_test_model_{m}.vx2" for m in MODELS}
NAMES = {m: COPIES[m].stem for m in MODELS}
PROJECT = "_test_scene"


def copy_models():
    for model, copy in COPIES.items():
        shutil.copyfile(SAVE_ROOT / f"{model}.vx2", copy)


def remove_test_files():
    for copy in COPIES.values():
        copy.unlink(missing_ok=True)
        (SAVE_ROOT.parent / "export" / f"{copy.stem}.vox").unlink(missing_ok=True)
    (SAVE_ROOT / f"{PROJECT}{SUFFIX}").unlink(missing_ok=True)
    (SAVE_ROOT / f"{PROJECT}.colors.json").unlink(missing_ok=True)


def all_orientations():
    found, todo = {IDENTITY}, [IDENTITY]
    while todo:
        o = todo.pop()
        for n in [rotated(o, a) for a in range(3)] + [mirrored(o, a) for a in range(3)]:
            if n not in found:
                found.add(n)
                todo.append(n)
    return found


class OrientationTests(unittest.TestCase):
    def test_48_orientations_planes_and_points_agree(self):
        orients = all_orientations()
        self.assertEqual(len(orients), 48)  # 24 rotations, each mirrored or not
        plane = np.random.default_rng(1).integers(0, 9, (5, 3, 4)).astype(np.uint8)  # (z, y, x): 4 x 3 x 5
        for o in orients:
            self.assertEqual(orient_from_text(orient_text(o)), o)
            placed = place_plane(plane, o)
            self.assertEqual(placed.shape[::-1], placed_size((4, 3, 5), o))
            for z, y, x in np.ndindex(*plane.shape):
                X, Y, Z = place_point((x, y, z), (4, 3, 5), o)
                self.assertEqual(placed[Z, Y, X], plane[z, y, x])

    def test_turns_are_counter_clockwise(self):
        self.assertEqual(orient_text(rotated(IDENTITY, 2)), "+y-x+z")  # about z: x goes to y
        self.assertEqual(orient_text(rotated(IDENTITY, 0)), "+x+z-y")  # about x: y goes to z
        self.assertEqual(orient_text(rotated(IDENTITY, 1)), "-z+y+x")  # about y: z goes to x
        self.assertEqual(rotated(IDENTITY, 2, 4), IDENTITY)
        self.assertEqual(orient_text(mirrored(IDENTITY, 0)), "-x+y+z")


class ProjectTests(unittest.TestCase):
    def setUp(self):
        copy_models()

    def tearDown(self):
        remove_test_files()

    def test_save_reopen_and_models_are_shared(self):
        project = Project()
        names = [project.add_model(COPIES[m]) for m in MODELS]
        self.assertEqual(project.add_model(COPIES["alchemist"]), names[0])  # a model loads once
        first, second = project.add_scene(), project.add_scene("Ring")
        a1 = project.add_instance(first, names[0])
        project.add_instance(first, names[1])
        a2 = project.array_grid(first, a1, (2, 1, 1))[0]
        project.reorient(a2, mirrored(rotated(a2.orient, 0), 1))
        project.add_instance(second, names[2], position=(5, -3, 2))
        project.save(PROJECT)

        reopened = Project()
        reopened.load(SAVE_ROOT / f"{PROJECT}{SUFFIX}")
        self.assertEqual([s.name for s in reopened.scenes], ["Scene-1", "Ring"])
        self.assertEqual([i.to_json() for i in reopened.scenes[0].instances], [i.to_json() for i in first.instances])
        self.assertEqual(reopened.scenes[1].instances[0].position, (5, -3, 2))

        # one Model per model: an edit shows in every instance of it, no copies
        model = reopened.models[names[0]]
        sz, sy, sx = model.colour.shape
        model.paint_box((0, 0, sz - 1), (0, 0, sz - 1), 1, 0)
        colour, _, lo, _ = reopened.merged(reopened.scenes[0])
        followers = [i for i in reopened.scenes[0].instances if i.model == names[0]]
        self.assertEqual(len(followers), 2)
        for instance in followers:
            x, y, z = np.add(place_point((0, 0, sz - 1), (sx, sy, sz), instance.orient), instance.position) - lo
            self.assertEqual(colour[z, y, x], 1)
        self.assertEqual(reopened.modified_models(), [names[0]])

    def test_rotation_keeps_the_bottom_and_the_centre(self):
        project = Project()
        name = project.add_model(COPIES["corpse"])  # 33 x 21 x 64
        scene = project.add_scene()
        instance = project.add_instance(scene, name, (10, 20, 5))
        before = project.box(instance)
        project.reorient(instance, rotated(instance.orient, 0))  # tip it over about x
        lo, hi = project.box(instance)
        self.assertEqual(lo[2], 5)
        self.assertEqual(tuple(hi - lo), (33, 64, 21))
        self.assertLessEqual(np.abs((lo + hi)[:2] / 2 - (before[0] + before[1])[:2] / 2).max(), 0.5)

    def test_arrays(self):
        project = Project()
        name = project.add_model(COPIES["skeleton"])  # 32 x 32 x 32
        scene = project.add_scene()
        source = project.add_instance(scene, name, (10, 10, 0))
        grid = project.array_grid(scene, source, (3, 2, 1), gap=2)
        self.assertEqual(len(grid), 5)
        self.assertEqual({i.position for i in scene.instances},
                         {(10 + 34 * a, 10 + 34 * b, 0) for a in range(3) for b in range(2)})
        ring_scene = project.add_scene()
        first = project.add_instance(ring_scene, name)
        ring = project.array_circle(ring_scene, first, 4, 40)
        centre = (np.array(project.box(first)[0]) + project.box(first)[1]) / 2 + (0, 40, 0)
        for instance, angle in zip(ring, (0, 90, 180)):  # first is at -90 degrees, the rest every 90
            lo, hi = project.box(instance)
            offset = (lo + hi) / 2 - centre
            expected = 40 * np.array([np.cos(np.radians(angle)), np.sin(np.radians(angle))])
            self.assertLessEqual(np.abs(offset[:2] - expected).max(), 0.5)
            # facing out: the model's front (-y) points away from the centre
            front = -np.array(instance.orient)[:, 1][:2]
            self.assertGreater(front @ expected, 0)


@unittest.skipIf(os.environ.get("SKIP_QT") == "1", "SKIP_QT=1")
class QtSceneTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6 import QtWidgets
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        copy_models()

    def tearDown(self):
        remove_test_files()

    def test_build_a_scene_edit_a_model_and_reopen(self):
        from PySide6 import QtCore, QtWidgets
        from PySide6.QtTest import QTest
        from qtui.window import EditorWindow
        Key, Mod = QtCore.Qt.Key, QtCore.Qt.KeyboardModifier

        window = EditorWindow()
        window._engine_started = True  # no GPU renderer for this check
        window.settings = QtCore.QSettings(str(Path(tempfile.mkdtemp()) / "layout.ini"),
                                           QtCore.QSettings.Format.IniFormat)  # leave the user's layout alone
        window.confirm_close = lambda: True  # close without asking to save
        window.show()
        QTest.qWait(200)
        scenes = window.scenes
        pdoc, outliner, view, panel = scenes.project_doc, scenes.outliner, scenes.scene_view, scenes.transform
        for model in MODELS:
            outliner.select_model(pdoc.add_model(COPIES[model]))
        for model in MODELS:
            outliner.select_model(NAMES[model])
            outliner.buttons["Add instance"].click()
        scene = pdoc.scene
        self.assertEqual([i.model for i in scene.instances], [NAMES[m] for m in MODELS])
        self.assertTrue(window.docks["Scene"].isCurrentTab())
        self.assertTrue(window.docks["Transform"].isCurrentTab())

        # click the alchemist in the view to select it, then drag it by 5 voxels along x
        alchemist = scene.instances[0]
        pdoc.select(None)
        view.frame()
        renderer = view.plotter.renderer

        def display(point):
            renderer.SetWorldPoint(*point, 1)
            renderer.WorldToDisplay()
            x, y, _ = renderer.GetDisplayPoint()
            return int(round(x)), int(round(y))

        lo, hi = pdoc.project.box(alchemist)
        grab = display(((lo[0] + hi[0]) / 2, lo[1], (lo[2] + hi[2]) / 2))
        view.click(grab)
        self.assertIs(pdoc.instance, alchemist)
        self.assertTrue(view.begin_drag(grab))
        view.continue_drag(display(view.drag[1] + (2.6, 0, 0)))
        view.end_drag(display(view.drag[1] + (5.2, 0, 0)))
        self.assertEqual(alchemist.position, (5, 0, 0))
        self.assertEqual(len(pdoc.undo_stack), 4)  # three instances added, one drag

        # keys: the view looks from -y, so Up moves away (+y) and Right along +x
        widget = view.plotter.interactor
        QTest.keyClick(widget, Key.Key_Left)
        QTest.keyClick(widget, Key.Key_Up, Mod.ShiftModifier)
        QTest.keyClick(widget, Key.Key_PageUp)
        self.assertEqual(alchemist.position, (4, 8, 1))
        QTest.keyClick(widget, Key.Key_R)
        self.assertEqual(orient_text(alchemist.orient), "+y-x+z")
        QTest.keyClick(widget, Key.Key_D, Mod.ControlModifier)
        copy = pdoc.instance
        self.assertEqual((copy.model, copy.orient), (alchemist.model, alchemist.orient))
        QTest.keyClick(widget, Key.Key_M)  # left-right as seen from -y: x
        self.assertEqual(orient_text(copy.orient), "+y+x+z")  # the model's y axis, along x, flips
        QTest.keyClick(widget, Key.Key_D, Mod.ControlModifier)
        QTest.keyClick(widget, Key.Key_Delete)
        self.assertEqual(len(scene.instances), 4)
        self.assertEqual(len(view.actors), 4)

        # the transform panel: position, rotations, mirror, a grid, then undo it with Ctrl+Z in the view
        pdoc.select(copy)
        panel.position[2].setValue(3)  # as a click on its arrows: moves at once, the yellow box with it
        self.assertEqual(copy.position[2], 3)
        lo, _ = pdoc.project.box(copy)
        self.assertAlmostEqual(view.plotter.actors["selected"].GetBounds()[4], lo[2] - 0.1, places=3)
        rotate_x_plus = panel.buttons[1]
        rotate_x_plus.click()
        self.assertEqual(copy.position[2], 3)  # the bottom stays
        panel.counts[0].setValue(2)
        panel.counts[1].setValue(3)
        panel._make_grid()
        self.assertEqual(len(scene.instances), 4 + 5)
        self.assertEqual(len(view.actors), 9)
        widget.setFocus()
        QTest.qWait(50)
        undo_action = next(a for a in window.menuBar().findChildren(QtWidgets.QMenu) if a.title() == "&Edit").actions()[0]
        self.assertEqual(undo_action.text(), "Undo")
        undo_action.trigger()  # Ctrl+Z; the focus is in the scene view, so the scene's grid goes
        self.assertEqual(len(scene.instances), 4)
        self.assertIs(pdoc.instance, scene.instances[3])
        scenes.redo()
        self.assertEqual(len(scene.instances), 9)
        scenes.undo()
        self.assertIn("4 instances", outliner.tree.topLevelItem(1).child(0).text(1))

        # a second scene, then back
        outliner.buttons["New scene"].click()
        self.assertEqual(len(view.actors), 0)
        pdoc.show_scene(scene)
        self.assertEqual(len(view.actors), 4)

        # save, edit the alchemist in the model docks, see both instances follow
        scenes._save_project(PROJECT)
        alchemist = scene.instances[0]
        pdoc.select(alchemist)
        view.buttons["Edit model"].click()
        model = pdoc.project.models[NAMES["alchemist"]]
        self.assertIs(window.doc.model, model)
        self.assertTrue(window.docks["3D edit"].isCurrentTab())
        sx, sy, sz = window.doc.size
        top = (sx // 2, sy // 2, sz - 1)
        before = window.doc.voxel(*top)
        window.doc.set_voxels([top], colour=1, material=0)
        QTest.qWait(100)  # the scene view rebuilds on a short timer
        followers = [i for i in scene.instances if i.model == NAMES["alchemist"]]
        self.assertEqual(len(followers), 2)
        for instance in followers:
            self.assertEqual(view.actors[instance][1][1], model.version)  # the mesh of the edited model
        QTest.qWait(400)  # the outliner marks edited models on a timer
        self.assertIn("*", outliner.tree.topLevelItem(0).child(0).text(0))
        window.edit_view.plotter.interactor.setFocus()
        QTest.qWait(50)
        scenes.undo()  # the focus is in the model docks: the model's edit is undone, not the scene's
        self.assertEqual(window.doc.voxel(*top), before)
        self.assertEqual(len(scene.instances), 4)

        # File > New while a project's model is open leaves that model as it is
        shape = model.colour.shape
        window.doc.new(8, 8, 8)
        self.assertIsNot(window.doc.model, model)
        self.assertEqual(model.colour.shape, shape)
        self.assertEqual(window.doc.size, (8, 8, 8))

        # reopen the saved project in the same window
        window.open_path(SAVE_ROOT / f"{PROJECT}{SUFFIX}")
        self.assertEqual([s.name for s in pdoc.project.scenes], ["Scene-1", "Scene-2"])
        self.assertEqual([i.to_json() for i in pdoc.project.scenes[0].instances], [i.to_json() for i in scene.instances])
        self.assertEqual(len(pdoc.project.models), 3)
        window.close()

    def _window(self, ask_to_save: bool = False):
        from PySide6 import QtCore
        from PySide6.QtTest import QTest
        from qtui.window import EditorWindow
        window = EditorWindow()
        window._engine_started = True
        window.settings = QtCore.QSettings(str(Path(tempfile.mkdtemp()) / "layout.ini"),
                                           QtCore.QSettings.Format.IniFormat)
        if not ask_to_save:
            window.confirm_close = lambda: True  # close without asking to save
        window.show()
        QTest.qWait(200)
        return window

    @staticmethod
    def _display(view, point):
        renderer = view.plotter.renderer
        renderer.SetWorldPoint(*point, 1)
        renderer.WorldToDisplay()
        return tuple(int(round(v)) for v in renderer.GetDisplayPoint()[:2])

    def test_the_render_follows_the_scene_or_the_model(self):
        from PySide6 import QtCore
        from PySide6.QtTest import QTest
        from core.model import ROOT as PIPELINE
        from qtui.window import EditorWindow
        window = EditorWindow()
        window._engine_started = True  # no GPU renderer for this check
        window.settings = QtCore.QSettings(str(Path(tempfile.mkdtemp()) / "layout.ini"),
                                           QtCore.QSettings.Format.IniFormat)
        window.confirm_close = lambda: True  # close without asking to save
        window.show()
        QTest.qWait(200)
        render, scenes = window.render_view, window.scenes
        self.assertFalse(window.docks["Project"].isClosed())  # open in the standard layout
        self.assertIs(render.drawn_model(), window.doc.model)
        window.open_path(PIPELINE / "assets" / "meadow.project.json")
        self.assertTrue(window.docks["Project"].isCurrentTab())  # its parts and instances
        shown = render.drawn_model()
        self.assertIsNot(shown, window.doc.model)
        project = scenes.project_doc.project
        lo, hi = project.bounds(scenes.project_doc.scene)
        self.assertEqual(shown.colour.shape, tuple(int(v) for v in (hi - lo)[::-1]))
        # arrow keys in the Project dock: the selection (and its yellow box) follows at every step
        tree, pdoc = scenes.outliner.tree, scenes.project_doc
        instances = pdoc.scene.instances
        scenes.outliner.tree.setFocus()
        pdoc.select(instances[0])
        for expected in instances[1:4]:
            QTest.keyClick(tree, QtCore.Qt.Key.Key_Down)
            self.assertIs(pdoc.instance, expected)
            lo, _ = pdoc.project.box(expected)
            self.assertAlmostEqual(scenes.scene_view.plotter.actors["selected"].GetBounds()[0], lo[0] - 0.1, places=3)
        # selected while the Scene tab is hidden behind another tab: drawn as soon as it shows again
        view, scene_dock = scenes.scene_view, window.docks["Scene"]
        next(d for d in scene_dock.dockAreaWidget().dockWidgets() if d is not scene_dock).setAsCurrentTab()
        QTest.qWait(50)
        self.assertFalse(view.isVisible())
        pdoc.select(instances[5])
        drawn, draw = [], view.plotter.render
        view.plotter.render = lambda: (drawn.append(1), draw())
        scene_dock.setAsCurrentTab()
        QTest.qWait(50)
        view.plotter.render = draw
        self.assertTrue(drawn)
        version = shown.version
        scenes.edit_model("bush")  # a part in the model docks: the render shows it
        self.assertIs(render.drawn_model(), project.models["bush"])
        window.doc.set_voxels([(0, 0, 0)], colour=60)
        scenes._render_scene(True)
        self.assertGreater(render.drawn_model().version, version)  # the edit shows in the scene
        window.close()

    def test_closing_asks_before_unsaved_work_is_lost(self):
        from unittest import mock
        from PySide6 import QtWidgets
        from core.model import Model
        Button = QtWidgets.QMessageBox.StandardButton
        asked = []

        def answering(button):  # the dialog, answered without showing it
            def warning(parent, title, text, *args):
                asked.append(text)
                return button
            return mock.patch.object(QtWidgets.QMessageBox, "warning", side_effect=warning)

        def recolour(doc, point):  # an edit: another colour at this voxel
            doc.set_voxels([point], colour=61 if doc.voxel(*point) == 60 else 60)
            return doc.voxel(*point)

        # nothing edited: the window closes without asking
        window = self._window(ask_to_save=True)
        self.assertEqual(window.unsaved(), [])
        with answering(Button.Cancel):
            self.assertTrue(window.close())
        self.assertEqual(asked, [])

        # an edited model: Cancel keeps the window open, Save saves it (as Ctrl+S) and closes
        window = self._window(ask_to_save=True)
        window.open_path(COPIES["alchemist"])
        colour = recolour(window.doc, (0, 0, 0))
        with answering(Button.Cancel):
            self.assertFalse(window.close())
        self.assertTrue(window.isVisible())
        self.assertIn(f"Model {COPIES['alchemist'].name}", asked[-1])
        self.assertNotIn("Project", asked[-1])
        with answering(Button.Save):
            self.assertTrue(window.close())
        saved = Model()
        saved.open(COPIES["alchemist"])
        self.assertEqual(int(saved.colour[0, 0, 0]), colour)

        # a new project with an edited part: one line for the project (the part is not a model of its own);
        # Save runs Save project, which asks for a name and saves the part too
        window = self._window(ask_to_save=True)
        scenes = window.scenes
        pdoc = scenes.project_doc
        name = pdoc.add_model(COPIES["skeleton"])
        pdoc.add_instance(name)
        scenes.edit_model(name)
        colour = recolour(window.doc, (0, 0, 0))
        with answering(Button.Cancel):
            self.assertFalse(window.close())
        self.assertEqual(window.unsaved(), [f"Project (new, never saved): edited parts: {name}; scenes or parts changed"])
        self.assertIn(window.unsaved()[0], asked[-1])
        with answering(Button.Save), mock.patch.object(QtWidgets.QInputDialog, "getText", return_value=(PROJECT, True)):
            self.assertTrue(window.close())
        project = SAVE_ROOT / f"{PROJECT}{SUFFIX}"
        self.assertTrue(project.exists())
        saved = Model()
        saved.open(COPIES["skeleton"])
        self.assertEqual(int(saved.colour[0, 0, 0]), colour)

        # the project reopened is saved; a moved instance is not, and Discard closes without saving it
        window = self._window(ask_to_save=True)
        window.open_path(project)
        pdoc = window.scenes.project_doc
        self.assertEqual(window.unsaved(), [])
        pdoc.select(pdoc.scene.instances[0])
        pdoc.move(1, 0, 0)
        self.assertEqual(window.unsaved(), [f"Project {project.name}: scenes or parts changed"])
        pdoc.move(-1, 0, 0)  # moved back: as saved
        self.assertEqual(window.unsaved(), [])
        pdoc.move(1, 0, 0)
        text = project.read_text(encoding="utf-8")
        with answering(Button.Discard):
            self.assertTrue(window.close())
        self.assertEqual(project.read_text(encoding="utf-8"), text)

    def test_a_model_as_stamp_brush(self):
        from PySide6 import QtCore
        from PySide6.QtTest import QTest

        window = self._window()
        scenes, doc, view = window.scenes, window.doc, window.edit_view
        name = scenes.project_doc.add_model(COPIES["skeleton"])
        brush = scenes.project_doc.project.models[name]
        solid = int((brush.colour > 0).sum())
        doc.new(64, 64, 48)
        scenes.outliner.select_model(name)
        scenes.outliner.buttons["Use as brush"].click()
        self.assertEqual((view.brush.kind, view.brush.stamp[0]), ("stamp", name))
        self.assertTrue(window.docks["3D edit"].isCurrentTab())
        self.assertIn(name, window.brush_panel.stamp_note.text())

        # hover the floor's centre: the see-through preview sits there, centred, on the floor; a click stamps it
        view.frame()
        pos = self._display(view, (32.5, 32.5, 0))
        view.update_hover(pos)
        self.assertIsNotNone(view.preview_actor)
        bounds = view.preview_actor.GetBounds()
        z, y, x = np.nonzero(brush.colour)  # the box's low corner is (16, 16, 0): the preview shows its voxels
        self.assertEqual((bounds[0], bounds[2], bounds[4]), (16.0 + x.min(), 16.0 + y.min(), float(z.min())))
        view.click(pos)
        self.assertEqual(int((doc.model.colour > 0).sum()), solid)
        np.testing.assert_array_equal(doc.model.colour[0:32, 16:48, 16:48], brush.colour)
        np.testing.assert_array_equal(doc.model.material[0:32, 16:48, 16:48], brush.material)

        # R turns the brush; attached to a +x face the box starts at the face, centred across it
        QTest.keyClick(view.plotter.interactor, QtCore.Qt.Key.Key_R)
        self.assertEqual(orient_text(view.brush.stamp[2]), "+y-x+z")
        from qtui.brush import stamp_low
        self.assertEqual(tuple(stamp_low((48, 30, 20), (1, 0, 0), (32, 32, 32))), (48, 14, 4))
        view.apply((47, 30, 20), (48, 30, 20))
        np.testing.assert_array_equal(doc.model.colour[4:36, 14:46, 48:64],
                                      place_plane(brush.colour, rotated(IDENTITY, 2))[:, :, :16])
        doc.undo()  # one stamp, one undo step
        self.assertEqual(int((doc.model.colour > 0).sum()), solid)

        # erase carves the stamp's shape: stamped over itself from the top it removes it all
        doc.set_tool("erase")
        QTest.keyClick(view.plotter.interactor, QtCore.Qt.Key.Key_R, QtCore.Qt.KeyboardModifier.ShiftModifier)
        view.apply((32, 32, 31), (32, 32, 32))  # from the box's top face it sinks back over the stamp
        self.assertEqual(int((doc.model.colour > 0).sum()), 0)
        doc.undo()
        doc.set_tool("attach")

        # Esc stops stamping
        QTest.keyClick(view.plotter.interactor, QtCore.Qt.Key.Key_Escape)
        self.assertEqual(view.brush.kind, "voxel")

        # a model stamped into itself reads its voxels before writing (attach: nothing to fill)
        scenes.edit_model(name)
        before = brush.colour.copy()
        scenes.use_as_brush(name, IDENTITY)
        view.apply(None, (16, 16, 0))
        np.testing.assert_array_equal(brush.colour, before)
        window.close()

    def test_brushes_and_the_brush_dock(self):
        from core.brushes import ellipsoid, offsets
        window = self._window()
        doc, view, panel = window.doc, window.edit_view, window.brush_panel
        brush = view.brush
        doc.new(32, 32, 16)
        self.assertTrue(window.docks["Brush"].isVisible())

        # the dock sets the brush and the mode
        panel.mode_buttons["erase"].click()
        self.assertEqual(doc.tool, "erase")
        panel.mode_buttons["attach"].click()
        panel.kind_buttons["face"].click()
        self.assertEqual(brush.kind, "face")
        panel.kind_buttons["voxel"].click()
        panel.size_box.setValue(5)
        panel.shape_buttons[True].click()
        self.assertEqual((brush.size, brush.shape), (5, "sphere"))

        # a sphere of 5 attached to the floor rests on it; the preview shows the same voxels first
        view.frame()
        view.update_hover(self._display(view, (16.5, 16.5, 0)))
        self.assertIsNotNone(view.preview_actor)
        sphere = len(offsets("sphere", 5))
        self.assertEqual(view.apply(None, (16, 16, 0)), sphere)
        z, y, x = np.nonzero(doc.model.colour)
        self.assertEqual((z.min(), z.max(), x.min(), x.max()), (0, 4, 14, 18))

        # paint with a 3-cube recolours only voxels that are there
        brush.set(round=False, size=3)
        doc.set_colour(5)
        doc.set_tool("paint")
        expected = int((doc.model.colour[3:6, 15:18, 15:18] > 0).sum())
        self.assertEqual(view.apply((16, 16, 4), (16, 16, 5)), expected)
        self.assertEqual(int((doc.model.colour > 0).sum()), sphere)
        doc.undo()
        doc.undo()

        # the face brush: attach builds a layer over a flat area, paint takes it whole
        doc.set_voxels([(x, y, 0) for x in range(4, 12) for y in range(4, 12)], colour=3)
        brush.set(kind="face")
        doc.set_tool("attach")
        self.assertEqual(view.apply((6, 6, 0), (6, 6, 1)), 64)
        self.assertEqual(int((doc.model.colour[1] > 0).sum()), 64)
        doc.set_tool("paint")
        doc.set_colour(9)
        self.assertEqual(view.apply((6, 6, 1), (6, 6, 2)), 64)
        self.assertEqual(int((doc.model.colour[1] == 9).sum()), 64)

        # the box brush: Shift + drag a rectangle on the floor, one undo step
        doc.new(32, 32, 16)
        brush.set(kind="box")
        doc.set_tool("attach")
        view.frame()
        view.begin_stroke(self._display(view, (4.5, 4.5, 0)))
        view.continue_stroke(self._display(view, (9.5, 6.5, 0)))
        view.end_stroke()
        z, y, x = np.nonzero(doc.model.colour)
        self.assertEqual((len(x), x.min(), x.max(), y.min(), y.max(), z.max()), (18, 4, 9, 4, 6, 0))
        doc.undo()
        self.assertFalse(doc.model.colour.any())

        # the ellipsoid brush: drag an 8 x 6 rectangle on the floor; attached, it rests there, 6 tall (auto)
        view.rebuild()  # the undone box leaves the view now, not on the rebuild timer: picks see the floor
        panel.kind_buttons["ellipsoid"].click()
        self.assertEqual((brush.kind, panel.options.currentIndex(), panel.height_box.text()),
                         ("ellipsoid", 3, "auto"))
        view.begin_stroke(self._display(view, (4.5, 4.5, 0)))
        view.continue_stroke(self._display(view, (11.5, 9.5, 0)))
        self.assertIsNotNone(view.preview_actor)  # the drag shows the ellipsoid before it is written
        view.end_stroke()
        view.rebuild()
        z, y, x = np.nonzero(doc.model.colour)
        self.assertEqual((x.min(), x.max(), y.min(), y.max(), z.min(), z.max()), (4, 11, 4, 9, 0, 5))
        self.assertEqual(len(x), len(ellipsoid((4, 4, 0), (11, 9, 0), (0, 0, 1), 6)))
        self.assertFalse(doc.model.colour[0, 4, 4])  # the box's corners stay empty
        # the same box through the assistant's fill_shape gives the same voxels
        from headless_api import VoxelEditor
        editor = VoxelEditor()
        editor.new_model(32, 32, 16)
        editor.fill_shape("ellipsoid", [4, 4, 0], [11, 9, 5], 3)
        np.testing.assert_array_equal(editor.model.colour > 0, doc.model.colour > 0)
        # a set height: 3 layers; erase sinks it into the top it was dragged on
        panel.height_box.setValue(3)
        self.assertEqual(brush.height, 3)
        doc.set_tool("erase")
        view.begin_stroke(self._display(view, (6.5, 6.5, 6)))
        view.continue_stroke(self._display(view, (9.5, 7.5, 6)))
        view.end_stroke()
        self.assertFalse(doc.model.colour[3:6, 6:8, 7:9].any())
        self.assertTrue(doc.model.colour[2, 6:8, 7:9].all())
        doc.undo()
        doc.undo()
        self.assertFalse(doc.model.colour.any())
        doc.set_tool("attach")

        # mirror x: the click and its mirror image
        brush.set(kind="voxel", size=1)
        panel.mirror_buttons[0].click()
        self.assertEqual(brush.mirror, (True, False, False))
        self.assertEqual(view.apply(None, (3, 5, 0)), 2)
        self.assertTrue(doc.model.colour[0, 5, 3] and doc.model.colour[0, 5, 28])

        # [ and ] change the size
        from PySide6 import QtCore
        from PySide6.QtTest import QTest
        QTest.keyClick(view.plotter.interactor, QtCore.Qt.Key.Key_BracketRight)
        self.assertEqual((brush.size, panel.size_box.value()), (2, 2))

        # and so does Alt + Shift + the wheel (sideways too: Qt turns it while Alt is held), in the slices too;
        # the plain wheel keeps zooming, and moving the layer
        from PySide6 import QtGui, QtWidgets
        Mod = QtCore.Qt.KeyboardModifier

        def wheel(widget, dy, modifiers, dx=0):
            centre = QtCore.QPointF(widget.width() / 2, widget.height() / 2)
            QtWidgets.QApplication.sendEvent(widget, QtGui.QWheelEvent(
                centre, widget.mapToGlobal(centre), QtCore.QPoint(), QtCore.QPoint(dx, dy),
                QtCore.Qt.MouseButton.NoButton, modifiers, QtCore.Qt.ScrollPhase.NoScrollPhase, False))
        both = Mod.AltModifier | Mod.ShiftModifier
        wheel(view.plotter.interactor, 120, both)
        wheel(view.plotter.interactor, 0, both, dx=120)
        self.assertEqual((brush.size, panel.size_box.value()), (4, 4))
        wheel(view.plotter.interactor, -120, both)
        wheel(view.plotter.interactor, 120, Mod.NoModifier)  # zooms
        self.assertEqual(brush.size, 3)
        top = window.slices["Top"]
        depth = top.depth_box.value()
        wheel(top.canvas, -120, both)
        self.assertEqual((brush.size, top.depth_box.value()), (2, depth))
        window.close()

    def test_painting_colour_material_or_both(self):
        window = self._window()
        doc, brush, panel, top = window.doc, window.edit_view.brush, window.brush_panel, window.slices["Top"]
        doc.new(8, 8, 4, ground=1)  # one layer of the current colour, matte
        top.depth_box.setValue(0)
        base_colour = int(doc.model.colour[0, 0, 0])
        brush.set(kind="voxel", size=1, volume=False)
        doc.set_colour(7)
        doc.set_material(4)

        panel.paint_buttons["colour"].click()  # recolours, the material stays
        self.assertEqual(doc.paints, "colour")
        top.draw([(1, 1)], "paint")
        self.assertEqual((doc.voxel(1, 1, 0), int(doc.model.material[0, 1, 1])), (7, 0))

        panel.paint_buttons["material"].click()  # the material, the colour stays; the views show materials
        self.assertTrue(doc.show_materials)
        top.draw([(2, 2)], "paint")
        self.assertEqual((doc.voxel(2, 2, 0), int(doc.model.material[0, 2, 2])), (base_colour, 4))

        panel.paint_buttons["both"].click()
        top.draw([(3, 3)], "paint")
        self.assertEqual((doc.voxel(3, 3, 0), int(doc.model.material[0, 3, 3])), (7, 4))
        doc.set_paints("colour")  # attach always adds both
        self.assertTrue(panel.paint_buttons["colour"].isChecked())
        top.depth_box.setValue(1)
        top.draw([(5, 5)], "attach")
        self.assertEqual((doc.voxel(5, 5, 1), int(doc.model.material[1, 5, 5])), (7, 4))
        window.close()

    def test_the_slices_draw_with_the_brush_and_the_sculpt_brushes(self):
        window = self._window()
        doc, brush, panel, top = window.doc, window.edit_view.brush, window.brush_panel, window.slices["Top"]
        self.assertIs(top.brush, brush)
        doc.new(32, 32, 16)
        top.depth_box.setValue(0)

        # a 3-square in the layer, a box dragged in it, the face brush takes the connected area of one colour
        brush.set(kind="voxel", size=3, round=False, volume=False)
        doc.set_tool("attach")
        self.assertEqual(sorted(top.footprint(10, 10)), [(u, v) for u in range(9, 12) for v in range(9, 12)])
        top.draw([(10, 10)], "attach")  # the hover showed what it fills
        self.assertEqual((int((doc.model.colour > 0).sum()), int((doc.model.colour[0] > 0).sum())), (9, 9))
        brush.set(kind="box")
        top.draw_box((2, 2), (5, 3), "attach")
        self.assertEqual(int((doc.model.colour[0, 2:4, 2:6] > 0).sum()), 8)
        brush.set(kind="face")
        doc.set_colour(7)
        top.draw([(10, 10)], "paint")
        self.assertEqual(int((doc.model.colour == 7).sum()), 9)

        # the Sculpt row is one choice with the brushes and takes the voxel brush's options
        panel.kind_buttons["grow"].click()
        self.assertEqual(brush.kind, "grow")
        self.assertFalse(panel.kind_buttons["face"].isChecked())
        self.assertEqual(panel.options.currentIndex(), 0)
        # a sculpting brush ignores the mode, so no mode shows as chosen; a mode goes back to the brush before
        self.assertFalse(any(button.isChecked() for button in panel.mode_buttons.values()))
        self.assertEqual(panel.mouse_label.text(), "Left: grow · Shift: erode · Alt: pick")
        panel.mode_buttons["erase"].click()
        self.assertEqual((doc.tool, brush.kind), ("erase", "face"))
        self.assertTrue(panel.mode_buttons["erase"].isChecked())
        panel.kind_buttons["smooth"].click()
        doc.set_tool("attach")  # a mode's key does the same
        self.assertEqual(brush.kind, "face")
        self.assertTrue(panel.mode_buttons["attach"].isChecked())
        panel.mode_buttons["pick"].click()
        panel.kind_buttons["grow"].click()  # in pick mode a sculpting brush would do nothing: attach underneath
        self.assertEqual((doc.tool, brush.kind), ("attach", "grow"))
        # grow adds the voxels beside the square inside a 5-square, in its colour; Shift erodes instead
        brush.set(size=5)
        top.draw([(10, 10)], "attach")
        self.assertEqual(int((doc.model.colour[0, 8:13, 8:13] == 7).sum()), 21)
        top.draw([(10, 10)], "attach", shift=True)
        self.assertFalse(doc.model.colour[0, 8:13, 8:13].any())
        self.assertEqual(int((doc.model.colour > 0).sum()), 8)  # the box stays

        # an ellipsoid dragged in a slice is centred on its layer
        brush.set(kind="ellipsoid", height=0)
        top.depth_box.setValue(8)
        top.draw_box((2, 2), (7, 7), "attach")
        z, y, x = np.nonzero(doc.model.colour[1:])  # above the layer the earlier strokes drew in
        z += 1
        self.assertEqual((z.min(), z.max(), x.min(), x.max()), (6, 11, 2, 7))
        self.assertTrue(doc.model.colour[8, 4, 4])
        window.close()

    def test_magicavoxel_mouse(self):
        from PySide6 import QtCore
        from PySide6.QtTest import QTest
        from qtui.brush import mode_for
        # the rule: the mode, Shift its partner, Ctrl paint (paint: attach), Alt pick
        self.assertEqual([mode_for(t, shift=True) for t in ("attach", "erase", "paint")], ["erase", "attach", "erase"])
        self.assertEqual([mode_for(t, ctrl=True) for t in ("attach", "erase", "paint")], ["paint", "paint", "attach"])
        self.assertEqual(mode_for("attach", alt=True), "pick")

        window = self._window()
        doc, view, panel = window.doc, window.edit_view, window.brush_panel
        doc.new(16, 16, 16)
        self.assertEqual(panel.mouse_label.text(), "Left: attach · Shift: erase · Ctrl: paint · Alt: pick")
        view.frame()
        iren = view.plotter.iren.interactor

        def press(point, button="Left", shift=0, ctrl=0, move_to=None):
            x, y = self._display(view, point)
            iren.SetEventInformation(x, y, ctrl, shift)
            iren.InvokeEvent(f"{button}ButtonPressEvent")
            for point in ([] if move_to is None else [move_to] if len(move_to) == 3 and np.isscalar(move_to[0])
                          else move_to):
                iren.SetEventInformation(*self._display(view, point), ctrl, shift)
                iren.InvokeEvent("MouseMoveEvent")
            iren.InvokeEvent(f"{button}ButtonReleaseEvent")

        press((4.5, 4.5, 0))  # a plain left click attaches on the floor
        self.assertEqual(doc.voxel(4, 4, 0), doc.colour)
        press((8.5, 4.5, 0), move_to=[(x + 0.5, 4.5, 0) for x in range(9, 12)])  # a plain drag draws, no Shift
        self.assertTrue(all(doc.voxel(x, 4, 0) for x in range(8, 12)))
        doc.set_colour(7)
        press((4.5, 4.5, 1), ctrl=1)  # Ctrl + left paints (the top face of the first voxel)
        self.assertEqual(doc.voxel(4, 4, 0), 7)
        press((4.5, 4.5, 1), shift=1)  # Shift + left erases
        self.assertEqual(doc.voxel(4, 4, 0), 0)
        before = doc.model.colour.copy()
        press((6.5, 6.5, 0), button="Right", move_to=(9.5, 9.5, 0))  # right drag orbits, draws nothing
        np.testing.assert_array_equal(doc.model.colour, before)

        # the slices: the same rule; right does nothing
        canvas = window.slices["Top"].canvas
        window.slices["Top"].depth_box.setValue(0)
        QTest.qWait(50)
        cell = canvas._screen_rect(1, 1).center().toPoint()
        QTest.mouseClick(canvas, QtCore.Qt.MouseButton.LeftButton, QtCore.Qt.KeyboardModifier.NoModifier, cell)
        self.assertEqual(doc.voxel(1, 1, 0), 7)
        doc.set_colour(9)
        QTest.mouseClick(canvas, QtCore.Qt.MouseButton.LeftButton, QtCore.Qt.KeyboardModifier.NoModifier, cell)
        self.assertEqual(doc.voxel(1, 1, 0), 7)  # attach never overwrites
        QTest.mouseClick(canvas, QtCore.Qt.MouseButton.LeftButton, QtCore.Qt.KeyboardModifier.ControlModifier, cell)
        self.assertEqual(doc.voxel(1, 1, 0), 9)
        QTest.mouseClick(canvas, QtCore.Qt.MouseButton.RightButton, QtCore.Qt.KeyboardModifier.NoModifier, cell)
        self.assertEqual(doc.voxel(1, 1, 0), 9)
        QTest.mouseClick(canvas, QtCore.Qt.MouseButton.LeftButton, QtCore.Qt.KeyboardModifier.ShiftModifier, cell)
        self.assertEqual(doc.voxel(1, 1, 0), 0)

        # in paint mode Shift erases and Ctrl attaches; the dock says so
        panel.mode_buttons["paint"].click()
        self.assertEqual(panel.mouse_label.text(), "Left: paint · Shift: erase · Ctrl: attach · Alt: pick")
        window.close()


if __name__ == "__main__":
    unittest.main()
