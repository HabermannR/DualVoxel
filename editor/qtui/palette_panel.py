"""The colours: whose they are, the current colour and material, changing a colour, and the table to pick from
(materials and the brush: their own docks).

Colours belong to a project (core/colours.py): the dock says at the top whose
colours are shown and whether they can be changed here. Only the open project's
own can, once it is saved; the default table and another project's are shown
read-only. A changed colour shows at once in every model on the table, the
render and the scene, and is saved by Save project (the colours file, and every
part restamped). The grid can show the slots in another order (by hue,
lightness, chroma, or similar colours side by side); that only lays them out,
the slot numbers stay.
"""
from __future__ import annotations

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

from core.colours import NEAR, ORDERS, default_table, display_order


SWATCH = 18
TOOL_KEYS = {"attach": "A", "paint": "B", "erase": "E", "pick": "P", "protect": "L"}
UNSAVED_MARK = QtGui.QColor(255, 200, 0)  # a slot changed and not saved yet
CHANGED_MARK = QtGui.QColor(255, 255, 255)  # a slot unlike the default table (saved)


class ColourGrid(QtWidgets.QWidget):
    """The 255 table colours in a display order (`order`, see core.colours.display_order); a click makes one
    current. A corner mark: changed from the default table (white), changed and not saved yet (yellow).
    While `frozen` (the colour dialog is open) the order stays put, so the slot being changed does not jump."""

    def __init__(self, doc):
        super().__init__()
        self.doc = doc
        self.order = "Table"
        self.frozen = False
        self._layout_key, self._slots = None, []
        self.setMouseTracking(True)
        doc.current_changed.connect(self.update)
        doc.colour_table_changed.connect(self.update)

    def set_order(self, order: str) -> None:
        if order != self.order:
            self.order = order
            self.update()

    def slots(self) -> list[int]:
        """The slots in the order shown."""
        table = self.doc.model.table
        key = (id(table), self.order, len(table.colors), table.version)
        frozen = self.frozen and self._layout_key is not None and self._layout_key[:3] == key[:3]
        if key != self._layout_key and not frozen:
            self._layout_key, self._slots = key, display_order(table, self.order)
        return self._slots

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
        slots = self.slots()
        return slots[index] if 0 <= index < len(slots) else None

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        cols = self._columns()
        table, default = self.doc.model.table, default_table()
        for i, slot in enumerate(self.slots()):
            c = table.by_id[slot]
            rect = QtCore.QRect((i % cols) * SWATCH, (i // cols) * SWATCH, SWATCH - 1, SWATCH - 1)
            painter.fillRect(rect, QtGui.QColor(*c["rgb"]))
            mark = (UNSAVED_MARK if c["hex"] != table.saved[c["id"]]
                    else CHANGED_MARK if c["rgb"] != default.by_id.get(c["id"], c)["rgb"] else None)
            if mark is not None and table is not default:
                corner = QtGui.QPolygon([rect.topRight() + QtCore.QPoint(1, 0), rect.topRight() + QtCore.QPoint(-5, 0),
                                         rect.topRight() + QtCore.QPoint(1, 6)])
                painter.setPen(QtCore.Qt.PenStyle.NoPen)
                painter.setBrush(mark)
                painter.drawPolygon(corner)
            if c["id"] == self.doc.colour:
                painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
                painter.setPen(QtGui.QPen(QtGui.QColor(255, 220, 0), 2))
                painter.drawRect(rect.adjusted(1, 1, -1, -1))

    def mousePressEvent(self, event):
        slot = self._slot_at(event.position())
        if slot:
            self.doc.set_colour(slot)

    def mouseMoveEvent(self, event):
        slot = self._slot_at(event.position())
        if slot:
            self.setToolTip(describe(self.doc.model.table, slot))


def describe(table, slot: int) -> str:
    """A slot's tooltip: number, colour, family, and how it differs from saved and from the default."""
    c = table.by_id[slot]
    default = default_table().by_id.get(slot)
    same = default is not None and default["rgb"] == c["rgb"]
    lines = [f"{slot}: {c['hex']}  {c.get('band', '') if same else ''}".rstrip()]
    if c["hex"] != table.saved[slot]:
        lines.append(f"changed from {table.saved[slot]}, not saved yet")
    if default is not None and not same:
        lines.append(f"default colours: {default['hex']} ({default.get('band', '')})")
    return "\n".join(lines)


class PalettePanel(QtWidgets.QWidget):
    def __init__(self, doc):
        super().__init__()
        self.doc = doc
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)

        # Whose colours these are: the first thing the dock says.
        self.table_title = QtWidgets.QLabel()
        self.table_title.setStyleSheet("font-weight: bold; font-size: 11pt")
        self.table_file = QtWidgets.QLabel()
        self.table_file.setStyleSheet("color: #888")
        self.table_file.setWordWrap(True)
        self.table_hint = QtWidgets.QLabel()
        self.table_hint.setWordWrap(True)
        self.table_hint.setStyleSheet("color: #888; font-style: italic")
        for widget in (self.table_title, self.table_file, self.table_hint):
            layout.addWidget(widget)

        current = QtWidgets.QHBoxLayout()
        self.swatch = QtWidgets.QLabel()
        self.swatch.setFixedSize(36, 36)
        self.colour_label = QtWidgets.QLabel()
        current.addWidget(self.swatch)
        current.addWidget(self.colour_label, 1)
        layout.addLayout(current)

        # Changing the current colour: a hex, the colour dialog (live), revert.
        edit = QtWidgets.QHBoxLayout()
        self.hex_box = QtWidgets.QLineEdit()
        self.hex_box.setFixedWidth(76)
        self.hex_box.setPlaceholderText("#rrggbb")
        self.hex_box.setToolTip("The current colour's value: type a new one and press Enter")
        self.hex_box.setValidator(QtGui.QRegularExpressionValidator(QtCore.QRegularExpression("#?[0-9a-fA-F]{0,6}")))
        self.hex_box.editingFinished.connect(self._typed)
        self.change_button = QtWidgets.QPushButton("Change colour…")
        self.change_button.setToolTip("Pick a new colour for this slot, live in every model, the render and the scene")
        self.change_button.clicked.connect(self.change_dialog)
        self.revert_button = QtWidgets.QPushButton("Revert")
        self.revert_button.setToolTip("This slot back to the project's colours as saved")
        self.revert_button.clicked.connect(lambda: self.doc.revert_colours(self.doc.colour))
        self.revert_all_button = QtWidgets.QPushButton("Revert all")
        self.revert_all_button.setToolTip("Every slot back to the project's colours as saved")
        self.revert_all_button.clicked.connect(lambda: self.doc.revert_colours())
        for widget in (self.hex_box, self.change_button, self.revert_button, self.revert_all_button):
            edit.addWidget(widget)
        edit.addStretch(1)
        layout.addLayout(edit)
        self.use_label = QtWidgets.QLabel()
        self.use_label.setWordWrap(True)
        self.use_label.setStyleSheet("color: #888")
        layout.addWidget(self.use_label)

        order_row = QtWidgets.QHBoxLayout()
        order_label = QtWidgets.QLabel("Order")
        self.order_box = QtWidgets.QComboBox()
        self.order_box.addItems(ORDERS)
        self.order_box.setToolTip("How the colours are laid out below; slot numbers and models stay as they are.\n"
                                  "Table: the table's own ramps. Hue: greys, then bands of hue, dark to light. "
                                  "Lightness, Chroma: by L* or C*. Similar: alike colours side by side.")
        order_row.addWidget(order_label)
        order_row.addWidget(self.order_box)
        order_row.addStretch(1)
        layout.addLayout(order_row)

        self.grid = ColourGrid(doc)
        self.order_box.currentTextChanged.connect(self.grid.set_order)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.grid)
        layout.addWidget(scroll, 1)

        # The colour dialog moves fast: its colour goes to the models at most every 60 ms.
        self._pending = None
        self._apply_timer = QtCore.QTimer(self, singleShot=True, interval=60, timeout=self._apply_pending)
        self._count_timer = QtCore.QTimer(self, singleShot=True, interval=300, timeout=self.refresh_use)
        doc.current_changed.connect(self.refresh)
        doc.colour_table_changed.connect(self.refresh)
        doc.changed.connect(self._count_timer.start)
        self.refresh()

    # --- showing --------------------------------------------------------------------------------
    def refresh(self):
        doc, table = self.doc, self.doc.model.table
        c = doc.model.by_id[doc.colour]
        self.swatch.setStyleSheet(f"background: {c['hex']}; border: 1px solid #555")
        m = doc.model.material_info(doc.material)
        default = default_table().by_id.get(c["id"])
        band = c.get("band", "") if default is not None and default["rgb"] == c["rgb"] else "(changed)"
        self.colour_label.setText(f"colour {c['id']}  {c['hex']}  {band}\nmaterial {m['id']}  {m['name']}"
                                  f"  ({m['group']})")
        self.colour_label.setToolTip(describe(table, doc.colour))
        editable, why = doc.colours_editable()
        self.table_title.setText(table.title)
        where = table.path.name if table.path else "no file yet"
        if table.is_default:
            where = "palette/colors.json"
        changed = table.changed_slots()
        state = (f"{len(changed)} changed, not saved (Save project)" if changed
                 else "the project's own" if editable else "read-only")
        self.table_file.setText(f"{where} · {state}")
        self.table_hint.setText(why)
        self.table_hint.setVisible(bool(why))
        if not self.hex_box.hasFocus():
            self.hex_box.setText(c["hex"])
        self.hex_box.setReadOnly(not editable)
        self.change_button.setEnabled(editable)
        self.revert_button.setEnabled(editable and doc.colour in changed)
        self.revert_all_button.setEnabled(editable and bool(changed))
        self.refresh_use()

    def refresh_use(self):
        """Where the current colour is used (all of it changes with it), and the slot most like it."""
        doc, slot = self.doc, self.doc.colour
        models = doc.colour_models()
        counts = [int(np.count_nonzero(m.colour == slot)) for m in models]
        used = sum(counts)
        where = (f"{used} voxels in {sum(1 for n in counts if n)} of {len(models)} models on these colours"
                 if len(models) > 1 else f"{used} voxels in this model")
        near, distance = doc.model.table.closest_other(slot)
        closeness = f"closest: colour {near}, ΔE {distance:.1f}"
        if distance < NEAR:
            closeness = f"<span style='color: #d08000'>almost the same as colour {near} (ΔE {distance:.1f})</span>"
        self.use_label.setText(f"Used by {where} · {closeness}")

    # --- changing -------------------------------------------------------------------------------
    def _typed(self):
        if self.hex_box.isReadOnly():
            return
        text = self.hex_box.text().strip().lstrip("#")
        if len(text) != 6:  # the validator lets only hex digits through
            self.hex_box.setText(self.doc.model.by_id[self.doc.colour]["hex"])
            return
        self.doc.set_slot_colour(self.doc.colour, [int(text[i:i + 2], 16) for i in (0, 2, 4)])

    def _set_later(self, slot: int, colour: QtGui.QColor):
        self._pending = (slot, [colour.red(), colour.green(), colour.blue()])
        if not self._apply_timer.isActive():
            self._apply_timer.start()

    def _apply_pending(self):
        if self._pending is not None:
            slot, rgb = self._pending
            self._pending = None
            self.doc.set_slot_colour(slot, rgb)

    def change_dialog(self):
        """The colour dialog for the current slot, live; Cancel puts the colour back."""
        slot = self.doc.colour
        before = list(self.doc.model.by_id[slot]["rgb"])
        dialog = QtWidgets.QColorDialog(QtGui.QColor(*before), self)
        dialog.setWindowTitle(f"Colour {slot} of {self.doc.model.table.title}")
        dialog.currentColorChanged.connect(lambda colour: self._set_later(slot, colour))
        self.grid.frozen = True  # the swatch stays where it is while its colour changes
        try:
            accepted = dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted
        finally:
            self.grid.frozen = False
        self._apply_timer.stop()
        self._pending = None
        self.doc.set_slot_colour(slot, [dialog.selectedColor().red(), dialog.selectedColor().green(),
                                        dialog.selectedColor().blue()] if accepted else before)
