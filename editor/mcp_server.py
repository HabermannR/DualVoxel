"""stdio MCP server over the editor's two-byte model (headless_api.py).

Coordinates are [x, y, z], z up, box ends inclusive. A voxel has a colour slot
(1-255 from the colour table, 0 = empty) and a material (see list_materials).
`render` shows the model in the path tracer; `preview` is a fast
flat diagram of the colours.

The server edits a model of its own, or, after connect_editor, the model open
in the editor window (live_link.py): the user watches each edit there and can
edit alongside. Pictures of the window's model are drawn here from a copy.
"""
import io
import os
import sys

# The protocol owns standard output. The renderer DLL (C++) prints status lines
# to it, so keep a private copy of the real output for MCP and point the
# process's standard output, at both the C runtime and (on Windows) the
# Windows handle, at stderr before the engine loads.
_protocol_out = os.dup(1)
os.dup2(2, 1)
if sys.platform == "win32":
    import ctypes
    import msvcrt
    ctypes.windll.kernel32.SetStdHandle(-11, msvcrt.get_osfhandle(2))  # STD_OUTPUT_HANDLE
sys.stdout = io.TextIOWrapper(os.fdopen(_protocol_out, "wb"), encoding="utf-8", write_through=True)

from mcp.server.fastmcp import FastMCP, Image  # noqa: E402

from pathlib import Path  # noqa: E402

from core.model import ROOT as PIPELINE  # noqa: E402
from headless_api import VoxelEditor  # noqa: E402
from live_link import LiveClient  # noqa: E402
from project_ops import HeadlessProject, ProjectOps, resolve  # noqa: E402

editor = VoxelEditor()
live: LiveClient | None = None  # the open editor, after connect_editor
mcp = FastMCP("DualVoxel")


def _do(op: str, **args):
    """An edit or question on the current model: the window's while connected, else the server's own."""
    global live
    if live is None:
        return getattr(editor, op)(**args)
    try:
        return live.call(op, **args)
    except ConnectionError as error:
        live.close()
        live = None
        raise ConnectionError(f"{error} Disconnected: tools work on the server's own model again.") from None


def _own_only(what: str) -> None:
    if live is not None:
        raise ValueError(f"Connected to the open editor, where the user {what}. disconnect_editor first to "
                         "work on a model of the server's own.")


def _surroundings(surroundings, strength, rotation, floor):
    return {"environment": surroundings, "strength": strength, "rotation": rotation, "floor": floor}


def _picture_model():
    """The model to draw: a copy of the window's while connected, else None (the server's own)."""
    global live
    if live is None:
        return None
    try:
        return live.model()
    except ConnectionError as error:
        live.close()
        live = None
        raise ConnectionError(f"{error} Disconnected.") from None


@mcp.tool()
def connect_editor() -> dict:
    """Work on the model open in the editor window (the user starts the editor; Tools > Assistant link is on
    by default). The user sees every edit and may edit too: undo/redo only take back your own steps, and
    voxels the user protected (info: user_protected) stay as they are. open_model opens a file there (asking the user first if the shown model has edits);
    new models and saving stay the user's."""
    global live
    if live is not None:
        live.close()
    live = LiveClient()
    return live.hello


@mcp.tool()
def disconnect_editor() -> dict:
    """Back to the server's own model (the window keeps everything done in it)."""
    global live
    if live is not None:
        live.close()
        live = None
    return {"connected": False, **editor.info()}


@mcp.tool()
def open_model(path: str, material_overrides: dict[str, int] | None = None) -> dict:
    """Open a .vx2, or import a .vox (colours snap to the table; MagicaVoxel materials map to ours;
    material_overrides maps a .vox palette index to a material id, e.g. {"23": 18}). A relative path is
    from VoxelPipeline, e.g. "assets/meadow.vx2". Connected, it opens in the window (a .project.json too),
    where the user is asked first if the model shown has edits; overrides are the server's own only."""
    target = Path(path) if Path(path).is_absolute() else PIPELINE / path
    if live is not None:
        if material_overrides:
            raise ValueError("material_overrides work on the server's own model: disconnect_editor first.")
        return _do("open_model", path=str(target.resolve()))
    return editor.open_model(str(target), material_overrides)


