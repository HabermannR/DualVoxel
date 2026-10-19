"""The Noise dock: the procedural tools of the API (speckle, terrain, erode, scatter) on a box of the model
open here, each run one undo step.

The box is the dock's own: two corners, the whole model to start with; a corner can take the voxel last
picked (Alt + left). While the dock is in sight the views outline the box (NoiseBox: the 3D edit view and the
slices, dashed in a slice whose layer is outside it); with "Drag box" on, a left drag in a slice sets the
box's two axes there and leaves the third (Alt + left still picks, the 3D view still draws).
Colours come from the Colours dock: "Add current" (showing the current colour) puts the current colour and
material in a list with a weight, and each takes its share of the voxels. The same seed gives the same voxels;
Reroll undoes the last run (when nothing came after it) and runs again with a new seed. The user's
protection is for the assistant, so it does not stop these.

Written for people: a line under the tool buttons says what the tool does, only its own settings show,
shares are percentages (the API takes fractions), sizes are whole voxels, and an empty colour list says what
to do or what it falls back to.

The window calls `install_noise_panel(window)` once, after its own docks.
"""
from __future__ import annotations

import random

import PySide6QtAds as QtAds
from PySide6 import QtCore, QtGui, QtWidgets

from headless_api import VoxelEditor
from qtui.brush_panel import segmented

TOOLS = (("speckle", "Speckle"), ("terrain", "Terrain"), ("erode", "Erode"), ("scatter", "Scatter"))
TOOL_TIPS = {
    "speckle": "Recolours the voxels in the box from your colours, scattered or in patches: moss, rust, dirt.",
    "terrain": "Fills the box from its floor up to rolling hills: a top layer, a few layers under it, soil "
               "below.",
    "erode": "Roughens the surface in the box: takes voxels away as pits, adds some as bumps.",
    "scatter": "Puts small columns on the top surface in the box: sprigs, flower dots, pebbles.",
}
FIELD_WIDTH = 150  # number fields keep this width however wide the dock is
BOX_WIDTH = 110  # the box's corner fields and buttons (up to 255)
NO_COLOURS = "None yet: choose a colour in the Colours dock, then Add current."


def run(doc, op: str, **args) -> int:
    """One of VoxelEditor's noise ops on the document's model, as one undo step: the voxels it changed."""
    editor = VoxelEditor(doc.model)  # protection starts empty: the user's own protection is for the assistant
    changed = getattr(editor, op)(**args)["changed_voxels"]
    if changed:
        doc.changed.emit()
    return changed


def swatch(rgb, size: int = 14) -> QtGui.QIcon:
    pixmap = QtGui.QPixmap(size, size)
    pixmap.fill(QtGui.QColor(*[int(v) for v in rgb]))
    return QtGui.QIcon(pixmap)


def spin(low, high, value, step=None, decimals=None, tip="", suffix="", special="", unit=""):
    """A number field FIELD_WIDTH wide; `special` is shown instead of the lowest value; `unit` ("voxel") is
    counted after the number: 1 voxel, 2 voxels."""
    box = QtWidgets.QDoubleSpinBox() if decimals is not None else QtWidgets.QSpinBox()
    if decimals is not None:
        box.setDecimals(decimals)
    box.setRange(low, high)
    if step is not None:
        box.setSingleStep(step)
    box.setSuffix(suffix)
    if unit:
        box.valueChanged.connect(lambda v: box.setSuffix(f" {unit}" if v == 1 else f" {unit}s"))
    box.setValue(value)
    box.setSuffix(suffix or (f" {unit}" if value == 1 else f" {unit}s" if unit else ""))
    box.setSpecialValueText(special)
    box.setToolTip(tip)
    box.setFixedWidth(FIELD_WIDTH)
    return box


def percent(value, tip=""):
    """A share as a percentage, 0-100 % (the API takes value / 100)."""
    return spin(0, 100, value, 1, 1, tip, " %")


def hint(text: str) -> QtWidgets.QLabel:
    label = QtWidgets.QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet("color: #888")
    return label


