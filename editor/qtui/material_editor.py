"""Material editor: create materials and tune them live in the render dock, then save the table.

Each field says how the renderer reads it today (material_rules.py):
used (the value matters), switch (only which side of a threshold) or ignored.
Edits and new materials stay in this session until "Save materials", which
writes them into palette/build_materials.py (the table's source), rebuilds
materials.json and restamps the models in assets/ (palette/material_source.py).
Materials are only ever added, never removed, so every id keeps its meaning.
"""
from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from qtui.material_rules import DEFAULTS, IGNORED, SWITCH, USED, reading, table_row
from voxel_renderer import LIGHT_STYLE

# field: (low, high on the slider, step, highest the box allows)
SLIDERS = {
    "roughness": (0.0, 1.0, 0.01, 1.0),
    "metal": (0.0, 1.0, 0.01, 1.0),
    "emission": (0.0, 8.0, 0.05, 32.0),
    "transmission": (0.0, 1.0, 0.01, 1.0),
    "density": (0.25, 32.0, 0.25, 256.0),
    "subsurface": (0.0, 1.0, 0.01, 1.0),
    "sss": (0.0, 4.0, 0.05, 16.0),
    "sheen": (0.0, 1.0, 0.01, 1.0),
    "ior": (1.0, 2.5, 0.01, 3.0),
    "anisotropy": (-0.95, 0.95, 0.01, 0.95),
}
LABELS = {"sss": "subsurface depth"}  # sss is how deep subsurface light travels; subsurface is how much
STATUS_STYLE = {USED: "color: white; background: #3c8c50", SWITCH: "color: white; background: #b4821e",
                IGNORED: "color: #777; background: #ddd"}


class FieldRow:
    def __init__(self, editor: "MaterialEditor", field: str, grid: QtWidgets.QGridLayout, row: int):
        self.editor = editor
        self.field = field
        self.lo, self.hi, self.step, top = SLIDERS[field]
        self.label = QtWidgets.QLabel(LABELS.get(field, field))
        self.slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.slider.setRange(0, round((self.hi - self.lo) / self.step))
        self.box = QtWidgets.QDoubleSpinBox()
        self.box.setRange(self.lo, top)
        self.box.setSingleStep(self.step)
        self.box.setDecimals(2 if self.step >= 0.01 else 3)
        self.box.setKeyboardTracking(False)
        self.status = QtWidgets.QLabel()
        self.status.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.status.setFixedWidth(64)
        for col, widget in enumerate((self.label, self.slider, self.box, self.status)):
            grid.addWidget(widget, row, col)
        self.slider.valueChanged.connect(self._from_slider)
        self.box.valueChanged.connect(self._from_box)

    def load(self, value):
        for widget in (self.slider, self.box):
            widget.blockSignals(True)
        self.box.setValue(float(value or 0))
        self.slider.setValue(round((min(max(float(value or 0), self.lo), self.hi) - self.lo) / self.step))
        for widget in (self.slider, self.box):
            widget.blockSignals(False)

    def _from_slider(self, position):
        value = round(self.lo + position * self.step, 3)
        self.box.blockSignals(True)
        self.box.setValue(value)
        self.box.blockSignals(False)
        self.editor.set_field(self.field, value)

    def _from_box(self, value):
        value = round(value, 3)
        self.slider.blockSignals(True)
        self.slider.setValue(round((min(max(value, self.lo), self.hi) - self.lo) / self.step))
        self.slider.blockSignals(False)
        self.editor.set_field(self.field, value)

    def show_status(self, status: str, why: str):
        self.status.setText(status)
        self.status.setStyleSheet(STATUS_STYLE[status])
        self.status.setToolTip(why)
        self.label.setToolTip(why)
        self.label.setEnabled(status != IGNORED)


