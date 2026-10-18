"""The one model every view edits and shows, with the current colour, material and tool.

Views never keep a copy of the voxels: they read `model.colour` / `model.material`
(planes shaped (z, y, x)) when `changed` fires. A stroke (press, drag, release in
any view) is one undo step.
"""
from __future__ import annotations

import copy
from pathlib import Path

import numpy as np
from PySide6 import QtCore

from core.model import HISTORY_LIMIT, Model
from material_source import send_tables  # palette/, on the path through core.model

# The edit views' material key: a colour per group (as the Dear PyGui editor's corner marks),
# lighter for later materials in the group, so each material is told apart.
GROUP_COLOUR = {"rough": (200, 192, 180), "glossy": (235, 235, 240), "metal": (120, 160, 220),
                "emissive": (255, 210, 40), "transparent": (70, 215, 255), "subsurface": (255, 120, 160),
                "special": (190, 80, 255)}


def material_colours(materials) -> np.ndarray:
    rgb = np.zeros((256, 3), dtype=np.uint8)
    groups = {}
    for m in materials:
        groups.setdefault(m["group"], []).append(m["id"])
    for group, ids in groups.items():
        base = np.array(GROUP_COLOUR.get(group, (200, 200, 200)), dtype=np.float32)
        for k, mid in enumerate(ids):
            shade = 0.6 + 0.4 * (k + 1) / len(ids)  # darker first, the group colour last
            rgb[mid] = np.clip(base * shade, 0, 255)
    return rgb


TOOLS = ("attach", "paint", "erase", "pick")


