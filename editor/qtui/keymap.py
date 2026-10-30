"""Every key the editor knows, in one place: what each does, where it works and its default keys.

Anywhere ("app") keys are the menus' shortcuts and work whatever has the focus (a text box keeps the keys it
types). The others work while their view has the focus; a view takes the focus when the mouse comes over it,
unless a text box is being typed in. Each action has at most two keys. One's own keys go in editor.local.json
as "keys": {"redo": ["Ctrl+Y", "Ctrl+Shift+Z"], "size_up": "+", ...} (an empty list: no key), written by
Edit > Keys…; only what differs from the defaults is kept. A key may serve one action where it works: an
anywhere key clashes with every view's, a view's key only with the same view's.

The guide's table of keys (docs/guide.md, section 8) is made from here: docs/keys_table.py rewrites it, and a
test checks it is up to date.
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6 import QtCore, QtGui, QtWidgets

APP, EDIT_3D, SLICES, SCENE = "app", "3D view", "Slices", "Scene view"
WHERE = {APP: "Anywhere", EDIT_3D: "3D edit view", SLICES: "Slices", SCENE: "Scene view"}
MAX_KEYS = 2


@dataclass(frozen=True)
class Action:
    name: str
    label: str
    scope: str
    keys: tuple[str, ...]


ACTIONS = [
    Action("new", "New model", APP, ("Ctrl+N",)),
    Action("open", "Open", APP, ("Ctrl+O",)),
    Action("save", "Save", APP, ("Ctrl+S",)),
    Action("save_as", "Save as", APP, ("Ctrl+Shift+S",)),
    Action("save_project", "Save the project", APP, ("Ctrl+Alt+S",)),
    Action("render_picture", "Render a picture", APP, ("Ctrl+Shift+R",)),
    Action("render_video", "Render a video", APP, ("Ctrl+Shift+V",)),
    Action("quit", "Quit", APP, ("Ctrl+Q",)),
    Action("undo", "Undo", APP, ("Ctrl+Z",)),
    Action("redo", "Redo", APP, ("Ctrl+Y", "Ctrl+Shift+Z")),
    Action("keys", "Keys…", APP, ("Ctrl+K",)),
    Action("pause_render", "Pause or resume the render", APP, ("F9",)),
    Action("tool_attach", "Attach", APP, ("A",)),
    Action("tool_paint", "Paint", APP, ("B",)),
    Action("tool_erase", "Erase", APP, ("E",)),
    Action("tool_pick", "Pick", APP, ("P",)),
    Action("tool_protect", "Protect", APP, ("L",)),
    Action("brush_voxel", "Voxel brush", APP, ("V",)),
    Action("brush_face", "Face brush", APP, ("F",)),
    Action("brush_box", "Box brush", APP, ("X",)),
    Action("brush_ellipsoid", "Ellipsoid brush", APP, ("O",)),
    Action("brush_line", "Line brush", APP, ("I",)),
    Action("brush_fill", "Fill brush", APP, ("G",)),
    Action("brush_stamp", "Stamp brush", APP, ("T",)),
    Action("brush_smear", "Smear brush", APP, ("U",)),
    Action("brush_smooth", "Smooth", APP, ("N",)),
    Action("brush_erode", "Erode", APP, ("K",)),
    Action("brush_grow", "Grow", APP, ("J",)),
    Action("size_down", "Brush size down", APP, ("[", "-")),
    Action("size_up", "Brush size up", APP, ("]", "+")),
    Action("round", "Square or circle brush", APP, ("C",)),
    Action("volume", "Flat (2D) or volume (3D) brush", APP, ("D",)),
    Action("mirror_x", "Mirror x on or off", APP, ("Alt+X",)),
    Action("mirror_y", "Mirror y on or off", APP, ("Alt+Y",)),
    Action("mirror_z", "Mirror z on or off", APP, ("Alt+Z",)),
    Action("behind", "Behind in the slices on or off", APP, ("Ctrl+B",)),
    Action("ortho", "Orthographic on or off", EDIT_3D, ("5",)),
    Action("view_front", "Look from the front", EDIT_3D, ("1",)),
    Action("view_back", "Look from the back", EDIT_3D, ("Ctrl+1",)),
    Action("view_right", "Look from the right", EDIT_3D, ("3",)),
    Action("view_left", "Look from the left", EDIT_3D, ("Ctrl+3",)),
    Action("view_top", "Look from the top", EDIT_3D, ("7",)),
    Action("view_bottom", "Look from the bottom", EDIT_3D, ("Ctrl+7",)),
    Action("view_iso_pixel", "Isometric 2:1 (pixel art)", EDIT_3D, ("0",)),
    Action("view_iso", "True isometric", EDIT_3D, ("Ctrl+0",)),
    Action("stamp_turn", "Turn the stamp", EDIT_3D, ("R",)),
    Action("stamp_turn_back", "Turn the stamp back", EDIT_3D, ("Shift+R",)),
    Action("stamp_stop", "Stop stamping", EDIT_3D, ("Esc",)),
    Action("layer_up", "One layer up", SLICES, ("PgUp", ".")),
    Action("layer_down", "One layer down", SLICES, ("PgDown", ",")),
    Action("slice_fit", "Fit the layer in the slice (after zooming)", SLICES, ("Home",)),
    Action("instance_turn", "Turn the selected instance", SCENE, ("R",)),
    Action("instance_turn_back", "Turn the selected instance back", SCENE, ("Shift+R",)),
    Action("instance_mirror", "Mirror the selected instance", SCENE, ("M",)),
    Action("instance_duplicate", "Duplicate the selected instance", SCENE, ("Ctrl+D",)),
    Action("instance_delete", "Delete the selected instance", SCENE, ("Del", "Backspace")),
    Action("instance_edit", "Edit the selected instance's model", SCENE, ("Return", "Enter")),
]
BY_NAME = {a.name: a for a in ACTIONS}

# Keys that are not actions of their own, for the guide's table: (where, keys, what they do)
FIXED = [
    (EDIT_3D, "Arrows, `Page Up`/`Page Down`", "Shift the model in its box (Shift: 8 voxels)"),
    (EDIT_3D, "`Alt` + `Shift` + wheel", "Brush size"),
    (SLICES, "Wheel", "Move the layer"),
    (SLICES, "`Alt` + `Shift` + wheel", "Brush size"),
    (SLICES, "`Ctrl` + wheel", "Zoom in or out around the mouse"),
    (SLICES, "Middle drag, `Shift` + right drag", "Pan"),
    (SLICES, "Middle double click", "Fit the layer in the slice"),
    (SCENE, "Arrows, `Page Up`/`Page Down`", "Move the selected instance (Shift: 8 voxels)"),
]


def _normal(text: str) -> str:
    """A key as Qt writes it ("ctrl+shift+z" -> "Ctrl+Shift+Z"), "" for none."""
    return QtGui.QKeySequence(text).toString(QtGui.QKeySequence.SequenceFormat.PortableText) if text else ""


def overrides() -> dict:
    """editor.local.json's "keys", each as a tuple of keys."""
    from local_config import load  # engine/, on the path through core.model
    keys = load().get("keys", {})
    return {name: tuple(_normal(k) for k in ([v] if isinstance(v, str) else v) if k)
            for name, v in keys.items() if name in BY_NAME}


