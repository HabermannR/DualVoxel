"""The Render setup dock: what the model stands in and on, and how the Render dock draws.

Surroundings (core/lights.py): the sun and sky of the Light dock, or an HDR
environment that lights the model instead (an .exr from the environments
folders, or any other by EXR file…) with its strength and turn; and the floor:
the wooden table, matte, mirror, polished metal, cloth or none, in its preset's
colour and roughness or one's own. Tilt blur switches the tilt-shift band;
Pause (or F9) stops the render and frees the GPU. Only the picture changes,
never the model.
"""
from __future__ import annotations

from pathlib import Path

import PySide6QtAds as QtAds
from PySide6 import QtCore, QtWidgets

from core.lights import environment_files, environment_folders
from qtui.light_panel import ColourButton

# voxel_renderer.FLOORS as the dock lists them, with each preset's own linear colour (gpu_renderer.cpp floor())
FLOOR_CHOICES = (("wood", "Wooden table", (0.255, 0.14, 0.064)), ("matte", "Matte", (0.35, 0.37, 0.40)),
                 ("mirror", "Mirror", (0.97, 0.97, 0.97)), ("polished metal", "Polished metal", (0.72, 0.75, 0.78)),
                 ("cloth", "Cloth", (0.36, 0.40, 0.46)), ("none", "None", (0.0, 0.0, 0.0)))


def install_render_setup_panel(window) -> "RenderSetupPanel":
    panel = RenderSetupPanel(window.render_view)
    window._dock("Render setup", panel, QtAds.DockWidgetArea.CenterDockWidgetArea,
                 window.docks["Brush"].dockAreaWidget(), scroll=True)
    window.docks["Brush"].setAsCurrentTab()
    return panel


