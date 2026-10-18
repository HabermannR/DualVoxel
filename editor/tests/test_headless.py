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
                self.assertEqual(len(tools.tools), 19)
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
