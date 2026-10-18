"""A model's own materials (ids 128-255): saved in its .vx2, made by editing a shared material or by
New material, carried along by stamps and scene merges; the shared table never changes."""
import copy
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

EDITOR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EDITOR))
import core.model as cm  # noqa: E402  (puts pipeline/ and palette/ on the path)
import vx2  # noqa: E402
from qtui.document import Document  # noqa: E402

ALCHEMIST = cm.ROOT / "assets" / "alchemist.vx2"


class ModelMaterialTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "assets").mkdir()
        (self.tmp / "export").mkdir()
        self.saved = cm.SAVE_ROOT, cm.ROOT
        cm.SAVE_ROOT, cm.ROOT = self.tmp / "assets", self.tmp
        self.table = (EDITOR.parent / "palette" / "materials.json").read_bytes()

    def tearDown(self):
        cm.SAVE_ROOT, cm.ROOT = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)
        self.assertEqual((EDITOR.parent / "palette" / "materials.json").read_bytes(), self.table,
                         "the shared table must never change")

    def test_a_file_without_own_materials_stays_version_1(self):
        colour, material = vx2.read(ALCHEMIST)
        out = self.tmp / "a.vx2"
        vx2.write(out, colour, material)
        self.assertEqual(out.read_bytes(), ALCHEMIST.read_bytes())

    def test_editing_a_shared_material_makes_the_models_own_copy(self):
        doc = Document()
        doc.open(ALCHEMIST)
        matte = int((doc.model.material[doc.model.colour > 0] == 0).sum())
        shared = copy.deepcopy(doc.model.materials[0])
        doc.set_material_field(0, "roughness", 0.3)
        own = doc.material
        self.assertGreaterEqual(own, 128)
        self.assertEqual(doc.model.materials[0], shared)            # the shared one is untouched
        self.assertEqual(doc.model.local[own]["roughness"], 0.3)
        self.assertEqual(int((doc.model.material == own).sum()), matte)  # its voxels moved over
        doc.set_material_field(own, "metal", 0.5)                    # the copy is edited from now on
        self.assertEqual(len(doc.model.local), 1)
        doc.undo()                                                   # the move is one undo step
        self.assertEqual(int((doc.model.material == own).sum()), 0)

    def test_own_materials_are_saved_with_the_model_and_reopened(self):
        doc = Document()
        doc.open(ALCHEMIST)
        doc.set_material_field(0, "sheen", 0.6)
        made = doc.add_material("my glass")
        doc.set_material_field(made, "transmission", 0.9)
        doc.set_voxels([(0, 0, 0)], colour=doc.colour, material=made)
        self.assertEqual(doc.unsaved_materials(), sorted(doc.model.local))
        path = doc.model.save("own_test")
        self.assertEqual(doc.unsaved_materials(), [])
        self.assertEqual(int.from_bytes(path.read_bytes()[4:8], "little"), vx2.LOCAL_VERSION)
        again = Document()
        again.open(path)
        self.assertEqual(again.model.local, doc.model.local)
        self.assertEqual(again.model.material[0, 0, 0], made)
        self.assertEqual(again.model.material_info(made)["name"], "my glass")

    def test_a_stamp_brings_its_own_materials_along(self):
        source = Document()
        source.new(4, 4, 4)
        mine = source.add_material("ember")
        source.set_voxels([(1, 1, 1)], colour=source.colour, material=mine)
        target = Document()
        target.new(8, 8, 8)
        plane = target.adopt_materials(source.model, source.model.material)
        adopted = int(plane[1, 1, 1])
        self.assertIn(adopted, target.model.local)
        self.assertEqual(target.model.local[adopted]["name"], "ember")
        again = target.adopt_materials(source.model, source.model.material)  # an identical one is reused
        self.assertEqual(int(again[1, 1, 1]), adopted)
        self.assertEqual(len(target.model.local), 1)

    def test_a_scene_merge_renumbers_each_models_own_materials(self):
        from core.scene import Project
        a, b = cm.Model(), cm.Model()
        for model, name in ((a, "a"), (b, "b")):
            model.new(2, 2, 2)
            own = model.add_local(dict(model.materials[4], name=f"{name}'s own"))
            model.colour[:] = 5
            model.material[:] = own  # both use id 128 for different materials
        project = Project()
        project.models = {"a": a, "b": b}
        scene = project.add_scene("s")
        project.add_instance(scene, "a", (0, 0, 0))
        project.add_instance(scene, "b", (4, 0, 0))
        colour, material, lo, local = project.merged(scene)
        self.assertEqual(sorted(m["name"] for m in local), ["a's own", "b's own"])
        self.assertEqual(sorted(np.unique(material[colour > 0]).tolist()), [128, 129])


if __name__ == "__main__":
    unittest.main()
