"""A 2D slice view: one layer of the model, painted with the mouse.

The 3D view's rule (brush.mode_for): left draws in the current mode (attach
fills empty cells, paint recolours, erase removes), Shift + left and Ctrl + left
use the other two modes, Alt + left picks. It draws with the Brush dock's brush
(qtui.brush.brush_edit): its size and shape at each cell the mouse crosses (flat
ones lie in the layer, volumes reach the layers around it), box a rectangle in
the layer (drag it), ellipsoid the ellipsoid over a dragged rectangle, centred
on the layer, face the connected area of the clicked cell's colour in the
layer, and the sculpting brushes; mirroring as set. A stamp is a 3D-view brush.
The wheel moves the layer (Alt + Shift + wheel: the brush size), Ctrl + wheel zooms around the cursor,
middle drag or Shift + right drag pans, Home or a middle double click fits the layer again; a stroke that
reaches the edge pans along. Empty cells show the nearest voxel behind the layer, dimmed, so the slice keeps
its place in the figure. With the pick
tool, left picks too. Voxels protected from the assistant are tinted violet.
While the Noise dock is in sight its box is outlined (dashed when the layer is
outside it); with its "Drag box" on, a left drag sets the box's two axes in this
slice instead of drawing (Alt + left still picks).
"""
from __future__ import annotations

import math

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

from core.brushes import layer_region, mirror_sum, mirrored, placed
from qtui import keymap
from qtui.brush import DRAGGED, SCULPT, Stroke, brush_edit, fill_region, held_mode, size_step
from qtui.document import PROTECT_MODES
from qtui.edit_view import AXIS_RGB, PROTECTED_RGB, PROTECTED_TINT

BACKGROUND = np.array([38, 38, 42], dtype=np.float32)
GHOST = 0.33  # how strongly the voxels behind the layer show through
ZOOM_STEP = 1.25  # one wheel step of Ctrl + wheel
MAX_CELL = 64.0  # the closest zoom, pixels per voxel
EDGE_PAN = 12  # pixels a stroke held past the canvas's edge pans by, every 30 ms

# name: (u axis, v axis, depth axis, flip u, flip v, the direction "behind" goes along the depth axis)
SLICES = {
    "Front": (0, 2, 1, False, True, +1),  # from -y, looking +y: x right, z up
    "Side": (1, 2, 0, False, True, -1),   # from +x, looking -x: y right, z up
    "Top": (0, 1, 2, False, True, -1),    # from above: x right, y up (the front at the bottom)
}
AXIS = "xyz"


