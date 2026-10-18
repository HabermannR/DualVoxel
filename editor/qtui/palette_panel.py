"""The current colour and material and the colour table to pick from (materials and the brush: their own
docks)."""
from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets


SWATCH = 18
TOOL_KEYS = {"attach": "A", "paint": "B", "erase": "E", "pick": "P"}


class ColourGrid(QtWidgets.QWidget):
    """The 255 table colours in table order; a click makes one current."""

    def __init__(self, doc):
        super().__init__()
        self.doc = doc
        self.setMouseTracking(True)
        doc.current_changed.connect(self.update)

    def _columns(self):
        return max(1, self.width() // SWATCH)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return -(-len(self.doc.model.colors) // max(1, width // SWATCH)) * SWATCH

    def sizeHint(self):
        return QtCore.QSize(16 * SWATCH, self.heightForWidth(16 * SWATCH))

    def resizeEvent(self, event):
        self.setMinimumHeight(self.heightForWidth(self.width()))
        super().resizeEvent(event)

    def _slot_at(self, pos):
        col, row = int(pos.x() // SWATCH), int(pos.y() // SWATCH)
        if col >= self._columns():
            return None
        index = row * self._columns() + col
        return self.doc.model.colors[index]["id"] if 0 <= index < len(self.doc.model.colors) else None

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        cols = self._columns()
        for i, c in enumerate(self.doc.model.colors):
            rect = QtCore.QRect((i % cols) * SWATCH, (i // cols) * SWATCH, SWATCH - 1, SWATCH - 1)
            painter.fillRect(rect, QtGui.QColor(*c["rgb"]))
            if c["id"] == self.doc.colour:
                painter.setPen(QtGui.QPen(QtGui.QColor(255, 220, 0), 2))
                painter.drawRect(rect.adjusted(1, 1, -1, -1))

    def mousePressEvent(self, event):
        slot = self._slot_at(event.position())
        if slot:
            self.doc.set_colour(slot)

    def mouseMoveEvent(self, event):
        slot = self._slot_at(event.position())
        if slot:
            c = self.doc.model.by_id[slot]
            self.setToolTip(f"{slot}: {c['hex']}  {c['band']}")


class PalettePanel(QtWidgets.QWidget):
    def __init__(self, doc):
        super().__init__()
        self.doc = doc
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)

        current = QtWidgets.QHBoxLayout()
        self.swatch = QtWidgets.QLabel()
        self.swatch.setFixedSize(36, 36)
        self.colour_label = QtWidgets.QLabel()
        current.addWidget(self.swatch)
        current.addWidget(self.colour_label, 1)
        layout.addLayout(current)


        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(ColourGrid(doc))
        layout.addWidget(scroll, 1)

        doc.current_changed.connect(self.refresh)
        self.refresh()

    def refresh(self):
        c = self.doc.model.by_id[self.doc.colour]
        self.swatch.setStyleSheet(f"background: {c['hex']}; border: 1px solid #555")
        m = self.doc.model.material_info(self.doc.material)
        self.colour_label.setText(f"colour {c['id']}  {c['hex']}  {c['band']}\nmaterial {m['id']}  {m['name']}"
                                  f"  ({m['group']})")