@mcp.tool()
def new_model(x: int = 32, y: int = 32, z: int = 64) -> dict:
    """Create an empty model (each side 1-256 voxels; a small figure is about 32 x 32 x 64)."""
    _own_only("starts new models")
    return editor.new_model(x, y, z)


@mcp.tool()
def model_info() -> dict:
    """Size, voxel count, bounds, the colours and colour-material pairs in use, undo and redo steps; and
    whether this is the open editor's model."""
    return {"editor_window": live is not None, **_do("info")}


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
    """All materials (id, name, group, whether the engine draws it yet, note), the model's own included."""
    return _do("materials")


@mcp.tool()
def add_material(base: int = 0, name: str = "", fields: dict | None = None) -> dict:
    """A material of the model's own (ids 128 up, saved in its .vx2): a copy of material `base` named
    `name`, with `fields` changed: roughness, metal, emission, ior, transmission, density, sss, subsurface,
    sheen, anisotropy, group ("gas" makes a volume), light (fire, pulse, flash, sickly, unnatural, arcane or
    "") and note. E.g. a beating red haze: base 37 (glowing gas), {"light": "pulse", "emission": 1.5}.
    Returns its id; paint with it like any material."""
    _own_only("adds materials (Materials dock: New material…)")
    return editor.add_material(base, name, fields)


@mcp.tool()
def paint_box(start: list[int], end: list[int], colour: int, material: int = 0) -> dict:
    """Fill an inclusive [x, y, z] box with a colour and material; colour 0 erases."""
    return _do("paint_box", start=start, end=end, colour=colour, material=material)


@mcp.tool()
def erase_box(start: list[int], end: list[int]) -> dict:
    """Empty an inclusive [x, y, z] box."""
    return _do("erase_box", start=start, end=end)


@mcp.tool()
def shape_slice(axis: str, depth: int, start: list[int], end: list[int], colour: int, material: int = 0,
                shape: str = "Rect") -> dict:
    """The slice tool: a Rect or Circle in one plane (axis x, y or z at depth), corners as [u, v]."""
    return _do("shape_slice", axis=axis, depth=depth, start=start, end=end, colour=colour, material=material,
               shape=shape)


@mcp.tool()
def set_material_box(start: list[int], end: list[int], material: int) -> dict:
    """Give the solid voxels in a box a material, keeping their colours."""
    return _do("set_material_box", start=start, end=end, material=material)


@mcp.tool()
def set_material_for_colour(colour: int, material: int) -> dict:
    """Give every voxel of one colour a material, e.g. the skin colours subsurface (15)."""
    return _do("set_material_for_colour", colour=colour, material=material)


@mcp.tool()
def replace_colour(old: int, new: int, material: int | None = None) -> dict:
    """Turn every voxel of colour `old` into `new` (and optionally that material)."""
    return _do("replace_colour", old=old, new=new, material=material)


@mcp.tool()
def fill_shape(shape: str, start: list[int], end: list[int], colour: int, material: int = 0, hollow: bool = False,
               axis: str = "z") -> dict:
    """An "ellipsoid", "cylinder" or "cone" filling the inclusive box start..end (cylinder and cone run along
    axis; the cone narrows to a point at the box's high end). hollow keeps a one-voxel shell; colour 0 carves."""
    return _do("fill_shape", shape=shape, start=start, end=end, colour=colour, material=material, hollow=hollow,
               axis=axis)


@mcp.tool()
def draw_line(start: list[int], end: list[int], colour: int, material: int = 0, radius: int = 0) -> dict:
    """Voxels along a line from start to end, radius voxels thick around it (0: one voxel): limbs, staffs, ropes."""
    return _do("draw_line", start=start, end=end, colour=colour, material=material, radius=radius)


@mcp.tool()
def set_voxels(voxels: list[list[int]], colour: int | None = None, material: int = 0) -> dict:
    """Single voxels, one undo step: [x, y, z] (with colour and material), [x, y, z, colour] or
    [x, y, z, colour, material]; colour 0 erases. For details: eyes, buttons, patterns."""
    return _do("set_voxels", voxels=voxels, colour=colour, material=material)


