import base64
import io
import os
import sys
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from headless_api import VoxelEditor, ROOT  # noqa: E402
from core.model import ROOT as PIPELINE  # noqa: E402
from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402

# the MagicaVoxel original that alchemist.vx2 was converted from; not part of this repository
GAME_VOX = Path(os.environ.get("ALCHEMIST_VOX", ""))
ALCHEMIST = PIPELINE / "assets" / "alchemist.vx2"
SKIP_GPU = os.environ.get("SKIP_GPU") == "1"
TEST_NAME = "_test_roundtrip"


class EditorTests(unittest.TestCase):
    def tearDown(self):
        for path in (PIPELINE / "assets" / f"{TEST_NAME}.vx2", PIPELINE / "export" / f"{TEST_NAME}.vox"):
            path.unlink(missing_ok=True)

    def test_roundtrip_with_materials_and_export(self):
        editor = VoxelEditor()
        editor.new_model(3, 4, 64)
        editor.paint_box([0, 0, 0], [0, 0, 0], 1, 15)
        editor.paint_box([2, 3, 63], [2, 3, 63], 255, 7)
        colour, material = editor.model.colour.copy(), editor.model.material.copy()
        saved = editor.save_model(TEST_NAME)
        fresh = VoxelEditor()
        fresh.open_model(saved["path"])
        np.testing.assert_array_equal(fresh.model.colour, colour)
        np.testing.assert_array_equal(fresh.model.material, material)
        exported = VoxelEditor()
        exported.open_model(saved["export"])  # the lossless .vox carries the pairs back
        np.testing.assert_array_equal(exported.model.colour, colour)

    def test_protection_undo_redo_and_bounds(self):
        editor = VoxelEditor()
        editor.new_model(8, 8, 8)
        editor.paint_box([1, 1, 1], [3, 3, 3], 54, 3)
        editor.protect_box([2, 2, 2], [2, 2, 2])
        before = editor.model.colour.copy()
        editor.paint_box([1, 1, 1], [3, 3, 3], 0)
        self.assertEqual(editor.model.colour[2, 2, 2], 54)
        self.assertEqual(editor.model.material[2, 2, 2], 3)
        self.assertEqual(int((editor.model.colour > 0).sum()), 1)
        editor.undo()
        np.testing.assert_array_equal(editor.model.colour, before)
        editor.redo()
        self.assertEqual(int((editor.model.colour > 0).sum()), 1)
        steps = editor.info()["undo"]
        with self.assertRaises(ValueError):
            editor.paint_box([-1, 0, 0], [3, 3, 3], 1)
        self.assertEqual(editor.info()["undo"], steps)
        with self.assertRaises(ValueError):
            editor.save_model("../escape")

    def test_shape_material_by_colour_and_replace(self):
        editor = VoxelEditor()
        editor.new_model(8, 8, 8)
        editor.shape_slice("z", 3, [1, 1], [5, 5], 54, 10, "Circle")
        self.assertEqual(editor.model.colour[3, 3, 3], 54)  # planes are (z, y, x)
        self.assertEqual(editor.model.material[3, 3, 3], 10)
        self.assertEqual(editor.model.colour[3, 1, 1], 0)
        editor.paint_box([7, 7, 7], [7, 7, 7], 52)
        editor.set_material_for_colour(52, 15)
        self.assertEqual(editor.model.material[7, 7, 7], 15)
        editor.replace_colour(54, 52)
        self.assertEqual(editor.model.colour[3, 3, 3], 52)
        self.assertEqual(editor.model.material[3, 3, 3], 10)  # replace keeps materials unless asked

    def test_shapes_lines_voxels_mirror_copy_and_reading(self):
        editor = VoxelEditor()
        editor.new_model(16, 16, 16)
        ball = editor.fill_shape("ellipsoid", [2, 2, 2], [8, 8, 8], 54)["changed_voxels"]
        self.assertTrue(100 < ball < 7 ** 3)
        self.assertEqual(editor.model.colour[5, 5, 5], 54)  # the centre
        self.assertEqual(editor.model.colour[2, 2, 2], 0)   # a corner
        editor.undo()
        shell = editor.fill_shape("ellipsoid", [2, 2, 2], [8, 8, 8], 54, hollow=True)["changed_voxels"]
        self.assertLess(shell, ball)
        self.assertEqual(editor.model.colour[5, 5, 5], 0)
        editor.new_model(16, 16, 16)
        editor.fill_shape("cone", [4, 4, 0], [10, 10, 9], 60)
        self.assertGreater((editor.model.colour[0] > 0).sum(), (editor.model.colour[9] > 0).sum())
        with self.assertRaises(ValueError):
            editor.fill_shape("box", [0, 0, 0], [1, 1, 1], 1)
        editor.new_model(16, 16, 16)
        self.assertEqual(editor.draw_line([0, 0, 0], [15, 0, 0], 52)["changed_voxels"], 16)
        self.assertGreater(editor.draw_line([0, 8, 8], [15, 8, 8], 52, radius=1)["changed_voxels"], 16 * 5)
        editor.set_voxels([[1, 2, 3], [2, 2, 3]], colour=60)
        editor.set_voxels([[3, 2, 3, 61, 15]])
        self.assertEqual(editor.model.colour[3, 2, 3], 61)
        self.assertEqual(editor.model.material[3, 2, 3], 15)
        with self.assertRaises(ValueError):
            editor.set_voxels([[1, 2, 3]])  # no colour
        editor.new_model(8, 4, 4)
        editor.paint_box([0, 0, 0], [1, 3, 3], 54)  # the low x side only
        editor.mirror("x")
        np.testing.assert_array_equal(editor.model.colour, editor.model.colour[:, :, ::-1])
        editor.copy_box([0, 0, 0], [1, 0, 0], [2, 0, 0])
        self.assertEqual(editor.model.colour[0, 0, 2], 54)
        rows = editor.read_slice("y", 0)
        self.assertEqual(rows["grid"][0].split(), ["54", "54", "..", "..", "..", "..", "54", "54"])  # z 3, the top
        self.assertEqual(rows["grid"][-1].split(), ["54", "54", "54", "54", "..", "..", "54", "54"])  # z 0, copied
        self.assertEqual(len(editor.read_slice("x", 7)["grid"]), 4)  # deeper than the model is along y and z
        found = editor.voxels_in_box([0, 0, 0], [7, 0, 0])
        self.assertEqual([v[0] for v in found["voxels"]], [0, 1, 2, 3, 6, 7])

    def test_noise_tools(self):
        editor = VoxelEditor()
        editor.new_model(24, 20, 12)
        # terrain: within the box, from its floor up, the top layer from the top palette, the same for a seed
        editor.noise_terrain([0, 0, 0], [23, 19, 5], top=[[155, 1, 16]], under=[[150, 1]], soil=[[68, 3], [67, 1]],
                             scale=8, seed=4)
        c = editor.model.colour
        self.assertFalse(c[6:].any())
        self.assertTrue(c[0].all())
        heights = (c > 0).sum(axis=0) - 1
        self.assertEqual((heights.min(), heights.max()), (0, 5))
        self.assertTrue((c[heights, *np.indices(heights.shape)] == 155).all())
        self.assertEqual(editor.model.material[c == 155].max(), 16)
        soil = c[(c == 68) | (c == 67)]
        self.assertAlmostEqual((soil == 68).mean(), 0.75, delta=0.01)  # a share is kept exactly
        first = c.copy()
        again = VoxelEditor()
        again.new_model(24, 20, 12)
        again.noise_terrain([0, 0, 0], [23, 19, 5], top=[[155, 1, 16]], under=[[150, 1]], soil=[[68, 3], [67, 1]],
                            scale=8, seed=4)
        np.testing.assert_array_equal(again.model.colour, first)
        # speckle: only the surface, only one colour, the shares exact, patches with a scale
        result = editor.speckle([0, 0, 0], [23, 19, 11], [[153, 1], [127, 1]], only_colour=155, scale=3, seed=1)
        self.assertGreater(result["changed_voxels"], 0)
        self.assertFalse((editor.model.colour == 155).any())
        self.assertLessEqual(abs(int((editor.model.colour == 153).sum()) - int((editor.model.colour == 127).sum())), 1)
        # scatter: columns stand on the chosen colours only, open above
        before = int((editor.model.colour > 0).sum())
        editor.scatter([0, 0, 0], [23, 19, 11], [{"stack": [150, 150, 251], "random_height": True, "material": 16}],
                       density=0.5, on_colours=[127], seed=2)
        c = editor.model.colour
        grown = (c == 251)
        self.assertGreater(int(grown.sum()), 10)
        stands_on = set()
        for z, y, x in zip(*np.nonzero(grown)):
            z -= 1
            while c[z, y, x] == 150:  # the column's stem
                z -= 1
            stands_on.add(int(c[z, y, x]))
        self.assertEqual(stands_on, {127})
        self.assertGreater(int((c > 0).sum()), before)
        # erode: pits take their share of the surface, the bottom layer stays whole, bumps add voxels
        editor.new_model(12, 12, 12)
        editor.fill_shape("ellipsoid", [0, 0, 0], [11, 11, 11], 144)
        whole = int((editor.model.colour > 0).sum())
        editor.erode_surface([0, 0, 0], [11, 11, 11], pits=0.2, seed=3)
        self.assertLess(int((editor.model.colour > 0).sum()), whole)
        bottom = int((editor.model.colour[0] > 0).sum())
        self.assertGreater(bottom, 0)
        editor.undo()
        self.assertEqual(int((editor.model.colour > 0).sum()), whole)  # one undo step
        editor.erode_surface([0, 0, 0], [11, 11, 11], pits=0, bumps=0.3, seed=3)
        self.assertGreater(int((editor.model.colour > 0).sum()), whole)
        with self.assertRaises(ValueError):
            editor.speckle([0, 0, 0], [1, 1, 1], [[153, -1]])

    def test_place_model_and_project_instances(self):
        from core.scene import orient_from_text, place_plane
        from project_ops import HeadlessProject, ProjectOps
        skeleton = VoxelEditor()
        skeleton.open_model(str(PIPELINE / "assets" / "skeleton.vx2"))
        sz, sy, sx = skeleton.model.colour.shape
        # place_model: a turned copy at a position, clipped at the edges, overwriting or filling only
        editor = VoxelEditor()
        editor.new_model(sy + 4, sx + 4, sz)
        editor.place_model("assets/skeleton.vx2", [2, 2, 0], turn=1)
        turned = place_plane(skeleton.model.colour, orient_from_text("+y-x+z"))
        np.testing.assert_array_equal(editor.model.colour[:, 2:2 + sx, 2:2 + sy], turned)
        editor.undo()
        self.assertFalse(editor.model.colour.any())  # one undo step
        editor.paint_box([0, 0, 0], [sy + 3, sx + 3, 0], 60)
        editor.place_model("assets/skeleton.vx2", [-3, 2, 0], turn=1, empty_only=True)
        self.assertTrue((editor.model.colour[0] == 60).all())  # the floor stayed
        self.assertGreater(int((editor.model.colour[1:] > 0).sum()), 0)
        # parts and instances on the server's own project
        doc = HeadlessProject(editor.model)
        ops = ProjectOps(lambda: doc)
        part = ops.add_part("assets/skeleton.vx2")["part"]
        self.assertEqual(ops.add_part(str(PIPELINE / "assets" / "skeleton.vx2"))["part"], part)  # once per file
        first = ops.add_instance(part, [0, 0, 0])
        second = ops.add_instance("assets/alchemist.vx2", [40, 0, 0], turn=2, scene="Two")
        self.assertEqual(second["orient"], "-x-y+z")
        ops.move_instance(first["name"], by=[5, 0, 0], scene=doc.project.scenes[0].name)
        moved = ops.move_instance(first["name"], turn=1, scene=doc.project.scenes[0].name)
        self.assertEqual(moved["orient"], "+y-x+z")
        info = ops.project_info()
        self.assertEqual(info["parts"][part]["instances"], 1)
        self.assertEqual([s["name"] for s in info["scenes"]], ["Scene-1", "Two"])
        colour, _, lo, _ = ops.merged(doc.project.scenes[0].name)
        np.testing.assert_array_equal(colour, turned)
        self.assertEqual(lo.tolist(), moved["position"])
        ops.remove_instance(first["name"], scene="Scene-1")
        self.assertEqual(ops.project_info()["parts"][part]["instances"], 0)
        with self.assertRaises(ValueError):
            ops.add_instance("no_such_part")

    @unittest.skipUnless(GAME_VOX.is_file(), "the original alchemist.vox is not here (set ALCHEMIST_VOX)")
    def test_game_vox_import_matches_the_converted_asset(self):
        editor = VoxelEditor()
        editor.open_model(str(GAME_VOX), {"23": 18})
        stored = VoxelEditor()
        stored.open_model(str(ALCHEMIST))
        np.testing.assert_array_equal(editor.model.colour, stored.model.colour)
        np.testing.assert_array_equal(editor.model.material, stored.model.material)
        image = Image.open(io.BytesIO(editor.preview_png()))
        self.assertEqual(image.size, (1200, 430))

