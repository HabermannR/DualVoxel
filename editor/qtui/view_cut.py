"""The 3D edit view's cut, as in the FEM workbench's view cut: a stack of planes across the model, each keeping
the voxels on one side. Whole voxels are kept or hidden (a voxel stays when its centre is on the kept side), and
the voxels the cut lays bare show as the section, so the inside of the model can be seen and painted. Two cuts
on one axis keep a band.

A cut belongs to the view: it changes nothing in the model and is not saved.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
from PySide6 import QtCore, QtWidgets

PLANES = (("X-Y plane", 2), ("X-Z plane", 1), ("Y-Z plane", 0))  # (name, the axis it cuts across), as in the FEM UI
AXIS_NAMES = "xyz"


@dataclass(frozen=True)
class Cut:
    """A plane across `axis` (0 x, 1 y, 2 z) between voxel at - 1 and voxel at, keeping the voxels below it (index
    < at) or, with keep_above, those from it on (index >= at)."""

    axis: int
    at: int
    keep_above: bool = False

    def text(self) -> str:
        return f"{AXIS_NAMES[self.axis]} {'≥' if self.keep_above else '<'} {self.at}"

    def clamped(self, size) -> "Cut":
        return replace(self, at=int(np.clip(self.at, 0, size[self.axis])))


def kept(shape_zyx, cuts) -> np.ndarray | None:
    """The voxels (bool, z y x) every cut keeps; None without cuts."""
    if not cuts:
        return None
    keep = np.ones(shape_zyx, dtype=bool)
    for cut in cuts:
        index = np.arange(shape_zyx[2 - cut.axis])
        side = index >= cut.at if cut.keep_above else index < cut.at
        shape = [1, 1, 1]
        shape[2 - cut.axis] = -1
        keep &= side.reshape(shape)
    return keep


class CutPanel(QtWidgets.QWidget):
    """Add, remove and set the cuts: the plane, where it lies (slider and box), the side kept (Flip)."""

    changed = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cuts: list[Cut] = []
        self.size = (1, 1, 1)
        self._syncing = False
        self.stack = QtWidgets.QListWidget(self)
        self.stack.setMaximumHeight(64)
        self.stack.setToolTip("The cuts, all applied together: two on one axis keep a band")
        self.stack.currentRowChanged.connect(self._show_selected)
        self.plane = QtWidgets.QComboBox(self)
        for name, axis in PLANES:
            self.plane.addItem(f"{name} ({AXIS_NAMES[axis]})", axis)
        self.plane.setToolTip("The plane the selected cut lies in (a new cut takes it too)")
        self.plane.currentIndexChanged.connect(lambda _: self._edit(axis=self.plane.currentData()))
        self.slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal, self)
        self.slider.setToolTip("Where the selected cut lies")
        self.slider.valueChanged.connect(lambda v: self._edit(at=v))
        self.spin = QtWidgets.QSpinBox(self)
        self.spin.setToolTip("Where the selected cut lies: the voxel layer it starts at")
        self.spin.valueChanged.connect(lambda v: self._edit(at=v))
        flip = QtWidgets.QPushButton("Flip", self)
        flip.setToolTip("Keep the other side of the selected cut")
        flip.clicked.connect(lambda: self._edit(flip=True))
        centre = QtWidgets.QPushButton("Centre", self)
        centre.setToolTip("Put the selected cut through the middle of the model")
        centre.clicked.connect(self._centre)
        add = QtWidgets.QPushButton("Add", self)
        add.setToolTip("A new cut in the chosen plane, through the middle, keeping the lower side")
        add.clicked.connect(self.add)
        remove = QtWidgets.QPushButton("Remove", self)
        remove.setToolTip("Take the selected cut away")
        remove.clicked.connect(self.remove)
        self.edit_widgets = (self.plane, self.slider, self.spin, flip, centre, remove)

        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        for widget in (self.plane, self.slider, self.spin, flip, centre):
            row.addWidget(widget, 1 if widget is self.slider else 0)
        buttons = QtWidgets.QVBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.addWidget(add)
        buttons.addWidget(remove)
        top = QtWidgets.QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.addWidget(self.stack, 1)
        top.addLayout(buttons)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.addLayout(top)
        layout.addLayout(row)
        self._show_selected(-1)

    def set_size(self, size):
        """The model's size (x, y, z): the slider's reach; cuts beyond it are pulled in."""
        self.size = tuple(size)
        self.cuts = [cut.clamped(self.size) for cut in self.cuts]
        self._list()
        self.changed.emit()

    def add(self):
        axis = self.plane.currentData()
        self.cuts.append(Cut(axis, self.size[axis] // 2))
        self._list(len(self.cuts) - 1)
        self.changed.emit()

    def remove(self):
        row = self.stack.currentRow()
        if 0 <= row < len(self.cuts):
            del self.cuts[row]
            self._list(min(row, len(self.cuts) - 1))
            self.changed.emit()

    def _centre(self):
        cut = self._selected()
        if cut is not None:
            self._edit(at=self.size[cut.axis] // 2)

    def _selected(self) -> Cut | None:
        row = self.stack.currentRow()
        return self.cuts[row] if 0 <= row < len(self.cuts) else None

    def _edit(self, axis=None, at=None, flip=False):
        cut = self._selected()
        if self._syncing or cut is None:
            return
        if axis is not None and axis != cut.axis:  # into another plane: the same share of the way through
            at = round(cut.at / max(self.size[cut.axis], 1) * self.size[axis])
            cut = replace(cut, axis=axis)
        if at is not None:
            cut = replace(cut, at=int(at))
        if flip:
            cut = replace(cut, keep_above=not cut.keep_above)
        cut = cut.clamped(self.size)
        row = self.stack.currentRow()
        if cut == self.cuts[row]:
            return
        self.cuts[row] = cut
        self._list(row)
        self.changed.emit()

    def _list(self, row=None):
        row = self.stack.currentRow() if row is None else row
        self._syncing = True
        self.stack.clear()
        for cut in self.cuts:
            self.stack.addItem(cut.text())
        self._syncing = False
        self.stack.setCurrentRow(row if 0 <= row < len(self.cuts) else -1)
        self._show_selected(self.stack.currentRow())

    def _show_selected(self, row):
        if self._syncing:
            return
        cut = self.cuts[row] if 0 <= row < len(self.cuts) else None
        for widget in self.edit_widgets:
            widget.setEnabled(cut is not None or widget is self.plane)
        if cut is None:
            return
        self._syncing = True
        self.plane.setCurrentIndex(self.plane.findData(cut.axis))
        for box in (self.slider, self.spin):
            box.setRange(0, self.size[cut.axis])
            box.setValue(cut.at)
        self._syncing = False
