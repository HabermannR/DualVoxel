"""The Light dock: the render's sun and sky, from presets or set freely.

The window calls `install_light_panel(window)` once, after the Brush dock; the
Light dock is a tab beside it, with Render setup and Export
(render_setup_panel.py, export_panel.py) beside it in turn. A preset is a
starting point: Golden hour and Day are the renderer's built-in light, Noon,
Overcast and Night are custom lights. Moving any control makes the light
custom (renderer_set_light): the sun's direction (azimuth around, 0° along +x,
90° along +y; elevation above the table) and colour, the sky's horizon and
zenith colours and the backdrop's top and bottom (what the camera sees past
the table). Sun and Sky then scale the sun's and the sky's strength (1 each as
set, 0 none). Only the picture changes, never the model.
"""
from __future__ import annotations

import math

import PySide6QtAds as QtAds
from PySide6 import QtCore, QtGui, QtWidgets

from core.lights import PRESETS

STEP, TOP = 0.05, 3.0
CUSTOM = "Custom"
COLOURS = (("sun", "Sun colour"), ("horizon", "Sky horizon"), ("zenith", "Sky zenith"),
           ("top", "Background top"), ("bottom", "Background bottom"))


def install_light_panel(window) -> "LightPanel":
    panel = LightPanel(window.render_view)
    window._dock("Light", panel, QtAds.DockWidgetArea.CenterDockWidgetArea, window.docks["Brush"].dockAreaWidget(),
                 scroll=True)
    window.docks["Brush"].setAsCurrentTab()
    return panel


def angles(direction) -> tuple[float, float]:
    """(azimuth, elevation) in degrees of a direction towards the sun."""
    x, y, z = direction
    length = math.sqrt(x * x + y * y + z * z)
    return math.degrees(math.atan2(y, x)) % 360, math.degrees(math.asin(max(-1.0, min(1.0, z / length))))


def direction(azimuth: float, elevation: float) -> tuple[float, float, float]:
    a, e = math.radians(azimuth), math.radians(elevation)
    return math.cos(e) * math.cos(a), math.cos(e) * math.sin(a), math.sin(e)


class ColourButton(QtWidgets.QPushButton):
    """A light colour: a hue (shown, picked with the colour dialog) times a strength (kept from the preset),
    since light colours go above 1."""
    changed = QtCore.Signal()

    def __init__(self, title: str):
        super().__init__()
        self.title = title
        self.value = (1.0, 1.0, 1.0)
        self.setFixedWidth(90)
        self.clicked.connect(self.pick)

    def set_value(self, value) -> None:
        self.value = tuple(float(v) for v in value)
        hue, strength = self._split()
        self.setStyleSheet(f"background: {hue.name()}; border: 1px solid #555")
        self.setToolTip(f"{self.title}: {', '.join(f'{v:.2f}' for v in self.value)} (linear); click to change")

    def _split(self):
        strength = max(1.0, *self.value)
        shown = [min(255, round(255 * (v / strength) ** (1 / 2.2))) for v in self.value]  # as sRGB
        return QtGui.QColor(*shown), strength

    def pick(self) -> None:
        hue, strength = self._split()
        chosen = QtWidgets.QColorDialog.getColor(hue, self, self.title)
        if chosen.isValid():
            linear = [(c / 255) ** 2.2 * strength for c in (chosen.red(), chosen.green(), chosen.blue())]
            self.set_value(linear)
            self.changed.emit()



