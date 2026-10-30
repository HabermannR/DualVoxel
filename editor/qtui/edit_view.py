"""The 3D edit view: the model as flat-coloured cubes in VTK, edited by picking faces.

This view is for editing, not for judging looks; the render dock shows the model
in the path tracer.

The mouse, as in MagicaVoxel: a left click or drag applies the brush (qtui/brush.py,
set in the Brush dock) in the current mode; Shift + left and Ctrl + left use the
other two modes (brush.mode_for), Alt + left picks. Right drag orbits, middle
drag or Shift + right drag pans (for trackpads), the wheel zooms (Alt + Shift + wheel: the brush size). Attach adds voxels against the clicked face (or on the floor) and only
fills empty ones, paint recolours solid voxels, erase removes them, pick takes a
voxel's colour and material, protect marks voxels the assistant may not change
(tinted violet; Shift lifts it). Brushes: voxel (size, square or circle, flat or a
volume), face (the clicked face's connected flat area), box (drag a
rectangle in one layer), line (drag between two voxels), fill (a connected area), stamp (a project's model; R turns it, Esc stops), each
mirrored across the model's centre if asked. A see-through preview, in the
colour of the mode the keys held give, shows what a click would change. A drag
applies the brush along it (attach stays in the first voxel's layer, so it does
not climb towards the camera; the box brush draws a rectangle); each click or
drag is one undo step. [ and ] change the size. The arrow keys shift the whole
model inside its box as seen (Up: away), Page Up / Page Down up and down, Shift
for BIG_STEP voxels, wrapping round as the Model dock's Wrap says.

The model is meshed in chunks of CHUNK voxels a side, one actor each (as vengi does): an edit remeshes
only the chunks its voxels touch, found by comparing the planes with those last shown, so a stroke on a
256-a-side model stays quick. Colours or materials shown differently remesh every chunk.
"""
from __future__ import annotations

import numpy as np
import pyvista as pv
from PySide6 import QtCore, QtGui, QtWidgets
from pyvistaqt import QtInteractor
from vtkmodules.vtkCommonDataModel import vtkStaticCellLocator
from vtkmodules.vtkInteractionStyle import vtkInteractorStyleTrackballCamera
from vtkmodules.vtkRenderingCore import vtkActor, vtkCellPicker, vtkPolyDataMapper

from core.brushes import mirror_sum
from core.scene import IDENTITY
from qtui import keymap
from qtui.brush import DRAGGED, SCULPT, SWAPPED_SCULPT, Brush, Stroke, brush_edit, held_mode, mode_for, size_step
from qtui.document import PROTECT_MODES
from qtui.view_cut import CutPanel, kept

HOVER_COLOUR = {"attach": (0.3, 1.0, 0.4), "paint": (1.0, 0.85, 0.1), "erase": (1.0, 0.3, 0.3),
                "pick": (0.4, 0.8, 1.0), "protect": (0.75, 0.45, 1.0), "unprotect": (0.6, 0.6, 0.65),
                # the sculpting brushes, which ignore the mode: grow adds as attach, erode takes off as erase
                "grow": (0.3, 1.0, 0.4), "erode": (1.0, 0.3, 0.3), "smooth": (0.92, 0.92, 1.0),
                "smear": (1.0, 0.6, 0.2)}
PROTECTED_RGB = np.array([150, 80, 255], dtype=np.float32)  # protected voxels lean towards this
PROTECTED_TINT = 0.45
CLICK_SLOP = 4  # pixels a press may move and still count as a click
PREVIEW_OPACITY = 0.4
PREVIEW_LIMIT = 200_000  # voxels a preview shows one by one; more (a big fill) show as their box's outline
CHUNK = 32  # the model is meshed in blocks this many voxels a side; an edit remeshes the blocks it touches
EDGE_RGB = (0.08, 0.08, 0.09)
AXIS_RGB = ((0.95, 0.3, 0.3), (0.35, 0.85, 0.35), (0.35, 0.55, 1.0))  # x, y, z, as the axes in the corner
MIRROR_OPACITY = 0.12
BACKGROUNDS = {"Dark": ((0.16, 0.16, 0.18), (0.27, 0.28, 0.32)),  # (bottom, top of the gradient; None: flat)
               "Light": ((0.80, 0.81, 0.84), (0.96, 0.96, 0.97)),
               "White": ((1.0, 1.0, 1.0), None)}