class MaterialEditor(QtWidgets.QWidget):
    def __init__(self, doc):
        super().__init__()
        self.doc = doc
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        table_bar = QtWidgets.QHBoxLayout()
        new_button = QtWidgets.QPushButton("New material…")
        new_button.setToolTip("One of this model's own materials (saved with the model), starting as a copy of "
                              "the current one")
        new_button.clicked.connect(self.new_material)
        self.unsaved_label = QtWidgets.QLabel()
        self.unsaved_label.setToolTip("The model's own materials are saved with the model (Ctrl+S)")
        table_bar.addWidget(new_button)
        table_bar.addWidget(self.unsaved_label, 1)
        layout.addLayout(table_bar)

        self.title = QtWidgets.QLabel()
        font = self.title.font()
        font.setBold(True)
        font.setPointSizeF(font.pointSizeF() * 1.15)
        self.title.setFont(font)
        layout.addWidget(self.title)
        self.whose_label = QtWidgets.QLabel()
        self.whose_label.setStyleSheet("color: #888")
        layout.addWidget(self.whose_label)
        names = QtWidgets.QFormLayout()
        self.name_edit = QtWidgets.QLineEdit()
        self.name_edit.editingFinished.connect(lambda: self._set_text("name", self.name_edit))
        self.group_box = QtWidgets.QComboBox()
        self.group_box.setEditable(True)
        self.group_box.setToolTip("rough, glossy, metal, emissive, transparent, subsurface, gas, fuzz, special or "
                                  "a new group; subsurface draws as scattering even without sss, gas as a volume, "
                                  "fuzz as a soft pile of fibres")
        self.group_box.lineEdit().editingFinished.connect(
            lambda: self.set_field("group", self.group_box.currentText().strip() or self.material["group"]))
        self.group_box.activated.connect(lambda _i: self.set_field("group", self.group_box.currentText()))
        self.note_edit = QtWidgets.QLineEdit()
        self.note_edit.editingFinished.connect(lambda: self._set_text("note", self.note_edit, allow_empty=True))
        names.addRow("name", self.name_edit)
        names.addRow("group", self.group_box)
        names.addRow("note", self.note_edit)
        layout.addLayout(names)
        self.reads_as = QtWidgets.QLabel()
        self.reads_as.setWordWrap(True)
        layout.addWidget(self.reads_as)

        grid = QtWidgets.QGridLayout()
        grid.setColumnStretch(1, 1)
        self.rows = {field: FieldRow(self, field, grid, i) for i, field in enumerate(SLIDERS)}
        n = len(SLIDERS)
        grid.addWidget(QtWidgets.QLabel("light"), n, 0)
        self.light_box = QtWidgets.QComboBox()
        self.light_box.addItem("(none)", "")
        for light in LIGHT_STYLE:
            self.light_box.addItem(light, light)
        self.light_box.setToolTip("A magic light: an animated emissive kind at the material's emission")
        self.light_box.currentIndexChanged.connect(lambda i: self.set_field("light", self.light_box.itemData(i)))
        grid.addWidget(self.light_box, n, 1, 1, 2)
        layout.addLayout(grid)

        buttons = QtWidgets.QHBoxLayout()
        self.revert_button = QtWidgets.QPushButton("Revert")
        self.revert_button.setToolTip("Back to materials.json's values")
        self.revert_button.clicked.connect(lambda: doc.revert_material(doc.material))
        copy_button = QtWidgets.QPushButton("Copy table row")
        copy_button.setToolTip("The material as a row of palette/build_materials.py's MATERIALS, to keep a result "
                               "(rebuild materials.json with that script)")
        copy_button.clicked.connect(self.copy_row)
        buttons.addWidget(self.revert_button)
        buttons.addWidget(copy_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        hint = QtWidgets.QLabel("Live in the Render dock; the model's own materials are saved with it (Ctrl+S; "
                                "until then they are marked * in the Materials dock). Green: the renderer uses the "
                                "value; amber: only a "
                                "threshold matters; grey: not read. Open assets/material_test.vx2 to see every "
                                "material, or give the current colour this material in the Materials dock.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #888")
        layout.addWidget(hint)
        layout.addStretch(1)

        doc.current_changed.connect(self.load)
        doc.material_edited.connect(self._edited)
        doc.tables_changed.connect(self.load)
        self.load()

    @property
    def material(self) -> dict:
        return self.doc.model.material_info(self.doc.material)

    def load(self):
        m = self.material
        for widget, text in ((self.name_edit, m["name"]), (self.note_edit, m.get("note", ""))):
            widget.blockSignals(True)
            widget.setText(text)
            widget.blockSignals(False)
        self.group_box.blockSignals(True)
        self.group_box.clear()
        self.group_box.addItems(sorted({x["group"] for x in self.doc.model.all_materials()}))
        self.group_box.setCurrentText(m["group"])
        self.group_box.blockSignals(False)
        for field, row in self.rows.items():
            row.load(m.get(field, DEFAULTS.get(field, 0)))
        self.light_box.blockSignals(True)
        self.light_box.setCurrentIndex(max(0, self.light_box.findData(m.get("light", ""))))
        self.light_box.blockSignals(False)
        self.show_reading()

    def _edited(self, material: int):
        if material == self.doc.material:
            if not self.doc.is_edited(material):
                self.load()  # reverted
            else:
                self.show_reading()

    def show_reading(self):
        m = self.material
        edited = "  (edited)" if self.doc.is_edited(m["id"]) else ""
        whose = "this model's own" if self.doc.is_own(m["id"]) else "shared: an edit makes this model's own copy"
        self.title.setText(f"{m['id']}  {m['name']}  ({m['group']}){edited}")
        self.title.setToolTip(whose)
        self.whose_label.setText(whose)
        draws, fields = reading(m)
        self.reads_as.setText(f"The renderer draws it as <b>{draws}</b>.")
        for field, row in self.rows.items():
            row.show_status(*fields[field])
        self.revert_button.setEnabled(bool(edited) and not self.doc.is_new(m["id"]))
        unsaved = self.doc.unsaved_materials()
        self.unsaved_label.setText(f"{len(unsaved)} of the model's own unsaved (Ctrl+S saves them with it)"
                                   if unsaved else "")

    def set_field(self, field, value):
        self.doc.set_material_field(self.doc.material, field, value)

    def _set_text(self, field, edit, allow_empty=False):
        text = edit.text().strip()
        if field == "name" and any(m["name"] == text for m in self.doc.model.all_materials()
                                   if m["id"] != self.doc.material):
            QtWidgets.QMessageBox.warning(self, "Material", f"Another material is already called {text!r}.")
            edit.setText(self.material["name"])
            return
        if text or allow_empty:
            self.set_field(field, text)
        else:
            edit.setText(self.material[field])

    def new_material(self):
        name, ok = QtWidgets.QInputDialog.getText(self, "New material",
                                                  f"Name (it starts as a copy of {self.material['name']!r}):")
        if not ok:
            return
        try:
            self.doc.add_material(name)
        except ValueError as error:
            QtWidgets.QMessageBox.warning(self, "New material", str(error))


    def copy_row(self):
        QtGui.QGuiApplication.clipboard().setText(table_row(self.material))
