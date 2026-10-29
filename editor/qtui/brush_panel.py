"""The Brush dock: the mode (attach, paint, erase, pick), the brush (voxel, face, box, ellipsoid, line, fill, stamp, or a sculpting
brush: smooth, erode, grow) with its options, and mirroring, for the 3D edit view and the slices;
MagicaVoxel's brush panel, plainer. The sculpting brushes reshape what is there in the size and shape set
below, whatever the mode, so while one is chosen no mode shows as chosen; Shift swaps erode and grow.
Choosing a mode (its button or its key) goes back from a sculpting brush to the brush used before it.

The window calls `install_brush_panel(window)` once, after its own docks.
"""
from __future__ import annotations

import PySide6QtAds as QtAds
from PySide6 import QtCore, QtWidgets

from core.brushes import MAX_SIZE
from core.scene import placed_size
from qtui.brush import MAX_TOLERANCE, SCULPT, mode_for
from qtui.document import TOOLS
from qtui.palette_panel import TOOL_KEYS

SEGMENT_STYLE = """
QToolButton { padding: 4px 10px; border: 1px solid #5a5a60; background: #3a3a40; color: #ddd; }
QToolButton:hover { background: #46464d; }
QToolButton:checked { background: #2f6fb5; border-color: #3d86d6; color: white; }
QToolButton:disabled { color: #777; }
"""
KIND_TIPS = {
    "voxel": "A square, circle, cube or sphere of the size below",
    "face": "The clicked face's whole connected flat area: attach builds a layer on it, paint and erase take it",
    "box": "Drag a rectangle in the clicked layer (a click: one voxel)",
    "ellipsoid": "Drag a rectangle on a face: the ellipsoid over it. Attach rests it on the face, paint and "
                 "erase sink it in (in a slice: centred on the layer)",
    "line": "Drag from one voxel to another: a straight line between them, as thick as the size and shape below",
    "fill": "Click a voxel: the area connected to it. Paint and erase take the voxels of its colour; attach "
            "fills an enclosed hollow (never the space around the model)",
    "stamp": "A project's model: select it in the Project dock, then Use as brush",
    "smooth": "Rounds off what is in the brush: fills hollows, takes off bumps",
    "erode": "Takes the outer skin of voxels off what is in the brush (Shift: grow)",
    "grow": "Adds a skin of voxels to what is in the brush, in the colours beside it (Shift: erode)",
}
PAGES = ("voxel", "face", "box", "ellipsoid", "stamp", "fill")  # the options shown for each brush kind
SIZED = (*SCULPT, "line")  # kinds that take the voxel brush's size and shape (its page)
SCOPE_TIPS = {"connected": "The area connected to the clicked voxel, in 3D",
              "layer": "Only in the clicked voxel's layer, across the clicked face (in a slice: the slice's layer)",
              "model": "Every matching voxel in the model, connected or not (paint and erase; attach stays "
                       "connected)"}
MATCH_TIPS = {"colour": "Voxels of the clicked voxel's colour (or within the tolerance of it)",
              "colour and material": "Voxels of its colour and its material",
              "solid": "Any solid voxel: the whole connected piece"}
MODE_TIPS = {"attach": "Add voxels against the clicked face; never overwrites",
             "paint": "Recolour voxels that are there", "erase": "Remove voxels",
             "pick": "Take a voxel's colour and material",
             "protect": "Mark voxels the assistant may not change over the live link (tinted violet; Shift lifts "
                        "it). Not an edit: no undo step, not saved"}