class RenderSetupPanel(QtWidgets.QWidget):
    def __init__(self, render_view):
        super().__init__()
        self.render_view = render_view
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(self._surroundings_box())
        render_row = QtWidgets.QHBoxLayout()
        self.blur_box = QtWidgets.QCheckBox("Tilt blur")
        self.blur_box.setToolTip("The tilt-shift blur above and below the model's band; off shows it sharp")
        self.blur_box.setChecked(render_view.tilt_blur)
        self.blur_box.toggled.connect(render_view.set_tilt_blur)
        self.pause_button = QtWidgets.QPushButton("Pause render", checkable=True)
        self.pause_button.setToolTip("Stop drawing and free the GPU; the last picture stays (F9)")
        self.pause_button.toggled.connect(render_view.set_paused)
        render_view.paused_changed.connect(self._show_paused)
        render_row.addWidget(self.blur_box)
        render_row.addStretch(1)
        render_row.addWidget(self.pause_button)
        layout.addLayout(render_row)
        hint = QtWidgets.QLabel("Live in the Render dock; the model's files are not touched.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #888")
        layout.addWidget(hint)
        layout.addStretch(1)

    # --- surroundings: an HDR environment and the floor --------------------------------------
    def _surroundings_box(self) -> QtWidgets.QGroupBox:
        box = QtWidgets.QGroupBox("Surroundings")
        grid = QtWidgets.QGridLayout(box)
        grid.setColumnStretch(1, 1)
        self.environment_box = QtWidgets.QComboBox()
        self.environment_box.addItem("Sun and sky (the light above)", "sky")
        for path in environment_files():  # the environments folders' (editor.local.json)
            self.environment_box.addItem(path.stem, path.name)
        self.environment_box.addItem("EXR file…", "file")
        self.environment_box.setToolTip("An HDR environment (OpenEXR) lights the model from all round instead of "
                                        f"the sun and sky above, and shows behind it. Listed: the .exr files in "
                                        f"{', '.join(str(f) for f in environment_folders())}")
        self.environment_box.activated.connect(self._environment_chosen)
        # long file names must not widen the dock
        self.environment_box.setSizeAdjustPolicy(QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.environment_box.setMinimumContentsLength(14)
        self.strength_box = QtWidgets.QDoubleSpinBox()
        self.strength_box.setRange(0, 100)
        self.strength_box.setSingleStep(0.05)
        self.strength_box.setKeyboardTracking(False)
        self.strength_box.setToolTip("The environment's strength: 1 as the file has it")
        self.strength_box.valueChanged.connect(lambda v: self._set_surroundings(strength=round(v, 3)))
        self.rotation_box = QtWidgets.QDoubleSpinBox()
        self.rotation_box.setRange(-360, 360)
        self.rotation_box.setSingleStep(5)
        self.rotation_box.setSuffix("\u00b0")
        self.rotation_box.setKeyboardTracking(False)
        self.rotation_box.setToolTip("Turn the environment about the vertical, to bring its sun or lamps round")
        self.rotation_box.valueChanged.connect(lambda v: self._set_surroundings(rotation=round(v, 2)))
        self.floor_box = QtWidgets.QComboBox()
        for key, label, _ in FLOOR_CHOICES:
            self.floor_box.addItem(label, key)
        self.floor_box.setToolTip("What the model stands on; None leaves it floating in the surroundings")
        self.floor_box.activated.connect(
            lambda i: self._set_surroundings(floor=self.floor_box.itemData(i), floor_colour=None, floor_roughness=None))
        self.floor_colour = ColourButton("Floor colour")
        self.floor_colour.changed.connect(lambda: self._set_surroundings(floor_colour=list(self.floor_colour.value)))
        self.floor_roughness = QtWidgets.QDoubleSpinBox()
        self.floor_roughness.setRange(0, 1)
        self.floor_roughness.setSingleStep(0.05)
        self.floor_roughness.setSpecialValueText("preset")  # 0: the preset's own
        self.floor_roughness.setKeyboardTracking(False)
        self.floor_roughness.setToolTip("How blurred the floor's reflections are (preset: the floor's own)")
        self.floor_roughness.valueChanged.connect(
            lambda v: self._set_surroundings(floor_roughness=round(v, 3) if v > 0 else None))
        rows = (("Environment", self.environment_box), ("Strength", self.strength_box), ("Turn", self.rotation_box),
                ("Floor", self.floor_box), ("Floor colour", self.floor_colour), ("Roughness", self.floor_roughness))
        for row, (label, widget) in enumerate(rows):
            grid.addWidget(QtWidgets.QLabel(label), row, 0)
            grid.addWidget(widget, row, 1, QtCore.Qt.AlignmentFlag.AlignLeft if widget is self.floor_colour
                           else QtCore.Qt.AlignmentFlag(0))
        self._show_surroundings()
        return box

    def _environment_chosen(self, index: int) -> None:
        key = self.environment_box.itemData(index)
        if key == "file":
            path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "HDR environment", str(environment_folders()[0]),
                                                            "OpenEXR (*.exr)")
            if not path:
                self._show_surroundings()
                return
            key = path
        self._set_surroundings(environment=key)

    def _set_surroundings(self, **changes) -> None:
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)  # an EXR takes a moment
        try:
            self.render_view.set_surroundings(**changes)
        except (OSError, ValueError, RuntimeError) as error:
            QtWidgets.QApplication.restoreOverrideCursor()
            QtWidgets.QMessageBox.warning(self, "Surroundings", str(error))
        else:
            QtWidgets.QApplication.restoreOverrideCursor()
        self._show_surroundings()

    def _show_surroundings(self) -> None:
        state = self.render_view.surroundings
        widgets = (self.environment_box, self.strength_box, self.rotation_box, self.floor_box, self.floor_roughness)
        for widget in widgets:
            widget.blockSignals(True)
        environment = state["environment"]
        index = self.environment_box.findData(environment)
        if index < 0:  # a file from elsewhere: listed by its name above "EXR file…", in place of the last one
            own = self.environment_box.count() - 1
            if self.environment_box.itemData(own - 1) and Path(self.environment_box.itemData(own - 1)).is_absolute():
                self.environment_box.removeItem(own - 1)
                own -= 1
            self.environment_box.insertItem(own, Path(environment).stem, environment)
            index = own
        self.environment_box.setCurrentIndex(index)
        self.strength_box.setValue(float(state["strength"]))
        self.rotation_box.setValue(float(state["rotation"]))
        hdr = environment != "sky"
        self.strength_box.setEnabled(hdr)
        self.rotation_box.setEnabled(hdr)
        floors = {key: colour for key, _, colour in FLOOR_CHOICES}
        self.floor_box.setCurrentIndex(self.floor_box.findData(state["floor"]))
        self.floor_colour.set_value(state["floor_colour"] or floors[state["floor"]])
        self.floor_colour.setEnabled(state["floor"] not in ("wood", "none"))  # the table's grain has its own colours
        self.floor_roughness.setValue(float(state["floor_roughness"] or 0))
        self.floor_roughness.setEnabled(state["floor"] not in ("wood", "none"))
        for widget in widgets:
            widget.blockSignals(False)

    def _show_paused(self, paused: bool) -> None:
        self.pause_button.blockSignals(True)
        self.pause_button.setChecked(paused)
        self.pause_button.blockSignals(False)
        self.pause_button.setText("Resume render" if paused else "Pause render")
