"""The 3D edit view: the model as flat-coloured cubes in VTK, edited by picking faces.

This view is for editing, not for judging looks; the render dock shows the model
in the path tracer.

The mouse, as in MagicaVoxel: a left click or drag applies the brush (qtui/brush.py,
set in the Brush dock) in the current mode; Shift + left and Ctrl + left use the
other two modes (brush.mode_for), Alt + left picks. Right drag orbits, middle
drag pans, the wheel zooms. Attach adds voxels against the clicked face (or on the floor) and only
fills empty ones, paint recolours solid voxels, erase removes them, pick takes a
voxel's colour and material, protect marks voxels the assistant may not change
(tinted violet; Shift lifts it). Brushes: voxel (size, square or circle, flat or a
volume), face (the clicked face's connected flat area), box (drag a
rectangle in one layer), stamp (a project's model; R turns it, Esc stops), each
mirrored across the model's centre if asked. A see-through preview, in the
colour of the mode the keys held give, shows what a click would change. A drag
applies the brush along it (attach stays in the first voxel's layer, so it does
not climb towards the camera; the box brush draws a rectangle); each click or
drag is one undo step. [ and ] change the size.
"""
from __future__ import annotations

import numpy as np
import pyvista as pv
from PySide6 import QtCore, QtWidgets
from pyvistaqt import QtInteractor
from vtkmodules.vtkInteractionStyle import vtkInteractorStyleTrackballCamera
from vtkmodules.vtkRenderingCore import vtkCellPicker

from core.scene import IDENTITY
from qtui.brush import Brush, brush_edit, held_mode, mode_for
from qtui.document import PROTECT_MODES

HOVER_COLOUR = {"attach": (0.3, 1.0, 0.4), "paint": (1.0, 0.85, 0.1), "erase": (1.0, 0.3, 0.3),
                "pick": (0.4, 0.8, 1.0), "protect": (0.75, 0.45, 1.0), "unprotect": (0.6, 0.6, 0.65)}
PROTECTED_RGB = np.array([150, 80, 255], dtype=np.float32)  # protected voxels lean towards this
PROTECTED_TINT = 0.45
CLICK_SLOP = 4  # pixels a press may move and still count as a click
PREVIEW_OPACITY = 0.4


def voxel_faces(colour_zyx: np.ndarray, rgb: np.ndarray, key_zyx: np.ndarray | None = None):
    """The model's exposed faces as quads: points, quads, each face's colour, voxel and outward normal.
    Faces take rgb[key] (the colour plane by default, e.g. the material plane to show materials)."""
    key_zyx = colour_zyx if key_zyx is None else key_zyx
    solid = colour_zyx.transpose(2, 1, 0) > 0  # (x, y, z)
    padded = np.pad(solid, 1)
    points, quads, colours, voxels, normals = [], [], [], [], []
    count = 0
    for axis in range(3):
        b, c = (axis + 1) % 3, (axis + 2) % 3
        eb, ec = np.eye(3, dtype=int)[b], np.eye(3, dtype=int)[c]
        for sign in (1, -1):
            shift = [0, 0, 0]
            shift[axis] = sign
            neighbour = np.roll(padded, -sign, axis=axis)[1:-1, 1:-1, 1:-1]
            idx = np.argwhere(solid & ~neighbour)
            if not len(idx):
                continue
            base = idx.copy()
            if sign > 0:
                base[:, axis] += 1
            corners = [base, base + eb, base + eb + ec, base + ec]
            if sign < 0:
                corners = corners[::-1]
            n = len(idx)
            points.append(np.stack(corners, axis=1).reshape(-1, 3))
            quads.append(count + np.arange(4 * n).reshape(n, 4))
            x, y, z = idx.T
            colours.append(rgb[key_zyx[z, y, x]])
            voxels.append(idx)
            normals.append(np.tile(shift, (n, 1)))
            count += 4 * n
    if not points:
        return None
    return (np.concatenate(points).astype(np.float32), np.concatenate(quads), np.concatenate(colours),
            np.concatenate(voxels), np.concatenate(normals))