BIG_STEP = 8  # voxels an arrow key moves with Shift
Key = QtCore.Qt.Key
VIEW_MOVES = {Key.Key_Up: (0, 1), Key.Key_Down: (0, -1), Key.Key_Right: (1, 0), Key.Key_Left: (-1, 0)}
# The view snaps: (direction from the model's centre to the eye, the view's up), as the slices see it: the
# front from -y, the right side from +x, the top from +z. The isometric views look from the front right, 2:1
# (pixel art's "isometric", 30 degrees up) or true (35.264 degrees, every axis equally short).
_ISO = lambda up: (np.cos(np.radians(up)) / np.sqrt(2), -np.cos(np.radians(up)) / np.sqrt(2), np.sin(np.radians(up)))
VIEWS = {"front": ((0, -1, 0), (0, 0, 1)), "back": ((0, 1, 0), (0, 0, 1)),
         "right": ((1, 0, 0), (0, 0, 1)), "left": ((-1, 0, 0), (0, 0, 1)),
         "top": ((0, 0, 1), (0, 1, 0)), "bottom": ((0, 0, -1), (0, -1, 0)),
         "iso 2:1": (_ISO(30), (0, 0, 1)), "iso": (_ISO(np.degrees(np.arctan(1 / np.sqrt(2)))), (0, 0, 1))}
VIEW_ACTIONS = {"view_front": "front", "view_back": "back", "view_right": "right", "view_left": "left",
                "view_top": "top", "view_bottom": "bottom", "view_iso_pixel": "iso 2:1", "view_iso": "iso"}  # keymap
STROKE_STEP = 3  # pixels between the picks filling in a fast 3D stroke's gaps


def view_axes(camera):
    """The axes (index, sign) nearest to the view's right and its forward along the floor."""
    forward = np.subtract(camera.focal_point, camera.position)[:2]
    if not np.any(forward):
        forward = np.array(camera.up)[:2]
    right = np.array([forward[1], -forward[0]])
    pick = lambda v: (int(np.argmax(np.abs(v))), int(np.sign(v[np.argmax(np.abs(v))])) or 1)
    return pick(right), pick(forward)


def view_delta(camera, key, step: int = 1):
    """(dx, dy, dz) an arrow key (as seen: Up away) or Page Up / Page Down means, or None for other keys."""
    delta = [0, 0, 0]
    if key in VIEW_MOVES:
        (r_axis, r_sign), (f_axis, f_sign) = view_axes(camera)
        across, ahead = VIEW_MOVES[key]
        delta[r_axis] += across * r_sign * step
        delta[f_axis] += ahead * f_sign * step
    elif key in (Key.Key_PageUp, Key.Key_PageDown):
        delta[2] = step if key == Key.Key_PageUp else -step
    else:
        return None
    return delta


def voxel_faces(colour_zyx: np.ndarray, rgb: np.ndarray, key_zyx: np.ndarray | None = None,
                lo=(0, 0, 0), hi=None):
    """The model's exposed faces as quads: points, quads, each face's colour, voxel and outward normal.
    Faces take rgb[key] (the colour plane by default, e.g. the material plane to show materials).
    Only the voxels in the box lo..hi (x, y, z, hi exclusive; the whole model by default), facing the
    voxels around the box too, so a chunk shows no faces between it and its neighbours."""
    key_zyx = colour_zyx if key_zyx is None else key_zyx
    size = colour_zyx.shape[::-1]
    hi = size if hi is None else hi
    # the box and a layer of voxels around it, empty outside the model
    near_lo = [max(l - 1, 0) for l in lo]
    near_hi = [min(h + 1, s) for h, s in zip(hi, size)]
    near = colour_zyx[near_lo[2]:near_hi[2], near_lo[1]:near_hi[1], near_lo[0]:near_hi[0]].transpose(2, 1, 0) > 0
    padded = np.zeros([h - l + 2 for l, h in zip(lo, hi)], dtype=bool)
    at = [n - l + 1 for n, l in zip(near_lo, lo)]
    padded[at[0]:at[0] + near.shape[0], at[1]:at[1] + near.shape[1], at[2]:at[2] + near.shape[2]] = near
    solid = padded[1:-1, 1:-1, 1:-1]  # (x, y, z)
    if not solid.any():
        return None
    points, quads, colours, voxels, normals = [], [], [], [], []
    count = 0
    for axis in range(3):
        b, c = (axis + 1) % 3, (axis + 2) % 3
        eb, ec = np.eye(3, dtype=int)[b], np.eye(3, dtype=int)[c]
        for sign in (1, -1):
            shift = [0, 0, 0]
            shift[axis] = sign
            beside = [slice(1, -1)] * 3
            beside[axis] = slice(1 + sign, padded.shape[axis] - 1 + sign)
            idx = np.argwhere(solid & ~padded[tuple(beside)]) + lo
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


def touched_chunks(changed_zyx: np.ndarray, chunk: int = CHUNK) -> set[tuple[int, int, int]]:
    """The chunks (x, y, z of each) whose faces a change can alter: those holding a changed voxel (a bool
    plane, z y x) or one next to it. Each chunk looks one voxel past its sides, one axis at a time."""
    near = changed_zyx
    for axis in range(3):
        a = np.moveaxis(near, axis, 0)
        whole = a.shape[0] // chunk * chunk  # (logical_or.reduceat is far slower than any on a reshape)
        out = a[:whole].reshape(-1, chunk, *a.shape[1:]).any(axis=1)
        if whole < a.shape[0]:
            out = np.concatenate([out, a[whole:].any(axis=0, keepdims=True)])
        starts = np.arange(0, a.shape[0], chunk)
        out[1:] |= a[starts[1:] - 1]  # the layer just before each chunk
        out[:-1] |= a[starts[1:]]  # the layer just after
        near = np.moveaxis(out, 0, axis)
    z, y, x = np.nonzero(near)
    return set(zip(x.tolist(), y.tolist(), z.tolist()))