def install_brush_panel(window) -> "BrushPanel":
    panel = BrushPanel(window.doc, window.edit_view.brush)
    window._dock("Brush", panel, QtAds.DockWidgetArea.TopDockWidgetArea, window.docks["Colours"].dockAreaWidget())
    window.docks["Colours"].setAsCurrentTab()
    from qtui import window as window_module
    window.default_layout = window.dock_manager.saveState(window_module.LAYOUT_VERSION)

    def fit():
        """Give the dock its own height, the colours the rest (after the window's first layout)."""
        if window.layout_restored:
            return
        area = window.docks["Brush"].dockAreaWidget()
        splitter = area.parentWidget()
        if isinstance(splitter, QtWidgets.QSplitter) and splitter.count() > 1:
            sizes = splitter.sizes()
            own = panel.sizeHint().height() + area.titleBar().sizeHint().height() + 8
            index = splitter.indexOf(area)
            spare = sizes[index] - own
            sizes[index] = own
            sizes[index + 1 if index + 1 < len(sizes) else index - 1] += spare
            splitter.setSizes(sizes)
            window.default_layout = window.dock_manager.saveState(window_module.LAYOUT_VERSION)
    QtCore.QTimer.singleShot(100, panel, fit)  # not once the window has gone
    return panel


class HalfSpinBox(QtWidgets.QDoubleSpinBox):
    """A coordinate in half voxels, shown as 12 or 12.5; its lowest value (-0.5) reads "centre"."""

    def __init__(self):
        super().__init__(decimals=1, singleStep=0.5, minimum=-0.5, specialValueText="centre")

    def textFromValue(self, value):
        return f"{value:g}"


def segmented(options, tips, on_click):
    """A row of exclusive toggle buttons: (layout, {value: button})."""
    row = QtWidgets.QHBoxLayout()
    row.setSpacing(0)
    group = QtWidgets.QButtonGroup(row)
    buttons = {}
    for value, text in options:
        button = QtWidgets.QToolButton(text=text, checkable=True)
        button.setToolTip(tips.get(value, ""))
        button.setStyleSheet(SEGMENT_STYLE)
        button.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed)
        button.clicked.connect(lambda _=False, v=value: on_click(v))
        group.addButton(button)
        row.addWidget(button)
        buttons[value] = button
    return row, buttons


