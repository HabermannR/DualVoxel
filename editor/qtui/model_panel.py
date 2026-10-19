"""The Model dock: the box of the model open here and everything in it, as MagicaVoxel's edit mode has them.

Size: a new box of 1-256 a side, the voxels placed in it by an anchor per axis
(low, centre or high end; x and y centred and on the floor to start with), and
Fit, which shrinks the box to its voxels. Shift moves every voxel inside the box,
wrapping round to the other side (Wrap, on to start with) or dropping what goes
out; the arrow keys in the 3D edit view do the same as seen. Turn and Flip turn
or mirror the whole model, the box with it. Each is one undo step; a part of a
project keeps its voxels where they were in the scenes when its box is resized.

The window calls `install_model_panel(window)` once, after its own docks.
"""
from __future__ import annotations

import PySide6QtAds as QtAds
from PySide6 import QtWidgets

from core.model import ANCHORS
from qtui.edit_view import BIG_STEP

AXES = ("X", "Y", "Z")
ANCHOR_TEXT = {"low": "Low", "centre": "Centre", "high": "High"}
ANCHOR_TIPS = ("Where the voxels go along x when the box grows or shrinks: at the low end (x = 0), centred, or "
               "at the high end", "The same along y", "The same along z (Low: on the floor)")


class ModelPanel(QtWidgets.QWidget):
    def __init__(self, doc):
        super().__init__()
        self.doc = doc

        size = QtWidgets.QGroupBox("Size")
        grid = QtWidgets.QGridLayout(size)
        self.size_boxes, self.anchors = [], []
        for i, name in enumerate(AXES):
            box = QtWidgets.QSpinBox(prefix=f"{name} ", minimum=1, maximum=256)
            box.setToolTip(f"The box's size along {name.lower()} in voxels (1-256); Apply makes it so")
            grid.addWidget(box, 0, i)
            self.size_boxes.append(box)
            anchor = QtWidgets.QComboBox()
            for value in ANCHORS:
                anchor.addItem(ANCHOR_TEXT[value], value)
            anchor.setCurrentIndex(ANCHORS.index("low" if i == 2 else "centre"))
            anchor.setToolTip(ANCHOR_TIPS[i])
            grid.addWidget(anchor, 1, i)
            self.anchors.append(anchor)
        apply = QtWidgets.QPushButton("Apply")
        apply.setToolTip("Resize the box; voxels left outside it are gone (Ctrl+Z brings them back)")
        apply.clicked.connect(self.apply_size)
        grid.addWidget(apply, 2, 0)
        fit = QtWidgets.QPushButton("Fit")
        fit.setToolTip("Shrink the box to the voxels it holds")
        fit.clicked.connect(self.fit)
        grid.addWidget(fit, 2, 1)
        revert = QtWidgets.QPushButton("As it is")
        revert.setToolTip("Put the fields back to the box's size now")
        revert.clicked.connect(self.update_fields)
        grid.addWidget(revert, 2, 2)

        shift = QtWidgets.QGroupBox("Shift")
        sgrid = QtWidgets.QGridLayout(shift)
        for i, name in enumerate(AXES):
            for column, sign in enumerate((-1, 1)):
                button = QtWidgets.QPushButton(f"{'−' if sign < 0 else '+'}{name}")
                button.setToolTip(f"Move every voxel {'down' if sign < 0 else 'up'} {name.lower()} by the step")
                button.clicked.connect(lambda _=False, a=i, s=sign: self.shift(a, s))
                sgrid.addWidget(button, i, column)
        self.step = QtWidgets.QSpinBox(prefix="step ", minimum=1, maximum=256, value=1, suffix=" voxels")
        self.step.setToolTip("How far each button moves the voxels")
        sgrid.addWidget(self.step, 0, 2)
        self.wrap = QtWidgets.QCheckBox("Wrap")
        self.wrap.setChecked(doc.shift_wrap)
        self.wrap.setToolTip("What leaves one side comes back in at the other (else it is gone); the 3D edit "
                             "view's arrow keys follow this too")
        self.wrap.toggled.connect(lambda on: setattr(doc, "shift_wrap", on))
        sgrid.addWidget(self.wrap, 1, 2)
        keys = QtWidgets.QLabel(f"In the 3D edit view: arrows (as seen), Page Up / Down; Shift: {BIG_STEP}")
        keys.setWordWrap(True)
        keys.setStyleSheet("color: #999")
        sgrid.addWidget(keys, 2, 2)

        turn = QtWidgets.QGroupBox("Turn and flip")
        tgrid = QtWidgets.QGridLayout(turn)
        for i, name in enumerate(AXES):
            tgrid.addWidget(QtWidgets.QLabel(name), i, 0)
            for column, (text, turns) in enumerate((("−90°", -1), ("+90°", 1), ("180°", 2))):
                button = QtWidgets.QPushButton(text)
                button.setToolTip(f"Turn the whole model about {name.lower()}, counter-clockwise looking down it "
                                  "for +90°; the box turns with it")
                button.clicked.connect(lambda _=False, a=i, t=turns: self.rotate(a, t))
                tgrid.addWidget(button, i, 1 + column)
            flip = QtWidgets.QPushButton(f"Flip {name}")
            flip.setToolTip(f"Mirror the whole model along {name.lower()}")
            flip.clicked.connect(lambda _=False, a=i: self.flip(a))
            tgrid.addWidget(flip, i, 4)

        self.status = QtWidgets.QLabel()
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color: #888")
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(size)
        layout.addWidget(shift)
        layout.addWidget(turn)
        layout.addWidget(self.status)
        layout.addStretch(1)
        doc.reset.connect(self.update_fields)
        doc.resized.connect(self.update_fields)
        self.update_fields()

    def update_fields(self):
        for box, value in zip(self.size_boxes, self.doc.size):
            box.setValue(value)

    def _tell(self, text: str) -> None:
        self.status.setText(text)

    def apply_size(self) -> int:
        size = tuple(box.value() for box in self.size_boxes)
        if size == self.doc.size:
            self._tell("The box is that size already.")
            return 0
        lost = self.doc.resize(size, [a.currentData() for a in self.anchors])
        self._tell(f"{' × '.join(map(str, size))}" + (f": {lost} voxels were outside and are gone "
                                                       "(Ctrl+Z brings them back)" if lost else ""))
        return lost

    def fit(self) -> bool:
        before = self.doc.size
        if not self.doc.fit():
            self._tell("Nothing to fit: the box holds no voxels." if not self.doc.model.colour.any()
                       else "The box fits its voxels already.")
            return False
        self._tell(f"{' × '.join(map(str, before))} → {' × '.join(map(str, self.doc.size))}")
        return True

    def shift(self, axis: int, sign: int) -> int:
        delta = [0, 0, 0]
        delta[axis] = sign * self.step.value()
        lost = self.doc.shift(delta, self.wrap.isChecked())
        self._tell(f"{lost} voxels went out of the box and are gone (Ctrl+Z brings them back)" if lost else "")
        return lost

    def rotate(self, axis: int, turns: int) -> None:
        self.doc.rotate(axis, turns)
        self._tell("")

    def flip(self, axis: int) -> None:
        self.doc.flip(axis)
        self._tell("")


def install_model_panel(window) -> ModelPanel:
    panel = ModelPanel(window.doc)
    window._dock("Model", panel, QtAds.DockWidgetArea.CenterDockWidgetArea, window.docks["Brush"].dockAreaWidget(),
                 scroll=True)
    window.docks["Brush"].setAsCurrentTab()
    view = next(m for m in window.menuBar().findChildren(QtWidgets.QMenu) if m.title() == "&View")
    first_separator = next((a for a in view.actions() if a.isSeparator()), None)  # after the docks listed
    view.insertAction(first_separator, window.docks["Model"].toggleViewAction())
    edit = next(m for m in window.menuBar().findChildren(QtWidgets.QMenu) if m.title() == "&Edit")
    edit.addSeparator()
    window._action(edit, "Fit box to voxels", panel.fit)
    from qtui import window as window_module
    window.default_layout = window.dock_manager.saveState(window_module.LAYOUT_VERSION)
    return panel
