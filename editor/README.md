# DualVoxel: two bytes per voxel, a colour and a material

The editor, seen live in a path tracer.

Every voxel has a **colour** (a slot 1-255 in `..\palette\colors.json`, 0 =
empty) and a **material** (an id in `..\palette\materials.json`). Models are
`.vx2` files (`..\pipeline\vx2.py`); `.vox` opens as an import (colours snap to
the table, MagicaVoxel material types become ours) and is written as an export
(with materials, or colours only).

The guide, with screenshots of the running editor, is
[`docs/guide.md`](docs/guide.md); the technical reference (material fields,
`.vx2`, the Python API and MCP server) is [`docs/reference.md`](docs/reference.md).
`docs\capture_manual.py` retakes the screenshots (its window shows for about
three minutes).

## How models are drawn

The render dock shows a model in the path tracer (`VoxelRenderer.dll`), on a
wooden table under a golden-hour sun; it takes
both bytes directly (`renderer_load_asset2` with the colour and material
tables). Every material but the fixed water, staff field and mirror is a blend
of its fields, as in Blender's Principled BSDF (see the Material editor below).
The magic lights (fire glow, pulse glow, flash, sickly glow, unnatural glow,
arcane glow) glow in the voxel colour and move with time; the view keeps
drawing at 15 fps while a model has them, water or the staff field. Patterns
such as rust patches, scratches or worn edges are painted voxel by voxel with
rust, worn metal, scratched metal, worn leather and so on.
`..\palette\build_material_test.py` builds `assets\material_test.vx2` (one
sphere per material) and renders it to `outputs\material_test.png`;
`..\palette\build_field_sweep.py` sweeps each field. After a change to the
shared table that keeps every number's meaning, `..\pipeline\vx2.py restamp`
updates the files' fingerprints (and a project with its own copies of the
tables needs them sent: File → Send tables).

## Desktop

    .venv\Scripts\python.exe qt_editor.py [model.vx2 | model.vox]

