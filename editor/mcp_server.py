"""stdio MCP server over the editor's two-byte model (headless_api.py).

Coordinates are [x, y, z], z up, box ends inclusive. A voxel has a colour slot
(1-255 from the colour table, 0 = empty) and a material (see list_materials).
`render` shows the model in the path tracer; `preview` is a fast
flat diagram of the colours.
"""
import ctypes
import io
import msvcrt
import os
import sys

# The protocol owns standard output. The renderer DLL (C++) prints status lines
# to it, so keep a private copy of the real output for MCP and point the
# process's standard output, at both the C runtime and the Windows handle,
# at stderr before the engine loads.
_protocol_out = os.dup(1)
os.dup2(2, 1)
ctypes.windll.kernel32.SetStdHandle(-11, msvcrt.get_osfhandle(2))  # STD_OUTPUT_HANDLE
sys.stdout = io.TextIOWrapper(os.fdopen(_protocol_out, "wb"), encoding="utf-8", write_through=True)

from mcp.server.fastmcp import FastMCP, Image  # noqa: E402

from headless_api import VoxelEditor  # noqa: E402

editor = VoxelEditor()
mcp = FastMCP("DualVoxel")


@mcp.tool()
def open_model(path: str, material_overrides: dict[str, int] | None = None) -> dict:
    """Open a .vx2, or import a .vox (colours snap to the table; MagicaVoxel materials map to ours;
    material_overrides maps a .vox palette index to a material id, e.g. {"23": 18})."""
    return editor.open_model(path, material_overrides)


@mcp.tool()
def new_model(x: int = 32, y: int = 32, z: int = 64) -> dict:
    """Create an empty model (each side 1-256 voxels; a small figure is about 32 x 32 x 64)."""
    return editor.new_model(x, y, z)


@mcp.tool()
def model_info() -> dict:
    """Size, voxel count, bounds, the colours and colour-material pairs in use, undo and redo steps."""
    return editor.info()


@mcp.tool()
def colour_table(family: str = "") -> list[dict]:
    """The 255 table colours (slot, hex, family), optionally filtered by family, e.g. "neutral" or "blue"."""
    return editor.colour_table(family or None)


@mcp.tool()
def find_colour(hex_value: str, count: int = 5) -> list[dict]:
    """The table colours nearest to a hex colour like "#c78665" (CIEDE2000 distance)."""
    return editor.nearest_colours(hex_value, count)


@mcp.tool()
def list_materials() -> list[dict]:
    """All materials (id, name, group, whether the engine draws it yet, note)."""
    return editor.materials()


@mcp.tool()
def paint_box(start: list[int], end: list[int], colour: int, material: int = 0) -> dict:
    """Fill an inclusive [x, y, z] box with a colour and material; colour 0 erases."""
    return editor.paint_box(start, end, colour, material)


@mcp.tool()
def erase_box(start: list[int], end: list[int]) -> dict:
    """Empty an inclusive [x, y, z] box."""
    return editor.erase_box(start, end)


@mcp.tool()
def shape_slice(axis: str, depth: int, start: list[int], end: list[int], colour: int, material: int = 0,
                shape: str = "Rect") -> dict:
    """The slice tool: a Rect or Circle in one plane (axis x, y or z at depth), corners as [u, v]."""
    return editor.shape_slice(axis, depth, start, end, colour, material, shape)


@mcp.tool()
def set_material_box(start: list[int], end: list[int], material: int) -> dict:
    """Give the solid voxels in a box a material, keeping their colours."""
    return editor.set_material_box(start, end, material)


@mcp.tool()
def set_material_for_colour(colour: int, material: int) -> dict:
    """Give every voxel of one colour a material, e.g. the skin colours subsurface (15)."""
    return editor.set_material_for_colour(colour, material)


@mcp.tool()
def replace_colour(old: int, new: int, material: int | None = None) -> dict:
    """Turn every voxel of colour `old` into `new` (and optionally that material)."""
    return editor.replace_colour(old, new, material)


@mcp.tool()
def protect_box(start: list[int], end: list[int]) -> dict:
    """Protect a box from later edits (e.g. a face) until clear_protection."""
    return editor.protect_box(start, end)


@mcp.tool()
def clear_protection() -> dict:
    """Remove all protected boxes."""
    return editor.clear_protection()


@mcp.tool()
def undo() -> dict:
    """Undo the last edit."""
    return editor.undo()


@mcp.tool()
def redo() -> dict:
    """Redo the last undone edit."""
    return editor.redo()


@mcp.tool()
def preview() -> Image:
    """Fast flat views of the voxel colours (front, back, right, isometric), no lighting or materials."""
    return Image(data=editor.preview_png(), format="png")


@mcp.tool()
def render(yaw: float = -25.0, pitch: float = 10.0, width: int = 640, height: int = 640, samples: int = 64) -> Image:
    """The model in the path tracer, on the wooden table under a golden-hour sun.
    yaw 0 looks at the front (from -y). The first call starts the engine (about half a minute)."""
    return Image(data=editor.render_png(yaw, pitch, width, height, samples), format="png")


@mcp.tool()
def save_model(name: str, export_vox: bool = True) -> dict:
    """Save as VoxelPipeline/assets/<name>.vx2 (and a lossless export/<name>.vox)."""
    return editor.save_model(name, export_vox)


if __name__ == "__main__":
    mcp.run(transport="stdio")