class SliceCanvas(QtWidgets.QWidget):
    def __init__(self, view: "SliceView"):
        super().__init__(view)
        self.view = view
        self.setMouseTracking(True)
        self.setMinimumSize(120, 120)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.ClickFocus)
        self.image = None
        self.hover = None  # (u, v)
        self.stroke_button = None
        self.stroke_mode = None
        self.stroke_shift = False
        self.box_start = None  # the cell a box drag began at
        self.last = None
        self.region = None  # the Noise dock's box (noise_panel.NoiseBox), outlined while it shows
        self.region_start = None  # the cell a drag setting it began at
        self.zoom = None  # pixels per cell; None: the layer fits the canvas
        self.pan = QtCore.QPointF(0, 0)  # how far the layer is moved from the centre
        self.pan_from = None  # (mouse position, pan) while a pan drag goes on
        self.cursor = None  # where a stroke held past the edge is, for the edge pan
        self._edge = QtCore.QTimer(self, interval=30, timeout=self._edge_pan)

    # --- geometry: cells fit the widget, centred, unless zoomed and panned ---------------
    def fit_cell(self) -> float:
        """Pixels per cell for the whole layer to fit: whole pixels, below one only if it must."""
        U, V = self.view.extent
        fit = min(self.width() / max(U, 1), self.height() / max(V, 1))
        return float(int(fit)) if fit >= 1 else fit

    def _layout(self):
        U, V = self.view.extent
        cell = self.zoom or self.fit_cell()
        ox = round((self.width() - cell * U) / 2 + self.pan.x())
        oy = round((self.height() - cell * V) / 2 + self.pan.y())
        return cell, ox, oy

    def fit(self) -> None:
        """The whole layer in the canvas again."""
        self.zoom, self.pan = None, QtCore.QPointF(0, 0)
        self.update()

    def zoom_at(self, pos: QtCore.QPointF, steps: float) -> None:
        """Zoom in (steps > 0) or out around a point, the cell under it staying put; out past the fit fits."""
        U, V = self.view.extent
        cell, ox, oy = self._layout()
        new = cell * ZOOM_STEP ** steps
        if new >= 1:  # whole pixels per cell, so every cell is as wide as the next
            new = float(round(new))
            if new == cell:
                new += 1 if steps > 0 else -1
        new = min(MAX_CELL, new)
        if new <= self.fit_cell():
            self.fit()
            return
        def kept(p, o):
            """Where the point is, in cells, at least half a pixel inside its cell: _layout rounds the corner to
            whole pixels, which must not move the point into the next cell."""
            at = (p - o) / cell
            margin = min(0.5, 0.5 / new)
            return math.floor(at) + min(max(at - math.floor(at), margin), 1 - margin)
        at = QtCore.QPointF(kept(pos.x(), ox), kept(pos.y(), oy))
        self.zoom = new
        self.pan = QtCore.QPointF(pos.x() - at.x() * new - (self.width() - new * U) / 2,
                                  pos.y() - at.y() * new - (self.height() - new * V) / 2)
        self.update()

    def cell_at(self, pos: QtCore.QPointF):
        U, V = self.view.extent
        cell, ox, oy = self._layout()
        col = int((pos.x() - ox) // cell)
        row = int((pos.y() - oy) // cell)
        if not (0 <= col < U and 0 <= row < V):
            return None
        u = U - 1 - col if self.view.flip_u else col
        v = V - 1 - row if self.view.flip_v else row
        return u, v

    def _screen_rect(self, u: int, v: int) -> QtCore.QRectF:
        U, V = self.view.extent
        cell, ox, oy = self._layout()
        col = U - 1 - u if self.view.flip_u else u
        row = V - 1 - v if self.view.flip_v else v
        return QtCore.QRectF(ox + col * cell, oy + row * cell, cell, cell)

    def _paint_region(self, painter):
        """The Noise dock's box across this slice: solid with a faint fill where the layer is inside it, dashed
        where it lies in front of or behind the layer."""
        lo, hi = self.region.bounds()
        view = self.view
        rect = self._screen_rect(lo[view.u], lo[view.v]).united(self._screen_rect(hi[view.u], hi[view.v])).toRect()
        inside = lo[view.d] <= view.depth_box.value() <= hi[view.d]
        colour = QtGui.QColor(*self.region.COLOUR)
        pen = QtGui.QPen(colour, 2, QtCore.Qt.PenStyle.SolidLine if inside else QtCore.Qt.PenStyle.DashLine)
        painter.setPen(pen)
        fill = QtGui.QColor(colour)
        fill.setAlpha(28)
        painter.setBrush(fill if inside else QtCore.Qt.BrushStyle.NoBrush)
        painter.drawRect(rect.adjusted(1, 1, -1, -1))

    def _paint_mirrors(self, painter):
        """The brush's mirror planes that cross this slice, dashed, in their axes' colours."""
        brush, view = self.view.brush, self.view
        if brush is None:
            return
        U, V = view.extent
        cell, ox, oy = self._layout()
        size = view.doc.size
        for axis, along_u in ((view.u, True), (view.v, False)):
            if not brush.mirror[axis]:
                continue
            at = mirror_sum(size, brush.mirror_plane, axis) / 2 + 0.5  # voxel p spans p..p + 1
            if not 0 <= at <= size[axis]:
                continue
            painter.setPen(QtGui.QPen(QtGui.QColor.fromRgbF(*AXIS_RGB[axis]), 2, QtCore.Qt.PenStyle.DashLine))
            if along_u:
                x = ox + round((U - at if view.flip_u else at) * cell)
                painter.drawLine(QtCore.QLineF(x, oy, x, oy + V * cell))
            else:
                y = oy + round((V - at if view.flip_v else at) * cell)
                painter.drawLine(QtCore.QLineF(ox, y, ox + U * cell, y))

    # --- drawing ----------------------------------------------------------------------
    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.fillRect(self.rect(), QtGui.QColor(28, 28, 31))
        if self.image is None:
            return
        U, V = self.view.extent
        cell, ox, oy = self._layout()
        target = QtCore.QRectF(ox, oy, cell * U, cell * V)
        painter.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform, False)
        painter.drawImage(target, self.image)
        if cell >= 6:  # the grid, only its lines in sight
            painter.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 60), 1))
            top, bottom = max(oy, 0), min(oy + V * cell, self.height())
            left, right = max(ox, 0), min(ox + U * cell, self.width())
            for i in range(max(0, int(-ox // cell)), min(U, int((self.width() - ox) // cell)) + 1):
                painter.drawLine(QtCore.QLineF(ox + i * cell, top, ox + i * cell, bottom))
            for j in range(max(0, int(-oy // cell)), min(V, int((self.height() - oy) // cell)) + 1):
                painter.drawLine(QtCore.QLineF(left, oy + j * cell, right, oy + j * cell))
        if self.region is not None and self.region.shown:
            self._paint_region(painter)
        self._paint_mirrors(painter)
        dragging_region = self.region is not None and self.region.drags
        if self.hover is not None and self.box_start is None and not dragging_region:  # the brush's cells
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            painter.setBrush(QtGui.QColor(255, 220, 0, 80))
            for u, v in self.view.footprint(*self.hover):
                painter.drawRect(self._screen_rect(u, v))
        if self.hover is not None:
            painter.setPen(QtGui.QPen(QtGui.QColor(255, 220, 0), 2))
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            painter.drawRect(self._screen_rect(*self.hover))
        if self.box_start is not None and self.last is not None:  # the box being dragged
            painter.setPen(QtGui.QPen(QtGui.QColor(80, 255, 110), 2))
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            rect = self._screen_rect(*self.box_start).united(self._screen_rect(*self.last))
            kind = self.view.brush.kind if self.view.brush is not None else None
            if kind == "ellipsoid":
                painter.drawEllipse(rect)
            elif kind == "line":
                painter.drawLine(self._screen_rect(*self.box_start).center(), self._screen_rect(*self.last).center())
            else:
                painter.drawRect(rect)

    # --- mouse ------------------------------------------------------------------------
    def _pans(self, event) -> bool:
        Button = QtCore.Qt.MouseButton
        return event.button() == Button.MiddleButton or (
            event.button() == Button.RightButton and event.modifiers() & QtCore.Qt.KeyboardModifier.ShiftModifier)

    def mousePressEvent(self, event):
        if self._pans(event) and self.stroke_button is None:
            if self.zoom is None:
                self.zoom = self.fit_cell()  # panning a fitted layer keeps its size
            self.pan_from = (event.position(), QtCore.QPointF(self.pan))
            return
        if event.button() != QtCore.Qt.MouseButton.LeftButton:
            return
        hit = self.cell_at(event.position())
        if hit is None:
            return
        if self.region is not None and self.region.drags and \
                not event.modifiers() & QtCore.Qt.KeyboardModifier.AltModifier:
            self.region_start = hit  # the Noise dock's box, not the brush
            self.view.drag_region(hit, hit)
            return
        mode = held_mode(self.view.doc.tool, event.modifiers())
        if mode == "pick":
            self.view.pick(*hit)
            return
        self.stroke_button = event.button()
        self.stroke_mode = mode
        self.stroke_shift = bool(event.modifiers() & QtCore.Qt.KeyboardModifier.ShiftModifier)
        self.last = hit
        self.view.begin_stroke()
        if self.view.brush is not None and self.view.brush.kind in DRAGGED:
            self.box_start = hit  # the box is written on release
            self.update()
            return
        self.view.draw([hit], mode, self.stroke_shift)

    def mouseDoubleClickEvent(self, event):
        if event.button() == QtCore.Qt.MouseButton.MiddleButton:
            self.fit()
            return
        self.mousePressEvent(event)

    def _stroking(self) -> bool:
        return self.stroke_button is not None or self.region_start is not None

    def _clamped(self, pos: QtCore.QPointF) -> QtCore.QPointF:
        return QtCore.QPointF(min(max(pos.x(), 0), self.width() - 1), min(max(pos.y(), 0), self.height() - 1))

    def mouseMoveEvent(self, event):
        pos = event.position()
        if self.pan_from is not None:
            start, pan = self.pan_from
            self.pan = pan + (pos - start)
            self.update()
            return
        if self._stroking():  # a stroke stops at the canvas's edge, and pans along while held past it
            inside = self._clamped(pos)
            if inside != pos:
                self.cursor = pos
                if not self._edge.isActive():
                    self._edge.start()
            else:
                self._edge.stop()
            pos = inside
        self._move_to(pos)

    def _edge_pan(self):
        """A stroke held past the edge: pan towards it while there is more layer that way, and go on drawing."""
        if not self._stroking() or self.cursor is None:
            self._edge.stop()
            return
        U, V = self.view.extent
        cell, ox, oy = self._layout()
        x, y, w, h = self.cursor.x(), self.cursor.y(), self.width(), self.height()
        dx = EDGE_PAN if x < 0 and ox < 0 else -EDGE_PAN if x >= w and ox + cell * U > w else 0
        dy = EDGE_PAN if y < 0 and oy < 0 else -EDGE_PAN if y >= h and oy + cell * V > h else 0
        if dx or dy:
            self.pan += QtCore.QPointF(dx, dy)
            self.update()
        self._move_to(self._clamped(self.cursor))

    def _move_to(self, pos: QtCore.QPointF):
        hit = self.cell_at(pos)
        if hit != self.hover:
            self.hover = hit
            self.view.report_hover(hit)
            self.update()
        if self.region_start is not None:
            if hit is not None:
                self.view.drag_region(self.region_start, hit)
            return
        if self.stroke_button is not None and hit is not None and hit != self.last and self.box_start is not None:
            self.last = hit
            self.update()
            return
        if self.stroke_button is not None and hit is not None and hit != self.last:
            steps = max(abs(hit[0] - self.last[0]), abs(hit[1] - self.last[1]))
            line = [(round(self.last[0] + (hit[0] - self.last[0]) * t / steps),
                     round(self.last[1] + (hit[1] - self.last[1]) * t / steps)) for t in range(1, steps + 1)]
            self.view.draw(list(dict.fromkeys(line)), self.stroke_mode, self.stroke_shift)  # in order, for smear
            self.last = hit

    def mouseReleaseEvent(self, event):
        if self.pan_from is not None and self._pans(event):
            self.pan_from = None
            return
        self._edge.stop()
        if self.region_start is not None and event.button() == QtCore.Qt.MouseButton.LeftButton:
            self.region_start = None
            return
        if self.stroke_button is not None and event.button() == self.stroke_button:
            self.stroke_button = None
            if self.box_start is not None:
                self.view.draw_box(self.box_start, self.last, self.stroke_mode, self.stroke_shift)
                self.box_start = None
                self.update()
            self.view.end_stroke()

    def enterEvent(self, event):
        keymap.take_focus(self)  # the slice's keys work without a click first

    def leaveEvent(self, event):
        self.hover = None
        self.view.report_hover(None)  # the status bar forgets the cell too
        self.update()

    def wheelEvent(self, event):
        if size_step(event) and self.view.brush is not None:
            self.view.brush.set(size=self.view.brush.size + size_step(event))
            self.update()
            return
        if event.modifiers() & QtCore.Qt.KeyboardModifier.ControlModifier:
            self.zoom_at(event.position(), event.angleDelta().y() / 120)
            return
        step = 1 if event.angleDelta().y() > 0 else -1
        self.view.depth_box.setValue(self.view.depth_box.value() + step)

    def event(self, event):
        if event.type() == QtCore.QEvent.Type.NativeGesture and \
                event.gestureType() == QtCore.Qt.NativeGestureType.ZoomNativeGesture:  # a trackpad's pinch
            self.zoom_at(event.position(), event.value() / math.log(ZOOM_STEP))
            return True
        return super().event(event)

    def keyPressEvent(self, event):
        if not self.view.key(event):
            super().keyPressEvent(event)


class SliceView(QtWidgets.QWidget):
    def __init__(self, doc, name: str):
        super().__init__()
        self.doc = doc
        self.name = name
        self.u, self.v, self.d, self.flip_u, self.flip_v, self.behind = SLICES[name]
        self.extent = (1, 1)
        self.brush = None  # the Brush dock's brush (the window gives it); None: single cells
        self.stroke = None  # the brush.Stroke drawn now (what a smear carries)
        self._bits = None  # _solid_bits': (model, colour plane, model version, bits)

        self.depth_box = QtWidgets.QSpinBox()
        self.depth_box.setPrefix(f"{AXIS[self.d]} = ")
        self.depth_box.setToolTip("The layer shown (the mouse wheel over the slice moves it too)")
        # at most once in 30 ms while a stroke changes voxels or the layer moves: each refresh reads the model
        self._refresh_soon = QtCore.QTimer(self, singleShot=True, interval=30, timeout=self.refresh)
        self.depth_box.valueChanged.connect(self.refresh_soon)
        self.ghost_box = QtWidgets.QCheckBox("Behind")
        self.ghost_box.setChecked(True)
        self.ghost_box.setToolTip("Show the nearest voxels behind the layer, dimmed")
        self.ghost_box.toggled.connect(self.refresh)
        bar = QtWidgets.QHBoxLayout()
        bar.setContentsMargins(4, 2, 4, 2)
        bar.addWidget(QtWidgets.QLabel(f"{AXIS[self.u]} →, {AXIS[self.v]} ↑"))
        bar.addStretch(1)
        bar.addWidget(self.ghost_box)
        bar.addWidget(self.depth_box)
        # The layer as a slider between a down and an up button (held, they keep stepping).
        self.depth_slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.depth_slider.setToolTip(f"The layer shown ({AXIS[self.d]})")
        self.depth_slider.valueChanged.connect(self.depth_box.setValue)
        self.depth_box.valueChanged.connect(self.depth_slider.setValue)
        steps = QtWidgets.QHBoxLayout()
        steps.setContentsMargins(4, 0, 4, 2)
        for text, step, tip in (("▼", -1, "One layer down"), ("▲", 1, "One layer up")):
            button = QtWidgets.QToolButton(text=text, autoRepeat=True)
            button.setAutoRepeatDelay(300)
            button.setAutoRepeatInterval(60)
            button.setToolTip(f"{tip} ({AXIS[self.d]} {'-' if step < 0 else '+'}1)")
            button.clicked.connect(lambda _=False, s=step: self.depth_box.setValue(self.depth_box.value() + s))
            if step < 0:
                steps.addWidget(button)
                steps.addWidget(self.depth_slider, 1)
            else:
                steps.addWidget(button)
        self.canvas = SliceCanvas(self)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(bar)
        layout.addLayout(steps)
        layout.addWidget(self.canvas, 1)

        doc.changed.connect(self.refresh_soon)
        doc.display_changed.connect(self.refresh)
        doc.protection_changed.connect(self.refresh_soon)
        doc.reset.connect(self.on_reset)
        doc.resized.connect(lambda: self.on_reset(keep_depth=True))
        doc.focus_changed.connect(self.on_focus)
        self.on_reset()

    def on_reset(self, keep_depth: bool = False):
        size = self.doc.size
        self.extent = (size[self.u], size[self.v])
        depth = min(self.depth_box.value(), size[self.d] - 1) if keep_depth else size[self.d] // 2
        for widget in (self.depth_box, self.depth_slider):
            widget.blockSignals(True)
            widget.setRange(0, size[self.d] - 1)
            widget.setValue(depth)
            widget.blockSignals(False)
        if not keep_depth:  # another model: seen whole
            self.canvas.fit()
        self.refresh()

    def refresh_soon(self):
        if not self._refresh_soon.isActive():
            self._refresh_soon.start()

    def on_focus(self, x, y, z):
        self.depth_box.setValue((x, y, z)[self.d])

    def _point(self, u: int, v: int):
        p = [0, 0, 0]
        p[self.u], p[self.v], p[self.d] = u, v, self.depth_box.value()
        return p

    def set_brush(self, brush) -> None:
        """Draw with this brush (the Brush dock's); the hover shows its size and shape."""
        self.brush = brush
        brush.changed.connect(self.canvas.update)

    def set_region(self, region) -> None:
        """Outline the Noise dock's box (noise_panel.NoiseBox) while it shows; drag it out while it drags."""
        self.canvas.region = region
        region.changed.connect(self.canvas.update)

    def drag_region(self, a, b) -> None:
        """The Noise dock's box from cell a to cell b of this layer: its two axes here; the third stays."""
        region = self.canvas.region
        start, end = list(region.start), list(region.end)
        for axis, i in ((self.u, 0), (self.v, 1)):
            start[axis], end[axis] = min(a[i], b[i]), max(a[i], b[i])
        region.set(start, end)

    def footprint(self, u: int, v: int):
        """The (u, v) cells of this layer the brush covers at a cell, mirrored (a box: the cell; the drag shows
        the rest)."""
        b, p = self.brush, self._point(u, v)
        if b is None or b.kind in (*DRAGGED, "stamp"):
            return [(u, v)]
        if b.kind == "face":
            points = layer_region(self.doc.model.colour, p, self.d)
        elif b.kind == "fill":  # what the mode the keys give would fill
            mode = held_mode(self.doc.tool, QtWidgets.QApplication.queryKeyboardModifiers())
            mode = "paint" if mode in PROTECT_MODES else mode
            points = fill_region(self.doc, b, mode, p, self._normal()) if mode != "pick" else [p]
        else:  # voxel and the sculpting brushes
            points = placed(b.shape, b.size, p, self._normal())
        points, _ = mirrored(points, self.doc.size, b.mirror, b.mirror_plane)
        size, depth = self.doc.size, self.depth_box.value()
        return [(int(q[self.u]), int(q[self.v])) for q in points
                if q[self.d] == depth and 0 <= q[self.u] < size[self.u] and 0 <= q[self.v] < size[self.v]]

    def _normal(self):
        """The layer's normal for the brush: along the depth axis, towards the viewer."""
        n = [0, 0, 0]
        n[self.d] = -self.behind
        return n

    def begin_stroke(self):
        self.stroke = Stroke()
        self.doc.begin_stroke()

    def end_stroke(self):
        self.stroke = None
        self.doc.end_stroke()

    def key(self, event) -> bool:
        """A slice's own key (keymap): the layer up or down, the zoom back to the fit. False for others."""
        action = keymap.action_for(event, keymap.SLICES)
        if action in ("layer_up", "layer_down"):
            self.depth_box.setValue(self.depth_box.value() + (1 if action == "layer_up" else -1))
        elif action == "slice_fit":
            self.canvas.fit()
        else:
            return False
        return True

    def draw(self, cells, mode: str, shift: bool = False):
        """The brush at cells of this layer in a mode: attach fills empty voxels, paint recolours solid ones,
        erase removes; a sculpting brush reshapes around the cell. Brushes that only write the current colour
        are worked out for every cell and written once; the sculpting ones, which read what the cell before
        wrote, one cell at a time."""
        if self.brush is None:
            points = [self._point(u, v) for u, v in cells]
            points = [p for p in points if bool(self.doc.voxel(*p)) == (mode != "attach")]
            if points and mode in PROTECT_MODES:
                self.doc.set_protected(points, mode == "protect")
            elif points:
                self.doc.set_voxels(points, colour=0 if mode == "erase" else None)
            return
        one_by_one = self.brush.kind in SCULPT and mode not in PROTECT_MODES
        found = []
        for u, v in cells:
            p = self._point(u, v)
            voxels = brush_edit(self.doc, self.brush, mode, p, self._normal(), hit=p if self.doc.voxel(*p) else None,
                                in_slice=True, shift=shift, stroke=self.stroke)
            if voxels is None:
                continue
            if one_by_one:
                self.doc.apply_brush(voxels, mode)
            else:
                found.append(voxels)
        if found:
            points = np.concatenate([f[0] for f in found])
            _, first = np.unique(points, axis=0, return_index=True)  # each voxel once
            self.doc.apply_brush(tuple(np.concatenate([f[i] for f in found])[first] for i in range(3)), mode)

    def draw_box(self, start, end, mode: str, shift: bool = False):
        """A box or ellipsoid brush dragged from cell `start` to cell `end` in this layer."""
        a, b = self._point(*start), self._point(*end)
        voxels = brush_edit(self.doc, self.brush, mode, b, self._normal(), hit=b if self.doc.voxel(*b) else None,
                            box_start=(a, self._normal()), box_end=b, in_slice=True, shift=shift)
        if voxels is not None:
            self.doc.apply_brush(voxels, mode)

    def pick(self, u, v):
        self.doc.pick(*self._point(u, v))

    def report_hover(self, hit):
        if hit is None:
            self.doc.hover_changed.emit("")
            return
        self.doc.hover_changed.emit(f"{self.name}: {self.doc.describe(*self._point(*hit))}")

    def _nearest_behind(self, stack: np.ndarray, depth: int) -> np.ndarray:
        """(U, V) the depth of the nearest voxel behind the layer in each cell's column, -1 where none."""
        bits, size = self._solid_bits(stack), stack.shape[2]
        word, bit = divmod(depth + 1 if self.behind > 0 else size - depth, 64)  # the first layer behind, in bits
        if word >= bits.shape[2]:
            return np.full(bits.shape[:2], -1)
        words = bits[:, :, word:].copy()
        words[:, :, 0] &= np.uint64((2 ** 64 - 1) << bit & (2 ** 64 - 1))  # none in front of that layer
        first = (words != 0).argmax(axis=2)
        found = np.take_along_axis(words, first[..., None], axis=2)[..., 0]
        lowest = found & (~found + np.uint64(1))  # its lowest bit alone: a power of two, exact as a float
        at = 64 * (word + first) + np.frexp(lowest.astype(np.float64))[1] - 1
        return np.where(found != 0, at if self.behind > 0 else size - 1 - at, -1)

    def _solid_bits(self, stack: np.ndarray) -> np.ndarray:
        """Which voxels are solid, each (u, v) column as bits from the front to the back (_pack). Kept between
        refreshes: after brush edits only the columns of the boxes they changed are packed again."""
        model, kept = self.doc.model, self._bits
        if kept is not None and kept[0] is model and kept[1] is model.colour:
            boxes = self.doc.edited_boxes(kept[2])
            if boxes is not None:
                for lo, hi in boxes:
                    cols = slice(lo[self.u], hi[self.u] + 1), slice(lo[self.v], hi[self.v] + 1)
                    kept[3][cols] = self._pack(stack[cols])
                self._bits = (model, model.colour, model.version, kept[3])
                return kept[3]
        self._bits = (model, model.colour, model.version, self._pack(stack))
        return self._bits[3]

    def _pack(self, stack: np.ndarray) -> np.ndarray:
        """(U, V, D) voxels -> (U, V, D / 64) uint64 words: bit p is the voxel p layers from the front, the way
        "behind" goes (zeros past the back)."""
        solid = (stack if self.behind > 0 else stack[:, :, ::-1]) > 0
        pad = -solid.shape[2] % 64
        if pad:
            solid = np.concatenate([solid, np.zeros((*solid.shape[:2], pad), dtype=bool)], axis=2)
        return np.ascontiguousarray(np.packbits(solid, axis=2, bitorder="little")).view("<u8")

    def refresh(self):
        key_plane, lookup = self.doc.display_planes()
        stack = np.moveaxis(self.doc.model.colour.transpose(2, 1, 0), self.d, -1)  # (U, V, D)
        keys = np.moveaxis(key_plane.transpose(2, 1, 0), self.d, -1)
        depth = min(self.depth_box.value(), stack.shape[2] - 1)
        layer = stack[:, :, depth]
        rgb = lookup[keys[:, :, depth]].astype(np.float32)
        empty = layer == 0
        protected = self.doc.protected()
        if protected is not None:
            hit = np.moveaxis(protected.transpose(2, 1, 0), self.d, -1)[:, :, depth] & ~empty
            rgb[hit] = rgb[hit] * (1 - PROTECTED_TINT) + PROTECTED_RGB * PROTECTED_TINT
        rgb[empty] = BACKGROUND
        if self.ghost_box.isChecked():
            near = self._nearest_behind(stack, depth)
            iu, iv = np.nonzero(empty & (near >= 0))
            rgb[iu, iv] = BACKGROUND * (1 - GHOST) + lookup[keys[iu, iv, near[iu, iv]]] * GHOST
        img = rgb.astype(np.uint8).transpose(1, 0, 2)  # rows v, columns u
        if self.flip_v:
            img = img[::-1]
        if self.flip_u:
            img = img[:, ::-1]
        self._pixels = np.ascontiguousarray(img)
        h, w = self._pixels.shape[:2]
        self.canvas.image = QtGui.QImage(self._pixels.data, w, h, 3 * w, QtGui.QImage.Format.Format_RGB888)
        self.canvas.update()