class ColourList(QtWidgets.QWidget):
    """Colours with weights, from the Colours dock's current colour and material: [[colour, weight,
    material], ...] for the API. Empty when nothing was added (`optional` lists then repeat another); `empty`
    says so under the title while it is."""

    def __init__(self, doc, title: str, tip: str = "", empty: str = NO_COLOURS):
        super().__init__()
        self.doc = doc
        self.rows = []  # [slot, material, weight box, row widget]
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        head = QtWidgets.QHBoxLayout()
        label = QtWidgets.QLabel(f"<b>{title}</b>")
        label.setToolTip(tip)
        head.addWidget(label, 1)
        self.add_button = QtWidgets.QPushButton("Add current")
        self.add_button.setToolTip("Add the Colours dock's current colour (the swatch), with the current material")
        self.add_button.clicked.connect(self.add_current)
        head.addWidget(self.add_button)
        layout.addLayout(head)
        self.empty = hint(empty)
        layout.addWidget(self.empty)
        self.list_layout = QtWidgets.QVBoxLayout()
        self.list_layout.setSpacing(1)
        layout.addLayout(self.list_layout)
        doc.colours_changed.connect(self.refresh)
        doc.reset.connect(self.refresh)
        doc.current_changed.connect(self._show_current)
        self._show_current()

    def _show_current(self) -> None:
        self.add_button.setIcon(swatch(self.doc.rgb[self.doc.colour]))

    def add_current(self) -> None:
        self.add(self.doc.colour, self.doc.material)

    def add(self, slot: int, material: int = 0, weight: float = 1.0) -> None:
        for row in self.rows:
            if row[0] == slot and row[1] == material:
                row[2].setValue(row[2].value() + weight)
                return
        widget = QtWidgets.QWidget()
        line = QtWidgets.QHBoxLayout(widget)
        line.setContentsMargins(0, 0, 0, 0)
        name = QtWidgets.QToolButton()
        name.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        name.setAutoRaise(True)
        name.setToolTip("Make this the current colour and material")
        name.clicked.connect(lambda: (self.doc.set_colour(slot), self.doc.set_material(material)))
        line.addWidget(name)
        weight_box = spin(0.01, 1000, weight, 0.5, 2, "Its weight: its share against the others")
        line.addWidget(weight_box)
        remove = QtWidgets.QToolButton(text="×")
        remove.setAutoRaise(True)
        remove.setToolTip("Take it off the list")
        line.addWidget(remove)
        line.addStretch(1)  # the row stays together on the left
        row = [slot, material, weight_box, widget, name]
        remove.clicked.connect(lambda: self._remove(row))
        self.rows.append(row)
        self.list_layout.addWidget(widget)
        self.refresh()

    def _remove(self, row) -> None:
        self.rows.remove(row)
        row[3].deleteLater()
        self.empty.setVisible(not self.rows)

    def clear(self) -> None:
        for row in list(self.rows):
            self._remove(row)

    def refresh(self) -> None:
        self.empty.setVisible(not self.rows)
        self._show_current()
        model = self.doc.model
        for slot, material, _, _, name in self.rows:
            known = 1 <= slot <= len(model.colors)
            name.setIcon(swatch(self.doc.rgb[slot] if known else (0, 0, 0)))
            material_name = model.material_info(material)["name"] if model.has_material(material) else "?"
            name.setText(f"{slot}  {material_name}")

    def entries(self) -> list:
        return [[slot, weight.value(), material] for slot, material, weight, _, _ in self.rows]

    def slots(self) -> list[int]:
        return [row[0] for row in self.rows]


