"""The materials, grouped, with their properties and how many voxels of the model use each.

A click makes a material current; * marks one edited in the Material editor. Each row shows the material's key colour (what
the edit views show with "Materials" on), its roughness, metal, emission,
transmission and scattering as bars, whether the renderer draws it
(yes, partly, new) and the voxels using it. The tooltip has the note.
"""
from __future__ import annotations

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

ROW = 22
HEADER = 20
BARS = (("roughness", "rough", 1.0), ("metal", "metal", 1.0), ("emission", "glow", 4.0),
        ("transmission", "trans", 1.0), ("sss", "sss", 2.0))
ENGINE_COLOUR = {"yes": QtGui.QColor(70, 160, 90), "partly": QtGui.QColor(200, 150, 40),
                 "new": QtGui.QColor(170, 70, 70)}


class MaterialList(QtWidgets.QWidget):
    def __init__(self, doc):
        super().__init__()
        self.doc = doc
        self.setMouseTracking(True)
        self.counts = np.zeros(256, dtype=int)
        self.rows = []  # ("group", name) or ("material", material dict)
        self._tops = []
        doc.current_changed.connect(self.update)
        doc.material_edited.connect(self.update)
        doc.changed.connect(self.recount)
        doc.reset.connect(self.recount)
        doc.tables_changed.connect(self.build_rows)
        self.build_rows()

    def build_rows(self):
        """The model's own materials first, then the shared ones by group, in table order within a group;
        again whenever materials are added or another model is shown."""
        groups = {}
        own = [self.doc.model.local[i] for i in sorted(self.doc.model.local)]
        if own:
            groups["this model"] = own
        for m in self.doc.model.materials:
            groups.setdefault(m["group"], []).append(m)
        self.rows = []
        for group, materials in groups.items():
            self.rows.append(("group", group))
            self.rows += [("material", m) for m in materials]
        self._tops = []
        y = HEADER
        for kind, _ in self.rows:
            self._tops.append(y)
            y += ROW if kind == "material" else HEADER
        self.setMinimumHeight(y + 4)
        self.recount()

    def recount(self):
        solid = self.doc.model.colour > 0
        self.counts = np.bincount(self.doc.model.material[solid].ravel(), minlength=256)
        self.update()

    def _label(self, m):
        return f"{m['id']}  {m['name']}" + (" *" if self.doc.is_edited(m["id"]) else "")

    def _row_at(self, y):
        for (kind, item), top in zip(self.rows, self._tops):
            if kind == "material" and top <= y < top + ROW:
                return item
        return None

    def _columns(self):
        """Name, bar and count widths from the font, so headers never overlap."""
        fm = self.fontMetrics()
        name_w = max(fm.horizontalAdvance(self._label(m) + " *") for kind, m in self.rows if kind == "material") + 8
        bar_w = fm.horizontalAdvance("trans") + 10
        count_w = fm.horizontalAdvance("000000") + 8
        self.setMinimumWidth(26 + name_w + bar_w * len(BARS) + 54 + count_w)
        return name_w, bar_w, count_w

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        palette = self.palette()
        name_w, bar_w, count_w = self._columns()
        x_bars = 26 + name_w
        x_engine = x_bars + bar_w * len(BARS) + 4
        painter.setPen(palette.color(QtGui.QPalette.ColorRole.PlaceholderText))
        for i, (_, label, _) in enumerate(BARS):
            painter.drawText(QtCore.QRect(x_bars + i * bar_w, 0, bar_w, HEADER), QtCore.Qt.AlignmentFlag.AlignCenter, label)
        painter.drawText(QtCore.QRect(x_engine, 0, 50, HEADER), QtCore.Qt.AlignmentFlag.AlignCenter, "engine")
        painter.drawText(QtCore.QRect(x_engine + 50, 0, count_w, HEADER), QtCore.Qt.AlignmentFlag.AlignRight
                         | QtCore.Qt.AlignmentFlag.AlignVCenter, "voxels")
        bold = QtGui.QFont(self.font())
        bold.setBold(True)
        for (kind, item), top in zip(self.rows, self._tops):
            if kind == "group":
                painter.setFont(bold)
                painter.setPen(palette.color(QtGui.QPalette.ColorRole.WindowText))
                painter.drawText(QtCore.QRect(4, top, 200, HEADER), QtCore.Qt.AlignmentFlag.AlignVCenter, item)
                painter.setFont(self.font())
                continue
            m = item
            row = QtCore.QRect(0, top, self.width(), ROW)
            if m["id"] == self.doc.material:
                painter.fillRect(row, palette.color(QtGui.QPalette.ColorRole.Highlight).lighter(170))
            key = self.doc.material_rgb[m["id"]]
            painter.fillRect(QtCore.QRect(6, top + 4, 14, 14), QtGui.QColor(*key))
            painter.setPen(palette.color(QtGui.QPalette.ColorRole.WindowText))
            painter.drawText(QtCore.QRect(26, top, name_w, ROW), QtCore.Qt.AlignmentFlag.AlignVCenter, self._label(m))
            for i, (field, _, scale) in enumerate(BARS):
                value = min(1.0, float(m.get(field, 0) or 0) / scale)
                cell = QtCore.QRect(x_bars + i * bar_w + 3, top + 7, bar_w - 6, ROW - 14)
                painter.fillRect(cell, QtGui.QColor(0, 0, 0, 30))
                if value > 0:
                    painter.fillRect(QtCore.QRect(cell.x(), cell.y(), max(1, int(cell.width() * value)), cell.height()),
                                     QtGui.QColor(90, 120, 170))
            engine = m.get("engine", "")
            badge = QtCore.QRect(x_engine + 4, top + 4, 42, ROW - 8)
            painter.fillRect(badge, ENGINE_COLOUR.get(engine, QtGui.QColor(120, 120, 120)))
            painter.setPen(QtGui.QColor(255, 255, 255))
            painter.drawText(badge, QtCore.Qt.AlignmentFlag.AlignCenter, engine)
            count = int(self.counts[m["id"]])
            painter.setPen(palette.color(QtGui.QPalette.ColorRole.WindowText if count else
                                         QtGui.QPalette.ColorRole.PlaceholderText))
            painter.drawText(QtCore.QRect(x_engine + 50, top, count_w, ROW),
                             QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter,
                             str(count) if count else "–")

    def mousePressEvent(self, event):
        m = self._row_at(event.position().y())
        if m is not None:
            self.doc.set_material(m["id"])

    def mouseMoveEvent(self, event):
        m = self._row_at(event.position().y())
        if m is None:
            self.setToolTip("")
            return
        props = ", ".join(f"{f} {m.get(f, 0)}" for f in ("roughness", "metal", "emission", "ior", "transmission", "sss"))
        self.setToolTip(f"<b>{m['id']} {m['name']}</b> ({m['group']})<br>{m.get('note', '')}<br><small>{props}</small>")


class MaterialPanel(QtWidgets.QWidget):
    def __init__(self, doc):
        super().__init__()
        self.doc = doc
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        self.show_box = QtWidgets.QCheckBox("Show materials in the edit views")
        self.show_box.setToolTip("Colour the voxels by material in the 3D edit view and the slices")
        self.show_box.toggled.connect(doc.set_show_materials)
        doc.display_changed.connect(lambda: self.show_box.setChecked(doc.show_materials))
        layout.addWidget(self.show_box)
        self.apply_button = QtWidgets.QPushButton()
        self.apply_button.setToolTip("Every voxel of the current colour gets the current material (one undo step), "
                                     "e.g. the skin colours become subsurface")
        self.apply_button.clicked.connect(self.apply_to_colour)
        layout.addWidget(self.apply_button)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(MaterialList(doc))
        layout.addWidget(scroll, 1)
        doc.current_changed.connect(self.refresh)
        self.refresh()

    def refresh(self):
        m = self.doc.model.material_info(self.doc.material)
        self.apply_button.setText(f"All voxels of colour {self.doc.colour} → {m['name']}")

    def apply_to_colour(self):
        if self.doc.model.set_material_for_colour(self.doc.colour, self.doc.material):
            self.doc.changed.emit()