class EditStyle(vtkInteractorStyleTrackballCamera):
    """MagicaVoxel's mouse: left draws (the mode; Shift, Ctrl and Alt pick another), right drag orbits, middle
    drag pans, the wheel zooms. Right drag is the trackball's left button, which pans when Shift is down,
    so Shift + right drag pans too (a trackpad has no middle button).

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
        # Alt from Qt: VTK's Qt widget passes Shift and Ctrl to VTK but never Alt, so Alt + left drew
        alt = bool(QtWidgets.QApplication.queryKeyboardModifiers() & QtCore.Qt.KeyboardModifier.AltModifier)
        mode = mode_for(self.view.doc.tool, bool(iren.GetShiftKey()), bool(iren.GetControlKey()), alt)
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
    background_changed = QtCore.Signal(str)

    def __init__(self, doc):
        super().__init__()
        self.doc = doc
        self.brush = Brush()
        self.plotter = QtInteractor(self)
        self.background = "Dark"
        self.plotter.set_background(BACKGROUNDS["Dark"][0], top=BACKGROUNDS["Dark"][1])
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
        self.edges_box.toggled.connect(self._show_edges)
        self.materials_box = QtWidgets.QCheckBox("Materials")
        self.materials_box.setToolTip("Colour the voxels by material (the key is in the Materials dock); "
                                      "the slices follow")
        self.materials_box.toggled.connect(doc.set_show_materials)
        doc.display_changed.connect(lambda: self.materials_box.setChecked(doc.show_materials))
        frame_button = QtWidgets.QPushButton("Frame")
        frame_button.setToolTip("Fit the model in the view")
        frame_button.clicked.connect(self.frame)
        self.ortho_box = QtWidgets.QCheckBox("Ortho")
        self.ortho_box.setToolTip("Orthographic: no perspective, so parallel edges stay parallel and voxels the "
                                  f"same size at any depth ({keymap.text('ortho')} with the view focused)")
        self.ortho_box.toggled.connect(self.set_ortho)
        views_button = QtWidgets.QToolButton(text="View")
        views_button.setToolTip("Look along an axis, or isometric (the keys in the menu work with the view "
                                "focused)")
        views_button.setPopupMode(QtWidgets.QToolButton.ToolButtonPopupMode.InstantPopup)
        views_menu = QtWidgets.QMenu(views_button)
        for action, name in VIEW_ACTIONS.items():
            text = {"iso 2:1": "Isometric 2:1 (pixel art)", "iso": "True isometric"}.get(name, name.capitalize())
            views_menu.addAction(f"{text}\t{keymap.text(action)}", lambda n=name: self.snap_view(n))
        views_button.setMenu(views_menu)
        background_button = QtWidgets.QToolButton(text="Background")
        background_button.setToolTip("The view's background: dark, light (for screenshots and prints) or white")
        background_button.setPopupMode(QtWidgets.QToolButton.ToolButtonPopupMode.InstantPopup)
        background_menu = QtWidgets.QMenu(background_button)
        self.background_actions = QtGui.QActionGroup(background_menu)
        for name in BACKGROUNDS:
            action = background_menu.addAction(name, lambda n=name: self.set_background(n))
            action.setCheckable(True)
            action.setChecked(name == self.background)
            self.background_actions.addAction(action)
        background_button.setMenu(background_menu)
        self.cut_box = QtWidgets.QCheckBox("Cut")
        self.cut_box.setToolTip("Cut the model open, as in the FEM view cut: planes that each keep the voxels on one "
                                "side; what they lay bare shows (and paints) as the section. Only this view; the "
                                "model is unchanged")
        self.cut_panel = CutPanel(self)
        self.cut_panel.hide()
        self.cut_panel.changed.connect(self._cut_changed)
        self.cut_box.toggled.connect(self._cut_toggled)
        bar = QtWidgets.QHBoxLayout()
        bar.setContentsMargins(4, 2, 4, 2)
        hint = QtWidgets.QLabel("Left: mode · Shift/Ctrl: the others · Alt: pick · right: orbit · "
                                "middle or Shift + right: pan")
        hint.setToolTip("Left click or drag: the brush in the current mode · Shift + left and Ctrl + left: the "
                        "other two modes (the Brush dock shows which) · Alt + left: pick colour and material · "
                        "right drag: orbit · middle drag or Shift + right drag: pan · wheel: zoom · [ and ], Alt + Shift + wheel: brush size · R: turn the "
                        "stamp · Esc: stop stamping · arrows, Page Up / Down: shift the model in its box as seen "
                        f"(Shift: {BIG_STEP} voxels)")
        hint.setStyleSheet("color: #999")
        hint.setMinimumWidth(0)
        hint.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored, QtWidgets.QSizePolicy.Policy.Preferred)
        bar.addWidget(hint, 1)
        bar.addWidget(self.materials_box)
        bar.addWidget(self.edges_box)
        bar.addWidget(self.ortho_box)
        bar.addWidget(self.cut_box)
        bar.addWidget(background_button)
        bar.addWidget(views_button)
        bar.addWidget(frame_button)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(bar)
        layout.addWidget(self.cut_panel)
        layout.addWidget(self.plotter.interactor, 1)

        self.chunks: dict[tuple[int, int, int], tuple] = {}  # (x, y, z) of a chunk -> (actor, faces, mesh, locator)
        self._chunk_of = {}  # actor -> its chunk, for picking
        self._shown = None  # the planes as the chunks show them: (colour, key or None, protected or None)
        self.floor_actor = None
        self.preview_actor = None
        self.stroke_layer = None
        self.last_stroke = None
        self.box_start = None  # (start voxel, normal) while a box is dragged
        self.stroke_mode = None  # the mode of the drag in progress
        self.stroke = None  # its brush.Stroke (what a smear carries)
        self.last_pos = None  # where its last mouse event was, to fill in the gaps of a fast drag
        self.hover_pos = None
        self._rebuild_timer = QtCore.QTimer(self, singleShot=True, interval=30, timeout=self.refresh)
        doc.changed.connect(self._rebuild_timer.start)
        doc.display_changed.connect(self.rebuild)
        doc.tables_changed.connect(self.rebuild)  # the material key may have grown
        doc.protection_changed.connect(self._rebuild_timer.start)
        doc.reset.connect(self.on_reset)
        doc.resized.connect(lambda: self.on_reset(frame=False))  # the camera stays
        doc.current_changed.connect(self._clear_hover)
        self.brush.changed.connect(self._clear_hover)
        self.brush.changed.connect(self.draw_mirror_planes)
        self.on_reset()

    # --- scene ------------------------------------------------------------------------
    def on_reset(self, frame: bool = True):
        sx, sy, sz = self.doc.size
        self.plotter.remove_actor("floor", render=False)
        self.plotter.remove_actor("bounds", render=False)
        floor = pv.Plane(center=(sx / 2, sy / 2, 0), direction=(0, 0, 1), i_size=sx, j_size=sy,
                         i_resolution=sx, j_resolution=sy)
        self.floor_actor = self.plotter.add_mesh(floor, name="floor", color=(0.45, 0.47, 0.52), opacity=0.18,
                                                 show_edges=True, edge_color=(0.55, 0.57, 0.62), lighting=False,
                                                 reset_camera=False)
        floor_cells = vtkStaticCellLocator()  # a cell for each floor voxel, which the picker would try one by one
        floor_cells.SetDataSet(self.floor_actor.GetMapper().GetInput())
        floor_cells.BuildLocator()
        self.picker.RemoveAllLocators()
        self.picker.AddLocator(floor_cells)
        self.plotter.add_mesh(pv.Box((0, sx, 0, sy, 0, sz)).outline(), name="bounds", color=(0.5, 0.5, 0.55),
                              line_width=1, pickable=False, reset_camera=False)
        self.cut_panel.blockSignals(True)  # the rebuild below shows the cuts pulled into the new size
        self.cut_panel.set_size(self.doc.size)
        self.cut_panel.blockSignals(False)
        self.draw_cuts(render=False)
        for actor in list(self._chunk_of):
            self.plotter.renderer.RemoveActor(actor)
        self.chunks.clear()
        self._chunk_of.clear()
        self._shown = None
        self.draw_mirror_planes(render=False)
        self.rebuild()
        if frame:
            self.frame()

    def draw_mirror_planes(self, render: bool = True):
        """Each mirror that is on as a see-through plane across the box, in its axis's colour."""
        size = self.doc.size
        for a in range(3):
            name = f"mirror {'xyz'[a]}"
            at = mirror_sum(size, self.brush.mirror_plane, a) / 2 + 0.5  # voxel p spans p..p + 1
            if not self.brush.mirror[a] or not 0 <= at <= size[a]:
                self.plotter.remove_actor(name, render=False)
                continue
            b, c = (a + 1) % 3, (a + 2) % 3
            corners = np.zeros((4, 3))
            corners[:, a] = at
            corners[:, b] = (0, size[b], size[b], 0)
            corners[:, c] = (0, 0, size[c], size[c])
            self.plotter.add_mesh(pv.PolyData.from_regular_faces(corners, [[0, 1, 2, 3]]), name=name,
                                  color=AXIS_RGB[a], opacity=MIRROR_OPACITY, show_edges=True,
                                  edge_color=AXIS_RGB[a], lighting=False, pickable=False, reset_camera=False,
                                  render=False)
        if render:
            self.plotter.render()

    # --- the cut ---------------------------------------------------------------------------
    def cuts(self):
        """The cuts in force: the panel's, while Cut is on."""
        return self.cut_panel.cuts if self.cut_box.isChecked() else []

    def _cut_toggled(self, on: bool):
        self.cut_panel.setVisible(on)
        if on and not self.cut_panel.cuts:  # a first cut to start from: the top half off
            self.cut_panel.add()  # emits changed, which redraws
        else:
            self._cut_changed()

    def _cut_changed(self):
        self.draw_cuts(render=False)
        self.rebuild()

    def draw_cuts(self, render: bool = True):
        """Each cut in force as an outline across the box, in its axis's colour."""
        size = self.doc.size
        for name in [n for n in self.plotter.actors if str(n).startswith("cut ")]:
            self.plotter.remove_actor(name, render=False)
        for i, cut in enumerate(self.cuts()):
            a = cut.axis
            b, c = (a + 1) % 3, (a + 2) % 3
            corners = np.zeros((4, 3))
            corners[:, a] = cut.at
            corners[:, b] = (0, size[b], size[b], 0)
            corners[:, c] = (0, 0, size[c], size[c])
            self.plotter.add_mesh(pv.PolyData.from_regular_faces(corners, [[0, 1, 2, 3]]).extract_all_edges(),
                                  name=f"cut {i}", color=AXIS_RGB[a], line_width=2, pickable=False,
                                  reset_camera=False, render=False)
        if render:
            self.plotter.render()

    # --- the voxels, in chunks ----------------------------------------------------------
    def rebuild(self):
        """Mesh every chunk again (colours or materials shown differently, another model)."""
        counts = [-(-n // CHUNK) for n in self.doc.size]
        every = {(x, y, z) for x in range(counts[0]) for y in range(counts[1]) for z in range(counts[2])}
        self._remesh(every | set(self.chunks))
        self._keep_shown()
        self.plotter.render()

    def refresh(self, points=None):
        """After an edit: remesh the chunks whose voxels changed since they were shown, or those the
        voxels at (x, y, z) points touch, when the edit says which it wrote."""
        if not self._shown_fits():
            self.rebuild()
            return
        chunks = touched_chunks(self._changed()) if points is None else self._chunks_near(points)
        if chunks:
            self._remesh(chunks)
            self._keep_shown(chunks)
            self.plotter.render()

    def _chunks_near(self, points) -> set[tuple[int, int, int]]:
        """touched_chunks for voxels at (x, y, z) points, on a grid around them only."""
        size = np.array(self.doc.size)
        points = np.asarray(points)
        points = points[((points >= 0) & (points < size)).all(axis=1)]
        if not len(points):
            return set()
        start = np.maximum(points.min(axis=0) - 1, 0) // CHUNK * CHUNK  # a chunk's corner, and a voxel to spare
        grid = np.zeros((np.minimum(points.max(axis=0) + 2, size) - start)[::-1], dtype=bool)
        x, y, z = (points - start).T
        grid[z, y, x] = True
        first = start // CHUNK
        return {(x + first[0], y + first[1], z + first[2]) for x, y, z in touched_chunks(grid)}

    def _planes(self):
        """(colour, key plane or None when it is the colour plane, key -> sRGB, protected or None); the colour
        plane emptied where a cut takes the voxels away, so what it lays bare is meshed as the section."""
        key, lookup = self.doc.display_planes()
        colour = self.doc.model.colour
        same = key is colour
        keep = kept(colour.shape, self.cuts())
        if keep is not None:
            colour = np.where(keep, colour, 0).astype(colour.dtype)
        return colour, None if same else key, lookup, self.doc.protected()

    def _shown_fits(self) -> bool:
        if self._shown is None:
            return False
        colour, key, _, _ = self._planes()
        return self._shown[0].shape == colour.shape and (key is None) == (self._shown[1] is None)

    def _changed(self) -> np.ndarray:
        """Voxels (bool plane, z y x) shown otherwise than they are now."""
        colour, key, _, protected = self._planes()
        shown_colour, shown_key, shown_protected = self._shown
        changed = colour != shown_colour
        if key is not None:
            changed |= key != shown_key
        if protected is not None and shown_protected is not None:
            changed |= protected != shown_protected
        elif protected is not None or shown_protected is not None:
            changed |= shown_protected if protected is None else protected
        return changed

    def _keep_shown(self, chunks=None):
        """Remember the planes as shown: all of them, or in these chunks."""
        colour, key, _, protected = self._planes()
        if chunks is None:
            self._shown = (colour.copy(), None if key is None else key.copy(),
                           None if protected is None else protected.copy())
            return
        shown_colour, shown_key, shown_protected = self._shown
        if protected is not None and shown_protected is None:
            shown_protected = np.zeros_like(protected)
            self._shown = shown_colour, shown_key, shown_protected
        for chunk in chunks:
            x, y, z = (slice(c * CHUNK, (c + 1) * CHUNK) for c in chunk)
            shown_colour[z, y, x] = colour[z, y, x]
            if key is not None:
                shown_key[z, y, x] = key[z, y, x]
            if shown_protected is not None:
                shown_protected[z, y, x] = False if protected is None else protected[z, y, x]

    def _remesh(self, chunks):
        """Mesh these chunks (x, y, z of each) from the planes now: a chunk without faces loses its actor."""
        colour, key, lookup, protected = self._planes()
        size = self.doc.size
        for chunk in chunks:
            lo = np.multiply(chunk, CHUNK)
            faces = voxel_faces(colour, lookup, key, lo, np.minimum(lo + CHUNK, size)) \
                if (lo < size).all() else None
            old = self.chunks.pop(chunk, None)
            if old is not None:
                self.picker.RemoveLocator(old[3])
            if faces is None:
                if old is not None:
                    self.plotter.renderer.RemoveActor(old[0])
                    del self._chunk_of[old[0]]
                continue
            points, quads, colours, voxels, _ = faces
            if protected is not None:  # tinted, so the user sees what the assistant may not change
                x, y, z = voxels.T
                hit = protected[z, y, x]
                if hit.any():
                    colours = colours.copy()
                    colours[hit] = (colours[hit] * (1 - PROTECTED_TINT) + PROTECTED_RGB * PROTECTED_TINT).astype(
                        np.uint8)
            mesh = pv.PolyData.from_regular_faces(points, quads)
            mesh.cell_data.set_scalars(colours, "rgb")
            actor = old[0] if old is not None else self._chunk_actor(chunk)
            actor.GetMapper().SetInputData(mesh)
            cells = vtkStaticCellLocator()  # the picker finds the face under the mouse without trying them all
            cells.SetDataSet(mesh)
            cells.BuildLocator()
            self.picker.AddLocator(cells)
            self.chunks[chunk] = (actor, faces, mesh, cells)
        self.picker.InitializePickList()
        for actor in (*self._chunk_of, self.floor_actor):
            if actor is not None:
                self.picker.AddPickList(actor)

    def _chunk_actor(self, chunk):
        mapper = vtkPolyDataMapper()
        mapper.SetScalarModeToUseCellData()
        mapper.SetColorModeToDirectScalars()
        actor = vtkActor()
        actor.SetMapper(mapper)
        prop = actor.GetProperty()
        prop.SetEdgeColor(*EDGE_RGB)
        prop.SetLineWidth(1)
        prop.SetEdgeVisibility(self.edges_box.isChecked())
        self.plotter.renderer.AddActor(actor)
        self._chunk_of[actor] = chunk
        return actor

    def _show_edges(self, on: bool):
        for actor in self._chunk_of:
            actor.GetProperty().SetEdgeVisibility(on)
        self.plotter.render()

    def frame(self):
        sx, sy, sz = self.doc.size
        self.plotter.camera_position = [(sx * 0.5 + sz * 1.3, -sz * 1.6, sz * 1.25), (sx / 2, sy / 2, sz / 2), (0, 0, 1)]
        self.plotter.reset_camera()  # in ortho, its scale fits the model too

    def set_background(self, name: str):
        """BACKGROUNDS' name: a gradient or a flat colour behind the model; unknown names (an old setting) are
        ignored."""
        if name not in BACKGROUNDS:
            return
        bottom, top = BACKGROUNDS[name]
        self.plotter.set_background(bottom, top=top)
        self.background = name
        for action in self.background_actions.actions():
            action.setChecked(action.text() == name)
        self.plotter.render()
        self.background_changed.emit(name)

    def set_ortho(self, on: bool):
        """Orthographic or perspective; the model keeps its size on screen. The wheel then zooms by scale."""
        camera = self.plotter.renderer.GetActiveCamera()
        on = bool(on)
        if self.ortho_box.isChecked() != on:
            self.ortho_box.setChecked(on)  # toggles back here
            return
        if bool(camera.GetParallelProjection()) == on:
            return
        if on:  # the height seen at the focal point, so nothing jumps
            camera.SetParallelScale(camera.GetDistance() * np.tan(np.radians(camera.GetViewAngle()) / 2))
        camera.SetParallelProjection(on)
        self.plotter.renderer.ResetCameraClippingRange()
        self.plotter.render()

    def snap_view(self, name: str):
        """Look at the model from one of VIEWS, framed."""
        direction, up = VIEWS[name]
        sx, sy, sz = self.doc.size
        centre = np.array([sx, sy, sz]) / 2
        self.plotter.camera_position = [tuple(centre + np.multiply(direction, max(sx, sy, sz) * 3)), tuple(centre),
                                        up]
        self.plotter.reset_camera()
        self._clear_hover()

    # --- picking ----------------------------------------------------------------------
    def _pick(self, pos):
        """(hit voxel or None, attach target or None) under a display position."""
        if not self.picker.Pick(pos[0], pos[1], 0, self.plotter.renderer):
            return None, None
        actor = self.picker.GetActor()
        chunk = self._chunk_of.get(actor)
        if chunk is not None:
            _, _, _, voxels, normals = self.chunks[chunk][1]
            cell = self.picker.GetCellId()
            return tuple(int(v) for v in voxels[cell]), tuple(int(v) for v in voxels[cell] + normals[cell])
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
    def brush_voxels(self, hit, attach, box_end=None, stroke=None):
        """What the brush would write for this pick in the current mode: (points, colours, materials), only
        voxels it changes, mirrored; None if nothing (qtui.brush.brush_edit, shared with the slices)."""
        tool = self.mode()
        target = attach if tool == "attach" else hit
        shift = bool(QtWidgets.QApplication.queryKeyboardModifiers() & QtCore.Qt.KeyboardModifier.ShiftModifier)
        return brush_edit(self.doc, self.brush, tool, target, self._normal(hit, attach), hit=hit,
                          box_start=self.box_start, box_end=box_end, shift=shift, stroke=stroke)

    def apply(self, hit, attach, box_end=None) -> int:
        """Write the brush here: how many voxels changed."""
        return self._write(hit, attach, box_end)[1]

    def _write(self, hit, attach, box_end=None, refresh: bool = True):
        """Write the brush here: (the points it wrote or None, how many changed). refresh: remesh them at once
        (so the next pick sees them), else the caller does."""
        voxels = self.brush_voxels(hit, attach, box_end, self.stroke)
        if voxels is None:
            return None, 0
        changed = self.doc.apply_brush(voxels, self.mode())
        if not changed:
            return None, 0
        if refresh:  # only the chunks the brush touched
            self.refresh(voxels[0])
        return voxels[0], changed

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
        self.stroke = Stroke()
        self.stroke_layer = None
        self.last_stroke = None
        self.last_pos = None
        if self.brush.kind in DRAGGED:
            hit, attach = self._pick(pos)
            target = attach if self.stroke_mode == "attach" else hit
            self.box_start = (target, self._normal(hit, attach)) if target is not None else None
            self.last_stroke = target
            self._show_preview(hit, attach, target)
            return
        self.continue_stroke(pos)

    def continue_stroke(self, pos):
        """The mouse moved while drawing: the brush at every voxel it passed over, not only where the mouse
        events came (a fast drag would leave gaps): picks every STROKE_STEP pixels between them."""
        if self.stroke_mode in (None, "pick"):
            return
        last, self.last_pos = self.last_pos, tuple(pos)
        if self.brush.kind in DRAGGED or last is None:
            self._stroke_at(pos)
            return
        steps = max(1, int(np.hypot(pos[0] - last[0], pos[1] - last[1]) // STROKE_STEP))
        touched = []
        for t in range(1, steps + 1):
            at = (round(last[0] + (pos[0] - last[0]) * t / steps), round(last[1] + (pos[1] - last[1]) * t / steps))
            touched += self._stroke_at(at, refresh=False)
        if touched:  # once for the whole run: only the chunks it touched
            self.refresh(np.concatenate(touched))

    def _stroke_at(self, pos, refresh: bool = True) -> list:
        """The brush where the stroke is now; the voxels written, as a list of point arrays."""
        hit, attach = self._pick(pos)
        target = attach if self.stroke_mode == "attach" else hit
        if self.brush.kind in DRAGGED:
            if self.box_start is not None and target is not None:
                self.last_stroke = target
                self._show_preview(hit, attach, target)
            return []
        if target is None or target == self.last_stroke:
            return []
        if self.stroke_mode == "attach":
            # stay in the first target's layer along its face normal, or attach climbs towards the camera
            if self.stroke_layer is None:
                axis = int(np.argmax(np.abs(np.subtract(attach, hit)))) if hit is not None else 2
                self.stroke_layer = (axis, target[axis])
            axis, value = self.stroke_layer
            if target[axis] != value:
                return []
        first = self.last_stroke is None
        self.last_stroke = target
        written, _ = self._write(hit, attach, refresh=refresh)
        if written is not None and first:
            self.doc.focus_changed.emit(*target)  # the slices follow the voxel first drawn
        return [] if written is None else [written]

    def end_stroke(self):
        if self.stroke_mode in (None, "pick"):
            self.stroke_mode = None
            return
        if self.brush.kind in DRAGGED and self.box_start is not None:
            start = self.box_start[0]
            self.apply(start, start, box_end=self.last_stroke)  # the box brush reads its start and normal
            self.box_start = None
        self.doc.end_stroke()
        self.stroke = None
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
        what = self.brush.stamp[0] if self.brush.kind == "stamp" and self.brush.stamp else self.brush.kind
        if len(points) > PREVIEW_LIMIT:  # a fill of a whole model: its box's outline, not every voxel's faces
            hi = points.max(axis=0) + 1
            self.preview_actor = self.plotter.add_mesh(
                pv.Box((lo[0], hi[0], lo[1], hi[1], lo[2], hi[2])).outline(), color=HOVER_COLOUR[mode],
                line_width=2, pickable=False, reset_camera=False, render=True)
            self.doc.hover_changed.emit(f"3D {mode} ({what}): {self.doc.describe(*target)} · "
                                        f"{len(points)} voxels (outlined)")
            return
        sx, sy, sz = points.max(axis=0) - lo + 1
        grid = np.zeros((sz, sy, sx), dtype=np.uint8)
        x, y, z = (points - lo).T
        stamp = self.brush.kind == "stamp" and mode not in ("erase", *PROTECT_MODES)
        grid[z, y, x] = colours if stamp else 1
        shown = mode
        if self.brush.kind in SCULPT and mode not in PROTECT_MODES:  # what the sculpting brush does, Shift held
            shift = QtWidgets.QApplication.queryKeyboardModifiers() & QtCore.Qt.KeyboardModifier.ShiftModifier
            shown = SWAPPED_SCULPT.get(self.brush.kind, self.brush.kind) if shift else self.brush.kind
        rgb = self.doc.rgb if stamp else np.array([[0, 0, 0]] + [np.multiply(HOVER_COLOUR[shown], 255)] * 255,
                                                  dtype=np.uint8)
        faces = voxel_faces(grid, rgb)
        if faces is None:
            return
        mesh_points, quads, face_rgb, _, _ = faces
        mesh = pv.PolyData.from_regular_faces(mesh_points + lo, quads)
        mesh.cell_data["rgb"] = face_rgb
        self.preview_actor = self.plotter.add_mesh(
            mesh, scalars="rgb", rgb=True, opacity=PREVIEW_OPACITY, show_edges=True,
            edge_color=HOVER_COLOUR[shown], line_width=1, pickable=False, reset_camera=False, render=False)
        # a paint or erase preview lies exactly on the model's faces: drawn in front of them, else the
        # depth test lets the model win on some faces (a paint preview's top went missing)
        mapper = self.preview_actor.GetMapper()
        mapper.SetResolveCoincidentTopologyToPolygonOffset()
        mapper.SetRelativeCoincidentTopologyPolygonOffsetParameters(-2, -8)
        mapper.SetRelativeCoincidentTopologyLineOffsetParameters(-2, -8)
        self.plotter.render()
        self.doc.hover_changed.emit(f"3D {mode} ({what}): {self.doc.describe(*target)} · "
                                    f"{len(points)} voxels")

    # --- the Noise dock's box ----------------------------------------------------------------
    def set_region(self, region):
        """Outline the Noise dock's box (noise_panel.NoiseBox) while it shows."""
        self.region = region
        region.changed.connect(self.draw_region)
        self.draw_region()

    def draw_region(self):
        if not self.region.shown:
            self.plotter.remove_actor("noise box", render=True)
            return
        lo, hi = np.array(self.region.bounds())
        lo, hi = lo - 0.03, hi + 1.03  # just outside the voxels' own edges, so they do not hide it
        self.plotter.add_mesh(pv.Box((lo[0], hi[0], lo[1], hi[1], lo[2], hi[2])).outline(), name="noise box",
                              color=np.divide(self.region.COLOUR, 255), line_width=2, pickable=False,
                              reset_camera=False, render=True)

    # --- keys -------------------------------------------------------------------------------
    def eventFilter(self, obj, event):
        if event.type() == QtCore.QEvent.Type.Wheel and size_step(event):
            self.brush.set(size=self.brush.size + size_step(event))  # instead of zooming
            if self.hover_pos is not None and self.stroke_mode is None:
                self.update_hover(self.hover_pos)
            return True
        if event.type() == QtCore.QEvent.Type.MouseButtonRelease:
            button = event.button()  # after the widget has passed it on to VTK, make sure it arrived
            QtCore.QTimer.singleShot(0, lambda: self.style.released(button))
            return False
        if event.type() in (QtCore.QEvent.Type.KeyPress, QtCore.QEvent.Type.KeyRelease) and event.key() in (
                QtCore.Qt.Key.Key_Shift, QtCore.Qt.Key.Key_Control, QtCore.Qt.Key.Key_Alt):
            if self.hover_pos is not None and self.stroke_mode is None:
                QtCore.QTimer.singleShot(0, lambda: self.update_hover(self.hover_pos))  # the preview follows the keys
            return False
        if event.type() == QtCore.QEvent.Type.Enter:
            keymap.take_focus(self.plotter.interactor)  # its keys work without a click first
            return False
        if event.type() == QtCore.QEvent.Type.KeyPress:
            key, shift = event.key(), bool(event.modifiers() & QtCore.Qt.KeyboardModifier.ShiftModifier)
            action = keymap.action_for(event, keymap.EDIT_3D)
            if self.brush.kind == "stamp" and action in ("stamp_turn", "stamp_turn_back"):
                self.brush.turn_stamp(-1 if action == "stamp_turn_back" else 1)
                return True
            if self.brush.kind == "stamp" and action == "stamp_stop":
                self.brush.set(kind="voxel")
                return True
            if action == "ortho":
                self.ortho_box.toggle()
                return True
            if action in VIEW_ACTIONS:
                self.snap_view(VIEW_ACTIONS[action])
                return True
            delta = view_delta(self.plotter.camera, key, BIG_STEP if shift else 1)
            if delta is not None and self.stroke_mode is None:
                self.doc.shift(delta, self.doc.shift_wrap)
                return True
        return super().eventFilter(obj, event)

    def close(self):
        self.plotter.close()
        return super().close()
