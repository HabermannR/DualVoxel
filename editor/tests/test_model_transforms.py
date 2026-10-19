"""The whole model's box and everything in it, as MagicaVoxel's edit mode has them: resize (with an anchor or an
offset), fit, shift (wrapping or not), turn and flip. Each is one undo step that undoes exactly; protection moves
with the voxels; a project's instances keep their voxels in place when their part is resized; the Model dock and
the 3D edit view's arrow keys drive them."""
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

EDITOR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EDITOR))
import sandbox  # noqa: E402,F401  the user's own editor and settings are left alone
from core.model import Model, anchor_offset, transform_plane  # noqa: E402
from core.scene import IDENTITY, Project, mirrored, place_plane, rotated  # noqa: E402


def model_with_voxels(x=6, y=5, z=4) -> Model:
    model = Model()
    model.new(x, y, z)
    model.colour[0, 1, 2], model.material[0, 1, 2] = 7, 1
    model.colour[3, 4, 5], model.material[3, 4, 5] = 9, 2
    model.colour[1, 0, 0] = 3
    return model


def solid_points(colour, offset=(0, 0, 0)):
    return sorted(map(tuple, np.argwhere(colour > 0)[:, ::-1] + np.asarray(offset)))


class TransformTests(unittest.TestCase):
    def test_resize_places_the_voxels_by_anchor_or_offset(self):
        self.assertEqual([anchor_offset(4, 10, a) for a in ("low", "centre", "high")], [0, 3, 6])
        model = model_with_voxels()
        before = solid_points(model.colour)
        self.assertEqual(model.resize((10, 9, 6)), 0)  # x and y centred, on the floor
        self.assertEqual(model.size, (10, 9, 6))
        self.assertEqual(solid_points(model.colour), [tuple(np.add(p, (2, 2, 0))) for p in before])
        self.assertEqual(model.resize((10, 9, 6), offset=(-2, -2, 0)), 0)
        self.assertEqual(model.size, (10, 9, 6))
        self.assertEqual(solid_points(model.colour), before)

    def test_a_crop_loses_what_is_outside_and_undo_brings_it_back(self):
        model = model_with_voxels()
        before = model.colour.copy(), model.material.copy()
        self.assertEqual(model.resize((3, 3, 3), anchor="low"), 1)  # (5, 4, 3) is outside
        self.assertEqual(model.size, (3, 3, 3))
        self.assertTrue(model.undo())
        self.assertTrue(np.array_equal(model.colour, before[0]) and np.array_equal(model.material, before[1]))
        self.assertTrue(model.redo())
        self.assertEqual(model.size, (3, 3, 3))

    def test_fit_shrinks_the_box_to_its_voxels(self):
        model = Model()
        model.new(20, 20, 20)
        model.colour[5:8, 3:5, 10:12] = 4
        self.assertEqual(model.fit(), (-10, -3, -5))
        self.assertEqual(model.size, (2, 2, 3))
        self.assertTrue((model.colour == 4).all())
        self.assertIsNone(model.fit())  # fits already: no step
        model.new(4, 4, 4)
        self.assertIsNone(model.fit())  # empty: nothing to fit
        self.assertEqual(model.undo_stack, [])

    def test_shift_wraps_round_or_drops(self):
        model = model_with_voxels()
        before = solid_points(model.colour)
        self.assertEqual(model.shift((1, 0, 0)), 0)
        self.assertEqual(model.colour[3, 4, 0], 9)  # x 5 wrapped to 0
        self.assertEqual(model.shift((-1, 0, 0)), 0)
        self.assertEqual(solid_points(model.colour), before)
        self.assertEqual(model.shift((0, 0, -1), wrap=False), 1)  # the voxel at z 0 fell out
        self.assertEqual(model.shift((6, 0, 0)), 0)  # a whole turn round: no change, no step
        model.undo()
        self.assertEqual(solid_points(model.colour), before)

    def test_turns_and_flips_agree_with_the_scene(self):
        model = model_with_voxels()
        plane = model.colour.copy()
        for axis in range(3):
            for turns in (1, 2, 3):
                self.assertTrue(np.array_equal(transform_plane(plane, ("rotate", axis, turns)),
                                               place_plane(plane, rotated(IDENTITY, axis, turns))))
            self.assertTrue(np.array_equal(transform_plane(plane, ("flip", axis)),
                                           place_plane(plane, mirrored(IDENTITY, axis))))
        model.rotate(2, 1)
        self.assertEqual(model.size, (5, 6, 4))  # the box turns with the voxels
        model.flip(0)
        model.undo()
        model.undo()
        self.assertTrue(np.array_equal(model.colour, plane))

    def test_steps_before_and_after_a_resize_still_undo(self):
        model = model_with_voxels()
        model.paint_box((0, 0, 0), (1, 1, 1), 5)
        painted = model.colour.copy()
        model.resize((8, 8, 8), anchor="high")
        model.paint_box((7, 7, 7), (7, 7, 7), 6)
        self.assertTrue(model.undo() and model.undo())
        self.assertTrue(np.array_equal(model.colour, painted))
        self.assertTrue(model.undo())  # the paint before the resize
        self.assertFalse((model.colour == 5).any())

    def test_the_log_names_each_transform_and_its_undo(self):
        model = model_with_voxels()
        start = model.transform_count
        model.resize((8, 5, 4), anchor="high")
        model.undo()
        log = model.transforms_since(start)
        self.assertEqual([entry[1] for entry in log], [("resize", (8, 5, 4), (2, 0, 0)), ("resize", (6, 5, 4), (-2, 0, 0))])
        self.assertEqual([(entry[2], entry[3]) for entry in log], [((6, 5, 4), (8, 5, 4)), ((8, 5, 4), (6, 5, 4))])
        self.assertEqual(model.transforms_since(model.transform_count), [])