@mcp.tool()
def mirror(axis: str = "x", keep: str = "low") -> dict:
    """Copy one half of the model onto the other across its centre: draw one side of a figure, mirror it.
    keep: the half that stays, "low" (below the centre on that axis) or "high"."""
    return _do("mirror", axis=axis, keep=keep)


@mcp.tool()
def resize_model(size: list[int], anchor: str | list[str] | None = None, offset: list[int] | None = None) -> dict:
    """Give the model a new box [x, y, z] (1-256 a side), as MagicaVoxel's size fields: room to grow, or a crop.
    anchor places the voxels per axis: "low", "centre" or "high" (one for all, or [x, y, z]; default x and y
    centred, z low: on the floor); or offset [x, y, z] says where the old voxel [0, 0, 0] lands. Voxels left
    outside are lost (lost_voxels), never protected ones. In a project, its instances keep their voxels in place."""
    return _do("resize_model", size=size, anchor=anchor, offset=offset)


@mcp.tool()
def fit_model() -> dict:
    """Shrink the model's box to its solid voxels."""
    return _do("fit_model")


@mcp.tool()
def shift_model(offset: list[int], wrap: bool = True) -> dict:
    """Move every voxel by [dx, dy, dz] inside the box (MagicaVoxel's Move): wrap brings what leaves one side
    in at the other, else it is lost (never protected voxels)."""
    return _do("shift_model", offset=offset, wrap=wrap)


@mcp.tool()
def rotate_model(axis: str = "z", turns: int = 1) -> dict:
    """Turn the whole model by quarter turns about "x", "y" or "z", counter-clockwise looking down the axis;
    the box turns with it (a 32 x 16 box turned about z is 16 x 32)."""
    return _do("rotate_model", axis=axis, turns=turns)


@mcp.tool()
def flip_model(axis: str = "x") -> dict:
    """Mirror the whole model along "x", "y" or "z" (unlike mirror, which copies one half onto the other)."""
    return _do("flip_model", axis=axis)


@mcp.tool()
def copy_box(start: list[int], end: list[int], offset: list[int], move: bool = False) -> dict:
    """Copy the solid voxels of a box by offset [dx, dy, dz]; move empties the source first."""
    return _do("copy_box", start=start, end=end, offset=offset, move=move)


@mcp.tool()
def speckle(start: list[int], end: list[int], colours: list[list[float]], surface_only: bool = True,
            only_colour: int | None = None, scale: float = 0, seed: int = 0) -> dict:
    """Recolour a box's solid voxels from a weighted palette [[colour, weight], ...] (or [colour, weight,
    material]), each colour taking its share exactly: leaves, moss, soil, worn paint. scale 0 scatters
    single voxels; scale 4 gathers each colour into patches about 4 voxels across. surface_only: only voxels
    with an empty neighbour; only_colour: only voxels of that colour. Without a material the voxel keeps its."""
    return _do("speckle", start=start, end=end, colours=_palette(colours), surface_only=surface_only,
               only_colour=only_colour, scale=scale, seed=seed)


@mcp.tool()
def noise_terrain(start: list[int], end: list[int], top: list[list[float]], under: list[list[float]] | None = None,
                  soil: list[list[float]] | None = None, under_depth: int = 1, scale: float = 12, octaves: int = 3,
                  seed: int = 0) -> dict:
    """Ground in a box: columns from its floor up to a smooth noise height spanning its z range (a flat box,
    z0 = z1, is a level slab). The top layer from the `top` palette, under_depth layers from `under`, the rest
    from `soil`, each [[colour, weight(, material)], ...]; a missing one repeats the one above. scale: the
    size of the hills in voxels; octaves add finer bumps. Fills only."""
    return _do("noise_terrain", start=start, end=end, top=_palette(top), under=_palette(under), soil=_palette(soil),
               under_depth=under_depth, scale=scale, octaves=octaves, seed=seed)


@mcp.tool()
def erode_surface(start: list[int], end: list[int], pits: float = 0.15, bumps: float = 0.0, scale: float = 0,
                  keep_bottom: bool = True, seed: int = 0) -> dict:
    """Roughen what is in a box: empty a `pits` share of its surface voxels (scale gathers pits into patches),
    then grow a `bumps` share of the rest by one voxel sideways or up, in its own colour: bushes, rocks,
    worn edges. keep_bottom keeps the box's lowest layer whole (what stands on the table)."""
    return _do("erode_surface", start=start, end=end, pits=pits, bumps=bumps, scale=scale, keep_bottom=keep_bottom,
               seed=seed)


