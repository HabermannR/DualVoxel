"""The one model every view edits and shows, with the current colour, material and tool.

Views never keep a copy of the voxels: they read `model.colour` / `model.material`
(planes shaped (z, y, x)) when `changed` fires. A stroke (press, drag, release in
any view) is one undo step.

A whole-model transform (resize, fit, shift, turn, flip; from here, the live link,
or undo and redo of one) is noticed on `changed`: the user's protection moves with
the voxels, `transformed` tells the scenes (instances keep their voxels in place
when a part is resized), and `resized` tells the views when the size changed.
"""
from __future__ import annotations

import copy
import weakref
from pathlib import Path

import numpy as np
from PySide6 import QtCore

from core.model import Model, transform_plane
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


TOOLS = ("attach", "paint", "erase", "pick", "protect")
PROTECT_MODES = ("protect", "unprotect")  # the Protect mode, and with Shift lifting it


class Document(QtCore.QObject):
    changed = QtCore.Signal()          # voxels changed
    reset = QtCore.Signal()            # a different model (new, open): sizes may change
    resized = QtCore.Signal()          # the same model, its box another size (resize, fit, turn, their undo)
    transformed = QtCore.Signal(object, object)  # (model, (count, op, old size, new size)): see core.model
    current_changed = QtCore.Signal()  # colour, material or tool
    focus_changed = QtCore.Signal(int, int, int)  # slice views follow a voxel picked in 3D
    hover_changed = QtCore.Signal(str)
    display_changed = QtCore.Signal()  # colours or materials shown in the edit views
    material_edited = QtCore.Signal(int)  # a material's fields changed (live; saved with the model)
    tables_changed = QtCore.Signal()      # the list of materials changed (own materials added, other model)
    protection_changed = QtCore.Signal()  # voxels the user protected from the assistant
    colours_changed = QtCore.Signal()     # a colour slot's value changed (live, every model on that table)
    colour_table_changed = QtCore.Signal()  # another table shown, or it was saved: who owns it, what changed

    def __init__(self):
        super().__init__()
        self.model = Model()
        self.model.new(32, 32, 64)
        # Per model (a project's parts each keep theirs), for this session: voxels the assistant may not
        # change over the live link. Not undo steps and not saved.
        self._protection = weakref.WeakKeyDictionary()
        # Per model: (version, (x, y, z) low, high) of the boxes the last few strokes and undo steps changed,
        # so views can reread only those (edited_boxes).
        self._edits = weakref.WeakKeyDictionary()
        # Per model: its transform_count when last seen here, so each transform is followed once.
        self._seen = weakref.WeakKeyDictionary({self.model: self.model.transform_count})
        self.changed.connect(self._follow_transforms)  # first, so later slots see the new size settled
        # The open project, set by the scene docks: its colours are the ones that can be changed.
        self.project = lambda: None
        self.colour = self.model.nearest_slot([150, 150, 150])
        self.material = 0
        self.tool = "attach"
        self.show_materials = False  # the edit views colour voxels by material instead of colour
        self.shift_wrap = True  # a shift brings what leaves one side in at the other (the Model dock's Wrap)
        self.picked = None  # the voxel last picked (Alt + left, or the Pick mode)
        self.material_rgb = material_colours(self.model.all_materials())
        self._before = None

    @property
    def rgb(self) -> np.ndarray:
        """Colour slot -> sRGB, (256, 3), from the shown model's colour table."""
        return self.model.table.rgb

    # --- colours: the shown model's table, which only its project changes ----------------------
    def colours_editable(self) -> tuple[bool, str]:
        """(whether the shown colours can be changed here, why not)."""
        table, project = self.model.table, self.project()
        if project is not None and table is project.table:
            if project.path is None:
                return False, ("Colours belong to a project and are saved beside it. Save the project "
                               "(Scene → Save project) to give it its own colours file; then they can be changed.")
            return True, ""
        if table.is_default:
            return False, ("The default colours (palette/colors.json, built by palette/build_colors.py) never "
                           "change here. Open or save a project to have colours of its own.")
        where = f" ({table.path.name})" if table.path else ", a project no longer open"
        return False, f"These are {table.title}{where}: open that project to change them."

    def colour_models(self) -> list[Model]:
        """The models a colour change reaches: every model open on the shown table."""
        project = self.project()
        models = [m for m in project.models.values() if m.table is self.model.table] if project else []
        return models if any(m is self.model for m in models) else [self.model, *models]

    def set_slot_colour(self, slot: int, rgb) -> bool:
        """Change what a colour slot looks like, live in every model on this table (the project's)."""
        editable, why = self.colours_editable()
        if not editable:
            raise ValueError(why)
        if not self.model.table.set_rgb(slot, rgb):
            return False
        self._colours_changed()
        return True

    def revert_colours(self, slot: int | None = None) -> None:
        """A slot (or all) back to the project's colours as saved."""
        if self.colours_editable()[0] and self.model.table.revert(slot):
            self._colours_changed()

    def _colours_changed(self) -> None:
        self.colours_changed.emit()
        self.colour_table_changed.emit()
        self.display_changed.emit()  # the edit views redraw their colours
        self.current_changed.emit()

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
        protected = self.protected()
        mark = "  protected" if protected is not None and protected[z, y, x] else ""
        return f"({x}, {y}, {z})  colour {slot}  {material['name']}{mark}"

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
            self.picked = (x, y, z)  # the assistant can ask what the user pointed at
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
        self._protection.pop(self.model, None)
        self._model_switched()

    def open(self, path) -> None:
        self.model.open(path)
        self._protection.pop(self.model, None)
        self._model_switched()

    def edit_model(self, model: Model) -> None:
        """Show and edit this Model itself (a project's model, so its instances follow every edit)."""
        self._before = None
        self.model = model
        self._model_switched()

    # --- the whole model: its box and everything in it (each one undo step) ---------------------
    def resize(self, size, anchor=("centre", "centre", "low")) -> int:
        """A new box (x, y, z), the voxels placed by `anchor` per axis (low, centre, high). Returns how many
        solid voxels were left outside and lost."""
        lost = self.model.resize(size, anchor=anchor)
        self.changed.emit()
        return lost

    def fit(self) -> bool:
        """Shrink the box to the solid voxels; False when there are none or it already fits."""
        fitted = self.model.fit() is not None
        self.changed.emit()
        return fitted

    def shift(self, delta, wrap: bool = True) -> int:
        """Move every voxel by (dx, dy, dz); wrap brings what leaves one side in at the other. Returns how many
        solid voxels were lost (none with wrap)."""
        lost = self.model.shift(delta, wrap)
        self.changed.emit()
        return lost

    def rotate(self, axis: int, quarter_turns: int = 1) -> None:
        self.model.rotate(axis, quarter_turns)
        self.changed.emit()

    def flip(self, axis: int) -> None:
        self.model.flip(axis)
        self.changed.emit()

    def _follow_transforms(self) -> None:
        """On `changed`: follow each transform of the shown model since it was last seen (see the module's note)."""
        model = self.model
        seen = self._seen.get(model)
        self._seen[model] = model.transform_count
        if seen is None or seen == model.transform_count:
            return
        entries = model.transforms_since(seen) or []
        mask = self._protection.get(model)
        for entry in entries:
            if mask is not None and mask.shape == tuple(entry[2][::-1]):
                mask = transform_plane(mask, entry[1])
            self.transformed.emit(model, entry)
        if mask is not None:
            if mask.shape == model.colour.shape:
                self._protection[model] = mask
            else:  # a transform too long ago to follow
                self._protection.pop(model, None)
            self.protection_changed.emit()
        self.picked = None
        if not entries or any(e[2] != e[3] for e in entries):
            self.resized.emit()

    def _model_switched(self) -> None:
        """Another model (new, opened, a project's): its own materials replace the last one's."""
        self._seen[self.model] = self.model.transform_count
        self.picked = None
        if not self.model.has_material(self.material):
            self.material = 0
        self.material_rgb = material_colours(self.model.all_materials())
        self.reset.emit()
        self.tables_changed.emit()
        self.colour_table_changed.emit()
        self.current_changed.emit()
        self.changed.emit()

    # --- protection from the assistant (the live link) ---------------------------------------
    def protected(self, model: Model | None = None) -> np.ndarray | None:
        """The voxels (bool plane, z y x) the user protected in a model (the shown one by default), or None."""
        mask = self._protection.get(model or self.model)
        return mask if mask is not None and mask.any() else None

    def set_protected(self, points, on: bool = True) -> int:
        """Protect voxels at (x, y, z) points from the assistant, or lift it (on=False). Returns how many changed."""
        pts = np.atleast_2d(np.asarray(points, dtype=int))
        mask = self._protection.get(self.model)
        if mask is None or mask.shape != self.model.colour.shape:
            mask = self._protection[self.model] = np.zeros(self.model.colour.shape, dtype=bool)
        if not len(pts):
            return 0
        x, y, z = pts.T
        changed = int((mask[z, y, x] != on).sum())
        mask[z, y, x] = on
        if changed:
            self.protection_changed.emit()
        return changed

    def clear_protected(self) -> None:
        if self._protection.pop(self.model, None) is not None:
            self.protection_changed.emit()

    def apply_brush(self, voxels, mode: str) -> int:
        """Write what brush_edit gave for a mode: protect or unprotect its voxels, else set them."""
        if mode in PROTECT_MODES:
            return self.set_protected(voxels[0], mode == "protect")
        return self.set_voxel_values(*voxels)

    def undo(self) -> None:
        if self.model.undo():
            self._log_step(self.model.redo_stack[-1])
            self.changed.emit()

    def redo(self) -> None:
        if self.model.redo():
            self._log_step(self.model.undo_stack[-1])
            self.changed.emit()

    def _log_step(self, step) -> None:
        z, y, x = step.box
        self._log_box((x.start, y.start, z.start), (x.stop - 1, y.stop - 1, z.stop - 1))

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
            self._log_edit(x, y, z)
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
            self._log_edit(x, y, z)
            self.changed.emit()
        if own_stroke:
            self.end_stroke()
        return changed

    def _log_edit(self, x, y, z) -> None:
        self._log_box((int(x.min()), int(y.min()), int(z.min())), (int(x.max()), int(y.max()), int(z.max())))

    def _log_box(self, lo, hi) -> None:
        log = self._edits.setdefault(self.model, [])
        log.append((self.model.version, lo, hi))
        del log[:-256]

    def edited_boxes(self, since: int, model: Model | None = None):
        """The boxes ((x, y, z) low, high, inclusive) a model's voxels changed in after its version `since`, or
        None when they also changed in other ways (the live link, opening): then read them all."""
        model = model or self.model
        if since == model.version:
            return []
        log = self._edits.get(model, [])
        boxes = [(lo, hi) for version, lo, hi in log if version > since]
        return boxes if log and log[-1][0] == model.version and len(boxes) == model.version - since else None

    def end_stroke(self) -> None:
        if self._before is None:
            return
        before_c, before_m = self._before
        self._before = None
        if before_c.shape == self.model.colour.shape:
            self.model.record(before_c, before_m)  # the step keeps only the box the stroke changed
