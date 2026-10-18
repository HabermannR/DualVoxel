"""The scene view: every instance of the scene shown, as flat-coloured voxels in VTK.

Each instance is an actor at its position over a mesh made from its model's
voxels as oriented; instances of the same model and orientation share the mesh,
which is rebuilt when the model changes, so an edit in the model docks shows on
every instance. A click selects an instance (a yellow box); dragging the
selected one moves it over its floor. The arrow keys move it relative to the
view (Up away from you), Page Up / Page Down up and down (Shift: 8 voxels), R
turns it a quarter turn about z (Shift+R back), M mirrors it left-right as seen,
Ctrl+D makes a linked copy, Del deletes, Enter or a double click edits its
model. Drag elsewhere orbits, middle drag pans, the wheel zooms.
"""
from __future__ import annotations

import numpy as np
import pyvista as pv
from PySide6 import QtCore, QtWidgets
from pyvistaqt import QtInteractor
from vtkmodules.vtkInteractionStyle import vtkInteractorStyleTrackballCamera
from vtkmodules.vtkRenderingCore import vtkCellPicker

from core.scene import place_plane
from qtui.edit_view import CLICK_SLOP, voxel_faces

SELECTED_COLOUR = (1.0, 0.85, 0.1)
BIG_STEP = 8
Key = QtCore.Qt.Key
VIEW_MOVES = {Key.Key_Up: (0, 1), Key.Key_Down: (0, -1), Key.Key_Right: (1, 0), Key.Key_Left: (-1, 0)}


class SceneStyle(vtkInteractorStyleTrackballCamera):
    """Trackball camera; a click selects, a drag that starts on the selected instance moves it."""

    def __init__(self, view: "SceneView"):
        super().__init__()
        self.view = view
        self.press = None
        self.dragging = False
        self.AddObserver("LeftButtonPressEvent", self.left_down)
        self.AddObserver("LeftButtonReleaseEvent", self.left_up)
        self.AddObserver("MouseMoveEvent", self.move)
        self.AddObserver("RightButtonPressEvent", lambda *_: self.OnLeftButtonDown())  # right drag orbits,
        self.AddObserver("RightButtonReleaseEvent", lambda *_: self.OnLeftButtonUp())  # as in the 3D view
        self.AddObserver("CharEvent", lambda *_: None)  # no VTK letter keys

    def left_down(self, *_):
        iren = self.GetInteractor()
        pos = iren.GetEventPosition()
        if iren.GetRepeatCount():
            self.view.double_click(pos)
            return
        if self.view.begin_drag(pos):
            self.dragging = True
            return
        self.press = pos
        self.OnLeftButtonDown()

    def move(self, *_):
        if self.dragging:
            self.view.continue_drag(self.GetInteractor().GetEventPosition())
            return
        self.OnMouseMove()

    def left_up(self, *_):
        pos = self.GetInteractor().GetEventPosition()
        if self.dragging:
            self.dragging = False
            self.view.end_drag(pos)
            return
        self.OnLeftButtonUp()
        if self.press is not None and max(abs(pos[0] - self.press[0]), abs(pos[1] - self.press[1])) <= CLICK_SLOP:
            self.view.click(pos)
        self.press = None