@mcp.tool()
def scatter(start: list[int], end: list[int], options: list[dict], density: float = 0.05,
            on_colours: list[int] | None = None, seed: int = 0) -> dict:
    """Small columns on the top surface in a box (solid voxels open above; on_colours: only on those), each
    such voxel taking one with chance density: grass sprigs, flower dots, pebbles. options:
    [{"weight": 3, "stack": [153, 153, 127], "material": 16, "random_height": true}, {"weight": 1, "stack": [251]}],
    stacks from the bottom, an entry may be [colour, material]; random_height keeps the tip, drops some below."""
    return _do("scatter", start=start, end=end, options=options, density=density, on_colours=on_colours, seed=seed)


@mcp.tool()
def cloud(start: list[int], end: list[int], colours: list[list[float]], shape: str = "ellipsoid",
          coverage: float = 0.6, scale: float = 4, softness: float = 0.5, seed: int = 0) -> dict:
    """A soft, uneven body in the empty cells of a box, never over a solid: gas puffs, mist banks, smoke
    (with a gas material: smoke 34, steam 35, mist 36, glowing gas 37, flame 38), leafy crowns. shape
    "ellipsoid" (the one the box holds) or "box"; coverage: the share of the shape's cells it takes; scale:
    its lumps in voxels (0: single scattered voxels, as fireflies or sparks); softness 0-1 thins it toward
    the edge. colours: [[colour, weight, material], ...] as in speckle (a material 0 when left out)."""
    return _do("cloud", start=start, end=end, colours=_palette(colours), shape=shape, coverage=coverage,
               scale=scale, softness=softness, seed=seed)


@mcp.tool()
def place_model(path: str, position: list[int], orient: str | None = None, turn: int = 0, mirror: str | None = None,
                empty_only: bool = False) -> dict:
    """Copy a saved model's voxels into the current one, its box's low corner at position [x, y, z]
    ("assets/flower.vx2" from VoxelPipeline). orient "+y-x+z" as in a project, or turn (quarter turns about
    z) and mirror ("x", "y" or "z"). Overwrites (empty_only: fills only empty cells). A copy, unlike an
    instance: for linked copies use add_instance."""
    return _do("place_model", path=path, position=position, orient=orient, turn=turn, mirror=mirror,
               empty_only=empty_only)


# --- parts and instances: a project, like a FEM assembly ------------------------------------------
own_project = HeadlessProject(editor.model)
projects = ProjectOps(lambda: own_project)


def _project(op: str, **args):
    """A project operation: the window's project while connected, else the server's own."""
    return getattr(projects, op)(**args) if live is None else _do(op, **args)


@mcp.tool()
def project_info() -> dict:
    """The project's parts (file, size, how many instances, edited or not) and its scenes with every instance:
    name, part, position (its box's low corner), orientation and box. Connected: the window's project."""
    return _project("project_info")


@mcp.tool()
def project_open(path: str) -> dict:
    """Open a .project.json ("assets/meadow.project.json"): connected, in the window (as File > Open)."""
    if live is not None:
        return _do("open_model", path=str(resolve(path).resolve()))
    own_project.open_project(resolve(path))
    return projects.project_info()


@mcp.tool()
def add_part(path: str) -> dict:
    """A .vx2 as a part of the project ("assets/bush.vx2"); returns its part name (once per file)."""
    return _project("add_part", path=path)


@mcp.tool()
def add_instance(part: str, position: list[int] | None = None, orient: str | None = None, turn: int = 0,
                 mirror: str | None = None, scene: str | None = None) -> dict:
    """Place a part (its name, or a .vx2 path, added as a part) in a scene (default the one shown; a new
    name makes a scene): position is its box's low corner (default: right of what the scene holds), orient
    "+y-x+z", or turn (quarter turns about z) and mirror ("x", "y" or "z"). A linked copy: edits to the part
    show in every instance."""
    return _project("add_instance", part=part, position=position, orient=orient, turn=turn, mirror=mirror,
                    scene=scene)


