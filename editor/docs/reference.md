# DualVoxel reference

The technical side of DualVoxel. For everyday use, read the [guide](guide.md) first.

- [Folders](#folders)
- [Setup: the renderer and local settings](#setup-the-renderer-and-local-settings)
- [Material fields](#material-fields)
- [Shared and own materials](#shared-and-own-materials)
- [The .vx2 format](#the-vx2-format)
- [Python API, command line and MCP server](#python-api-command-line-and-mcp-server)
- [Tests](#tests)

---

## Folders

| Folder | Contents |
|---|---|
| `editor/` | The editor (PySide6, VTK), its Python API, command line and MCP server |
| `engine/` | The ctypes wrapper of the renderer and the local settings |
| `palette/` | The colour and material tables (`colors.json`, `materials.json`) and the material table's source |
| `pipeline/` | The `.vx2` format and MagicaVoxel `.vox` import and export |
| `assets/` | Models; saving writes here |

---

## Setup: the renderer and local settings

Install the Python environment in the `editor` folder with `uv sync` (it creates `.venv`).

The Render dock, `render` in the API and the render scripts use a GPU path tracer that ships as a binary: `VoxelRenderer.dll` with `trace.spv` and `rr_io.spv`, on Windows with a Vulkan GPU that has hardware ray tracing. NVIDIA's DLSS files (`nvngx_dlssd.dll`) are optional: with them the picture is denoised by DLSS Ray Reconstruction; without them the renderer accumulates samples and the Render dock says *no DLSS*.

By default the editor looks for these files in `editor/renderer/`. Without them the editor still works; the Render dock says that the renderer is missing and where it looked.

Settings for this machine go in `editor/editor.local.json` (not committed; `editor.local.example.json` is a template):

```json
{
  "renderer_path": "C:/path/to/renderer",
  "send_tables": [{"name": "MyGame", "path": "C:/path/to/MyGame"}]
}
```

- `renderer_path`: the folder with `VoxelRenderer.dll`, instead of `editor/renderer/`.
- `send_tables`: projects that keep their own copies of the colour and material tables in `<path>/assets/palette`. For each, the File menu offers **Send tables to <name>…**: after asking, it copies `colors.json` and `materials.json` there and restamps that project's `.vx2` files, but only if the colour table is the same and every material the project knows keeps its id and name. Without targets the menu item does not appear.

Relative paths are relative to the `editor` folder.

---

## Material fields

A material is one row of `palette/materials.json` (shared) or of a model's own list (saved in its `.vx2`). Amounts are 0 to 1 unless noted.

| Field | Meaning |
|---|---|
| `id` | 0–127 shared, 128–255 a model's own. |
| `name`, `group`, `note` | Shown in the Materials dock. A few names select fixed effects (below). |
| `roughness` | Blur of every reflection. From 0.85 up a non-metal no longer reflects: plain matte. |
| `metal` | Share of the surface that is metal, tinted by the voxel colour. |
| `transmission` | Share of the non-metal light that enters, as through glass. |
| `density` | With transmission: the voxels light travels inside before it has taken the colour once (default 4). |
| `subsurface` | Share of the remaining light that scatters under the surface. |
| `sss` | With subsurface: how deep it scatters, as a mean free path in voxels. Shown as *subsurface depth*. |
| `sheen` | Soft brightening at grazing angles and from behind. |
| `emission` | Light added in the voxel colour (clamped to 32). |
| `ior` | Index of refraction: non-metal reflection strength (1.5 ≈ 4 % head-on) and the bending of glass. |
| `light` | `""` or an animated glow: `fire`, `pulse`, `flash`, `sickly`, `unnatural`, `arcane`; `emission` sets its strength. |
| `engine` | `yes` or `partly`: how fully the renderer draws it (informational). |

### How the fields blend

The renderer blends the fields as Blender's Principled BSDF does, in a fixed order:

1. The voxel's **colour** is the base.
2. **metal** goes over everything; at 1 the surface is all metal.
3. Of the non-metal light, **transmission** is the share that goes through, as glass (**density** sets how deep the colour builds).
4. Of the rest, **subsurface** is the share that scatters under the surface (**sss** sets how deep).
5. What remains is a diffuse surface with a clear reflection blurred by **roughness**.
6. **sheen** and **emission** are added on top.

The Material editor labels each field **used** or **ignored** (`qtui/material_rules.py`). A field is ignored when another makes it irrelevant: density without transmission, sss without subsurface, transmission/subsurface/sheen/ior under a full metal, ior on a plain matte.

Three names are fixed effects that ignore their fields: `water`, `staff field` and `mirror metal`.

<img src="figures/current_material_editor_skin.png" width="480" alt="The Material editor on skin">

*`skin`: subsurface 1, depth 0.8 voxels, roughness 0.45.*

`palette/build_field_sweep.py` renders one row of spheres per field, from low to high:

![The field sweep](figures/render_field_sweep.png)

*Front to back: metal, roughness, transmission, density (1 to 32 voxels), subsurface, sheen, ior (1.0 to 2.4).*

---

## Shared and own materials

- **Shared materials** (ids 0–127) live in `palette/materials.json`, generated by `palette/build_materials.py`. The editor never changes them; edit `build_materials.py` and run it. **Copy table row** in the Material editor copies a material as a row for that file.
- **A model's own materials** (ids 128–255) are saved inside its `.vx2` and used only by it. A stamp brings the stamped model's own materials along; merging a scene renumbers every model's own materials into one list.

The colour table is `palette/colors.json` (255 colours, slot 0 is empty), generated by `palette/build_colors.py`.

---

## The .vx2 format

Two bytes per voxel: a colour slot and a material id. `pipeline/vx2.py` reads and writes it; all numbers are little-endian.

| Bytes | Content |
|---|---|
| 4 | magic `VX2\0` |
| uint32 | version: 1, or 2 with the model's own materials |
| 3 × uint32 | size x, y, z |
| 8 | colour table fingerprint |
| 8 | material table fingerprint |
| x·y·z | colour plane: slot 1–255, 0 = empty |
| x·y·z | material plane: shared id, or 128–255 for the model's own (0 where the colour is 0) |
| version 2 only: 4 + uint32 + n | `MATS`, n, then n bytes of UTF-8 JSON `{"materials": [...]}` with the model's own materials |

Both planes run x fastest, then y, then z (index `z·x·y + y·x + x`).

The fingerprints are the first 8 bytes of a SHA-256 over the colour table (ids and RGB) and over the material list of `materials.json`. A mismatch means the file's numbers point into a different table. After a table change that keeps every number's meaning (new materials at the end, a tuned value), restamp the files:

```
.venv\Scripts\python.exe ..\pipeline\vx2.py restamp ..\assets\*.vx2
```

`.vox` (MagicaVoxel) is import and export only. Saving writes `export/<name>.vox` beside the `.vx2`: lossless by default (each colour + material pair is one palette entry, with `_spell_color` and `_spell_material` in its `MATL` chunk; at most 255 pairs per model), or colours only.

Projects (`assets/<name>.project.json`) list parts as `.vx2` paths and scenes of instances, each with a position (the low corner of its box) and an orientation written as where the model's axes point (`+y-x+z` is a quarter turn about z).

---

## Python API, command line and MCP server

The same model works without a window.

### Python

```python
from headless_api import VoxelEditor

editor = VoxelEditor()
editor.open_model("../assets/corpse.vx2")
slot = editor.nearest_colours("#c78665", 1)[0]["slot"]
editor.set_material_for_colour(slot, 15)     # skin
editor.save_render("corpse-skin.png")       # rendered, into outputs/
editor.save_model("corpse-skin")             # assets/corpse-skin.vx2
```

Methods: `new_model`, `open_model`, `save_model`, `info`, `colour_table`, `nearest_colours`, `materials`, `paint_box`, `erase_box`, `shape_slice`, `set_material_box`, `set_material_for_colour`, `replace_colour`, `protect_box`, `clear_protection`, `undo`, `redo`, `preview_png`, `render_png`, `save_preview`, `save_render`, `close`. Coordinates are `[x, y, z]` with z up; boxes are inclusive. Protected boxes survive every edit until cleared.

### Command line

```
.venv\Scripts\python.exe editor_cli.py inspect|preview|render|edit <model> [--output name.png] [--operations ops.json --save name]
```

`--operations` takes a JSON list of `{"operation": name, "arguments": {...}}` using the edit methods above.

### MCP server

`run_mcp.cmd` starts a stdio MCP server for an AI assistant; `mcp.example.json` is a client entry (adjust its paths). Its tools: `open_model`, `new_model`, `model_info`, `colour_table`, `find_colour`, `list_materials`, `paint_box`, `erase_box`, `shape_slice`, `set_material_box`, `set_material_for_colour`, `replace_colour`, `protect_box`, `clear_protection`, `undo`, `redo`, `preview` (fast flat views), `render` (a path-traced image; the first call starts the renderer) and `save_model`. Standard output is kept for the protocol; the renderer's log goes to stderr.

---

## Tests

```
.venv\Scripts\python.exe -m unittest discover -s tests
```

`SKIP_GPU=1` skips the render check, `SKIP_QT=1` the window checks. A few mouse tests need a real display and fail under `QT_QPA_PLATFORM=offscreen`.

`docs/capture_manual.py` retakes the guide's `current_*` screenshots from the running editor; its window stays on top for about three minutes.
