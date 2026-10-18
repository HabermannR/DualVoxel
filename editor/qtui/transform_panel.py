"""The selected instance's transform (position, rotation, mirror) and arrays of it.

Arrays make plain instances of the same model (each linked to it, each movable
on its own), in one undo step: a grid (counts along x, y and z with a gap
between the boxes, the instance at the low corner) or a circle about z (the
instance first, the centre behind it, each copy turned to face out).
"""
from __future__ import annotations

from PySide6 import QtWidgets

from core.scene import orient_text

AXIS_NAMES = ("X", "Y", "Z")
LIMIT = 4096


class TransformPanel(QtWidgets.QWidget):
    def __init__(self, project_doc):
        super().__init__()
        self.pdoc = project_doc
        self.title = QtWidgets.QLabel()
        self.title.setStyleSheet("font-weight: bold")

        transform = QtWidgets.QGroupBox("Transform")
        grid = QtWidgets.QGridLayout(transform)
        grid.addWidget(QtWidgets.QLabel("Position"), 0, 0)
        self.position = []
        for i, name in enumerate(AXIS_NAMES):
            box = QtWidgets.QSpinBox(prefix=f"{name} ", minimum=-LIMIT, maximum=LIMIT)
            box.setToolTip(f"The box's low corner, {name.lower()} in voxels (arrows and the wheel move it at once; "
                           "a typed number on Enter)")
            box.setKeyboardTracking(False)  # typing 49 does not stop at 4 on the way
            box.valueChanged.connect(self._apply_position)
            grid.addWidget(box, 0, 1 + i)
            self.position.append(box)
        self.buttons = []
        for i, name in enumerate(AXIS_NAMES):
            row = 1 + i
            grid.addWidget(QtWidgets.QLabel(f"Rotate {name}"), row, 0)
            for col, (text, turns) in enumerate((("−90°", -1), ("+90°", 1), ("180°", 2))):
                button = QtWidgets.QPushButton(text)
                button.setToolTip(f"Turn about {name.lower()}, counter-clockwise looking down it for +90°"
                                  + (" (R / Shift+R in the scene view)" if i == 2 and turns != 2 else ""))
                button.clicked.connect(lambda _=False, a=i, t=turns: self.pdoc.rotate(a, t))
                grid.addWidget(button, row, 1 + col)
                self.buttons.append(button)
        grid.addWidget(QtWidgets.QLabel("Mirror"), 4, 0)
        for i, name in enumerate(AXIS_NAMES):
            button = QtWidgets.QPushButton(name)
            button.setToolTip(f"Mirror along {name.lower()} (M in the scene view mirrors left-right as seen)")
            button.clicked.connect(lambda _=False, a=i: self.pdoc.mirror(a))
            grid.addWidget(button, 4, 1 + i)
            self.buttons.append(button)
        self.orient_label = QtWidgets.QLabel()
        self.orient_label.setToolTip("Where the model's x, y and z axes point in the scene")
        self.orient_label.setStyleSheet("color: #999")
        grid.addWidget(self.orient_label, 5, 0, 1, 3)
        reset = QtWidgets.QPushButton("Reset")
        reset.setToolTip("Back to the model's own orientation")
        reset.clicked.connect(self.pdoc.reset_orientation)
        grid.addWidget(reset, 5, 3)
        self.buttons.append(reset)

        array = QtWidgets.QGroupBox("Array (linked copies)")
        form = QtWidgets.QGridLayout(array)
        form.addWidget(QtWidgets.QLabel("Grid"), 0, 0)
        self.counts = []
        for i, name in enumerate(AXIS_NAMES):
            box = QtWidgets.QSpinBox(prefix=f"{name} × ", minimum=1, maximum=64, value=3 if i == 0 else 1)
            box.setToolTip(f"How many along {name.lower()}, the instance included")
            form.addWidget(box, 0, 1 + i)
            self.counts.append(box)
        form.addWidget(QtWidgets.QLabel("Gap"), 1, 0)
        self.gap = QtWidgets.QSpinBox(minimum=-256, maximum=256, value=4, suffix=" voxels")
        self.gap.setToolTip("Space between the boxes (negative overlaps them)")
        form.addWidget(self.gap, 1, 1)
        make_grid = QtWidgets.QPushButton("Make grid")
        make_grid.clicked.connect(self._make_grid)
        form.addWidget(make_grid, 1, 2, 1, 2)
        form.addWidget(QtWidgets.QLabel("Circle"), 2, 0)
        self.circle_count = QtWidgets.QSpinBox(prefix="× ", minimum=2, maximum=64, value=6)
        self.circle_count.setToolTip("How many around the circle, the instance included")
        form.addWidget(self.circle_count, 2, 1)
        self.radius = QtWidgets.QSpinBox(prefix="r ", minimum=1, maximum=LIMIT, value=48, suffix=" voxels")
        self.radius.setToolTip("From the circle's centre (behind the instance) to each box's centre")
        form.addWidget(self.radius, 2, 2)
        self.face_out = QtWidgets.QCheckBox("Face out")
        self.face_out.setChecked(True)
        self.face_out.setToolTip("Turn each copy to face away from the centre (to the nearest quarter turn)")
        form.addWidget(self.face_out, 2, 3)
        make_circle = QtWidgets.QPushButton("Make circle")
        make_circle.clicked.connect(self._make_circle)
        form.addWidget(make_circle, 3, 2, 1, 2)
        self.buttons += [make_grid, make_circle]

        hint = QtWidgets.QLabel("Select an instance in the scene view or the Project dock. Ctrl+Z there undoes "
                                "scene changes.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #999")
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self.title)
        layout.addWidget(transform)
        layout.addWidget(array)
        layout.addWidget(hint)
        layout.addStretch(1)
        project_doc.changed.connect(self.update_fields)
        project_doc.selected.connect(self.update_fields)
        self.update_fields()

    def update_fields(self):
        instance = self.pdoc.instance
        has = instance is not None
        self.title.setText(f"{instance.name}  ({instance.model})" if has else "No instance selected")
        for i, box in enumerate(self.position):
            box.blockSignals(True)
            box.setValue(instance.position[i] if has else 0)
            box.setEnabled(has)
            box.blockSignals(False)
        for button in self.buttons:
            button.setEnabled(has)
        self.orient_label.setText(f"axes {orient_text(instance.orient)}" if has else "")

    def _apply_position(self):
        if self.pdoc.instance is not None:
            self.pdoc.move_to([box.value() for box in self.position])

    def _make_grid(self):
        return self.pdoc.array_grid([box.value() for box in self.counts], self.gap.value())

    def _make_circle(self):
        return self.pdoc.array_circle(self.circle_count.value(), self.radius.value(), self.face_out.isChecked())
