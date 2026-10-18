"""The outliner: the project's models, and its scenes with their instances.

Selecting an instance selects it in the scene view (and shows its scene); a
double click on a model or an instance edits that model in the model docks. The
buttons add a model (a .vx2), a new scene, an instance of the selected model in
the scene shown, remove the selected instance or scene, and make the selected
model (or instance, as it is turned) the 3D edit view's stamp brush.
"""
from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from core.model import ROOT
from core.scene import IDENTITY, orient_text

ROLE = QtCore.Qt.ItemDataRole.UserRole


class Outliner(QtWidgets.QWidget):
    brush_requested = QtCore.Signal(str, object)  # a model's name and the brush's orientation

    def __init__(self, doc, project_doc):
        super().__init__()
        self.doc = doc
        self.pdoc = project_doc
        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderLabels(["Project", ""])
        self.tree.setColumnCount(2)
        self.tree.header().setStretchLastSection(True)
        self.tree.itemSelectionChanged.connect(self._on_tree_selection)
        self.tree.itemDoubleClicked.connect(self._on_double_click)
        self.buttons = {}
        grid = QtWidgets.QGridLayout()
        grid.setContentsMargins(4, 4, 4, 4)
        for n, (text, tip, slot) in enumerate((
                ("Add model…", "Add a .vx2 model to the project", self.add_model_dialog),
                ("New scene", "An empty scene", self.pdoc.new_scene),
                ("Add instance", "Place the selected model in the scene shown", self.add_instance),
                ("Edit model", "Open the selected model, or the instance's model, in the model docks", self.edit_selected),
                ("Remove", "Remove the selected instance or scene (models stay)", self.remove_selected),
                ("Use as brush", "Stamp the selected model (or instance, as turned) in the 3D edit view",
                 self.use_as_brush))):
            button = QtWidgets.QPushButton(text)
            button.setToolTip(tip)
            button.clicked.connect(lambda _=False, s=slot: s())
            grid.addWidget(button, n // 2, n % 2)
            self.buttons[text] = button
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.tree, 1)
        layout.addLayout(grid)
        self._updating = False
        project_doc.changed.connect(self.rebuild)
        project_doc.selected.connect(self._select_current)
        doc.reset.connect(self.rebuild)  # the model being edited is marked
        self._mark_timer = QtCore.QTimer(self, singleShot=True, interval=300, timeout=self._mark_models)
        doc.changed.connect(self._mark_timer.start)
        self.rebuild()

    # --- the tree ---------------------------------------------------------------------------
    def rebuild(self):
        self._updating = True
        project = self.pdoc.project
        self.tree.clear()
        title = project.path.name if project.path else "untitled project"
        modified = set(project.modified_models())
        models = QtWidgets.QTreeWidgetItem(self.tree, ["Models", str(len(project.models))])
        models.setData(0, ROLE, ("models", None, None))
        for name, model in project.models.items():
            x, y, z = project.model_size(name)
            uses = len(project.instances_of(name))
            item = QtWidgets.QTreeWidgetItem(models, [self._model_label(name, modified), f"{x}×{y}×{z} · {uses} instances"])
            item.setData(0, ROLE, ("model", name, None))
            item.setToolTip(0, f"{model.path}\n✎ open in the model docks · * edited, not saved")
        scenes = QtWidgets.QTreeWidgetItem(self.tree, ["Scenes", str(len(project.scenes))])
        scenes.setData(0, ROLE, ("scenes", None, None))
        for scene in project.scenes:
            s_item = QtWidgets.QTreeWidgetItem(scenes, [scene.name, f"{len(scene.instances)} instances"])
            s_item.setData(0, ROLE, ("scene", scene, None))
            for instance in scene.instances:
                orient = orient_text(instance.orient)
                orient = "" if orient == "+x+y+z" else f" · {orient}"
                i_item = QtWidgets.QTreeWidgetItem(s_item, [instance.name, f"{instance.model} @ {instance.position}{orient}"])
                i_item.setData(0, ROLE, ("instance", scene, instance))
        self.tree.expandAll()
        self.tree.resizeColumnToContents(0)
        self.tree.setHeaderLabels([title, ""])
        self._updating = False
        self._select_current()

    def _model_label(self, name, modified):
        model = self.pdoc.project.models[name]
        return name + (" *" if name in modified else "") + ("  ✎" if model is self.doc.model else "")

    def _mark_models(self):
        modified = set(self.pdoc.project.modified_models())
        for item in self._items():
            kind, name, _ = item.data(0, ROLE)
            if kind == "model" and name in self.pdoc.project.models:
                item.setText(0, self._model_label(name, modified))

    def _select_current(self):
        """Mark the selected instance (or the scene shown) in the tree."""
        want = self.pdoc.instance if self.pdoc.instance is not None else self.pdoc.scene
        current = self.selection()
        if want is None or (current and want in current[1:]):
            return
        self._updating = True
        for item in self._items():
            kind, a, i = item.data(0, ROLE)
            if (kind == "instance" and i is want) or (kind == "scene" and a is want):
                self.tree.setCurrentItem(item)
                break
        self._updating = False

    def _items(self):
        it = QtWidgets.QTreeWidgetItemIterator(self.tree)
        while it.value():
            yield it.value()
            it += 1

    def selection(self):
        item = self.tree.currentItem()
        return item.data(0, ROLE) if item is not None else None

    def select_model(self, name: str) -> None:
        for item in self._items():
            if item.data(0, ROLE) == ("model", name, None):
                self.tree.setCurrentItem(item)
                return

    def _on_tree_selection(self):
        if self._updating:
            return
        selection = self.selection()
        if selection is None:
            return
        kind, scene, instance = selection
        if kind == "instance":
            self.pdoc.select(instance, scene)
        elif kind == "scene":
            self.pdoc.show_scene(scene)

    def _on_double_click(self, item, _column):
        kind, a, i = item.data(0, ROLE)
        if kind == "model":
            self.pdoc.request_edit(a)
        elif kind == "instance":
            self.pdoc.request_edit(i.model)

    # --- buttons ----------------------------------------------------------------------------
    def add_model_dialog(self):
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(self, "Add models", str(ROOT / "assets"), "Models (*.vx2)")
        for path in paths:
            try:
                self.select_model(self.pdoc.add_model(path))
            except Exception as error:
                QtWidgets.QMessageBox.warning(self, "Add model", str(error))

    def selected_model(self) -> str | None:
        selection = self.selection()
        if selection is None:
            return None
        kind, a, i = selection
        return a if kind == "model" else i.model if kind == "instance" else None

    def add_instance(self):
        model = self.selected_model()
        if model is None:
            QtWidgets.QMessageBox.information(self, "Add instance", "Select a model first.")
            return
        self.pdoc.add_instance(model)

    def edit_selected(self):
        model = self.selected_model()
        if model is not None:
            self.pdoc.request_edit(model)

    def use_as_brush(self):
        selection = self.selection()
        model = self.selected_model()
        if model is None:
            QtWidgets.QMessageBox.information(self, "Use as brush", "Select a model or an instance first.")
            return
        self.brush_requested.emit(model, selection[2].orient if selection[0] == "instance" else IDENTITY)

    def remove_selected(self):
        selection = self.selection()
        if selection is None:
            return
        kind, scene, instance = selection
        if kind == "instance":
            self.pdoc.select(instance, scene)
            self.pdoc.delete()
        elif kind == "scene":
            self.pdoc.remove_scene(scene)