class NoiseBox(QtCore.QObject):
    """The Noise dock's box, for the views to show and set: two corners (x, y, z), both ends included, in any
    order; `shown` while the dock is in sight, `dragging` while "Drag box" is on."""
    changed = QtCore.Signal()
    COLOUR = (70, 200, 255)

    def __init__(self):
        super().__init__()
        self.start, self.end = (0, 0, 0), (0, 0, 0)
        self.shown = False
        self.dragging = False

    def set(self, start, end) -> None:
        start, end = tuple(int(v) for v in start), tuple(int(v) for v in end)
        if (start, end) != (self.start, self.end):
            self.start, self.end = start, end
            self.changed.emit()

    def bounds(self):
        """(low, high) corners, (x, y, z) inclusive."""
        return tuple(map(min, self.start, self.end)), tuple(map(max, self.start, self.end))

    def set_shown(self, shown: bool) -> None:
        if shown != self.shown:
            self.shown = shown
            self.changed.emit()

    def set_dragging(self, on: bool) -> None:
        if on != self.dragging:
            self.dragging = on
            self.changed.emit()

    @property
    def drags(self) -> bool:
        """A left drag in a slice sets the box instead of drawing."""
        return self.shown and self.dragging


class NoisePanel(QtWidgets.QWidget):
    def __init__(self, doc):
        super().__init__()
        self.doc = doc
        self.tool = "speckle"
        self._last = None  # (model, version) after the last run, for Reroll
        self.region = NoiseBox()  # the box as the views see it; the spin boxes and it follow each other
        self.region.changed.connect(self._region_changed)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(8)
        tools, self.tool_buttons = segmented(TOOLS, TOOL_TIPS, self.set_tool)
        layout.addLayout(tools)
        self.about = hint("")  # what the current tool does
        layout.addWidget(self.about)

        layout.addWidget(self._box_group())
        self.page = {}  # only the current tool's page shows, so no page keeps room for a taller one
        for name, build in (("speckle", self._speckle_page), ("terrain", self._terrain_page),
                            ("erode", self._erode_page), ("scatter", self._scatter_page)):
            self.page[name] = build()
            layout.addWidget(self.page[name])

        bottom = QtWidgets.QHBoxLayout()
        bottom.addWidget(QtWidgets.QLabel("Seed"))
        self.seed = spin(0, 999_999, 0, tip="The same seed gives the same voxels; Reroll picks a new one")
        self.seed.setFixedWidth(BOX_WIDTH)
        bottom.addWidget(self.seed)
        bottom.addStretch(1)
        self.reroll_button = QtWidgets.QPushButton("Reroll")
        self.reroll_button.setToolTip("Undo the last run (when nothing came after it) and run again with a new seed")
        self.reroll_button.clicked.connect(self.reroll)
        bottom.addWidget(self.reroll_button)
        self.apply_button = QtWidgets.QPushButton("Apply")
        self.apply_button.setToolTip("Run it on the box: one undo step")
        self.apply_button.setStyleSheet("font-weight: bold")
        self.apply_button.clicked.connect(self.apply)
        bottom.addWidget(self.apply_button)
        layout.addLayout(bottom)
        self.status = hint("")
        layout.addWidget(self.status)
        layout.addStretch(1)

        doc.reset.connect(self._model_reset)
        doc.resized.connect(self._model_reset)
        self._model_reset()
        self.set_tool("speckle")

    # --- the box -------------------------------------------------------------------------------
    def _box_group(self):
        """x, y, z rows of from – to, each corner's Picked under it, then Whole model, Drag box and the box's
        size; spare width stays on the right."""
        group = QtWidgets.QGroupBox("Box")
        grid = QtWidgets.QGridLayout(group)
        grid.setContentsMargins(8, 4, 8, 6)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(4)
        self.corner = {"from": [], "to": []}
        for column, name in ((1, "from"), (3, "to")):
            grid.addWidget(QtWidgets.QLabel(name), 0, column)
        for row, axis in enumerate("xyz", start=1):
            grid.addWidget(QtWidgets.QLabel(axis), row, 0)
            grid.addWidget(QtWidgets.QLabel("–"), row, 2)
            for column, name in ((1, "from"), (3, "to")):
                box = QtWidgets.QSpinBox()
                box.setToolTip(f"The box's {'first' if name == 'from' else 'second'} corner, {axis}; "
                               "both ends included")
                box.setFixedWidth(BOX_WIDTH)
                box.valueChanged.connect(lambda _: self.region.set(*self.box()))
                grid.addWidget(box, row, column)
                self.corner[name].append(box)
        for column, name in ((1, "from"), (3, "to")):
            pick = QtWidgets.QPushButton("Picked")
            pick.setToolTip(f"The {name} corner at the voxel last picked (Alt + left in a view)")
            pick.setFixedWidth(BOX_WIDTH)
            pick.clicked.connect(lambda _=False, n=name: self.corner_to_picked(n))
            grid.addWidget(pick, 4, column)
        whole = QtWidgets.QPushButton("Whole model")
        whole.setToolTip("The box around the whole model")
        whole.setFixedWidth(BOX_WIDTH)
        whole.clicked.connect(self.whole_model)
        grid.addWidget(whole, 5, 1)
        self.drag_button = QtWidgets.QPushButton("Drag box", checkable=True)
        self.drag_button.setToolTip("While on, a left drag in the Front, Side or Top view sets the box's two axes "
                                    "in that view; the third stays. Alt + left still picks")
        self.drag_button.setFixedWidth(BOX_WIDTH)
        self.drag_button.toggled.connect(self.region.set_dragging)
        grid.addWidget(self.drag_button, 5, 3)
        self.box_size = hint("")  # how big the box is
        grid.addWidget(self.box_size, 6, 0, 1, 5)
        grid.setColumnStretch(4, 1)
        return group

    def _show_box_size(self) -> None:
        lo, hi = self.region.bounds()
        x, y, z = (h - l + 1 for l, h in zip(lo, hi))
        whole = " (the whole model)" if (x, y, z) == tuple(self.doc.size) else ""
        self.box_size.setText(f"{x} × {y} × {z} voxels{whole}")

    def box(self):
        """(start, end), (x, y, z) inclusive."""
        return [b.value() for b in self.corner["from"]], [b.value() for b in self.corner["to"]]

    def set_box(self, start, end) -> None:
        self._write_corners(start, end)
        self.region.set(*self.box())

    def _write_corners(self, start, end) -> None:
        for boxes, point in ((self.corner["from"], start), (self.corner["to"], end)):
            for box, value in zip(boxes, point):
                box.blockSignals(True)  # one region change for the lot, not one a spin box
                box.setValue(int(value))
                box.blockSignals(False)

    def _region_changed(self) -> None:
        """A view set the box: the spin boxes follow (clamped to the model)."""
        if (tuple(self.box()[0]), tuple(self.box()[1])) != (self.region.start, self.region.end):
            self.set_box(self.region.start, self.region.end)
        self._show_box_size()

    def showEvent(self, event):
        super().showEvent(event)
        self.region.set_shown(True)

    def hideEvent(self, event):
        super().hideEvent(event)
        self.region.set_shown(False)

    def whole_model(self) -> None:
        self.set_box((0, 0, 0), [n - 1 for n in self.doc.size])

    def corner_to_picked(self, name: str) -> None:
        picked = self.doc.picked
        if picked is None:
            self.status.setText("Pick a voxel first (Alt + left in a view).")
            return
        for box, value in zip(self.corner[name], picked):
            box.setValue(value)

    def _model_reset(self) -> None:
        for boxes in self.corner.values():
            for box, size in zip(boxes, self.doc.size):
                box.setRange(0, size - 1)
        self.whole_model()
        self._show_box_size()  # also when the box came out as it was
        self._last = None

    # --- each tool's options ------------------------------------------------------------------
    @staticmethod
    def _form():
        """A tool's page: label and field rows, the fields at their own width."""
        page = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(page)
        form.setContentsMargins(0, 0, 0, 0)
        form.setFieldGrowthPolicy(QtWidgets.QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)
        form.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        return page, form

    def _speckle_page(self):
        page, form = self._form()
        self.speckle_colours = ColourList(self.doc, "Colours", "Each takes its share of the voxels recoloured")
        form.addRow(self.speckle_colours)
        self.speckle_scale = spin(0, 256, 0, tip="Single voxels, or each colour gathered into patches about this "
                                                 "many voxels across", unit="voxel", special="single voxels")
        form.addRow("Patch size", self.speckle_scale)
        self.speckle_surface = QtWidgets.QCheckBox("Surface only")
        self.speckle_surface.setChecked(True)
        self.speckle_surface.setToolTip("Only voxels with an empty neighbour; the inside stays as it is")
        form.addRow(self.speckle_surface)
        self.speckle_only = QtWidgets.QCheckBox("Only on the current colour")
        self.speckle_only.setToolTip("Only voxels of the colour current when you apply (moss on grass)")
        form.addRow(self.speckle_only)
        return page

    def _terrain_page(self):
        page, form = self._form()
        self.terrain_top = ColourList(self.doc, "Top", "The top layer: grass, sand, snow")
        self.terrain_under = ColourList(self.doc, "Under", "The layers under the top",
                                        "None: the Top colours go on down.")
        self.terrain_soil = ColourList(self.doc, "Soil", "The rest down to the box's floor",
                                       "None: the Under colours go on down.")
        for colours in (self.terrain_top, self.terrain_under, self.terrain_soil):
            form.addRow(colours)
        self.terrain_depth = spin(0, 256, 1, tip="How many layers under the top take the Under colours",
                                  unit="layer")
        form.addRow("Under depth", self.terrain_depth)
        self.terrain_scale = spin(1, 256, 12, tip="How wide the hills are", unit="voxel")
        form.addRow("Hill size", self.terrain_scale)
        self.terrain_octaves = spin(1, 8, 3, tip="1 gives smooth hills; each step more adds smaller hills on the "
                                                 "larger (octaves)")
        form.addRow("Detail", self.terrain_octaves)
        form.addRow(hint("The hills reach the box's top, so a flat box gives gentle ground. Everything in the box "
                         "at or below the ground becomes ground; what is above it stays."))
        return page

    def _erode_page(self):
        page, form = self._form()
        self.erode_pits = percent(15, "How many of the surface voxels are taken away")
        form.addRow("Pits", self.erode_pits)
        self.erode_bumps = percent(0, "How many of the voxels left grow a voxel beside or above, in their colour")
        form.addRow("Bumps", self.erode_bumps)
        self.erode_scale = spin(0, 256, 0, tip="Single pits, or pits gathered into patches about this many voxels "
                                               "across", unit="voxel", special="single voxels")
        form.addRow("Patch size", self.erode_scale)
        self.erode_bottom = QtWidgets.QCheckBox("Keep the bottom layer")
        self.erode_bottom.setChecked(True)
        self.erode_bottom.setToolTip("Leave the box's lowest layer whole, so the model still stands")
        form.addRow(self.erode_bottom)
        return page

    def _scatter_page(self):
        page, form = self._form()
        self.scatter_tips = ColourList(self.doc, "Tips", "The top voxel of each column: one of these")
        form.addRow(self.scatter_tips)
        self.scatter_stem = ColourList(self.doc, "Stem", "The voxels under the tip, when a column is taller than one",
                                       "None: the tip colour all the way down.")
        form.addRow(self.scatter_stem)
        self.scatter_height = spin(1, 64, 1, tip="Voxels in a column, tip included", unit="voxel")
        form.addRow("Height", self.scatter_height)
        self.scatter_random = QtWidgets.QCheckBox("Random heights")
        self.scatter_random.setToolTip("Some columns shorter, down to the tip alone")
        form.addRow(self.scatter_random)
        self.scatter_density = percent(5, "How many of the open top voxels get a column")
        form.addRow("Density", self.scatter_density)
        self.scatter_only = QtWidgets.QCheckBox("Only on the current colour")
        self.scatter_only.setToolTip("Only on voxels of the colour current when you apply (flowers on the grass, "
                                     "not on the path)")
        form.addRow(self.scatter_only)
        return page

    def set_tool(self, tool: str) -> None:
        self.tool = tool
        self.tool_buttons[tool].setChecked(True)
        for name, page in self.page.items():
            page.setVisible(name == tool)
        self.about.setText(f"{TOOL_TIPS[tool]} Apply runs it once over everything in the box.")

    # --- running --------------------------------------------------------------------------------
    def arguments(self) -> tuple[str, dict]:
        """(the API op, its arguments) from the dock; ValueError says what is missing."""
        start, end = self.box()
        common = {"start": start, "end": end, "seed": self.seed.value()}
        if self.tool == "speckle":
            colours = self.speckle_colours.entries()
            if not colours:
                raise ValueError("Add a colour to speckle with (Add current).")
            return "speckle", {**common, "colours": colours, "scale": self.speckle_scale.value(),
                               "surface_only": self.speckle_surface.isChecked(),
                               "only_colour": self.doc.colour if self.speckle_only.isChecked() else None}
        if self.tool == "terrain":
            top = self.terrain_top.entries()
            if not top:
                raise ValueError("Add a colour for the top layer (Add current).")
            return "noise_terrain", {**common, "top": top, "under": self.terrain_under.entries() or None,
                                     "soil": self.terrain_soil.entries() or None,
                                     "under_depth": self.terrain_depth.value(),
                                     "scale": self.terrain_scale.value(), "octaves": self.terrain_octaves.value()}
        if self.tool == "erode":
            return "erode_surface", {**common, "pits": self.erode_pits.value() / 100,
                                     "bumps": self.erode_bumps.value() / 100,
                                     "scale": self.erode_scale.value(), "keep_bottom": self.erode_bottom.isChecked()}
        tips = self.scatter_tips.entries()
        if not tips:
            raise ValueError("Add a colour for the tips (Add current).")
        stems = self.scatter_stem.entries()
        height = self.scatter_height.value()
        options = []
        for tip_slot, weight, tip_material in tips:
            below = [[slot, material] for slot, _, material in stems] or [[tip_slot, tip_material]]
            # a column per stem colour, the tip's weight shared between them
            for slot, material in below:
                options.append({"weight": weight / len(below), "random_height": self.scatter_random.isChecked(),
                                "stack": [[slot, material]] * (height - 1) + [[tip_slot, tip_material]]})
        return "scatter", {**common, "options": options, "density": self.scatter_density.value() / 100,
                           "on_colours": [self.doc.colour] if self.scatter_only.isChecked() else None}

    def apply(self) -> int | None:
        try:
            op, args = self.arguments()
            changed = run(self.doc, op, **args)
        except ValueError as error:
            self.status.setText(str(error))
            return None
        model = self.doc.model
        self._last = (model, model.version) if changed else None
        self.status.setText(f"{dict(TOOLS)[self.tool]}: {changed} voxels changed (seed {self.seed.value()})."
                            if changed else "Nothing in the box to change.")
        return changed

    def reroll(self) -> int | None:
        model = self.doc.model
        if self._last == (model, model.version):
            self.doc.undo()
        self.seed.setValue(random.randrange(1, 1_000_000))
        return self.apply()


def install_noise_panel(window) -> NoisePanel:
    panel = NoisePanel(window.doc)
    # a tab beside the Brush dock, so the Colours dock below stays in sight while colours are added
    window._dock("Noise", panel, QtAds.DockWidgetArea.CenterDockWidgetArea, window.docks["Brush"].dockAreaWidget(),
                 scroll=True)
    window.docks["Brush"].setAsCurrentTab()
    for box_view in (window.edit_view, *window.slices.values()):
        box_view.set_region(panel.region)  # they outline the box while the dock is in sight
    view = next(m for m in window.menuBar().findChildren(QtWidgets.QMenu) if m.title() == "&View")
    first_separator = next((a for a in view.actions() if a.isSeparator()), None)  # after the docks listed
    view.insertAction(first_separator, window.docks["Noise"].toggleViewAction())
    from qtui import window as window_module
    window.default_layout = window.dock_manager.saveState(window_module.LAYOUT_VERSION)
    return panel
