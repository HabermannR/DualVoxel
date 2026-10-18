"""The Brush dock: the mode (attach, paint, erase, pick), the brush (voxel, face, box, stamp, or a sculpting
brush: smooth, erode, grow) with its options, and mirroring, for the 3D edit view and the slices;
MagicaVoxel's brush panel, plainer. The sculpting brushes reshape what is there in the size and shape set
below, whatever the mode; Shift swaps erode and grow.

The window calls `install_brush_panel(window)` once, after its own docks.
"""
from __future__ import annotations

import PySide6QtAds as QtAds
from PySide6 import QtCore, QtWidgets

from core.brushes import MAX_SIZE
from core.scene import placed_size
from qtui.brush import SCULPT, mode_for
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
    "stamp": "A project's model: select it in the Outliner, then Use as brush",
    "smooth": "Rounds off what is in the brush: fills hollows, takes off bumps",
    "erode": "Takes the outer skin of voxels off what is in the brush (Shift: grow)",
    "grow": "Adds a skin of voxels to what is in the brush, in the colours beside it (Shift: erode)",
}
MODE_TIPS = {"attach": "Add voxels against the clicked face; never overwrites",
             "paint": "Recolour voxels that are there", "erase": "Remove voxels",
             "pick": "Take a voxel's colour and material"}


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
    QtCore.QTimer.singleShot(100, fit)
    return panel


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
                                           {t: f"{MODE_TIPS[t]} ({TOOL_KEYS[t]})" for t in TOOLS}, doc.set_tool)
        grid.addWidget(label("Mode"), 0, 0)
        grid.addLayout(row, 0, 1)
        self.mouse_label = QtWidgets.QLabel()
        self.mouse_label.setStyleSheet("color: #999")
        self.mouse_label.setToolTip("What the left button does in the 3D view and the slices; right drag orbits, "
                                    "middle drag pans")
        grid.addWidget(self.mouse_label, 1, 1)
        row, self.kind_buttons = segmented([("voxel", "Voxel"), ("face", "Face"), ("box", "Box"), ("stamp", "Stamp")],
                                           KIND_TIPS, self._set_kind)
        grid.addWidget(label("Brush"), 2, 0)
        grid.addLayout(row, 2, 1)
        sculpt_row, sculpt_buttons = segmented([(k, k.capitalize()) for k in SCULPT], KIND_TIPS, self._set_kind)
        group = self.kind_buttons["voxel"].group()
        for button in sculpt_buttons.values():
            group.addButton(button)  # one choice across both rows
        self.kind_buttons.update(sculpt_buttons)
        grid.addWidget(label("Sculpt"), 3, 0)
        grid.addLayout(sculpt_row, 3, 1)

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

        self.stamp_note = note()
        self.options = QtWidgets.QStackedWidget()
        self.options.addWidget(voxel)
        self.options.addWidget(note(KIND_TIPS["face"] + "."))
        self.options.addWidget(note(KIND_TIPS["box"] + "."))
        self.options.addWidget(self.stamp_note)
        grid.addWidget(self.options, 4, 0, 1, 2)

        row, self.mirror_buttons = QtWidgets.QHBoxLayout(), []
        row.setSpacing(0)
        for axis in "XYZ":
            button = QtWidgets.QToolButton(text=axis, checkable=True)
            button.setToolTip(f"Repeat every edit mirrored across the model's centre in {axis.lower()}")
            button.setStyleSheet(SEGMENT_STYLE)
            button.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed)
            button.toggled.connect(self._set_mirror)
            row.addWidget(button)
            self.mirror_buttons.append(button)
        grid.addWidget(label("Mirror"), 5, 0)
        grid.addLayout(row, 5, 1)
        grid.setRowStretch(6, 1)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Preferred, QtWidgets.QSizePolicy.Policy.Maximum)

        brush.changed.connect(self.refresh)
        doc.current_changed.connect(self.refresh)
        self.refresh()

    def _set_kind(self, kind):
        if kind == "stamp" and self.brush.stamp is None:
            self.refresh()  # nothing to stamp yet: the note says how
            self.options.setCurrentIndex(3)
            return
        self.brush.set(kind=kind)

    def _set_mirror(self):
        self.brush.set(mirror=[b.isChecked() for b in self.mirror_buttons])

    def refresh(self):
        b = self.brush
        self.mode_buttons[self.doc.tool].setChecked(True)
        tool = self.doc.tool
        if tool == "pick":
            self.mouse_label.setText("Left: pick")
        else:
            self.mouse_label.setText(f"Left: {tool} · Shift: {mode_for(tool, shift=True)} · "
                                     f"Ctrl: {mode_for(tool, ctrl=True)} · Alt: pick")
        self.kind_buttons[b.kind].setChecked(True)
        page = "voxel" if b.kind in SCULPT else b.kind  # sculpting takes the voxel brush's size and shape
        self.options.setCurrentIndex(("voxel", "face", "box", "stamp").index(page))
        for widget in (self.size_slider, self.size_box):
            widget.blockSignals(True)
            widget.setValue(b.size)
            widget.blockSignals(False)
        self.shape_buttons[b.round].setChecked(True)
        self.dims_buttons[b.volume].setChecked(True)
        for button, on in zip(self.mirror_buttons, b.mirror):
            button.blockSignals(True)
            button.setChecked(on)
            button.blockSignals(False)
        if b.stamp is None:
            self.stamp_note.setText("No stamp yet: select a model or an instance in the Outliner, then "
                                    "Use as brush.")
        else:
            name, model, orient = b.stamp
            x, y, z = placed_size(model.colour.shape[::-1], orient)
            self.stamp_note.setText(f"<b>{name}</b> · {x}×{y}×{z}<br>R turns it (Shift+R back), Esc stops. "
                                    "Attach adds it, paint gives its colours to what is there, erase carves "
                                    "its shape.")
