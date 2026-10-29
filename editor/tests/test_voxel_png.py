import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import voxel_png  # noqa: E402
from core.model import Model  # noqa: E402
from headless_api import VoxelEditor  # noqa: E402


def figure() -> Model:
    """A small solid figure: a 4 x 3 x 6 block of colour 10, a red front face, a metal top."""
    model = Model()
    model.new(6, 5, 8)
    model.colour[1:7, 1:4, 1:5] = 10
    model.colour[1:7, 1, 1:5] = 30  # front face (low y)
    model.material[1:7, 1:4, 1:5] = 0
    model.material[6, 1:4, 1:5] = 6  # top layer: rough metal
    return model


def strip_text(path: Path) -> None:
    """Save the picture again without its text chunk, as a paint program may."""
    with Image.open(path) as image:
        image.load()
        kept = image.copy()
    kept.save(path, **({"transparency": 0} if kept.mode == "P" else {}))


class SliceTests(unittest.TestCase):
    def test_round_trip_is_exact(self):
        model = figure()
        with tempfile.TemporaryDirectory() as folder:
            colour_png, material_png = voxel_png.export_slices(model.colour, model.material, model.table,
                                                               Path(folder) / "fig")
            self.assertTrue(colour_png.name.endswith(".slices-6x5x8.colour.png"))
            with Image.open(colour_png) as image:
                self.assertEqual(image.mode, "P")  # the table as palette: a paint program offers just it
            colour, material, report = voxel_png.import_slices(colour_png, model.table, model.has_material)
        np.testing.assert_array_equal(colour, model.colour)
        np.testing.assert_array_equal(material, model.material)
        self.assertEqual(report["voxels"], int((model.colour > 0).sum()))

    def test_name_alone_is_enough(self):
        model = figure()
        with tempfile.TemporaryDirectory() as folder:
            paths = voxel_png.export_slices(model.colour, model.material, model.table, Path(folder) / "fig")
            for path in paths:
                strip_text(path)
            self.assertIsNone(voxel_png.read_info(paths[0]))
            colour, material, _ = voxel_png.import_slices(paths[0], model.table, model.has_material)
        np.testing.assert_array_equal(colour, model.colour)
        np.testing.assert_array_equal(material, model.material)

    def test_rgb_picture_and_colours_not_in_the_table(self):
        model = figure()
        with tempfile.TemporaryDirectory() as folder:
            path = voxel_png.export_slices(model.colour, model.material, model.table, Path(folder) / "fig")[0]
            rgba = np.asarray(Image.open(path).convert("RGBA")).copy()
            off = rgba[..., 3] > 0
            rgba[off, 0] = np.clip(rgba[off, 0].astype(int) + 1, 0, 255)  # a shade off every table colour
            Image.fromarray(rgba, "RGBA").save(path)
            colour, _, report = voxel_png.import_slices(path, model.table, model.has_material)
        np.testing.assert_array_equal(colour, model.colour)  # the nearest slot is the one it was
        self.assertEqual(report["snapped_pixels"], int(off.sum()))

    def test_unknown_material_colour_is_refused(self):
        model = figure()
        with tempfile.TemporaryDirectory() as folder:
            colour_png, material_png = voxel_png.export_slices(model.colour, model.material, model.table,
                                                               Path(folder) / "fig")
            rgba = np.asarray(Image.open(material_png)).copy()
            rgba[0, 0] = (1, 2, 3, 255)
            Image.fromarray(rgba, "RGBA").save(material_png)
            with self.assertRaisesRegex(ValueError, "no material's colour"):
                voxel_png.import_slices(colour_png, model.table, model.has_material)