class LightPanel(QtWidgets.QWidget):
    def __init__(self, render_view):
        super().__init__()
        self.render_view = render_view
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        top = QtWidgets.QHBoxLayout()
        top.addWidget(QtWidgets.QLabel("Preset"))
        self.preset_box = QtWidgets.QComboBox()
        self.preset_box.addItems([*PRESETS, CUSTOM])
        self.preset_box.setToolTip("Golden hour and Day: the renderer's built-in light. The others are starting points.")
        self.preset_box.activated.connect(lambda i: self.choose(self.preset_box.itemText(i)))
        top.addWidget(self.preset_box, 1)
        layout.addLayout(top)

        grid = QtWidgets.QGridLayout()
        grid.setColumnStretch(1, 1)
        self.sliders, self.boxes = {}, {}
        rows = (("Sun", 0, TOP, STEP, "The sun's strength: 1 as set, 0 none"),
                ("Sky", 0, TOP, STEP, "The sky's light: 1 as set, 0 none"),
                ("Azimuth", 0, 360, 1, "Where the sun stands around the table: 0° along +x, 90° along +y"),
                ("Elevation", 1, 89, 1, "How high the sun stands above the table"))
        for row, (name, low, high, step, tip) in enumerate(rows):
            label = QtWidgets.QLabel(name)
            slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
            slider.setRange(round(low / step), round(high / step))
            box = QtWidgets.QDoubleSpinBox()
            box.setRange(low, high)
            box.setSingleStep(step)
            box.setDecimals(2 if step < 1 else 0)
            box.setKeyboardTracking(False)
            for widget in (label, slider, box):
                widget.setToolTip(tip)
            slider.valueChanged.connect(lambda v, n=name, s=step: self._moved(n, v * s))
            box.valueChanged.connect(lambda v, n=name: self._moved(n, v))
            grid.addWidget(label, row, 0)
            grid.addWidget(slider, row, 1)
            grid.addWidget(box, row, 2)
            self.sliders[name], self.boxes[name] = (slider, step), box
        layout.addLayout(grid)

        colours = QtWidgets.QGridLayout()
        self.colour_buttons = {}
        for i, (key, title) in enumerate(COLOURS):
            button = ColourButton(title)
            button.changed.connect(self._custom)
            colours.addWidget(QtWidgets.QLabel(title), i, 0)
            colours.addWidget(button, i, 1)
            self.colour_buttons[key] = button
        colours.setColumnStretch(2, 1)
        layout.addLayout(colours)

        buttons = QtWidgets.QHBoxLayout()
        reset = QtWidgets.QPushButton("Default light")
        reset.setToolTip("The built-in golden hour at its own strength")
        reset.clicked.connect(lambda: (self.set_strength(1.0, 1.0), self.choose("Golden hour")))
        night = QtWidgets.QPushButton("Lights off")
        night.setToolTip("Sun and sky off, to see what glows on its own")
        night.clicked.connect(lambda: self.set_strength(0.0, 0.0))
        buttons.addWidget(reset)
        buttons.addWidget(night)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        hint = QtWidgets.QLabel("Live in the Render dock; the model's files are not touched. An HDR environment "
                                "(Render setup) lights the model in place of this sun and sky.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #888")
        layout.addWidget(hint)
        layout.addStretch(1)

        self.choose("Golden hour" if render_view.golden else "Day")
        self._show_strength(render_view.sun, render_view.sky)

    # --- presets and the custom light ------------------------------------------------------
    def choose(self, name: str) -> None:
        """Load a preset into the controls and the render (Custom keeps what is set)."""
        if name not in PRESETS:
            return
        golden, sun_dir, sun, horizon, zenith, top, bottom = PRESETS[name]
        azimuth, elevation = angles(sun_dir)
        self._show_number("Azimuth", azimuth)
        self._show_number("Elevation", elevation)
        for key, value in zip(("sun", "horizon", "zenith", "top", "bottom"), (sun, horizon, zenith, top, bottom)):
            self.colour_buttons[key].set_value(value)
        self._direction = sun_dir  # the preset's own vector, so the built-in values stay exact
        self.preset_box.setCurrentText(name)
        if golden is not None:
            self.render_view.set_light(None, golden=golden)  # the built-in light, exactly
        else:
            self.render_view.set_light(self.values(), golden=False)

    def values(self) -> list[float]:
        b = self.colour_buttons
        return [*self._direction, *b["sun"].value, *b["horizon"].value, *b["zenith"].value, *b["top"].value,
                *b["bottom"].value]

    def _custom(self) -> None:
        self.preset_box.setCurrentText(CUSTOM)
        self.render_view.set_light(self.values())

    # --- the sliders ------------------------------------------------------------------------
    def set_strength(self, sun: float, sky: float) -> None:
        self.render_view.set_daylight(sun, sky)
        self._show_strength(sun, sky)

    def _moved(self, name: str, value: float) -> None:
        if name in ("Sun", "Sky"):
            sun, sky = self.render_view.sun, self.render_view.sky
            sun, sky = (round(value, 2), sky) if name == "Sun" else (sun, round(value, 2))
            self.set_strength(sun, sky)
            return
        self._show_number(name, value)
        self._direction = direction(self.boxes["Azimuth"].value(), self.boxes["Elevation"].value())
        self._custom()

    def _show_strength(self, sun: float, sky: float) -> None:
        self._show_number("Sun", sun)
        self._show_number("Sky", sky)

    def _show_number(self, name: str, value: float) -> None:
        slider, step = self.sliders[name]
        for widget, shown in ((slider, round(value / step)), (self.boxes[name], value)):
            widget.blockSignals(True)
            widget.setValue(shown)
            widget.blockSignals(False)