class SceneFollowTests(unittest.TestCase):
    def test_instances_keep_their_voxels_in_place_in_every_orientation(self):
        model = model_with_voxels()
        project = Project()
        project.models["part"] = model
        scene = project.add_scene()
        for orient in (IDENTITY, rotated(IDENTITY, 2, 1), mirrored(IDENTITY, 0), rotated(IDENTITY, 0, 3)):
            project.add_instance(scene, "part", (10, 20, 30), orient)

        def world():
            return [solid_points(project.placed_planes(i)[0], i.position) for i in scene.instances]
        before = world()
        for anchor in (("high", "centre", "low"), ("low", "high", "centre")):
            model.resize((9, 8, 7), anchor=anchor)
            _, op, old_size, new_size = model.transforms_since(model.transform_count - 1)[0]
            project.follow_resize("part", old_size, new_size, op[2])
            self.assertEqual(world(), before)
            model.undo()
            _, op, old_size, new_size = model.transforms_since(model.transform_count - 1)[0]
            project.follow_resize("part", old_size, new_size, op[2])
            self.assertEqual(world(), before)
        self.assertEqual({i.position for i in scene.instances}, {(10, 20, 30)})


class ApiTests(unittest.TestCase):
    def test_protected_voxels_move_along_and_are_never_cut_off(self):
        from headless_api import VoxelEditor
        editor = VoxelEditor()
        editor.new_model(8, 8, 8)
        editor.paint_box([2, 2, 0], [4, 4, 3], 5)
        editor.protect_box([2, 2, 0], [2, 2, 0])
        result = editor.resize_model([12, 10, 8])
        self.assertEqual((result["size"], result["lost_voxels"], result["protected_voxels"]), ([12, 10, 8], 0, 1))
        self.assertTrue(editor._protected[0, 3, 4])  # moved with its voxel
        with self.assertRaises(ValueError):
            editor.resize_model([3, 3, 3], anchor="low")
        with self.assertRaises(ValueError):
            editor.shift_model([-5, 0, 0], wrap=False)
        self.assertEqual(editor.model.size, (12, 10, 8))
        self.assertEqual(editor.rotate_model("z", 1)["size"], [10, 12, 8])
        self.assertEqual(editor.fit_model()["size"], [3, 3, 4])
        self.assertEqual(editor.info()["protected_voxels"], 1)
        for _ in range(3):
            editor.undo()
        self.assertEqual(editor.info()["size"], [8, 8, 8])
        self.assertTrue(editor._protected[0, 2, 2])
        self.assertTrue(editor.flip_model("y")["changed"])
        with self.assertRaises(ValueError):
            editor.rotate_model("w")


class QtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6 import QtWidgets
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

    def test_the_document_moves_protection_and_says_when_the_size_changed(self):
        from qtui.document import Document
        doc = Document()
        doc.new(8, 8, 8, ground=2)
        doc.set_protected([(1, 1, 0)])
        sizes = []
        doc.resized.connect(lambda: sizes.append(doc.size))
        doc.resize((10, 8, 8), ["high", "low", "low"])
        self.assertEqual(sizes, [(10, 8, 8)])
        self.assertTrue(doc.protected()[0, 1, 3])
        doc.shift((0, 1, 0))
        self.assertEqual(len(sizes), 1)  # a shift keeps the size
        self.assertTrue(doc.protected()[0, 2, 3])
        doc.undo()
        doc.undo()
        self.assertEqual(sizes[-1], (8, 8, 8))
        self.assertTrue(doc.protected()[0, 1, 1])
        doc.model.rotate(2, 1)  # as the live link does it: on the model, then `changed`
        doc.changed.emit()
        self.assertEqual(doc.protected().shape, doc.model.colour.shape)

    def _window(self):
        from PySide6 import QtCore
        from PySide6.QtTest import QTest
        from qtui.window import EditorWindow
        window = EditorWindow()
        window._engine_started = True  # no GPU renderer for this check
        window.settings = QtCore.QSettings(str(Path(tempfile.mkdtemp()) / "layout.ini"),
                                           QtCore.QSettings.Format.IniFormat)
        window.confirm_close = lambda: True
        window.show()
        QTest.qWait(200)
        return window

    def test_the_model_dock_and_the_arrow_keys(self):
        from PySide6 import QtCore
        from PySide6.QtTest import QTest
        window = self._window()
        doc, panel = window.doc, window.model_panel
        self.assertIn("Model", window.docks)
        window.new_model(16, 16, 8, "Floor", 2)
        self.assertEqual([b.value() for b in panel.size_boxes], [16, 16, 8])
        for box, value in zip(panel.size_boxes, (20, 16, 12)):
            box.setValue(value)
        panel.apply_size()
        self.assertEqual(doc.size, (20, 16, 12))
        self.assertEqual(window.slices["Top"].depth_box.maximum(), 11)
        QTest.qWait(50)
        self.assertIn("20 × 16 × 12", window.info_label.text())
        self.assertTrue(panel.fit())
        self.assertEqual(doc.size, (16, 16, 2))
        self.assertEqual([b.value() for b in panel.size_boxes], [16, 16, 2])

        doc.model.colour[:] = 0
        doc.model.colour[0, 0, 0] = 5
        doc.changed.emit()
        view = window.edit_view
        camera = view.plotter.camera
        camera.position, camera.focal_point, camera.up = (8, -40, 10), (8, 8, 1), (0, 0, 1)  # looking along +y
        interactor = view.plotter.interactor
        interactor.setFocus()
        QTest.keyClick(interactor, QtCore.Qt.Key.Key_Right)
        self.assertEqual(doc.model.colour[0, 0, 1], 5)
        QTest.keyClick(interactor, QtCore.Qt.Key.Key_Up, QtCore.Qt.KeyboardModifier.ShiftModifier)
        self.assertEqual(doc.model.colour[0, 8, 1], 5)  # away from the camera: +y, 8 voxels
        panel.wrap.setChecked(False)
        QTest.keyClick(interactor, QtCore.Qt.Key.Key_Left)
        QTest.keyClick(interactor, QtCore.Qt.Key.Key_Left)
        self.assertFalse(doc.model.colour.any())  # out past x 0, not wrapped round
        window.close()

    def test_a_part_resized_keeps_its_instances_in_place(self):
        from core.model import SAVE_ROOT
        window = self._window()
        pdoc = window.scenes.project_doc
        source = SAVE_ROOT / "_test_transform_part.vx2"
        model = model_with_voxels()
        model.save_path(source, export_vox=False)
        try:
            name = pdoc.add_model(source)
            pdoc.add_instance(name)
            instance = pdoc.instance
            pdoc.move_to((5, 5, 0))
            pdoc.rotate(2, 1)
            window.scenes.edit_model(name)
            part = pdoc.project.models[name]

            def world():
                return solid_points(pdoc.project.placed_planes(instance)[0], instance.position)
            before, position = world(), instance.position
            window.model_panel.anchors[0].setCurrentIndex(2)  # x: high
            for box, value in zip(window.model_panel.size_boxes, (10, 9, 4)):
                box.setValue(value)
            window.model_panel.apply_size()
            self.assertEqual(part.size, (10, 9, 4))
            self.assertNotEqual(instance.position, position)
            self.assertEqual(world(), before)
            pdoc.undo()  # the scene's own last step (the turn), from positions of the new box
            self.assertEqual(pdoc.scene.instances[0].orient, IDENTITY)
            pdoc.redo()
            instance = pdoc.scene.instances[0]
            self.assertEqual(world(), before)
            window.doc.undo()  # the resize: the instance goes back with it
            self.assertEqual(part.size, (6, 5, 4))
            self.assertEqual(world(), before)
        finally:
            for path in (source, source.with_suffix(".vox")):
                path.unlink(missing_ok=True)
        window.close()


if __name__ == "__main__":
    unittest.main()