class ViewTests(unittest.TestCase):
    def test_views_see_the_first_voxel(self):
        model = figure()
        slots, ids, xyz, found, depth = voxel_png.view_planes(model.colour, model.material, "front")
        self.assertEqual(slots.shape, (8, 6))  # rows z, columns x
        self.assertTrue((slots[found] == 30).all())  # the red front face
        self.assertTrue((xyz[found][:, 1] == 1).all())
        top_slots, top_ids, *_ = voxel_png.view_planes(model.colour, model.material, "top")
        self.assertEqual(top_slots.shape, (5, 6))  # rows y (back at the top), columns x
        self.assertTrue((top_ids[top_slots > 0] == 6).all())
        back = voxel_png.view_planes(model.colour, model.material, "back")[0]
        np.testing.assert_array_equal(back[back > 0], 10)
        # back is the front mirrored: x runs the other way
        left = voxel_png.view_hits(model.colour, "left")[0]
        right = voxel_png.view_hits(model.colour, "right")[0]
        self.assertTrue((left[..., 0][voxel_png.view_hits(model.colour, "left")[1]] == 1).all())
        self.assertTrue((right[..., 0][voxel_png.view_hits(model.colour, "right")[1]] == 4).all())

    def test_unpainted_views_change_nothing(self):
        model = figure()
        with tempfile.TemporaryDirectory() as folder:
            paths = voxel_png.export_views(model.colour, model.material, model.table, Path(folder) / "fig", scale=4)
            pictures = [p for p in paths if not p.name.endswith(".shaded.png")]
            points, *_, report = voxel_png.import_views(model.colour, model.material, pictures, model.table,
                                                        model.has_material)
        self.assertEqual(len(points), 0)
        self.assertEqual(report["changed_voxels"], 0)

    def test_paint_erase_and_material(self):
        model = figure()
        with tempfile.TemporaryDirectory() as folder:
            paths = voxel_png.export_views(model.colour, model.material, model.table, Path(folder) / "fig",
                                           views=("front", "top"), scale=4)
            front = Path(folder) / "fig.front.colour.png"
            image = Image.open(front)
            pixels = np.asarray(image).copy()
            # rows run z from the top: voxel (x 2, z 3) is row 8 - 1 - 3 = 4; paint it slot 50, erase (x 3, z 3)
            pixels[4 * 4:5 * 4, 2 * 4:3 * 4] = 50
            pixels[4 * 4:5 * 4, 3 * 4 + 1:4 * 4] = 0  # most of the block: the block's majority counts
            painted = Image.fromarray(pixels, "P")
            painted.putpalette(image.getpalette())
            painted.save(front, transparency=0)
            strip_text(front)  # no record: compared with the model as it is
            top_material = Path(folder) / "fig.top.material.png"
            rgba = np.asarray(Image.open(top_material)).copy()
            rgba[0:4, 1 * 4:2 * 4] = (*voxel_png.MATERIAL_RGB[7], 255)  # top view, row 0 = back (y 4): empty
            rgba[1 * 4:2 * 4, 1 * 4:2 * 4] = (*voxel_png.MATERIAL_RGB[7], 255)  # y 3, x 1: polished metal
            Image.fromarray(rgba, "RGBA").save(top_material)
            points, colours, materials, report = voxel_png.import_views(
                model.colour, model.material, [front, top_material], model.table, model.has_material)
        changes = {tuple(p): (int(c), int(m)) for p, c, m in zip(points.tolist(), colours, materials)}
        self.assertEqual(changes, {(2, 1, 3): (50, 0), (3, 1, 3): (0, 0), (1, 3, 6): (10, 7)})
        self.assertEqual(report["views"]["front"], {"recoloured": 1, "erased": 1, "rematerialed": 0, "outside": 0})
        self.assertEqual(report["views"]["top"]["outside"], 1)

    def test_record_keeps_later_model_edits(self):
        model = figure()
        with tempfile.TemporaryDirectory() as folder:
            voxel_png.export_views(model.colour, model.material, model.table, Path(folder) / "fig", views=("front",))
            model.colour[3, 1, 2] = 77  # an edit in the editor after the export
            points, *_ = voxel_png.import_views(model.colour, model.material,
                                                [Path(folder) / "fig.front.colour.png"], model.table,
                                                model.has_material)
        self.assertEqual(len(points), 0)  # the unpainted picture does not undo it

    def test_wrong_size_is_refused(self):
        model = figure()
        with tempfile.TemporaryDirectory() as folder:
            voxel_png.export_views(model.colour, model.material, model.table, Path(folder) / "fig", views=("front",))
            other = Model()
            other.new(7, 5, 8)
            with self.assertRaisesRegex(ValueError, "shows a model of 6 x 5 x 8"):
                voxel_png.import_views(other.colour, other.material, [Path(folder) / "fig.front.colour.png"],
                                       other.table, other.has_material)


class HeadlessTests(unittest.TestCase):
    def test_export_and_import_through_the_editor(self):
        editor = VoxelEditor()
        editor.new_model(6, 5, 8)
        editor.paint_box([1, 1, 1], [4, 3, 6], 10, 0)
        with tempfile.TemporaryDirectory() as folder:
            out = editor.export_views(Path(folder) / "fig", views=["front"], scale=2)
            self.assertEqual(len(out["files"]), 3)
            front = Path(folder) / "fig.front.colour.png"
            pixels = np.asarray(Image.open(front)).copy()
            palette = Image.open(front).getpalette()
            pixels[2:4, 2:4] = 40  # row 1 (z 6), column 1 (x 1)
            painted = Image.fromarray(pixels, "P")
            painted.putpalette(palette)
            painted.save(front, transparency=0)
            editor.protect_box([1, 1, 6], [1, 1, 6])
            self.assertEqual(editor.import_views([str(front)])["changed_voxels"], 0)  # protected voxels stay
            editor.clear_protection()
            undo_before = len(editor.model.undo_stack)
            result = editor.import_views([str(front)])
            self.assertEqual(result["changed_voxels"], 1)
            self.assertEqual(result["views"]["front"]["recoloured"], 1)
            self.assertEqual(int(editor.model.colour[6, 1, 1]), 40)
            self.assertEqual(len(editor.model.undo_stack), undo_before + 1)  # one undo step
            sheets = editor.export_slices(Path(folder) / "fig")
            fresh = VoxelEditor()
            fresh.import_slices(sheets["files"][0])
            np.testing.assert_array_equal(fresh.model.colour, editor.model.colour)
            self.assertIsNone(fresh.model.path)  # a new, unsaved model


if __name__ == "__main__":
    unittest.main()