class Document(QtCore.QObject):
    changed = QtCore.Signal()          # voxels changed
    reset = QtCore.Signal()            # a different model (new, open): sizes may change
    current_changed = QtCore.Signal()  # colour, material or tool
    focus_changed = QtCore.Signal(int, int, int)  # slice views follow a voxel picked in 3D
    hover_changed = QtCore.Signal(str)
    display_changed = QtCore.Signal()  # colours or materials shown in the edit views
    material_edited = QtCore.Signal(int)  # a material's fields changed (live; saved with the model)
    tables_changed = QtCore.Signal()      # the list of materials changed (own materials added, other model)

    def __init__(self):
        super().__init__()
        self.model = Model()
        self.model.new(32, 32, 64)
        self.rgb = np.zeros((256, 3), dtype=np.uint8)  # colour slot -> sRGB
        for c in self.model.colors:
            self.rgb[c["id"]] = c["rgb"]
        self.colour = self.model.nearest_slot([150, 150, 150])
        self.material = 0
        self.tool = "attach"
        self.show_materials = False  # the edit views colour voxels by material instead of colour
        self.material_rgb = material_colours(self.model.all_materials())
        self._before = None

    # --- current colour, material, tool ------------------------------------------------
    def set_colour(self, slot: int) -> None:
        if 1 <= slot <= len(self.model.colors) and slot != self.colour:
            self.colour = slot
            self.current_changed.emit()

    def set_material(self, material: int) -> None:
        if self.model.has_material(material) and material != self.material:
            self.material = material
            self.current_changed.emit()

    def set_tool(self, tool: str) -> None:
        if tool in TOOLS and tool != self.tool:
            self.tool = tool
            self.current_changed.emit()

    def set_show_materials(self, show: bool) -> None:
        if show != self.show_materials:
            self.show_materials = show
            self.display_changed.emit()

    def display_planes(self):
        """(key plane, key -> sRGB) for the edit views: colours, or materials when shown."""
        if self.show_materials:
            return self.model.material, self.material_rgb
        return self.model.colour, self.rgb

    def describe(self, x: int, y: int, z: int) -> str:
        slot = self.voxel(x, y, z)
        if not slot:
            return f"({x}, {y}, {z})"
        material = self.model.material_info(self.model.material[z, y, x])
        return f"({x}, {y}, {z})  colour {slot}  {material['name']}"

    # --- materials: the shared table, and the model's own (saved with the model) -------
    # Editing never changes the shared table: a shared material is first copied into the
    # model (one of its own, ids 128-255) and the model's voxels move onto the copy. The
    # model's own materials are saved in its .vx2 with Save; the shared table changes only in
    # palette/build_materials.py.
    def set_material_field(self, material: int, field: str, value) -> None:
        """Change one field of a material, live in the render dock. A shared material becomes a
        copy of the model's own first (see own_copy), which then becomes current."""
        if self.model.material_info(material).get(field) == value:
            return
        if material not in self.model.local:
            material = self.own_copy(material)
        self.model.local[material][field] = value
        self.material_edited.emit(material)

    def own_copy(self, shared: int) -> int:
        """Copy a shared material into the model and move the model's voxels of it onto the copy
        (one undo step); the copy becomes current. Returns its id."""
        source = self.model.material_info(shared)
        names = {m["name"] for m in self.model.all_materials()}
        name = f"{source['name']} (own)"
        while name in names:
            name += "'"
        copied = self.model.add_local(dict(source, name=name, note=f"the model's copy of shared material {shared}"
                                           + (f": {source['note']}" if source.get("note") else "")))
        self.model._edit(lambda c, m: m.__setitem__((m == shared) & (c > 0), copied))
        self.material = copied
        self._materials_changed()
        self.changed.emit()
        return copied

    def is_own(self, material: int) -> bool:
        return material in self.model.local

    def is_new(self, material: int) -> bool:
        return material in self.model.local and material not in self.model.saved_local

    def is_edited(self, material: int) -> bool:
        return material in self.model.local and self.model.local[material] != self.model.saved_local.get(material)

    def unsaved_materials(self) -> list[int]:
        return [i for i in sorted(self.model.local) if self.is_edited(i)]

    def add_material(self, name: str, group: str | None = None) -> int:
        """One of the model's own materials, starting as a copy of the current one; it becomes
        current and is saved with the model."""
        name = name.strip()
        if not name or any(m["name"] == name for m in self.model.all_materials()):
            raise ValueError("give the material a new name")
        m = dict(copy.deepcopy(self.model.material_info(self.material)), name=name, engine="yes", note="")
        if group:
            m["group"] = group
        self.material = self.model.add_local(m)
        self._materials_changed()
        return self.material

    def adopt_materials(self, source: Model, material: np.ndarray) -> np.ndarray:
        """A material plane from another model (a stamp), its own materials made this model's own
        too: an identical one is reused, else a copy is added. Shared ids pass through."""
        if source is self.model or not source.local:
            return material
        out = material.copy()
        added = False
        for mid in np.unique(material):
            if int(mid) in source.local:
                own, new = self._own_like(source.local[int(mid)])
                out[material == mid] = own
                added |= new
        if added:
            self._materials_changed()
        return out

    def _own_like(self, material: dict) -> tuple[int, bool]:
        """(id of this model's own material equal to `material` but for its id, whether it is new)."""
        key = {k: v for k, v in material.items() if k != "id"}
        for mid, own in self.model.local.items():
            if {k: v for k, v in own.items() if k != "id"} == key:
                return mid, False
        return self.model.add_local(material), True

    def _materials_changed(self) -> None:
        self.material_rgb = material_colours(self.model.all_materials())
        self.tables_changed.emit()
        self.current_changed.emit()

    def send_tables_to(self, project: Path) -> dict:
        """Copy the shared tables into a project's assets/palette and restamp its .vx2 files."""
        return send_tables(project)

    def revert_material(self, material: int) -> None:
        """Back to the model's material as last saved (a new one has nothing to go back to)."""
        if self.is_edited(material) and not self.is_new(material):
            self.model.local[material] = copy.deepcopy(self.model.saved_local[material])
            self.material_edited.emit(material)

    def pick(self, x: int, y: int, z: int) -> None:
        """Pipette: the voxel's colour and material become current."""
        if self.inside(x, y, z) and self.model.colour[z, y, x]:
            self.colour = int(self.model.colour[z, y, x])
            self.material = int(self.model.material[z, y, x])
            self.current_changed.emit()

    # --- the model ------------------------------------------------------------------------
    @property
    def size(self) -> tuple[int, int, int]:
        """(x, y, z) voxels."""
        sz, sy, sx = self.model.colour.shape
        return sx, sy, sz

    def inside(self, x: int, y: int, z: int) -> bool:
        sx, sy, sz = self.size
        return 0 <= x < sx and 0 <= y < sy and 0 <= z < sz

    def voxel(self, x: int, y: int, z: int) -> int:
        return int(self.model.colour[z, y, x]) if self.inside(x, y, z) else 0

    def new(self, x: int, y: int, z: int, ground: int = 0) -> None:
        """An empty model of any size up to 256 a side; `ground` layers at the bottom start filled with
        the current colour and material (a diorama's floor)."""
        self.model.new(x, y, z)
        if not self.model.has_material(self.material):
            self.material = 0
        if ground > 0:
            self.model.colour[:ground] = self.colour
            self.model.material[:ground] = self.material
            self.model.version += 1
        self._model_switched()

    def open(self, path) -> None:
        self.model.open(path)
        self._model_switched()

    def edit_model(self, model: Model) -> None:
        """Show and edit this Model itself (a project's model, so its instances follow every edit)."""
        self._before = None
        self.model = model
        self._model_switched()

    def _model_switched(self) -> None:
        """Another model (new, opened, a project's): its own materials replace the last one's."""
        if not self.model.has_material(self.material):
            self.material = 0
        self.material_rgb = material_colours(self.model.all_materials())
        self.reset.emit()
        self.tables_changed.emit()
        self.current_changed.emit()
        self.changed.emit()

    def undo(self) -> None:
        if self.model.undo():
            self.changed.emit()

    def redo(self) -> None:
        if self.model.redo():
            self.changed.emit()

    # --- strokes: direct writes, one undo step per stroke ----------------------------------
    def begin_stroke(self) -> None:
        self._before = (self.model.colour.copy(), self.model.material.copy())

    def set_voxels(self, points, colour: int | None = None, material: int | None = None) -> int:
        """Set voxels at (x, y, z) points to a colour (0 erases) and material; the current ones by
        default. Outside the model is ignored. Returns how many changed."""
        colour = self.colour if colour is None else colour
        material = self.material if material is None else material
        pts = np.atleast_2d(np.asarray(points, dtype=int))
        if not len(pts):
            return 0
        sx, sy, sz = self.size
        pts = pts[(pts >= 0).all(axis=1) & (pts[:, 0] < sx) & (pts[:, 1] < sy) & (pts[:, 2] < sz)]
        if not len(pts):
            return 0
        x, y, z = pts.T
        own_stroke = self._before is None
        if own_stroke:
            self.begin_stroke()
        before = (self.model.colour[z, y, x].copy(), self.model.material[z, y, x].copy())
        self.model.colour[z, y, x] = colour
        self.model.material[z, y, x] = material if colour else 0
        changed = int(((self.model.colour[z, y, x] != before[0]) | (self.model.material[z, y, x] != before[1])).sum())
        if changed:
            self.model.version += 1
            self.changed.emit()
        if own_stroke:
            self.end_stroke()
        return changed

    def set_voxel_values(self, points, colours, materials) -> int:
        """Set voxels at (x, y, z) points to their own colours and materials (a stamp). Outside the model is
        ignored; one undo step unless a stroke is open. Returns how many changed."""
        pts = np.atleast_2d(np.asarray(points, dtype=int))
        colours, materials = np.asarray(colours, dtype=np.uint8), np.asarray(materials, dtype=np.uint8)
        if not len(pts):
            return 0
        sx, sy, sz = self.size
        keep = (pts >= 0).all(axis=1) & (pts[:, 0] < sx) & (pts[:, 1] < sy) & (pts[:, 2] < sz)
        pts, colours, materials = pts[keep], colours[keep], materials[keep]
        if not len(pts):
            return 0
        x, y, z = pts.T
        own_stroke = self._before is None
        if own_stroke:
            self.begin_stroke()
        before = (self.model.colour[z, y, x].copy(), self.model.material[z, y, x].copy())
        self.model.colour[z, y, x] = colours
        self.model.material[z, y, x] = np.where(colours > 0, materials, 0)
        changed = int(((self.model.colour[z, y, x] != before[0]) | (self.model.material[z, y, x] != before[1])).sum())
        if changed:
            self.model.version += 1
            self.changed.emit()
        if own_stroke:
            self.end_stroke()
        return changed

    def end_stroke(self) -> None:
        if self._before is None:
            return
        before_c, before_m = self._before
        self._before = None
        if before_c.shape == self.model.colour.shape and (
                not np.array_equal(before_c, self.model.colour) or not np.array_equal(before_m, self.model.material)):
            self.model.undo_stack.append((before_c, before_m))
            del self.model.undo_stack[:-HISTORY_LIMIT]
            self.model.redo_stack.clear()
