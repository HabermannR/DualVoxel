# DualVoxel

Two bytes per voxel: a colour and a material. DualVoxel is a voxel editor for models and dioramas, with a live path-traced preview. Every voxel stores a **colour** from a shared table of 255 colours and a **material** that says how its surface takes the light (matte, glossy, metal, glass, subsurface, glowing). The materials blend like Blender's Principled BSDF.

![The alchemist, path-traced at golden hour](editor/docs/figures/current_cover.png)

*Early release, made for my own game's assets and shared as is.*

- Draw as in MagicaVoxel: attach, paint, erase and pick, with voxel, face, box, line, fill and stamp brushes, sculpting (smooth, erode, grow, smear) and mirroring, in a 3D view and in slices you can zoom. Every key can be changed.
- See the model in a GPU path tracer while you work, under adjustable sun and sky.
- Make materials of your own per model; they are saved inside the model file.
- Place models together as linked instances in scenes; multi-model MagicaVoxel files open as projects.
- Script it from Python, the command line, or an AI assistant through an MCP server.

## Materials and light

One colour, many materials: each row of spheres sweeps one field from low to high (front to back: metal, roughness, transmission, density, subsurface, sheen, ior).

![Spheres sweeping each material field](editor/docs/figures/render_field_sweep.png)

The same model under the four light presets:

| Golden hour | Day |
|---|---|
| ![Golden hour](editor/docs/figures/current_light_golden_hour.png) | ![Day](editor/docs/figures/current_light_day.png) |
| **Overcast** | **Night** |
| ![Overcast](editor/docs/figures/current_light_overcast.png) | ![Night](editor/docs/figures/current_light_night.png) |

## Working in it

Slices on the left, the 3D edit view in flat colours for drawing, the path-traced render beside it, and the brush, colour and material docks on the right:

![The editor](editor/docs/figures/current_desktop.png)

Gas is a volume that light passes through and scatters in. Below, mist lies between the graves, a fire burns with smoke above it, and a red haze beats around the heart, all lit by their own lanterns and flames at night:

<img src="editor/docs/figures/current_gas.png" width="520" alt="A voxel graveyard at night with mist, a fire and a glowing red haze">

## Getting started

The editor is Python (PySide6, VTK) and runs on Windows, macOS 13 or newer and Linux; its tests run on macOS and Linux with every push, the Linux ones with path-traced renders. The renderer ships for Windows and Linux; on macOS the editor works without the render view (see the [reference](editor/docs/reference.md#setup-the-renderer-and-local-settings)). Day-to-day use has so far been on Windows; if something feels wrong on a Mac or on Linux, please open an issue. The render view needs a Vulkan GPU with hardware ray tracing:

- **NVIDIA RTX:** the picture is denoised by DLSS Ray Reconstruction, so it is clean while you move.
- **Other ray-tracing GPUs** (AMD RX 6000 or newer, Intel Arc): the renderer falls back to an accumulating preview that is noisy while you move and sharpens within seconds once the view is still. This path has not yet been tested on AMD or Intel cards.
- **Linux:** the renderer is built without DLSS, so it draws the accumulating preview on any GPU. Without a ray-tracing GPU, Mesa's lavapipe (`mesa-vulkan-drivers`) draws the same picture on the CPU, about twenty times slower: enough for stills, slow for the live view.
- **No hardware ray tracing** (for example Intel's integrated UHD and Iris Xe graphics) on Windows: the render view cannot run. The Render dock says which GPU it found and what that GPU lacks; drawing, the edit views and everything else work without it.

If the Render dock shows an error you cannot place, please open an issue with its message and your GPU.

1. Install [uv](https://docs.astral.sh/uv/), then in the `editor` folder run `uv sync`.
2. Download the renderer zip from the releases (`renderer-win64-…` or `renderer-linux-x64-…`) and unpack it into `editor/renderer/`.
3. Start the editor with an example model (the alchemist; `corpse.vx2` and `skeleton.vx2` are there too):

   ```
   cd editor
   uv run qt_editor.py ../assets/alchemist.vx2
   ```

   Or a whole scene built from parts, the meadow: 20 linked copies of grass, flowers, ferns, mushrooms and bushes on a patch of ground (`uv run qt_editor.py ../assets/meadow.project.json`).

Read the [guide](editor/docs/guide.md) to learn the editor, and the [reference](editor/docs/reference.md) for material fields, the `.vx2` file format, the Python API and the folder layout.

## Scenes from parts

A project places models together. Its models are **parts**, each an ordinary `.vx2`, and its **scenes** place them as **instances**: linked copies with a position and a quarter-turn orientation. Paint a part and every instance of it changes, and moving an instance never touches a voxel. The project itself is a short, readable `.project.json` that lists the parts' files and where each instance stands. **Save project** writes it together with every part you edited.

In the editor, the **Project** dock lists the parts and instances, the **Scene** view moves and turns them, and a double click on an instance opens its part for drawing. The Render dock path-traces the whole scene while you work in the Scene tab. The [guide](editor/docs/guide.md#6-scenes-and-parts) has the details.

## Let an AI assistant build with it

The editor's MCP server gives an assistant such as Claude the same model the editor uses: it can open and create models, paint and erase boxes, set materials, undo, look at a quick preview or a path-traced render under the editor's light presets, and save. With `connect_editor` it works on the model open in the editor window instead, while you watch and keep editing; voxels you mark with the Protect mode stay out of its reach. It can also read the open project and add, move, turn or remove its instances. Add it to your assistant's MCP configuration (for Claude Desktop, `claude_desktop_config.json`), with your own path to the `editor` folder (after `uv sync`):

```json
{
  "mcpServers": {
    "dualvoxel": {
      "command": "C:\\path\\to\\DualVoxel\\editor\\.venv\\Scripts\\python.exe",
      "args": ["-u", "C:\\path\\to\\DualVoxel\\editor\\mcp_server.py"]
    }
  }
}
```

On macOS the command is `/path/to/DualVoxel/editor/.venv/bin/python` and the script `/path/to/DualVoxel/editor/mcp_server.py`.

The same functions are available from Python (`headless_api.VoxelEditor`) and the command line (`editor_cli.py`); the [reference](editor/docs/reference.md#python-api-command-line-and-mcp-server) lists them.

## Licence

The editor's source is under the [MIT licence](LICENSE). The renderer (`VoxelRenderer.dll` or `libVoxelRenderer.so` and its shaders) is distributed separately as a binary under its own terms, which come with it; the Windows build includes NVIDIA DLSS, under NVIDIA's licence.