class SceneView(QtWidgets.QWidget):
    def __init__(self, doc, project_doc):
        super().__init__()
        self.doc = doc
        self.pdoc = project_doc
        self.plotter = QtInteractor(self)
        self.plotter.set_background((0.15, 0.16, 0.17), top=(0.26, 0.29, 0.31))
        self.plotter.enable_lightkit()
        self.plotter.add_axes()
        try:
            self.plotter.iren.clear_key_event_callbacks()
        except AttributeError:
            pass
        self.style = SceneStyle(self)
        self.plotter.iren.interactor.SetInteractorStyle(self.style)
        self.plotter.interactor.installEventFilter(self)
        self.plotter.iren.untrack_click_position(side="left")  # PyVista's double click would replace the style
        self.plotter.interactor.setToolTip(
            "Click selects an instance · drag it to move it · arrows move it as seen (Up: away), "
            f"Page Up / Page Down: up and down, Shift: {BIG_STEP} voxels · R turns it (Shift+R back) · "
            "M mirrors it left-right · Ctrl+D linked copy · Del deletes · Enter or double click edits its model · "
            "Ctrl+Z undoes · drag elsewhere: orbit · middle drag: pan · wheel: zoom")
        self.picker = vtkCellPicker()
        self.picker.SetTolerance(0.0005)
        self.picker.PickFromListOn()

        bar = QtWidgets.QHBoxLayout()
        bar.setContentsMargins(4, 2, 4, 2)
        self.buttons = {}
        for text, tip, slot in (("Turn", "A quarter turn about z (R)", lambda: self.pdoc.rotate(2, 1)),
                                ("Mirror", "Mirror left-right as seen (M)", lambda: self.pdoc.mirror(self.screen_axis())),
                                ("Duplicate", "A linked copy beside it (Ctrl+D)", self.pdoc.duplicate),
                                ("Delete", "Remove the instance (Del)", self.pdoc.delete),
                                ("Edit model", "Open its model in the model docks (Enter)", self.pdoc.request_edit)):
            button = QtWidgets.QPushButton(text)
            button.setToolTip(tip)
            button.clicked.connect(lambda _=False, s=slot: s())
            bar.addWidget(button)
            self.buttons[text] = button
        bar.addStretch(1)
        frame_button = QtWidgets.QPushButton("Frame")
        frame_button.setToolTip("Fit the scene in the view")
        frame_button.clicked.connect(self.frame)
        bar.addWidget(frame_button)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(bar)
        layout.addWidget(self.plotter.interactor, 1)

        self.meshes = {}  # (model, version, orient, by material) -> PolyData in the oriented box's frame
        self.actors = {}  # instance -> (actor, mesh key)
        self.shown_scene = None
        self.frame_pending = False  # framed when the view next shows (a hidden view has no size to fit)
        self.drag = None  # (instance position at the press, grabbed point, recorded)
        self._refresh_timer = QtCore.QTimer(self, singleShot=True, interval=30, timeout=self.refresh)
        project_doc.changed.connect(self.refresh)
        project_doc.selected.connect(self.refresh)
        doc.changed.connect(self._refresh_timer.start)  # a model's voxels, through the model docks
        doc.display_changed.connect(self.refresh)
        self.refresh()

    # --- scene ------------------------------------------------------------------------
    def _mesh(self, instance):
        model = self.pdoc.project.models[instance.model]
        key = (instance.model, model.version, instance.orient, self.doc.show_materials)
        if key not in self.meshes:
            colour = place_plane(model.colour, instance.orient)
            if self.doc.show_materials:
                faces = voxel_faces(colour, self.doc.material_rgb, place_plane(model.material, instance.orient))
            else:
                faces = voxel_faces(colour, self.doc.rgb)
            mesh = None
            if faces is not None:
                points, quads, colours, _, _ = faces
                mesh = pv.PolyData.from_regular_faces(points, quads)
                mesh.cell_data["rgb"] = colours
            for k in [k for k in self.meshes if k[0] == key[0] and k[1] != key[1]]:
                del self.meshes[k]  # older versions of this model
            self.meshes[key] = mesh
        return key, self.meshes[key]

    def refresh(self):
        scene = self.pdoc.scene
        instances = list(scene.instances) if scene is not None else []
        for instance in [i for i in self.actors if i not in instances]:
            self.plotter.remove_actor(self.actors.pop(instance)[0], render=False)
        for instance in instances:
            key, mesh = self._mesh(instance)
            actor, shown_key = self.actors.get(instance, (None, None))
            if shown_key != key:
                if actor is not None:
                    self.plotter.remove_actor(actor, render=False)
                actor = None
                if mesh is not None:
                    actor = self.plotter.add_mesh(mesh, scalars="rgb", rgb=True, show_edges=True,
                                                  edge_color=(0.08, 0.08, 0.09), line_width=1, reset_camera=False)
                self.actors[instance] = (actor, key)
            if actor is not None:
                actor.SetPosition(*instance.position)
        self.picker.InitializePickList()
        for actor, _ in self.actors.values():
            if actor is not None:
                self.picker.AddPickList(actor)
        self._floor()
        self._selection_box()
        has = self.pdoc.instance is not None
        for button in self.buttons.values():
            button.setEnabled(has)
        if scene is not self.shown_scene:
            self.shown_scene = scene
            self.frame_pending = True
        if self.frame_pending and self.isVisible():
            QtCore.QTimer.singleShot(0, self.frame)
        self.redraw()

    def redraw(self):
        """Draw now, and once more through Qt's paint (the interactor's own way, as a mouse drag draws): once
        the 3D edit view has shown in the same dock area, a draw from outside the view alone can stay off screen."""
        self.plotter.render()
        self.plotter.interactor.update()

    def _floor(self):
        self.plotter.remove_actor("floor", render=False)
        if self.pdoc.scene is None:
            return
        lo, hi = self.pdoc.project.bounds(self.pdoc.scene)
        lo, hi = lo - 8, hi + 8
        size = hi - lo
        floor = pv.Plane(center=((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, 0), direction=(0, 0, 1),
                         i_size=size[0], j_size=size[1], i_resolution=max(1, size[0] // 8),
                         j_resolution=max(1, size[1] // 8))
        self.plotter.add_mesh(floor, name="floor", color=(0.45, 0.47, 0.52), opacity=0.18, show_edges=True,
                              edge_color=(0.55, 0.57, 0.62), lighting=False, pickable=False, reset_camera=False)

    def _selection_box(self):
        self.plotter.remove_actor("selected", render=False)
        instance = self.pdoc.instance
        if instance is None:
            return
        lo, hi = self.pdoc.project.box(instance)
        box = pv.Box((lo[0] - 0.1, hi[0] + 0.1, lo[1] - 0.1, hi[1] + 0.1, lo[2] - 0.1, hi[2] + 0.1)).outline()
        self.plotter.add_mesh(box, name="selected", color=SELECTED_COLOUR, line_width=3, pickable=False,
                              reset_camera=False)

    def showEvent(self, event):
        super().showEvent(event)
        # Changes made while hidden (a selection in the Project dock, say) were never drawn: draw them now.
        QtCore.QTimer.singleShot(0, self.frame if self.frame_pending else self.redraw)

    def frame(self):
        self.frame_pending = False
        if self.pdoc.scene is None:
            return
        lo, hi = self.pdoc.project.bounds(self.pdoc.scene)
        centre = (lo + hi) / 2
        reach = float(max(hi - lo))
        self.plotter.camera_position = [(centre[0] + reach * 0.4, centre[1] - reach * 1.4, centre[2] + reach * 0.9),
                                        tuple(centre), (0, 0, 1)]
        self.plotter.reset_camera()
        self.redraw()

    # --- picking and dragging -------------------------------------------------------------
    def instance_at(self, pos):
        if not self.picker.Pick(pos[0], pos[1], 0, self.plotter.renderer):
            return None
        actor = self.picker.GetActor()
        return next((i for i, (a, _) in self.actors.items() if a is actor), None)

    def click(self, pos):
        self.pdoc.select(self.instance_at(pos))

    def double_click(self, pos):
        instance = self.instance_at(pos)
        if instance is not None:
            self.pdoc.select(instance)
            self.pdoc.request_edit()

    def floor_point(self, pos, z: float):
        """Where the view ray under a display position meets the plane at height z (None if parallel)."""
        renderer = self.plotter.renderer
        ends = []
        for depth in (0.0, 1.0):
            renderer.SetDisplayPoint(pos[0], pos[1], depth)
            renderer.DisplayToWorld()
            w = renderer.GetWorldPoint()
            ends.append(np.array(w[:3]) / w[3])
        near, far = ends
        if abs(far[2] - near[2]) < 1e-9:
            return None
        t = (z - near[2]) / (far[2] - near[2])
        return near + t * (far - near)

    def begin_drag(self, pos) -> bool:
        """Start moving the selected instance if the press is on it: the grabbed point follows the cursor."""
        instance = self.pdoc.instance
        if instance is None or self.instance_at(pos) is not instance:
            return False
        start = np.array(self.picker.GetPickPosition())  # moves along the plane at the grabbed height
        self.drag = (instance.position, start, False)
        return True

    def continue_drag(self, pos):
        if self.drag is None or self.pdoc.instance is None:
            return
        position, start, recorded = self.drag
        point = self.floor_point(pos, start[2])
        if point is None:
            return
        dx, dy = np.round(point[:2] - start[:2]).astype(int)
        target = (position[0] + int(dx), position[1] + int(dy), position[2])
        if target != self.pdoc.instance.position:
            if not recorded:
                self.pdoc.begin_drag()  # one undo step for the whole drag
                self.drag = (position, start, True)
            self.pdoc.move_to(target, record=False)

    def end_drag(self, pos):
        self.continue_drag(pos)
        self.drag = None

    # --- keys -------------------------------------------------------------------------------
    def _view_axes(self):
        """The scene axes (index, sign) nearest to the view's right and its forward along the floor."""
        camera = self.plotter.camera
        forward = np.subtract(camera.focal_point, camera.position)[:2]
        if not np.any(forward):
            forward = np.array(camera.up)[:2]
        right = np.array([forward[1], -forward[0]])
        pick = lambda v: (int(np.argmax(np.abs(v))), int(np.sign(v[np.argmax(np.abs(v))])) or 1)
        return pick(right), pick(forward)

    def screen_axis(self) -> int:
        """The scene axis closest to left-right on screen, for mirroring as seen."""
        return self._view_axes()[0][0]

    def eventFilter(self, obj, event):
        if event.type() == QtCore.QEvent.Type.KeyPress and self.key(event):
            return True
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event):
        if not self.key(event):
            super().keyPressEvent(event)

    def key(self, event) -> bool:
        """Handle a placement key; False for keys this view does not use."""
        k, mods = event.key(), event.modifiers()
        shift = bool(mods & QtCore.Qt.KeyboardModifier.ShiftModifier)
        step = BIG_STEP if shift else 1
        if k in VIEW_MOVES:
            (r_axis, r_sign), (f_axis, f_sign) = self._view_axes()
            across, ahead = VIEW_MOVES[k]
            delta = [0, 0, 0]
            delta[r_axis] += across * r_sign * step
            delta[f_axis] += ahead * f_sign * step
            self.pdoc.move(*delta)
        elif k in (Key.Key_PageUp, Key.Key_PageDown):
            self.pdoc.move(0, 0, step if k == Key.Key_PageUp else -step)
        elif k == Key.Key_R:
            self.pdoc.rotate(2, -1 if shift else 1)
        elif k == Key.Key_M:
            self.pdoc.mirror(self.screen_axis())
        elif k == Key.Key_D and mods & QtCore.Qt.KeyboardModifier.ControlModifier:
            self.pdoc.duplicate()
        elif k in (Key.Key_Delete, Key.Key_Backspace):
            self.pdoc.delete()
        elif k in (Key.Key_Return, Key.Key_Enter):
            self.pdoc.request_edit()
        else:
            return False
        return True

    def close(self):
        self.plotter.close()
        return super().close()
