# DualVoxel guide

DualVoxel stores two bytes per voxel: a colour and a material. Build models and dioramas voxel by voxel, give every voxel a colour and a material, and see the result live in a path tracer.

![The editor with the alchemist open](figures/current_cover.png)

Most work follows one loop:

> **pick a colour and a material → pick a mode and a brush → draw → look at the Render dock → save**

This guide walks through that loop. The [reference](reference.md) covers the technical parts: material fields in detail, the `.vx2` file format, and using the editor from Python or an AI assistant.

Every screenshot here comes from the running editor (`capture_manual.py` retakes them).

**Contents**

1. [Start](#1-start)
2. [Find your way around](#2-find-your-way-around)
3. [Draw](#3-draw)
4. [Colours and materials](#4-colours-and-materials)
5. [Light and the render](#5-light-and-the-render)
6. [Scenes and parts](#6-scenes-and-parts)
7. [Keys](#7-keys)

---

## 1. Start

Start the editor from the `editor` folder, optionally with a model to open:

```
.venv\Scripts\python.exe qt_editor.py ..\assets\corpse.vx2
```

or double-click `run_qt_editor.cmd`. The window opens at once. The first time, the Render dock takes about half a minute before the picture appears while the renderer prepares itself. (The [reference](reference.md#setup-the-renderer-and-local-settings) says how to install the editor and where it finds the renderer.)

![The whole editor](figures/current_desktop.png)

*The editor with the alchemist open. Left: the Outliner and the Front, Side and Top slices. Middle: the 3D edit view, with a sphere brush's green preview on the floor. Next to it: the Render dock. Far right: Brush (Light behind it), Colours (Material editor and Transform behind it) and Materials.*

### Your first model

1. **File → New…** (`Ctrl+N`). Give the size in voxels (up to 256 a side). For a diorama, add a few **floor layers**.
2. Click a colour in the **Colours** dock and a material in the **Materials** dock. **matte** is the plain one.
3. In the **Brush** dock choose **Attach** and **Voxel**, and a size.
4. Draw in the 3D edit view with the left mouse button. Right drag turns the view, middle drag moves it, the wheel zooms.
5. **File → Save** (`Ctrl+S`). The model goes to `assets/<name>.vx2`, with a MagicaVoxel copy in `export/<name>.vox`.

> **Tip:** the 3D edit view is for drawing. It shows flat colours so every voxel is easy to hit. Judge how the model *looks* in the Render dock.

**File → Open** (`Ctrl+O`) reads `.vx2` files and MagicaVoxel `.vox` files from any folder. A `.vox` file's colours snap to the nearest colours of the editor's table.

---

## 2. Find your way around

Every part of the window is a dock. Drag a dock by its tab to move it beside another, onto another as a tab, or out as its own window. The layout is remembered. **View → Reset layout** brings back the standard one, and the **View** menu shows or hides each dock. All docks show the same model: an edit in one shows everywhere at once.

| Dock | What it is for |
|---|---|
| 3D edit | Drawing in 3D, with a see-through preview of what a click would change. **Materials** colours voxels by material, **Edges** outlines them, **Frame** fits the model in view. |
| Front, Side, Top | One layer of the model at a time, like a paint program ([Slices](#slices)). |
| Render | The model in the path tracer, on a wooden table in sunlight. |
| Brush | The mode, the brush, its size and shape, sculpting, mirroring. |
| Light | Sun and sky, presets, tilt blur, pause. |
| Colours | The 255 colours; a click picks one. |
| Materials | The materials, grouped; a click picks one. |
| Material editor | The current material's settings, live in the render. |
| Outliner, Scene, Transform | Several models placed together ([Scenes and parts](#6-scenes-and-parts)). |

The status bar names the model, its size and voxel count, and what the mouse is over, for example `3D attach (voxel): (6, 2, 1) · 66 voxels`: the mode, the brush, the voxel, and how many voxels a click would change.

**Undo** with `Ctrl+Z`, redo with `Ctrl+Y`. Every click or drag is one step, however many voxels it changed. While the Outliner, the Scene view or the Transform dock has the focus, undo works on the scene instead of the model.

---

## 3. Draw

The mouse works as in MagicaVoxel, in the 3D view and in the slices alike. The **mode** decides what the left button does; the **brush** decides how many voxels, in which shape.

| Mouse | Does |
|---|---|
| Left click or drag | The current mode with the current brush. A drag is one undo step. |
| Shift + left | Swaps attach and erase (in Paint mode: erases). With Erode or Grow, swaps those two. |
| Ctrl + left | Paints (in Paint mode: attaches). |
| Alt + left | Picks the clicked voxel's colour and material. |
| Right drag | Turns the view. |
| Middle drag | Moves the view. |
| Wheel | Zooms (in the slices: moves the layer). |

You never have to remember this: the Brush dock shows the current mapping under the mode buttons, and the preview in the 3D view changes as you press Shift or Ctrl.

<img src="figures/current_brush_dock.png" width="468" alt="The Brush dock">

*The Brush dock: mode, mouse mapping, brush, sculpting, size and shape, mirror.*

### Modes

- **Attach** (`A`) adds voxels against the clicked face, or on the floor. It only fills empty places and never overwrites a voxel.
- **Paint** (`B`) gives existing voxels the current colour and material.
- **Erase** (`E`) removes voxels.
- **Pick** (`P`) takes a voxel's colour and material.

### Brushes

- **Voxel**: a square or circle (**2D**, flat against the clicked face) or a cube or sphere (**3D**), 1 to 32 voxels. `[` and `]` change the size in the 3D view.
- **Face**: the clicked face's whole connected flat area. Attach builds a new layer on it; paint and erase take all of it.
- **Box**: drag a rectangle in the clicked layer.
- **Stamp**: a whole model as the brush ([Stamps](#a-model-as-a-stamp)).

![The 3D edit view with a sphere brush preview](figures/current_edit_view.png)

*The green see-through sphere at the foot of the staff shows exactly the voxels a click would add. The preview is green for attach, yellow for paint and red for erase.*

### Sculpting

The **Sculpt** row reshapes what is already there, inside the brush's size and shape:

- **Smooth** rounds off: fills small hollows, takes off small bumps.
- **Erode** takes the outer skin of voxels off.
- **Grow** adds a skin of voxels in the colours of their neighbours.

Shift swaps Erode and Grow. Dragging over the same place several times digs (or builds) deeper; for a light touch, click once.

<img src="figures/current_brush_sculpt.png" width="468" alt="Smooth chosen in the Sculpt row">

### Mirror

**Mirror X**, **Y** and **Z** repeat every edit across the model's centre. Mirror X is the usual one for figures.

### Slices

The Front, Side and Top docks show one layer of the model each. Draw in them with the same mouse rules and the same brush as in the 3D view (except Stamp, which works only in 3D). The shaded cells under the mouse are exactly what a click changes.

Move the layer with the slider, the arrow buttons, the number box or the wheel. **Behind** shows the nearest voxels behind the layer, dimmed, so you can draw on top of what is there.

<img src="figures/current_slice_top.png" width="318" alt="The Top slice">

*The Top slice through the alchemist's legs. The shaded circle is a size-5 circle brush.*

---

## 4. Colours and materials

Every voxel stores two things:

- a **colour**: *what colour it is*, and
- a **material**: *how its surface takes the light* — matte or shiny, metal, glass, glowing, waxy.

The renderer combines the two: red + matte is a brick, red + glass is ruby glass. Drawing gives each new voxel the current colour *and* the current material.

### Colours

The **Colours** dock holds a table of 255 colours. Click one to make it current; hover for its number and hex value. All models share this table.

<img src="figures/current_colours.png" width="468" alt="The Colours dock">

### Materials

The **Materials** dock lists the materials by group: rough, glossy, metal, glowing, transparent, subsurface and so on. Small bars show how rough, metallic, glowing, see-through and translucent each one is; **voxels** counts how many voxels of this model use it. Hover for a short description.

- Click a material to make it current.
- **All voxels of colour N → material** gives every voxel of the current colour the current material in one step. It is the quick way to make all the skin voxels skin, or all the gold trim metal.
- **Show materials in the edit views** colours the 3D view and the slices by material instead of colour, so you can see where each one is used.

<img src="figures/current_materials.png" width="468" alt="The Materials dock">

> **Tip:** rust patches, scratches and worn edges are not textures. Paint them voxel by voxel with materials such as **rust**, **worn metal**, **scratched metal** and **worn leather**.

### Making your own materials

The listed materials are shared by all models; the editor never changes them. To make one of your own, use **New material…** in the **Material editor** (a tab beside Colours): it starts as a copy of the current material, and it is saved inside this model only.

You can also just move a slider on a shared material. The editor then makes this model's own copy (for example `matte (own)`), moves this model's voxels onto it and changes the copy. Other models are not affected.

> **Watch out:** a copy keeps its name. If you turn `matte`'s roughness down to 0, the copy is called `matte (own)` but it is now glossy. Rename it in the **name** field.

Your own materials are marked `*` until you save the model. **Revert** takes one back to how it was saved.

<img src="figures/current_material_editor_glass.png" width="480" alt="The Material editor on glass">

*The Material editor on **glass**: nearly all light goes through.*

### What the settings do

| Setting | What it does |
|---|---|
| roughness | How blurred reflections are: 0 is a mirror-smooth surface, 1 is dull. |
| metal | 0 is not metal, 1 is metal. Metal reflects in its own colour. |
| transmission | How much light goes *through*, as through glass. |
| density | For see-through materials: how quickly the colour builds up inside. Pale glass is high, deep coloured glass is low. |
| subsurface | How much light goes *into* the surface and scatters before coming out: skin, wax, leaves, jade. |
| subsurface depth | How deep that light goes, in voxels. |
| sheen | A soft brightening where light grazes the surface: cloth, moss, dust. |
| emission | The voxel glows in its own colour. |
| ior | How strongly glass bends light and how strong reflections are. 1.5 suits almost everything. |
| light | An animated glow pattern (fire, pulse, flash, …); usually none. |

The settings are not separate looks that switch each other off: they are shares of one surface, and a half-metal is half metal, half what is below. The label beside each slider says whether it matters right now: **used** (green) or **ignored** (grey), for example density without transmission, or everything under a full metal. An ignored slider is safe to leave alone. The [reference](reference.md#material-fields) explains the blending order.

<img src="figures/current_material_editor_metal.png" width="480" alt="The Material editor on polished metal">

*Polished metal: with metal at 1, transmission, subsurface, sheen and ior are ignored.*

To get a feel for it: pick a material, set roughness to 0.2 and watch the Render dock; then metal to 1; then metal back to 0 and transmission to 1. Those three moves show most of what the system does.

---

## 5. Light and the render

### The Render dock

The Render dock shows the model in a GPU path tracer, standing on a wooden table. The picture starts noisy and settles within a second or two; the number at the bottom right counts the samples so far.

- Drag to turn, middle drag to move, wheel to zoom, double click to frame the model.
- Every edit, material change and light change shows at once.
- A hidden or closed Render dock draws nothing and costs nothing.
- Models with animated glows keep drawing, since they move.

![The Render dock](figures/current_render.png)

### The Light dock

The **Light** dock (a tab beside Brush) sets the sun and the sky. Only the picture changes, never the model.

<img src="figures/current_light_dock.png" width="480" alt="The Light dock">

- **Preset**: a starting point — Golden hour, Day, Noon, Overcast or Night.
- **Sun**, **Sky**: their strength, from 0 (off) to 3.
- **Azimuth**, **Elevation**: where the sun stands around the table and how high.
- **Colour buttons**: the sun's colour, the sky's horizon and zenith, and the background. A bright sun stays bright in a new colour.
- **Default light**: back to the standard golden hour.
- **Lights off**: sun and sky off, to see what glows on its own.
- **Tilt blur**: the miniature-style blur above and below the model; off shows everything sharp.
- **Pause render** (`F9`): stops drawing and frees the GPU, keeping the last picture.

Changing the direction or a colour turns the preset into **Custom**.

| Golden hour | Day |
|---|---|
| ![Golden hour](figures/current_light_golden_hour.png) | ![Day](figures/current_light_day.png) |
| **Overcast** | **Night** |
| ![Overcast](figures/current_light_overcast.png) | ![Night](figures/current_light_night.png) |

*The same model under four presets. At night the glowing crystal on the staff is the main light.*

---

## 6. Scenes and parts

A **project** places several models together, like MagicaVoxel's world view or Blender's objects. It is a file `assets/<name>.project.json` that lists **parts** (models, each a `.vx2` file) and any number of **scenes** made of **instances**. Use **Scene → New project / Open project… / Save project** (`Ctrl+Alt+S`). Save project also saves edited parts.

An instance is a *linked* copy: it points at its part and never copies the voxels, so painting the part changes every instance of it. Each instance has a position and a quarter-turn orientation, mirrored or not.

Opening a MagicaVoxel file with several models makes a new project: each model becomes a part and MagicaVoxel's scene becomes a scene of instances. Save project writes the parts to `assets` as `<file>-<n>.vx2`.

![A project open in the Scene view](figures/current_scene.png)

*`demo.project.json`: the Outliner lists its three parts and two scenes; the Scene view shows `Scene-1` with a skeleton selected.*

### The Outliner

Lists the **Models** (parts) and the **Scenes** with their instances; `*` marks a part that is edited but not saved. Its buttons: **Add model…**, **New scene**, **Add instance** (of the selected model), **Edit model** (or a double click) to open it in the drawing docks, **Remove**, and **Use as brush**.

### The Scene view

Click an instance to select it; drag it to move it (dragging elsewhere, or a right drag, turns the view). With an instance selected:

- the arrow keys move it as seen (Up is away from you), `Page Up` / `Page Down` move it up and down; with Shift, 8 voxels at a time;
- `R` turns it (`Shift+R` back), `M` mirrors it left–right;
- `Ctrl+D` makes a linked copy beside it, `Del` deletes it;
- `Enter` or a double click edits its part.

### The Transform dock

Type a position; rotate by ±90° or 180° about x, y or z; mirror; **Reset**. **Array** makes linked copies in a **Grid** (counts along x, y, z and a gap) or a **Circle** (count, radius, and optionally each copy turned to face out).

<img src="figures/current_transform.png" width="480" alt="The Transform dock">

### A model as a stamp

**Use as brush** in the Outliner makes the selected model (or instance, as it is turned) the brush, until `Esc` or another brush. Its preview follows the mouse in the 3D view.

- **Attach** adds its voxels, with their colours and materials, where the model is empty.
- **Paint** gives its colours to the voxels that are there.
- **Erase** carves out its shape.

`R` turns the stamp (`Shift+R` back).

> **Note:** the Render dock shows the model being edited, not the whole scene.

---

## 7. Keys

The 3D-view keys work while the 3D edit view has the focus.

| Key | Does |
|---|---|
| `Ctrl+N`, `Ctrl+O` | New model, open |
| `Ctrl+S`, `Ctrl+Shift+S` | Save, save as |
| `Ctrl+Z`, `Ctrl+Y` | Undo, redo |
| `A`, `B`, `E`, `P` | Attach, paint, erase, pick |
| `[`, `]` | Brush size down, up |
| `R`, `Shift+R` | Turn the stamp, or the selected instance |
| `Esc` | Stop stamping |
| `F9` | Pause or resume the render |
| `Ctrl+Alt+S` | Save the project |
| Arrows, `Page Up`/`Page Down` | Move the selected instance (Shift: 8 voxels) |
| `M`, `Ctrl+D`, `Del` | Mirror, duplicate, delete the selected instance |
| `Ctrl+Q` | Quit |