_current: dict | None = None


def current() -> dict[str, tuple[str, ...]]:
    """{action: its keys}: the defaults with one's own over them."""
    global _current
    if _current is None:
        _current = {a.name: a.keys for a in ACTIONS}
        _current.update(overrides())
    return _current


def reload() -> None:
    global _current
    _current = None


def keys(name: str) -> tuple[str, ...]:
    return current()[name]


def sequences(name: str) -> list[QtGui.QKeySequence]:
    return [QtGui.QKeySequence(k) for k in keys(name)]


def text(name: str) -> str:
    """Its keys as a menu or tooltip shows them: "Ctrl+Y or Ctrl+Shift+Z", "" for none."""
    return " or ".join(QtGui.QKeySequence(k).toString(QtGui.QKeySequence.SequenceFormat.NativeText)
                       for k in keys(name))


def clashes(scope_a: str, scope_b: str) -> bool:
    return scope_a == scope_b or APP in (scope_a, scope_b)


def conflicts(bindings: dict[str, tuple[str, ...]] | None = None) -> list[tuple[str, str, str]]:
    """(key, action, other action) for each key two actions share where both work."""
    bindings = current() if bindings is None else bindings
    found, seen = [], {}
    for action in ACTIONS:
        for key in bindings.get(action.name, ()):
            key = _normal(key)
            for other in seen.get(key, []):
                if clashes(action.scope, BY_NAME[other].scope):
                    found.append((key, other, action.name))
            seen.setdefault(key, []).append(action.name)
    return found


def event_key(event) -> str:
    """A key press as text ("Ctrl+1"); the number pad's keys count as the main ones."""
    mods = event.modifiers() & ~QtCore.Qt.KeyboardModifier.KeypadModifier
    combo = QtCore.QKeyCombination(mods, QtCore.Qt.Key(event.key()))
    return QtGui.QKeySequence(combo).toString(QtGui.QKeySequence.SequenceFormat.PortableText)


def action_for(event, scope: str) -> str | None:
    """The action of this scope a key press is bound to, or None."""
    if event.key() in (QtCore.Qt.Key.Key_Shift, QtCore.Qt.Key.Key_Control, QtCore.Qt.Key.Key_Alt,
                       QtCore.Qt.Key.Key_Meta, QtCore.Qt.Key.Key_unknown):
        return None
    pressed = event_key(event)
    bindings = current()
    for action in ACTIONS:
        if action.scope == scope and pressed in (_normal(k) for k in bindings[action.name]):
            return action.name
    return None


TYPING = (QtWidgets.QLineEdit, QtWidgets.QAbstractSpinBox, QtWidgets.QTextEdit, QtWidgets.QPlainTextEdit,
          QtWidgets.QKeySequenceEdit)