@mcp.tool()
def move_instance(name: str, position: list[int] | None = None, by: list[int] | None = None,
                  orient: str | None = None, turn: int = 0, mirror: str | None = None,
                  scene: str | None = None) -> dict:
    """Move an instance (position: its box's low corner, or by: [dx, dy, dz]) and turn it (orient outright;
    turn and mirror keep its centre and bottom)."""
    return _project("move_instance", name=name, position=position, by=by, orient=orient, turn=turn, mirror=mirror,
                    scene=scene)


@mcp.tool()
def remove_instance(name: str, scene: str | None = None) -> dict:
    """Remove an instance from a scene (its part stays in the project)."""
    return _project("remove_instance", name=name, scene=scene)


@mcp.tool()
def merge_scene(scene: str | None = None) -> dict:
    """The server's own project only: a scene merged into one model (later instances win where they meet),
    which then becomes the current model, to render, edit or save. In the window the Scene view shows it."""
    _own_only("arranges scenes in the Scene view")
    colour, material, lo, local = projects.merged(scene)
    return {"low_corner": [int(v) for v in lo], **editor.load_volume(colour, material, local, projects.doc.project.table)}


@mcp.tool()
def project_save(name: str) -> dict:
    """The server's own project only: save it as assets/<name>.project.json (edited parts are saved too)."""
    _own_only("saves projects")
    return {"path": str(own_project.project.save(name)), **projects.project_info()}


def _palette(entries):
    """JSON numbers to [int colour, float weight(, int material)] rows (None stays None)."""
    if entries is None or isinstance(entries, int):
        return entries
    return [[int(e[0]), float(e[1]), *([int(e[2])] if len(e) > 2 else [])] for e in entries]


@mcp.tool()
def read_slice(axis: str, depth: int, what: str = "colour") -> dict:
    """One layer as a grid of colour slots (or materials), "." empty, cropped to what is in it: see exactly
    what is there, e.g. what the user drew. axis z: a floor plan, rows from back (high y) to front; x or y:
    rows from the top down."""
    return _do("read_slice", axis=axis, depth=depth, what=what)


@mcp.tool()
def voxels_in_box(start: list[int], end: list[int], limit: int = 2000) -> dict:
    """The solid voxels in a box as [x, y, z, colour, material]."""
    return _do("voxels_in_box", start=start, end=end, limit=limit)


@mcp.tool()
def user_state() -> dict:
    """Connected only: what the user has chosen and points at: current colour, material and mode, the voxel
    they last picked (Alt + click: "this one"), where their last stroke began, what the mouse was last over."""
    if live is None:
        raise ValueError("Not connected to the editor: connect_editor first.")
    return _do("user_state")


@mcp.tool()
def user_view(width: int = 640, height: int = 0, samples: int = 64, look: str = "none") -> Image:
    """Connected only: the model as the user sees it in the Render dock, with their camera and light.
    height 0 keeps the dock's shape. look: a finish, as for render."""
    if live is None:
        raise ValueError("Not connected to the editor: connect_editor first.")
    view = _do("view_state")
    height = height or max(16, min(1080, round(width / view["aspect"])))
    return Image(data=editor.render_png(width=width, height=height, samples=samples, model=_picture_model(),
                                        view=view, look=look), format="png")


@mcp.tool()
def protect_box(start: list[int], end: list[int]) -> dict:
    """Protect a box from later edits (e.g. a face) until clear_protection."""
    return _do("protect_box", start=start, end=end)


@mcp.tool()
def clear_protection() -> dict:
    """Remove all boxes you protected (the user's protection in the editor stays)."""
    return _do("clear_protection")


@mcp.tool()
def undo() -> dict:
    """Undo the last edit (connected: only your own; the user's steps are theirs to undo)."""
    return _do("undo")


@mcp.tool()
def redo() -> dict:
    """Redo the last undone edit."""
    return _do("redo")


@mcp.tool()
def preview() -> Image:
    """Fast flat views of the voxel colours (front, back, right, isometric), no lighting or materials."""
    return Image(data=editor.preview_png(_picture_model()), format="png")