class MCPTests(unittest.IsolatedAsyncioTestCase):
    async def test_stdio_tools_preview_and_render(self):
        params = StdioServerParameters(command=sys.executable, args=[str(ROOT / "mcp_server.py")], cwd=str(ROOT))
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer) as client:
                await client.initialize()
                tools = await client.list_tools()
                self.assertEqual(len(tools.tools), 49)
                self.assertFalse((await client.call_tool("open_model", {"path": str(ALCHEMIST)})).isError)
                found = await client.call_tool("find_colour", {"hex_value": "#c78665", "count": 1})
                self.assertFalse(found.isError)
                self.assertFalse((await client.call_tool("set_material_for_colour",
                                                         {"colour": 84, "material": 15})).isError)
                result = await client.call_tool("preview", {})
                images = [c for c in result.content if c.type == "image"]
                self.assertEqual(len(images), 1)
                self.assertEqual(Image.open(io.BytesIO(base64.b64decode(images[0].data))).size, (1200, 430))
                if not SKIP_GPU:
                    rendered = await client.call_tool("render", {"width": 320, "height": 320, "samples": 16})
                    self.assertFalse(rendered.isError, rendered.content)
                    data = base64.b64decode([c for c in rendered.content if c.type == "image"][0].data)
                    picture = Image.open(io.BytesIO(data))
                    self.assertEqual(picture.size, (320, 320))
                    (ROOT / "outputs").mkdir(exist_ok=True)
                    picture.save(ROOT / "outputs" / "mcp-render.png")
                self.assertFalse((await client.call_tool("undo", {})).isError)


if __name__ == "__main__":
    unittest.main()