class BrushPanel(QtWidgets.QWidget):
    def __init__(self, doc, brush):
        super().__init__()
        self.doc = doc
        self.brush = brush
        grid = QtWidgets.QGridLayout(self)
        grid.setContentsMargins(8, 6, 8, 6)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(1, 1)

        def label(text):
            widget = QtWidgets.QLabel(text)
            widget.setStyleSheet("color: #aaa")
            return widget

        row, self.mode_buttons = segmented([(t, f"{t.capitalize()}") for t in TOOLS],
                                           {t: f"{MODE_TIPS[t]} ({TOOL_KEYS[t]})" for t in TOOLS}, self._set_mode)
        self._tool = doc.tool
        self._last_brush = brush.kind if brush.kind not in SCULPT else "voxel"  # the brush a mode goes back to
        grid.addWidget(label("Mode"), 0, 0)
        grid.addLayout(row, 0, 1)
        self.mouse_label = QtWidgets.QLabel()
        self.mouse_label.setStyleSheet("color: #999")
        self.mouse_label.setToolTip("What the left button does in the 3D view and the slices; right drag orbits, "
                                    "middle drag pans")
        paints_row, self.paint_buttons = segmented(
            [("both", "Colour + material"), ("colour", "Colour"), ("material", "Material")],
            {"both": "Painting gives voxels the current colour and material",
             "colour": "Painting recolours voxels and leaves their materials",
             "material": "Painting gives voxels the current material and leaves their colours (the edit views "
                         "show materials meanwhile)"}, doc.set_paints)
        grid.addWidget(self.mouse_label, 1, 1)
        paints_label = label("Paints")
        paints_label.setToolTip("What Paint (and Ctrl + left in Attach) changes; Attach always adds both")
        grid.addWidget(paints_label, 2, 0)
        grid.addLayout(paints_row, 2, 1)
        row, self.kind_buttons = segmented([("voxel", "Voxel"), ("face", "Face"), ("box", "Box"),
                                            ("ellipsoid", "Ellipsoid"), ("line", "Line"), ("fill", "Fill"),
                                            ("stamp", "Stamp")],
                                           KIND_TIPS, self._set_kind)
        grid.addWidget(label("Brush"), 3, 0)
        grid.addLayout(row, 3, 1)
        sculpt_row, sculpt_buttons = segmented([(k, k.capitalize()) for k in SCULPT], KIND_TIPS, self._set_kind)
        group = self.kind_buttons["voxel"].group()
        for button in sculpt_buttons.values():
            group.addButton(button)  # one choice across both rows
        self.kind_buttons.update(sculpt_buttons)
        grid.addWidget(label("Sculpt"), 4, 0)
        grid.addLayout(sculpt_row, 4, 1)

        # the voxel brush's options
        voxel = QtWidgets.QWidget()
        options = QtWidgets.QGridLayout(voxel)
        options.setContentsMargins(0, 0, 0, 0)
        self.size_slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal, minimum=1, maximum=MAX_SIZE)
        self.size_box = QtWidgets.QSpinBox(minimum=1, maximum=MAX_SIZE, suffix=" vx")
        for widget in (self.size_slider, self.size_box):
            widget.setToolTip("Brush width in voxels ([ and ] in the 3D view)")
            widget.valueChanged.connect(lambda v: self.brush.set(size=v))
        options.addWidget(label("Size"), 0, 0)
        options.addWidget(self.size_slider, 0, 1)
        options.addWidget(self.size_box, 0, 2)
        shape_row, self.shape_buttons = segmented([(False, "■ Square"), (True, "● Circle")],
                                                  {False: "Square / cube", True: "Circle / sphere"},
                                                  lambda v: self.brush.set(round=v))
        dims_row, self.dims_buttons = segmented([(False, "2D"), (True, "3D")],
                                                {False: "Flat, across the clicked face",
                                                 True: "A volume: cube or sphere"},
                                                lambda v: self.brush.set(volume=v))
        options.addWidget(label("Shape"), 1, 0)
        shapes = QtWidgets.QHBoxLayout()
        shapes.addLayout(shape_row, 2)
        shapes.addSpacing(8)
        shapes.addLayout(dims_row, 1)
        options.addLayout(shapes, 1, 1, 1, 2)

        def note(text=""):
            widget = QtWidgets.QLabel(text)
            widget.setWordWrap(True)
            widget.setStyleSheet("color: #999")
            return widget

        # the ellipsoid brush's height
        ellipsoid = QtWidgets.QWidget()
        options = QtWidgets.QGridLayout(ellipsoid)
        options.setContentsMargins(0, 0, 0, 0)
        self.height_box = QtWidgets.QSpinBox(minimum=0, maximum=MAX_SIZE, suffix=" vx", specialValueText="auto")
        self.height_box.setToolTip("Layers along the face's normal; auto: the rectangle's shorter side")
        self.height_box.valueChanged.connect(lambda v: self.brush.set(height=v))
        options.addWidget(label("Height"), 0, 0)
        options.addWidget(self.height_box, 0, 1)
        options.addWidget(note(KIND_TIPS["ellipsoid"] + "."), 1, 0, 1, 3)
        options.setColumnStretch(2, 1)

        # the fill brush's reach, what it spreads through, and how near a colour counts
        fill = QtWidgets.QWidget()
        options = QtWidgets.QGridLayout(fill)
        options.setContentsMargins(0, 0, 0, 0)
        scope_row, self.scope_buttons = segmented([("connected", "Connected"), ("layer", "Layer"),
                                                   ("model", "Whole model")], SCOPE_TIPS,
                                                  lambda v: self.brush.set(fill_scope=v))
        match_row, self.match_buttons = segmented([("colour", "Colour"), ("colour and material", "+ material"),
                                                   ("solid", "Any")], MATCH_TIPS,
                                                  lambda v: self.brush.set(fill_match=v))
        self.diagonal_box = QtWidgets.QCheckBox("Diagonal")
        self.diagonal_box.setToolTip("Voxels touching only at an edge or a corner count as connected too")
        self.diagonal_box.toggled.connect(lambda on: self.brush.set(fill_diagonal=on))
        self.tolerance_box = QtWidgets.QDoubleSpinBox(minimum=0, maximum=MAX_TOLERANCE, decimals=0,
                                                      specialValueText="exact", prefix="ΔE ")
        self.tolerance_box.setToolTip("Colours this close to the clicked one (CIEDE2000) fill with it; "
                                      "exact: its colour only")
        self.tolerance_box.valueChanged.connect(lambda v: self.brush.set(fill_tolerance=v))
        options.addWidget(label("Reach"), 0, 0)
        options.addLayout(scope_row, 0, 1, 1, 2)
        options.addWidget(label("Match"), 1, 0)
        options.addLayout(match_row, 1, 1, 1, 2)
        options.addWidget(self.tolerance_box, 2, 1)
        options.addWidget(self.diagonal_box, 2, 2)
        options.addWidget(note("Attach fills an enclosed hollow; one open to the box's sides (the floor "
                               "closes it) is left alone."), 3, 0, 1, 3)
        options.setColumnStretch(1, 1)

        self.stamp_note = note()
        self.options = QtWidgets.QStackedWidget()
        self.options.addWidget(voxel)
        self.options.addWidget(note(KIND_TIPS["face"] + "."))
        self.options.addWidget(note(KIND_TIPS["box"] + "."))
        self.options.addWidget(ellipsoid)
        self.options.addWidget(self.stamp_note)
        self.options.addWidget(fill)
        grid.addWidget(self.options, 5, 0, 1, 2)

        row, self.mirror_buttons = QtWidgets.QHBoxLayout(), []
        row.setSpacing(0)
        for axis in "XYZ":
            button = QtWidgets.QToolButton(text=axis, checkable=True)
            button.setToolTip(f"Repeat every edit mirrored in {axis.lower()}, across the plane set below "
                              "(the model's centre by default)")
            button.setStyleSheet(SEGMENT_STYLE)
            button.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed)
            button.toggled.connect(self._set_mirror)
            row.addWidget(button)
            self.mirror_buttons.append(button)
        grid.addWidget(label("Mirror"), 6, 0)
        grid.addLayout(row, 6, 1)
        # where each axis mirrors: the centre, or a voxel coordinate in half steps (12: through voxel 12's
        # centre, 12.5: between voxels 12 and 13)
        row, self.plane_boxes, self.plane_pick_buttons = QtWidgets.QHBoxLayout(), [], []
        row.setSpacing(2)
        for a, axis in enumerate("xyz"):
            box = HalfSpinBox()
            box.setToolTip(f"The {axis} mirror's plane: centre (the model's), or an {axis} in half voxels "
                           f"(12: through voxel 12, 12.5: between 12 and 13)")
            box.valueChanged.connect(lambda v, a=a: self._set_plane(a, None if v < 0 else round(2 * v)))
            pick = QtWidgets.QToolButton(text="⌖")
            pick.setToolTip(f"Mirror {axis} through the voxel last picked (Alt + left), and turn it on")
            pick.clicked.connect(lambda _=False, a=a: self.plane_to_picked(a))
            row.addWidget(box, 1)
            row.addWidget(pick)
            if a < 2:
                row.addSpacing(6)
            self.plane_boxes.append(box)
            self.plane_pick_buttons.append(pick)
        grid.addWidget(label("Plane"), 7, 0)
        grid.addLayout(row, 7, 1)
        grid.setRowStretch(8, 1)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Preferred, QtWidgets.QSizePolicy.Policy.Maximum)

        brush.changed.connect(self.refresh)
        doc.current_changed.connect(self.refresh)
        doc.resized.connect(self.refresh)
        doc.reset.connect(self.refresh)
        self.refresh()

    def _set_kind(self, kind):
        if kind in SCULPT and self.doc.tool in ("pick", "protect"):  # where a sculpting brush would do nothing
            self.doc.set_tool("attach")
        if kind == "stamp" and self.brush.stamp is None:
            self.refresh()  # nothing to stamp yet: the note says how
            self.options.setCurrentIndex(PAGES.index("stamp"))
            return
        self.brush.set(kind=kind)

    def _set_mode(self, tool):
        """A mode chosen: its strokes, so a sculpting brush gives way to the brush used before it."""
        self.doc.set_tool(tool)
        if self.brush.kind in SCULPT:
            self.brush.set(kind=self._last_brush)
        self.refresh()

    def _set_mirror(self):
        self.brush.set(mirror=[b.isChecked() for b in self.mirror_buttons])

    def _set_plane(self, axis: int, doubled):
        planes = list(self.brush.mirror_plane)
        planes[axis] = doubled
        self.brush.set(mirror_plane=planes)

    def plane_to_picked(self, axis: int):
        """Mirror on this axis through the voxel last picked, the mirror turned on."""
        if self.doc.picked is None:
            return
        self._set_plane(axis, 2 * self.doc.picked[axis])
        mirror = list(self.brush.mirror)
        mirror[axis] = True
        self.brush.set(mirror=mirror)

    def refresh(self):
        b = self.brush
        tool = self.doc.tool
        if tool != self._tool:  # a mode's key while sculpting: back to painting, attaching, ...
            self._tool = tool
            if b.kind in SCULPT:
                self.brush.set(kind=self._last_brush)  # refreshes again
                return
        if b.kind not in SCULPT:
            self._last_brush = b.kind
        self.paint_buttons[self.doc.paints].setChecked(True)
        modes = self.mode_buttons[tool].group()
        modes.setExclusive(False)  # none shows as chosen while a sculpting brush ignores the mode
        for name, button in self.mode_buttons.items():
            button.setChecked(name == tool and b.kind not in SCULPT)
        modes.setExclusive(True)
        if b.kind in SCULPT:
            swapped = {"erode": "grow", "grow": "erode"}.get(b.kind)
            self.mouse_label.setText(f"Left: {b.kind}" + (f" · Shift: {swapped}" if swapped else "") +
                                     " · Alt: pick")
        elif tool == "pick":
            self.mouse_label.setText("Left: pick")
        elif tool == "protect":
            self.mouse_label.setText("Left: protect · Shift: unprotect · Alt: pick")
        else:
            self.mouse_label.setText(f"Left: {tool} · Shift: {mode_for(tool, shift=True)} · "
                                     f"Ctrl: {mode_for(tool, ctrl=True)} · Alt: pick")
        self.kind_buttons[b.kind].setChecked(True)
        page = "voxel" if b.kind in SIZED else b.kind  # sculpting and lines take the voxel brush's size and shape
        self.options.setCurrentIndex(PAGES.index(page))
        for widget, value in ((self.size_slider, b.size), (self.size_box, b.size), (self.height_box, b.height),
                              (self.tolerance_box, b.fill_tolerance)):
            widget.blockSignals(True)
            widget.setValue(value)
            widget.blockSignals(False)
        self.scope_buttons[b.fill_scope].setChecked(True)
        self.match_buttons[b.fill_match].setChecked(True)
        self.diagonal_box.blockSignals(True)
        self.diagonal_box.setChecked(b.fill_diagonal)
        self.diagonal_box.blockSignals(False)
        self.tolerance_box.setEnabled(b.fill_match != "solid")
        self.shape_buttons[b.round].setChecked(True)
        self.dims_buttons[b.volume].setChecked(True)
        for button, on in zip(self.mirror_buttons, b.mirror):
            button.blockSignals(True)
            button.setChecked(on)
            button.blockSignals(False)
        for a, (box, pick) in enumerate(zip(self.plane_boxes, self.plane_pick_buttons)):
            plane = b.mirror_plane[a]
            box.blockSignals(True)
            box.setRange(-0.5, self.doc.size[a] - 1)
            box.setValue(-0.5 if plane is None else plane / 2)
            box.blockSignals(False)
            pick.setEnabled(self.doc.picked is not None)
        if b.stamp is None:
            self.stamp_note.setText("No stamp yet: select a model or an instance in the Project dock, then "
                                    "Use as brush.")
        else:
            name, model, orient = b.stamp
            x, y, z = placed_size(model.colour.shape[::-1], orient)
            self.stamp_note.setText(f"<b>{name}</b> · {x}×{y}×{z}<br>R turns it (Shift+R back), Esc stops. "
                                    "Attach adds it, paint gives its colours to what is there, erase carves "
                                    "its shape.")