@mcp.tool()
def render(yaw: float = -25.0, pitch: float = 10.0, width: int = 640, height: int = 640, samples: int = 64,
           light: str = "Golden hour", look: str = "none", surroundings: str = "sky",
           surroundings_strength: float = 1.0, surroundings_rotation: float = 0.0, floor: str = "wood") -> Image:
    """The model in the path tracer, on the wooden table. light is a Light dock preset: "Golden hour"
    (warm, orange), "Day", "Noon", "Overcast" (soft and neutral: best for judging colours) or "Night".
    yaw 0 looks at the front (from -y). The first call starts the engine (about half a minute).
    look finishes the picture: "none" (as traced: judge colours with it), "film" (tone curve, soft bloom,
    vignette) or "night" (strong bloom on glows and reds, cool shadows, grain): for final images.
    surroundings: "sky" (the light's own sun and sky) or an HDR environment that lights the model
    instead: a path to an .exr, or the name of one in the environments folder (editor.local.json); surroundings_strength and surroundings_rotation (degrees)
    for an environment. floor: "wood" (the table), "matte", "mirror", "polished metal", "cloth" or "none"."""
    return Image(data=editor.render_png(yaw, pitch, width, height, samples, light, _picture_model(), look=look,
                                        surroundings=_surroundings(surroundings, surroundings_strength,
                                                                   surroundings_rotation, floor)),
                 format="png")


@mcp.tool()
def render_file(name: str, width: int = 3840, height: int = 0, samples: int = 512, look: str = "none",
                yaw: float = -25.0, pitch: float = 10.0, light: str = "Golden hour",
                users_view: bool = False, surroundings: str = "sky", surroundings_strength: float = 1.0,
                surroundings_rotation: float = 0.0, floor: str = "wood") -> dict:
    """A high-resolution render saved as editor/outputs/<name>.png (up to 8192 a side, 4096 samples)
    instead of handed back: for final and print pictures. Same camera, light and look as render; or
    users_view (connected): the Render dock's camera and light, as user_view. height 0 keeps the shape:
    the dock's for users_view, else square. About a minute at 2160 x 2700 and 768 samples. Returns the
    file's path and size; look at it with Read."""
    view = None
    if users_view:
        if live is None:
            raise ValueError("users_view needs the editor: connect_editor first.")
        view = _do("view_state")
    height = height or (max(16, round(width / view["aspect"])) if view else width)
    name = name if name.lower().endswith(".png") else f"{name}.png"
    path = editor.save_render(name, yaw, pitch, width, height, samples, light, _picture_model(), view, look,
                              _surroundings(surroundings, surroundings_strength, surroundings_rotation, floor))
    return {"path": path, "width": width, "height": height, "samples": samples, "look": look}


@mcp.tool()
def render_orbit(name: str, frames: int = 300, fps: float = 30, degrees: float = 360, swing: bool = False,
                 yaw: float = -25.0, pitch: float = 20.0, width: int = 720, height: int = 720, samples: int = 128,
                 light: str = "Golden hour", look: str = "none", surroundings: str = "sky",
                 surroundings_strength: float = 1.0, surroundings_rotation: float = 0.0, floor: str = "wood") -> dict:
    """An orbit animation saved as editor/outputs/<name> (.mp4 needs ffmpeg; .gif or .webp always work):
    the camera turns about the model by `degrees` from the view at yaw and pitch: 360 goes round from
    there, a smaller angle sweeps an arc centred there; swing goes out to both ends and back, eased, so any
    angle loops. `frames` frames at `fps` (more frames for the same angle: a slower camera; 300 at 30 is
    10 s), each a still of `samples` per pixel, light and look as in
    render. Flames and the other magic lights move with the frames. A frame takes as long as a picture
    of its size: about 2 s at 720 x 900 and 128 samples with gas at night, so mind long ones."""
    return editor.save_orbit(name, frames, fps, degrees, swing, yaw, pitch, width, height, samples, light,
                             _picture_model(), look,
                             _surroundings(surroundings, surroundings_strength, surroundings_rotation, floor))


@mcp.tool()
def save_model(name: str, export_vox: bool = True) -> dict:
    """Save as VoxelPipeline/assets/<name>.vx2 (and a lossless export/<name>.vox)."""
    _own_only("saves (File > Save)")
    return editor.save_model(name, export_vox)


if __name__ == "__main__":
    mcp.run(transport="stdio")