class EditStyle(vtkInteractorStyleTrackballCamera):
    """MagicaVoxel's mouse: left draws (the mode; Shift, Ctrl and Alt pick another), right drag orbits, middle
    drag pans, the wheel zooms.

    PyVistaQt's widget remembers one active button: a right click during a left drag makes the left release
    arrive as a right release, so the stroke would never end and the view would stop orbiting. The style
    therefore also hears Qt's own releases (released, from the view's event filter) and ends a stroke or
    an orbit whose button went up; a right click during a stroke is ignored."""

    def __init__(self, view: "EditView"):
        super().__init__()
        self.view = view
        self.stroking = False
        self.orbiting = False
        self.AddObserver("LeftButtonPressEvent", self.left_down)
        self.AddObserver("LeftButtonReleaseEvent", self.left_up)
        self.AddObserver("RightButtonPressEvent", self.right_down)
        self.AddObserver("RightButtonReleaseEvent", self.right_up)
        self.AddObserver("MouseMoveEvent", self.move)
        self.AddObserver("CharEvent", lambda *_: None)  # no VTK letter keys (w, s, e, q, ...)

    def released(self, button):
        """Qt released this button: end its stroke or orbit if VTK's release went astray."""
        if button == QtCore.Qt.MouseButton.LeftButton and self.stroking:
            self.stroking = False
            self.view.end_stroke()
        if button == QtCore.Qt.MouseButton.RightButton and self.orbiting:
            self.orbiting = False
            self.OnLeftButtonUp()

    def left_down(self, *_):
        if self.orbiting:
            return  # no drawing while the right button orbits
        iren = self.GetInteractor()
        self.stroking = True
        mode = mode_for(self.view.doc.tool, bool(iren.GetShiftKey()), bool(iren.GetControlKey()),
                        bool(iren.GetAltKey()))
        self.view.begin_stroke(iren.GetEventPosition(), mode)

    def move(self, *_):
        pos = self.GetInteractor().GetEventPosition()
        if self.stroking:
            self.view.continue_stroke(pos)
            return
        if not self.orbiting:
            self.view.update_hover(pos)
        self.OnMouseMove()

    def left_up(self, *_):
        if self.stroking:
            self.stroking = False
            self.view.end_stroke()

    def right_down(self, *_):
        if self.stroking:
            return  # a right click while drawing does nothing
        self.orbiting = True
        self.view._clear_hover()
        self.OnLeftButtonDown()  # the trackball's rotate, on the right button

    def right_up(self, *_):
        if self.orbiting:
            self.OnLeftButtonUp()
            self.orbiting = False