or double-click `run_qt_editor.cmd`. The first start takes about half a minute
before the render appears: the engine builds its shaders and DLSS once. The
model in movable docks (PySide6 with the Qt
Advanced Docking System, as in PythonFEM's CAE): Front, Side and Top slices,
a 3D edit view in VTK, the renderer, the colours and the materials.
The VTK view shows flat colours for editing only; looks are judged in the
render dock.

- **Your own models and dioramas:** File → New… makes an empty model of any
  size up to 256 voxels a side, optionally with floor layers of the current
  colour and material. Save writes
  `..\assets\<name>.vx2` (and `..\export\<name>.vox`); Open reads it back;
  the render dock shows it under the golden-hour light. The render dock uses
  the renderer (`VoxelRenderer.dll`, found in `renderer_path` of the gitignored `editor.local.json`, else in
  `renderer\`; see `docs\reference.md`).
- **Mouse, as in MagicaVoxel** (the 3D view and the slices): the mode decides
  what a left click or drag does; Shift + left and Ctrl + left reach the other
  two: Shift swaps attach and erase (in Paint mode it erases), Ctrl paints (in
  Paint mode it attaches); Alt + left picks colour and material. The Brush dock
  shows the current mapping, and the 3D preview follows the keys as you press
  them. Right drag orbits, middle drag pans, the wheel zooms (the 3D view and
  the scene view; the slices' wheel moves the layer).
- **Brush** (a dock at the top right, as MagicaVoxel's brush panel; it acts
  in the 3D view and the slices). **Mode:** Attach (A) adds voxels against the clicked face
  or the floor and only fills empty ones, Paint (B) recolours voxels that are
  there, Erase (E) removes them, Pick (P) takes colour and material.
  **Brush:** Voxel (a size, 1-32, `[` and `]` in the 3D view; square or
  circle; 2D, flat across the clicked face, or 3D, a cube or sphere, resting
  on the face when attaching), Face (the clicked face's whole connected flat
  area: attach builds a layer on it), Box (drag a rectangle in the clicked
  layer), Stamp (a project's model, see Scenes). **Sculpt:** Smooth (rounds
  off what is in the brush: fills hollows, takes off bumps), Erode (takes the
  outer skin off) and Grow (adds a skin, in the colours beside it), in the
  Voxel brush's size and shape, whatever the mode; Shift swaps Erode and Grow.
  A drag sculpts again at every step, so going over a place digs or builds
  deeper. **Mirror** X / Y / Z
  repeats every edit across the model's centre. A see-through preview in the
  mode's colour shows exactly what a click would change. A drag applies the
  brush along it (attach stays in one layer); each click or drag is one undo
  step.
- **Slices:** the mouse rule above with the Brush dock's brush (attach fills
  empty cells, paint recolours, erase removes): its size and shape at every
  cell the mouse crosses (2D lies in the layer, 3D reaches the layers around
  it), Box a rectangle dragged in the layer (outlined while dragging), Face the
  connected area of the clicked cell's colour in the layer, the sculpting
  brushes and mirroring; Stamp is a 3D-view brush. The layer moves with the slider, the ▼/▲ buttons (held, they keep
  stepping), the number box or the wheel; "Behind" shows the nearest voxels
  behind it, dimmed.
- **Materials:** grouped, with roughness, metal, glow, transmission and
  scattering as bars, whether the renderer draws them (yes, partly, new), the
  voxels using each and the note as tooltip. A click makes one current; the
  button gives every voxel of the current colour the current material.
  "Materials" in the 3D view (or the dock's checkbox) colours voxels by
  material, in the slices too; the dock's squares are the key.
- **Material editor** (a tab beside Colours): the materials are the shared
  table (ids 0 up, from `..{B}palette{B}build_materials.py`) and the model's
  **own** (ids 128-255), which are saved in its `.vx2` and never touch the
  shared table. **New material…** makes one of the model's own, starting as
  a copy of the current one. Editing a shared material makes the model's own
  copy of it ("matte (own)") and moves this model's voxels onto the copy
  (one undo step); the shared one stays as it is. Name, group and note are
  editable; sliders for roughness, metal, emission, transmission, density,
  subsurface, subsurface depth (sss), sheen and ior, and its magic light,
  live in the Render dock. The Materials dock lists the model's own
  first ("this model"). The renderer blends every field as Blender's Principled BSDF does:
  the voxel colour is the base, **metal** goes over the rest,
  **transmission** is the share of the non-metal light that enters as
  through glass (**density**: the voxels it travels before it has taken the
  colour once), **subsurface** the share of the rest that scatters under the
  surface (**sss**: how deep, in voxels), **sheen** a soft brightening where
  light grazes (cloth, moss, dust), **emission** light added in the voxel
  colour (a magic light's moving pattern with **light**), **roughness** the
  blur of every reflection (from 0.85 a non-metal stops reflecting: plain
  matte) and **ior** the reflection and refraction. Each field's label says
  whether it counts (`qtui\material_rules.py`, a mirror of the renderer's
  material code); **ignored** only for the fixed
  water, staff field and mirror, a full metal's other fields, density
  without transmission and sss without subsurface.
  `..\palette\build_field_sweep.py` renders seven fields from low to
  high. The model's own materials are marked * until the model is saved
  (Ctrl+S): they go into its `.vx2` (format version 2, `..\pipeline\vx2.py`;
  a model without them stays version 1, the simpler one). Revert
  takes one back to how it was saved; "Copy table row" copies a material as a
  row of `build_materials.py`, for when one should become shared (the shared
  table is changed there, with `..\palette\material_source.py` to restamp the
  models). A stamp brings the stamped model's own materials along, and a
  scene merge renumbers every model's own into one list.
- **File → Send tables to <name>…** (explicit, with a question first; one
  item per `send_tables` target in `editor.local.json`, none without):
  copies `colors.json` and `materials.json` into the target's
  `assets\palette` and restamps its `.vx2` files, only if the colour table is
  the same and every material it knows keeps its id and name. Until then the
  target keeps its own copies.
- **Render:** drag orbits (the same way round as the 3D view), middle drag
  pans, double click frames. Pause (in the Light dock, or F9) stops drawing
  and frees the GPU, keeping the last picture; edits made meanwhile show on
  resume. A hidden or closed render dock draws nothing.
- **Light** (a tab beside Brush): a preset to start from, Golden hour and
  Day the renderer's built-in light, Noon, Overcast
  and Night custom ones; the sun's direction (azimuth around the table, 0°
  along +x, and elevation) and colour, the sky's horizon and zenith and the
  background's top and bottom (colour buttons; a light colour keeps its
  strength), all live in the render; moving any of them makes the light
  Custom (the renderer's `renderer_set_light`). Sun and Sky scale the sun's and
  the sky's strength (1 each as set, 0 none, up to 3); Default light goes back
  to the golden hour at its own strength, Lights off shows what glows on its
  own; Tilt blur switches the tilt-shift band; Pause render (F9)
  stops the render. Only the picture changes, never the model.
- **Scenes** (models placed together, as MagicaVoxel's world or Blender's
  objects): a project, `..\assets\<name>.project.json` (Scene → New / Open /
  Save project, Ctrl+Alt+S; the command line opens one too), lists
  models (`.vx2` files) and any number of scenes of **instances**. An instance
  is a linked copy: it names its model and never copies its voxels, so
  painting the model changes every instance of it at once. Each has a position
  (its box's low corner) and an orientation, any quarter-turn rotation,
  mirrored or not, written as where the model's axes point (`"+y-x+z"` is a
  quarter turn about z). `..\assets\demo.project.json` places alchemist,
  skeleton and corpse, and a ring of skeletons.
  - **Outliner:** Models (✎ the one in the model docks, * edited and not
    saved) and Scenes with their instances. Add model…, New scene, Add
    instance (of the selected model), Edit model (or a double click) opens it
    in the slices, 3D edit, colours and materials, Remove.
  - **Scene view** (beside Render): a click selects an instance; drag it to
    move it (a drag elsewhere, or right drag, orbits); the arrows move it as seen (Up away from you), Page Up / Down up
    and down, Shift 8 voxels at a time; R turns it about z (Shift+R back), M
    mirrors it left-right as seen, Ctrl+D a linked copy beside it, Del deletes,
    Enter or a double click edits its model.
  - **Transform** (a tab beside Colours): position fields, rotate ±90° or 180°
    about x, y or z (keeping the bottom where it was), mirror x, y or z, reset;
    **Array**: a grid of linked copies (counts along x, y, z and a gap) or a
    circle (count, radius, each copy turned to face out).
  - Ctrl+Z / Ctrl+Y undo scene changes while the outliner, the scene view or
    the transform panel has focus, the model's edits elsewhere. Save project
    also saves edited models (into `..\assets`, as Ctrl+S does).
  - **Stamp brush:** "Use as brush" in the outliner makes the selected model
    (or instance, as it is turned) the Brush dock's stamp until Esc or another
    brush. Its preview follows the cursor, against the face pointed at (or on
    the floor) and centred across it. Attach adds its voxels with their
    colours and materials where the model is empty, Paint gives its colours
    to the voxels there, Erase carves its shape (sunk into the clicked face).
    R turns it (Shift+R back). It is read when stamping, so edits to its model
    show in the next stamp.
  - Not yet: the Render dock shows the model being edited, not the scene.
- One undo step per stroke; View → Reset layout; the layout is remembered.
  `--smoke out.png` waits for the render and saves a screenshot.

Code in `qt_editor.py` and `qtui\`, over `core\model.py` (the model),
`core\camera.py` and `engine_view.py` (the render). Scenes are
`core\scene.py` (projects, instances, orientations, arrays; no Qt) with
`qtui\project_document.py`, `outliner.py`, `scene_view.py` and
`transform_panel.py`, put into the window by `scene_docks.py`. Brushes are
`core\brushes.py` (shapes, face area, box, mirror; no Qt), `qtui\brush.py` (the
brush state) and `qtui\brush_panel.py` (the dock).

## Python, CLI and MCP

`headless_api.VoxelEditor` is the same model without a window:

    from headless_api import VoxelEditor
    editor = VoxelEditor()
    editor.open_model(r"..\assets\corpse.vx2")
    slot = editor.nearest_colours("#c78665", 1)[0]["slot"]
    editor.set_material_for_colour(slot, 15)       # skin -> subsurface
    editor.save_render("corpse-skin.png")         # the path tracer
    editor.save_model("corpse-skin")               # assets/corpse-skin.vx2

    .venv\Scripts\python.exe editor_cli.py inspect|preview|render|edit <model> [--operations ops.json --save name]

`run_mcp.cmd` starts the stdio MCP server (`mcp.example.json` has the client
entry). Its 19 tools: `open_model`, `new_model`, `model_info`,
`colour_table`, `find_colour`, `list_materials`, `paint_box`, `erase_box`,
`shape_slice`, `set_material_box`, `set_material_for_colour`,
`replace_colour`, `protect_box`, `clear_protection`, `undo`, `redo`,
`preview` (fast flat views of the colours) and `render` (the model in
the path tracer, returned as an image; the first call starts the
engine) and `save_model`. Coordinates are [x, y, z], z up, boxes inclusive.
Protected boxes survive every edit until cleared. The server keeps standard
output for the protocol and sends the renderer's own log lines to stderr.

Models open from any folder; saves go to `VoxelPipeline\assets` only. A
MagicaVoxel file of several models opens as a new project: each model a part,
its scene (positions and quarter-turn rotations) a scene of instances, and an
animated shape's frames parts side by side in a second scene; Save project
writes the parts into `assets` as `<file>-<n>.vx2`.

    .venv\Scripts\python.exe -m unittest discover -s tests

(`SKIP_GPU=1` skips the render check, `SKIP_QT=1` the scene editor's window check.)

## Structure

`core\model.py` the two-byte model, its own materials, edits and undo;
`core\scene.py` projects; `core\brushes.py` brush shapes; `core\camera.py`
the render dock's orbit camera; `qtui\` the window; `logic\tools.py` the
shape and fill helpers the headless API uses; `engine_view.py` the live engine
view; `voxel_preview.py` the flat preview pictures; `headless_api.py`,
`mcp_server.py`, `editor_cli.py`. `core\palette.py` keeps the old elemental
palette, which `..\palette\build_colors.py` reads as a source. The earlier
Dear PyGui editor (`main.py`, `ui\`, `core\state.py`) and its CPU renderer
were removed on 18 October.