def take_focus(widget: QtWidgets.QWidget) -> None:
    """The mouse came over a view: its keys work from now on, unless a text box is being typed in or another
    window is in front."""
    if not widget.isActiveWindow():
        return
    focused = QtWidgets.QApplication.focusWidget()
    if isinstance(focused, TYPING) or (isinstance(focused, QtWidgets.QComboBox) and focused.isEditable()):
        return
    widget.setFocus(QtCore.Qt.FocusReason.MouseFocusReason)


# --- the guide's table ------------------------------------------------------------------------------------
def _markdown_keys(keys_: tuple[str, ...]) -> str:
    names = {"PgUp": "Page Up", "PgDown": "Page Down"}
    return ", ".join(f"`{names.get(k, k)}`" for k in keys_) or "none"


def guide_table() -> str:
    """The keys section's tables, with the default keys, by where they work."""
    out = []
    for scope in (APP, EDIT_3D, SLICES, SCENE):
        out += [f"**{WHERE[scope]}**", "", "| Key | Does |", "|---|---|"]
        out += [f"| {_markdown_keys(a.keys)} | {a.label} |" for a in ACTIONS if a.scope == scope]
        out += [f"| {k} | {what} |" for where, k, what in FIXED if where == scope]
        out.append("")
    return "\n".join(out).rstrip() + "\n"


# --- Edit > Keys… -----------------------------------------------------------------------------------------
class KeysDialog(QtWidgets.QDialog):
    """Every action with its two keys to change; a key two actions share where both work is shown in red and
    keeps OK off. OK saves what differs from the defaults to editor.local.json."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Keys")
        self.resize(620, 640)
        layout = QtWidgets.QVBoxLayout(self)
        self.table = QtWidgets.QTableWidget(len(ACTIONS), 2 + MAX_KEYS)
        self.table.setHorizontalHeaderLabels(["Does", "Where", "Key", "Also"])
        self.table.verticalHeader().hide()
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.NoSelection)
        self.edits = {}
        bindings = current()
        for row, action in enumerate(ACTIONS):
            for col, value in ((0, action.label), (1, WHERE[action.scope])):
                item = QtWidgets.QTableWidgetItem(value)
                item.setFlags(QtCore.Qt.ItemFlag.ItemIsEnabled)
                self.table.setItem(row, col, item)
            edits = []
            for i in range(MAX_KEYS):
                edit = QtWidgets.QKeySequenceEdit()
                if hasattr(edit, "setMaximumSequenceLength"):
                    edit.setMaximumSequenceLength(1)
                if hasattr(edit, "setClearButtonEnabled"):
                    edit.setClearButtonEnabled(True)
                current_keys = bindings[action.name]
                if i < len(current_keys):
                    edit.setKeySequence(QtGui.QKeySequence(current_keys[i]))
                edit.keySequenceChanged.connect(self.check)
                self.table.setCellWidget(row, 2 + i, edit)
                edits.append(edit)
            self.edits[action.name] = edits
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        for col in range(1, 2 + MAX_KEYS):
            header.setSectionResizeMode(col, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.table, 1)
        self.warning = QtWidgets.QLabel()
        self.warning.setWordWrap(True)
        self.warning.setStyleSheet("color: #e05555")
        layout.addWidget(self.warning)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok
                                             | QtWidgets.QDialogButtonBox.StandardButton.Cancel
                                             | QtWidgets.QDialogButtonBox.StandardButton.RestoreDefaults)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QtWidgets.QDialogButtonBox.StandardButton.RestoreDefaults).clicked.connect(self.defaults)
        self.ok = buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Ok)
        layout.addWidget(buttons)
        self.check()

    def bindings(self) -> dict[str, tuple[str, ...]]:
        return {name: tuple(dict.fromkeys(  # each key once
            e.keySequence().toString(QtGui.QKeySequence.SequenceFormat.PortableText)
            for e in edits if not e.keySequence().isEmpty()))
            for name, edits in self.edits.items()}

    def defaults(self):
        for action in ACTIONS:
            for i, edit in enumerate(self.edits[action.name]):
                edit.setKeySequence(QtGui.QKeySequence(action.keys[i] if i < len(action.keys) else ""))

    def check(self):
        """Mark the keys two actions share, and say which."""
        found = conflicts(self.bindings())
        bad = {(name, key) for key, a, b in found for name in (a, b)}
        for name, edits in self.edits.items():
            for edit in edits:
                key = edit.keySequence().toString(QtGui.QKeySequence.SequenceFormat.PortableText)
                edit.setStyleSheet("background: #6b2525" if (name, key) in bad else "")
        self.warning.setText("".join(f"{key} is both “{BY_NAME[a].label}” and “{BY_NAME[b].label}”. "
                                     for key, a, b in found))
        self.ok.setEnabled(not found)

    def accept(self):
        save(self.bindings())
        super().accept()


def save(bindings: dict[str, tuple[str, ...]]) -> None:
    """Keep what differs from the defaults in editor.local.json's "keys" (none differing: no "keys")."""
    import local_config
    changed = {name: list(k) for name, k in bindings.items()
               if tuple(_normal(x) for x in k) != tuple(_normal(x) for x in BY_NAME[name].keys)}
    local_config.update("keys", changed or None)
    reload()