class EditView(QtWidgets.QWidget):
    def __init__(self, doc):
        super().__init__()
        self.doc = doc
        self.brush = Brush()
        self.plotter = QtInteractor(self)
        self.plotter.set_background((0.16, 0.16, 0.18), top=(0.27, 0.28, 0.32))
        self.plotter.enable_lightkit()
        self.plotter.add_axes()
        try:
            self.plotter.iren.clear_key_event_callbacks()
        except AttributeError:
            pass
        self.style = EditStyle(self)
        self.plotter.iren.interactor.SetInteractorStyle(self.style)
        self.plotter.interactor.installEventFilter(self)
        # PyVista toggles chart interaction on a left double click and, doing so, puts its own
        # camera style back on the interactor: the view still orbits, but clicks no longer draw.
        # There are no charts here.
        self.plotter.iren.untrack_click_position(side="left")
        self.picker = vtkCellPicker()
        self.picker.SetTolerance(0.0005)
        self.picker.PickFromListOn()

        self.edges_box = QtWidgets.QCheckBox("Edges")
        self.edges_box.setChecked(True)
        self.edges_box.setToolTip("Draw each voxel face's border")
        self.edges_box.toggled.connect(self.rebuild)
        self.materials_box = QtWidgets.QCheckBox("Materials")
        self.materials_box.setToolTip("Colour the voxels by material (the key is in the Materials dock); "
                                      "the slices follow")
        self.materials_box.toggled.connect(doc.set_show_materials)
        doc.display_changed.connect(lambda: self.materials_box.setChecked(doc.show_materials))
        frame_button = QtWidgets.QPushButton("Frame")
        frame_button.setToolTip("Fit the model in the view")
        frame_button.clicked.connect(self.frame)
        bar = QtWidgets.QHBoxLayout()
        bar.setContentsMargins(4, 2, 4, 2)
        hint = QtWidgets.QLabel("Left: mode · Shift/Ctrl: the others · Alt: pick · right: orbit · middle: pan")
        hint.setToolTip("Left click or drag: the brush in the current mode · Shift + left and Ctrl + left: the "
                        "other two modes (the Brush dock shows which) · Alt + left: pick colour and material · "
                        "right drag: orbit · middle drag: pan · wheel: zoom · [ and ]: brush size · R: turn the "
                        "stamp · Esc: stop stamping")
        hint.setStyleSheet("color: #999")
        hint.setMinimumWidth(0)
        hint.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored, QtWidgets.QSizePolicy.Policy.Preferred)
        bar.addWidget(hint, 1)
        bar.addWidget(self.materials_box)
        bar.addWidget(self.edges_box)
        bar.addWidget(frame_button)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(bar)
        layout.addWidget(self.plotter.interactor, 1)

        self.faces = None
        self.voxel_actor = None
        self.floor_actor = None
        self.preview_actor = None
        self.stroke_layer = None
        self.last_stroke = None
        self.box_start = None  # (start voxel, normal) while a box is dragged
        self.stroke_mode = None  # the mode of the drag in progress
        self.hover_pos = None
        self._rebuild_timer = QtCore.QTimer(self, singleShot=True, interval=30, timeout=self.rebuild)
        doc.changed.connect(self._rebuild_timer.start)
        doc.display_changed.connect(self.rebuild)
        doc.tables_changed.connect(self.rebuild)  # the material key may have grown
        doc.protection_changed.connect(self._rebuild_timer.start)
        doc.reset.connect(self.on_reset)
        doc.current_changed.connect(self._clear_hover)
        self.brush.changed.connect(self._clear_hover)
        self.on_reset()

    # --- scene ------------------------------------------------------------------------
    def on_reset(self):
        sx, sy, sz = self.doc.size
        self.plotter.remove_actor("floor", render=False)
        self.plotter.remove_actor("bounds", render=False)
        floor = pv.Plane(center=(sx / 2, sy / 2, 0), direction=(0, 0, 1), i_size=sx, j_size=sy,
                         i_resolution=sx, j_resolution=sy)
        self.floor_actor = self.plotter.add_mesh(floor, name="floor", color=(0.45, 0.47, 0.52), opacity=0.18,
                                                 show_edges=True, edge_color=(0.55, 0.57, 0.62), lighting=False,
                                                 reset_camera=False)
        self.plotter.add_mesh(pv.Box((0, sx, 0, sy, 0, sz)).outline(), name="bounds", color=(0.5, 0.5, 0.55),
                              line_width=1, pickable=False, reset_camera=False)
        self.rebuild()
        self.frame()

    def rebuild(self):
        key, lookup = self.doc.display_planes()
        self.faces = voxel_faces(self.doc.model.colour, lookup, key)
        if self.faces is None:
            self.plotter.remove_actor("voxels", render=False)
            self.voxel_actor = None
        else:
            points, quads, colours, voxels, _ = self.faces
            protected = self.doc.protected()
            if protected is not None:  # tinted, so the user sees what the assistant may not change
                x, y, z = voxels.T
                hit = protected[z, y, x]
                colours = colours.copy()
                colours[hit] = (colours[hit] * (1 - PROTECTED_TINT) + PROTECTED_RGB * PROTECTED_TINT).astype(np.uint8)
            mesh = pv.PolyData.from_regular_faces(points, quads)
            mesh.cell_data["rgb"] = colours
            self.voxel_actor = self.plotter.add_mesh(
                mesh, name="voxels", scalars="rgb", rgb=True, show_edges=self.edges_box.isChecked(),
                edge_color=(0.08, 0.08, 0.09), line_width=1, reset_camera=False)
        self.picker.InitializePickList()
        for actor in (self.voxel_actor, self.floor_actor):
            if actor is not None:
                self.picker.AddPickList(actor)
        self.plotter.render()

    def frame(self):
        sx, sy, sz = self.doc.size
        self.plotter.camera_position = [(sx * 0.5 + sz * 1.3, -sz * 1.6, sz * 1.25), (sx / 2, sy / 2, sz / 2), (0, 0, 1)]
        self.plotter.reset_camera()

    # --- picking ----------------------------------------------------------------------
    def _pick(self, pos):
        """(hit voxel or None, attach target or None) under a display position."""
        if not self.picker.Pick(pos[0], pos[1], 0, self.plotter.renderer):
            return None, None
        actor = self.picker.GetActor()
        if actor is self.voxel_actor and self.faces is not None:
            cell = self.picker.GetCellId()
            voxel = self.faces[3][cell]
            return tuple(int(v) for v in voxel), tuple(int(v) for v in voxel + self.faces[4][cell])
        if actor is self.floor_actor:
            x, y, _ = self.picker.GetPickPosition()
            target = (int(np.floor(x)), int(np.floor(y)), 0)
            return None, target if self.doc.inside(*target) else None
        return None, None

    @staticmethod
    def _normal(hit, attach):
        return np.subtract(attach, hit) if hit is not None else np.array([0, 0, 1])

    def mode(self) -> str:
        """What the left button does now: the drag's mode, or the mode with the keys held."""
        if self.stroke_mode is not None:
            return self.stroke_mode
        return held_mode(self.doc.tool, QtWidgets.QApplication.queryKeyboardModifiers())

    def click(self, pos, mode=None):
        """A left click: a drag that does not move."""
        self.begin_stroke(pos, mode)
        self.end_stroke()

    # --- the brush --------------------------------------------------------------------------
    def brush_voxels(self, hit, attach, box_end=None):
        """What the brush would write for this pick in the current mode: (points, colours, materials), only
        voxels it changes, mirrored; None if nothing (qtui.brush.brush_edit, shared with the slices)."""
        tool = self.mode()
        target = attach if tool == "attach" else hit
        shift = bool(QtWidgets.QApplication.queryKeyboardModifiers() & QtCore.Qt.KeyboardModifier.ShiftModifier)
        return brush_edit(self.doc, self.brush, tool, target, self._normal(hit, attach), hit=hit,
                          box_start=self.box_start, box_end=box_end, shift=shift)

    def apply(self, hit, attach, box_end=None) -> int:
        voxels = self.brush_voxels(hit, attach, box_end)
        if voxels is None:
            return 0
        changed = self.doc.apply_brush(voxels, self.mode())
        self.rebuild()  # at once, so the next pick sees the new voxels
        return changed

    def set_stamp(self, name, model, orient=IDENTITY):
        self.brush.set_stamp(name, model, orient)

    # --- strokes ----------------------------------------------------------------------
    def begin_stroke(self, pos, mode=None):
        self.stroke_mode = mode or self.mode()
        self._clear_hover()
        if self.stroke_mode == "pick":
            hit, _ = self._pick(pos)
            if hit:
                self.doc.pick(*hit)
            return
        self.doc.begin_stroke()
        self.stroke_layer = None
        self.last_stroke = None
        if self.brush.kind == "box":
            hit, attach = self._pick(pos)
            target = attach if self.stroke_mode == "attach" else hit
            self.box_start = (target, self._normal(hit, attach)) if target is not None else None
            self.last_stroke = target
            self._show_preview(hit, attach, target)
            return
        self.continue_stroke(pos)

    def continue_stroke(self, pos):
        if self.stroke_mode in (None, "pick"):
            return
        hit, attach = self._pick(pos)
        target = attach if self.stroke_mode == "attach" else hit
        if self.brush.kind == "box":
            if self.box_start is not None and target is not None:
                self.last_stroke = target
                self._show_preview(hit, attach, target)
            return
        if target is None or target == self.last_stroke:
            return
        if self.stroke_mode == "attach":
            # stay in the first target's layer along its face normal, or attach climbs towards the camera
            if self.stroke_layer is None:
                axis = int(np.argmax(np.abs(np.subtract(attach, hit)))) if hit is not None else 2
                self.stroke_layer = (axis, target[axis])
            axis, value = self.stroke_layer
            if target[axis] != value:
                return
        first = self.last_stroke is None
        self.last_stroke = target
        if self.apply(hit, attach) and first:
            self.doc.focus_changed.emit(*target)  # the slices follow the voxel first drawn

    def end_stroke(self):
        if self.stroke_mode in (None, "pick"):
            self.stroke_mode = None
            return
        if self.brush.kind == "box" and self.box_start is not None:
            start = self.box_start[0]
            self.apply(start, start, box_end=self.last_stroke)  # the box brush reads its start and normal
            self.box_start = None
        self.doc.end_stroke()
        self.stroke_layer = None
        self.stroke_mode = None
        self._clear_hover()

    # --- the preview: what a click would change, see-through --------------------------------
    def _clear_hover(self):
        if self.preview_actor is not None:
            self.plotter.remove_actor(self.preview_actor, render=True)
            self.preview_actor = None

    def update_hover(self, pos):
        self.hover_pos = pos
        hit, attach = self._pick(pos)
        target = attach if self.mode() == "attach" else hit
        self._show_preview(hit, attach, target)

    def _show_preview(self, hit, attach, target):
        mode = self.mode()
        if target is None or mode == "pick":
            self._clear_hover()
            self.doc.hover_changed.emit("" if target is None else f"3D pick: {self.doc.describe(*target)}")
            return
        voxels = self.brush_voxels(hit, attach, target if self.box_start is not None else None)
        self._clear_hover()
        if voxels is None:
            self.doc.hover_changed.emit(f"3D {mode}: {self.doc.describe(*target)} (nothing to change)")
            return
        points, colours, _ = voxels
        lo = points.min(axis=0)
        sx, sy, sz = points.max(axis=0) - lo + 1
        grid = np.zeros((sz, sy, sx), dtype=np.uint8)
        x, y, z = (points - lo).T
        stamp = self.brush.kind == "stamp" and mode not in ("erase", *PROTECT_MODES)
        grid[z, y, x] = colours if stamp else 1
        rgb = self.doc.rgb if stamp else np.array([[0, 0, 0]] + [np.multiply(HOVER_COLOUR[mode], 255)] * 255,
                                                  dtype=np.uint8)
        faces = voxel_faces(grid, rgb)
        if faces is None:
            return
        mesh_points, quads, face_rgb, _, _ = faces
        mesh = pv.PolyData.from_regular_faces(mesh_points + lo, quads)
        mesh.cell_data["rgb"] = face_rgb
        self.preview_actor = self.plotter.add_mesh(
            mesh, scalars="rgb", rgb=True, opacity=PREVIEW_OPACITY, show_edges=True,
            edge_color=HOVER_COLOUR[mode], line_width=1, pickable=False, reset_camera=False, render=True)
        what = self.brush.stamp[0] if self.brush.kind == "stamp" and self.brush.stamp else self.brush.kind
        self.doc.hover_changed.emit(f"3D {mode} ({what}): {self.doc.describe(*target)} · "
                                    f"{len(points)} voxels")

    # --- keys -------------------------------------------------------------------------------
    def eventFilter(self, obj, event):
        if event.type() == QtCore.QEvent.Type.MouseButtonRelease:
            button = event.button()  # after the widget has passed it on to VTK, make sure it arrived
            QtCore.QTimer.singleShot(0, lambda: self.style.released(button))
            return False
        if event.type() in (QtCore.QEvent.Type.KeyPress, QtCore.QEvent.Type.KeyRelease) and event.key() in (
                QtCore.Qt.Key.Key_Shift, QtCore.Qt.Key.Key_Control, QtCore.Qt.Key.Key_Alt):
            if self.hover_pos is not None and self.stroke_mode is None:
                QtCore.QTimer.singleShot(0, lambda: self.update_hover(self.hover_pos))  # the preview follows the keys
            return False
        if event.type() == QtCore.QEvent.Type.KeyPress:
            key, shift = event.key(), bool(event.modifiers() & QtCore.Qt.KeyboardModifier.ShiftModifier)
            if key == QtCore.Qt.Key.Key_BracketLeft:
                self.brush.set(size=self.brush.size - 1)
                return True
            if key == QtCore.Qt.Key.Key_BracketRight:
                self.brush.set(size=self.brush.size + 1)
                return True
            if self.brush.kind == "stamp" and key == QtCore.Qt.Key.Key_R:
                self.brush.turn_stamp(-1 if shift else 1)
                return True
            if self.brush.kind == "stamp" and key == QtCore.Qt.Key.Key_Escape:
                self.brush.set(kind="voxel")
                return True
        return super().eventFilter(obj, event)

    def close(self):
        self.plotter.close()
        return super().close()
