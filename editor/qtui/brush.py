"""The 3D edit view's brush: which voxels a click touches (the mode, attach / paint / erase / pick, is the
Document's tool).

Kinds, as in MagicaVoxel: voxel (a size and a shape: square or circle, flat
across the clicked face or a volume, cube or sphere), face (the clicked face's
connected flat area), box (drag a rectangle in one layer) and stamp (a
project's model, from the outliner's "Use as brush"); and the sculpting ones,
which reshape what is there within the voxel brush's size and shape: smooth,
erode (peel the outer layer) and grow (add one; Shift swaps erode and grow).
Mirror x / y / z repeats every edit across the model's centre. brush_edit()
says what a click writes, for the 3D view and the slices alike.

The mouse, as in MagicaVoxel: the mode decides what a left click or drag does;
Shift + left and Ctrl + left reach the other two (`mode_for`), Alt + left picks.
"""
from __future__ import annotations

import numpy as np
from PySide6 import QtCore

from core.brushes import MAX_SIZE, SCULPT_OPS, box, face_region, layer_region, mirrored, placed, sculpt
from core.scene import place_plane, rotated

SCULPT = SCULPT_OPS  # smooth, erode, grow
KINDS = ("voxel", "face", "box", "stamp", *SCULPT)
SWAPPED_SCULPT = {"erode": "grow", "grow": "erode"}  # with Shift, as attach and erase
SHIFT_MODE = {"attach": "erase", "erase": "attach", "paint": "erase"}  # MagicaVoxel's attach / erase tandem
CTRL_MODE = {"attach": "paint", "erase": "paint", "paint": "attach"}


def mode_for(tool: str, shift: bool = False, ctrl: bool = False, alt: bool = False) -> str:
    """What a left click or drag does in this mode with these keys held: the mode itself, Shift its partner
    (attach and erase swap; paint erases), Ctrl paint (in paint mode, attach), Alt (or the pick mode) pick."""
    if alt or tool == "pick":
        return "pick"
    if shift:
        return SHIFT_MODE[tool]
    if ctrl:
        return CTRL_MODE[tool]
    return tool


def held_mode(tool: str, modifiers) -> str:
    """mode_for with Qt's keyboard modifiers."""
    Mod = QtCore.Qt.KeyboardModifier
    return mode_for(tool, bool(modifiers & Mod.ShiftModifier), bool(modifiers & Mod.ControlModifier),
                    bool(modifiers & Mod.AltModifier))


class Brush(QtCore.QObject):
    changed = QtCore.Signal()

    def __init__(self):
        super().__init__()
        self.kind = "voxel"
        self.size = 1
        self.round = False   # circle / sphere instead of square / cube
        self.volume = True   # 3D (cube, sphere) instead of 2D (square, circle)
        self.mirror = (False, False, False)
        self.stamp = None    # (name, Model, orientation) for the stamp kind

    @property
    def shape(self) -> str:
        if self.volume:
            return "sphere" if self.round else "cube"
        return "circle" if self.round else "square"

    def set(self, **fields) -> None:
        changed = False
        for name, value in fields.items():
            if name == "size":
                value = max(1, min(MAX_SIZE, int(value)))
            if name == "mirror":
                value = tuple(bool(v) for v in value)
            if name == "kind" and value not in KINDS:
                raise ValueError(f"brush kinds: {', '.join(KINDS)}")
            if getattr(self, name) != value:
                setattr(self, name, value)
                changed = True
        if changed:
            self.changed.emit()

    def set_stamp(self, name, model, orient) -> None:
        """Stamp this Model (read when stamping, so its own edits show)."""
        self.stamp = (name, model, orient)
        self.kind = "stamp"
        self.changed.emit()

    def turn_stamp(self, quarter_turns: int = 1) -> None:
        if self.stamp is not None:
            name, model, orient = self.stamp
            self.stamp = (name, model, rotated(orient, 2, quarter_turns))
            self.changed.emit()


def stamp_low(target, normal, size):
    """A box's low corner against a face: from the target along the normal, centred across it."""
    size = np.asarray(size)
    low = np.asarray(target) - size // 2
    axis = int(np.argmax(np.abs(normal)))
    low[axis] = target[axis] if normal[axis] > 0 else target[axis] - size[axis] + 1
    return low


def brush_edit(doc, brush: Brush, tool: str, target, normal, hit=None, box_start=None, box_end=None,
               in_slice: bool = False, shift: bool = False):
    """What the brush writes for a click: (points, colours, materials) of the voxels it changes (colour 0:
    removed), mirrored, or None. tool: attach, paint or erase (Document.tool with the keys held); target: the
    voxel the mode acts on (attach: the empty one before the face, else the solid one); normal: the clicked
    face's outward normal (a slice: its viewing axis); hit: the solid voxel clicked (None on the floor or an
    empty cell); box_start: (voxel, normal) where a box drag began; in_slice: a slice, where the face brush
    fills the connected area of the clicked cell's colour in its layer and a stamp is a 3D-view brush."""
    if tool == "pick" or target is None and hit is None:
        return None
    normal = np.asarray(normal)
    if brush.kind in SCULPT:
        op = SWAPPED_SCULPT.get(brush.kind, brush.kind) if shift else brush.kind
        anchor = hit if hit is not None else target
        region, _ = mirrored(placed(brush.shape, brush.size, anchor, normal), doc.size, brush.mirror)
        return sculpt(doc.model.colour, doc.model.material, region, op)
    if target is None:
        return None
    colours = materials = None
    if brush.kind == "stamp" and not in_slice:
        if brush.stamp is None:
            return None
        _, model, orient = brush.stamp
        colour, material = place_plane(model.colour, orient).copy(), place_plane(model.material, orient).copy()
        material = doc.adopt_materials(model, material)  # the stamp's own materials come along
        z, y, x = np.nonzero(colour)
        # attach rests the brush on the face; paint and erase sink it into the surface from the face
        low = stamp_low(target, normal if tool == "attach" else -normal, colour.shape[::-1])
        points = np.stack([x, y, z], axis=1) + low
        colours, materials = colour[z, y, x], material[z, y, x]
    elif brush.kind == "face":
        if in_slice:
            points = layer_region(doc.model.colour, target, int(np.argmax(np.abs(normal))))
        elif hit is None:
            points = np.array([target])
        else:
            points = face_region(doc.model.colour > 0, hit, normal)
            if tool == "attach":
                points = points + normal
    elif brush.kind == "box":
        start, start_normal = box_start if box_start is not None else (target, normal)
        points = box(start, box_end if box_end is not None else target, start_normal)
    else:
        shape = brush.shape
        points = placed(shape, brush.size, target, normal, against=tool == "attach" and not in_slice)
    points, source = mirrored(points, doc.size, brush.mirror)
    if colours is None:
        colours = np.full(len(points), doc.colour, dtype=np.uint8)
        materials = np.full(len(points), doc.material, dtype=np.uint8)
    else:
        colours, materials = colours[source], materials[source]
    sx, sy, sz = doc.size
    inside = (points >= 0).all(axis=1) & (points[:, 0] < sx) & (points[:, 1] < sy) & (points[:, 2] < sz)
    points, colours, materials = points[inside], colours[inside], materials[inside]
    x, y, z = points.T
    solid = doc.model.colour[z, y, x] > 0
    keep = ~solid if tool == "attach" else solid
    if tool == "erase":
        colours = np.zeros_like(colours)
    if not keep.any():
        return None
    return points[keep], colours[keep], materials[keep]
