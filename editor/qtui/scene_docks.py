"""Models in scenes, added to the editor window: the Project dock, Scene and Transform docks and a Scene menu.

The window calls `install_scenes(window)` once, after its own docks and menus.
To leave window.py and document.py as they are, this wraps a few of their
calls instead of editing them:

- `doc.new` / `doc.open`: while the model docks show a project's model, a fresh
  Model takes its place first, so New and Open never overwrite a model that
  scenes use (a project's model is edited in place, through `doc.edit_model`).
  Either starts on the project's colours: a new model keeps them, an opened one
  keeps them if its file has the same colours, else takes its file's own.
- `window.open_path`: a `.project.json` (from the command line) opens as a project.
- `window._save_to`: saving the model being edited (Ctrl+S) marks it saved in
  the project; with the project's colours changed, Save project goes first (the
  colours file, and every part on them).
- `window.unsaved` / `window.save_unsaved` (the ask on closing): the project's
  edited parts and changed scenes too, saved by Save project; a part in the
  model docks counts as the project's, not as a model of its own.
- `window.closeEvent`: a close that goes ahead closes the scene view too.
- Edit → Undo / Redo: the scene's last change while the Project dock, the scene view
  or the transform panel has focus, the model's otherwise.

A part resized in the model docks (the Model dock, or its undo) moves its
instances so their voxels stay where they were (`doc.transformed`).

The outliner's "Use as brush" hands a model to the 3D edit view as a stamp brush.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6 import QtCore, QtWidgets

import PySide6QtAds as QtAds

from core.model import ROOT, Model, read_vox_scene
from core.scene import SUFFIX, share_tables
from qtui.outliner import Outliner
from qtui.project_document import ProjectDocument
from qtui.scene_view import SceneView
from qtui.transform_panel import TransformPanel


def install_scenes(window) -> "SceneDocks":
    return SceneDocks(window)


def _menu(window, title: str):
    return next(m for m in window.menuBar().findChildren(QtWidgets.QMenu) if m.title() == title)


class SceneDocks(QtCore.QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.doc = window.doc
        self.project_doc = ProjectDocument(self.doc)
        self.doc.project = lambda: self.project_doc.project  # its colours are the ones the Colours dock changes
        if self.doc.model.path is None and not (self.doc.model.colour > 0).any():
            self.doc.model.table = self.project_doc.project.table  # the empty model at the start
            self.doc.colour_table_changed.emit()
        self.project_doc.noted.connect(self.show_notes)
        self.scene_view = SceneView(self.doc, self.project_doc)
        self.outliner = Outliner(self.doc, self.project_doc)
        self.transform = TransformPanel(self.project_doc)
        self._docks()
        self._menus()
        self._wrap()
        self.project_label = QtWidgets.QLabel()
        window.statusBar().addPermanentWidget(self.project_label)
        self.project_doc.changed.connect(self.update_label)
        self.doc.reset.connect(self.update_label)
        self.project_doc.selected.connect(self._show_scene)
        self.project_doc.edit_model.connect(self.edit_model)
        self.outliner.brush_requested.connect(self.use_as_brush)
        self.doc.transformed.connect(self.follow_transform)
        self._scene_model, self._scene_key, self.render_scene = None, None, False
        window.render_view.source = self.scene_model
        window.docks["Scene"].visibilityChanged.connect(lambda shown: shown and self._render_scene(True))
        window.docks["3D edit"].visibilityChanged.connect(lambda shown: shown and self._render_scene(False))
        self.update_label()

    # --- docks and menus --------------------------------------------------------------------
    def _docks(self):
        w = self.window
        w._dock("Scene", self.scene_view, QtAds.DockWidgetArea.CenterDockWidgetArea, w.docks["Render"].dockAreaWidget())
        w._dock("Project", self.outliner, QtAds.DockWidgetArea.TopDockWidgetArea, w.docks["Front"].dockAreaWidget(),
                name="dock_outliner")  # its old name: saved layouts keep their place for it
        w._dock("Transform", self.transform, QtAds.DockWidgetArea.CenterDockWidgetArea,
                w.docks["Colours"].dockAreaWidget(), scroll=True)
        w.docks["Render"].setAsCurrentTab()
        w.docks["Colours"].setAsCurrentTab()
        from qtui import window as window_module
        w.default_layout = w.dock_manager.saveState(window_module.LAYOUT_VERSION)

    def _menus(self):
        w = self.window
        menu = QtWidgets.QMenu("&Scene", w)
        w.menuBar().insertMenu(_menu(w, "&View").menuAction(), menu)
        w._action(menu, "New project", self.project_doc.new_project)
        w._action(menu, "Open project…", self.open_project_dialog)
        w._action(menu, "Save project", self.save_project, "Ctrl+Alt+S")
        w._action(menu, "Save project as…", self.save_project_as)
        menu.addSeparator()
        w._action(menu, "Add model…", self.outliner.add_model_dialog)
        w._action(menu, "New scene", self.project_doc.new_scene)
        view = _menu(w, "&View")
        first = view.actions()[0] if view.actions() else None
        for title in ("Project", "Scene", "Transform"):
            view.insertAction(first, w.docks[title].toggleViewAction())
        for action in _menu(w, "&Edit").actions():
            if action.text() in ("Undo", "Redo"):
                action.triggered.disconnect()
                action.triggered.connect(self.undo if action.text() == "Undo" else self.redo)

    def _wrap(self):
        w, doc = self.window, self.doc
        for name in ("new", "open"):
            original = getattr(doc, name)

            def wrapped(*args, _original=original, **kwargs):
                shown, table = doc.model, doc.model.table
                if self.project_doc.project.name_of(shown) is not None:
                    doc.model = share_tables(Model(), shown)  # leave the project's model as it is
                doc.model.table = self.project_doc.project.table  # open: kept if the file has the same colours
                try:
                    result = _original(*args, **kwargs)
                except Exception:
                    doc.model = shown
                    shown.table = table
                    raise
                self._render_scene(False)
                return result
            setattr(doc, name, wrapped)

        open_path = w.open_path

        def open_any(path):
            if str(path).endswith(SUFFIX):
                try:
                    self.project_doc.open_project(path)
                except Exception as error:
                    QtWidgets.QMessageBox.warning(w, "Open project", str(error))
                    return
                w.docks["Project"].toggleView(True)  # its parts and instances
                w.docks["Project"].setAsCurrentTab()
                self._render_scene(True)
                w.remember_recent(path)
            elif str(path).lower().endswith(".vox") and self._vox_models(path) > 1:
                try:  # a MagicaVoxel scene: its models become the project's parts
                    self.project_doc.import_vox(path)
                except Exception as error:
                    QtWidgets.QMessageBox.warning(w, "Open", str(error))
                    return
                first = next(iter(self.project_doc.project.models))
                self.edit_model(first)
                w.remember_recent(path)
                w.statusBar().showMessage(f"{len(self.project_doc.project.models)} parts from {Path(path).name}: "
                                          "a new project (Save project writes them into assets/)", 6000)
            else:
                open_path(path)
        w.open_path = open_any

        save_to = w._save_to

        def save_and_mark(path):
            project = self.project_doc.project
            if doc.model.table is project.table and project.colours_modified():
                self._save_project(None)  # the colours file first, so the model's fingerprint names saved colours
                if project.colours_modified():
                    return  # the project's save failed (and said why)
            save_to(path)
            model = self.project_doc.project.name_of(doc.model)
            if model is not None:  # the project now reads the model from this file
                self.project_doc.project.mark_saved(model)
                self.project_doc.changed.emit()
        w._save_to = save_and_mark

        model_unsaved, unsaved, save_unsaved = w.model_unsaved, w.unsaved, w.save_unsaved
        w.model_unsaved = lambda: (self.project_doc.project.name_of(doc.model) is None and model_unsaved())

        def unsaved_with_project():
            return unsaved() + self.project_unsaved()
        w.unsaved = unsaved_with_project

        def save_with_project():
            if self.project_unsaved():
                self.save_project()
            save_unsaved()
        w.save_unsaved = save_with_project

        close_event = w.closeEvent

        def close_scene_view(event):
            close_event(event)
            if event.isAccepted():
                self.scene_view.close()
        w.closeEvent = close_scene_view

    @staticmethod
    def _vox_models(path) -> int:
        try:
            return len(read_vox_scene(Path(path))["models"])
        except Exception:
            return 1  # let the model's own open report it

    # --- projects -----------------------------------------------------------------------------
    def open_project_dialog(self):
        path = self.project_doc.project.path
        start = str(path.parent if path else ROOT / "assets")
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self.window, "Open a project", start, f"Projects (*{SUFFIX})")
        if path:
            self.window.open_path(path)

    def save_project(self):
        if self.project_doc.project.path is None:
            self.save_project_as()
        else:
            self._save_project(None)

    def save_project_as(self):
        path = self.project_doc.project.path
        default = path.name.removesuffix(SUFFIX) if path else ""
        name, ok = QtWidgets.QInputDialog.getText(self.window, "Save project", f"Name (saved as assets/<name>{SUFFIX};\n"
                                                  "edited models are saved too):", text=default)
        if ok and name:
            self._save_project(name)

    def project_unsaved(self) -> list[str]:
        """The project's line for the ask on closing, if its parts or scenes have unsaved changes."""
        project = self.project_doc.project
        edited = project.modified_models()
        if not edited and not self.project_doc.modified() and not project.colours_modified():
            return []
        name = f"Project {project.path.name}" if project.path else "Project (new, never saved)"
        what = [f"edited parts: {', '.join(edited)}"] if edited else []
        if self.project_doc.modified():
            what.append("scenes or parts changed")
        if project.colours_modified():
            what.append(f"colours changed: {', '.join(map(str, project.table.changed_slots()))}")
        return [f"{name}: {'; '.join(what)}"]

    def _save_project(self, name):
        try:
            target = self.project_doc.save_project(name)
        except Exception as error:
            QtWidgets.QMessageBox.warning(self.window, "Save project", str(error))
            return
        self.window.remember_recent(target)
        self.window.statusBar().showMessage(f"Saved {target}", 4000)

    def show_notes(self, text: str):
        """What a project's open or Add model did to a part (colours remapped), without stopping the work."""
        box = QtWidgets.QMessageBox(QtWidgets.QMessageBox.Icon.Information, "Colours", text,
                                    QtWidgets.QMessageBox.StandardButton.Ok, self.window)
        box.setModal(False)
        box.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)
        box.show()
        self.window.statusBar().showMessage(text.split("\n")[0], 8000)

    def edit_model(self, name: str):
        """The project's own Model goes to the model docks: every edit shows on each of its instances."""
        self.doc.edit_model(self.project_doc.project.models[name])
        self._render_scene(False)
        self.window.docks["3D edit"].setAsCurrentTab()
        self.window.docks["Colours"].setAsCurrentTab()
        count = len(self.project_doc.project.instances_of(name))
        self.window.statusBar().showMessage(f"Editing model {name} ({count} instances follow)", 4000)

    def follow_transform(self, model, entry):
        """A part's box was resized (or fitted, or that undone): its instances move so its voxels stay where
        they were in the scenes. A shift, turn or flip moves the voxels in the box; the box stays put."""
        _, op, old_size, new_size = entry
        name = self.project_doc.project.name_of(model)
        if name is not None and op[0] == "resize":
            self.project_doc.follow_resize(name, old_size, new_size, op[2])

    def use_as_brush(self, name: str, orient):
        """Stamp this project model in the 3D edit view (into the model being edited)."""
        view = self.window.edit_view
        view.set_stamp(name, self.project_doc.project.models[name], orient)
        self.window.docks["3D edit"].setAsCurrentTab()
        view.plotter.interactor.setFocus()
        self.window.docks["Brush"].setAsCurrentTab()
        self.window.statusBar().showMessage(f"Stamping {name}: click in the 3D edit view, R turns, Esc stops", 6000)

    def update_label(self):
        project = self.project_doc.project
        name = project.name_of(self.doc.model)
        parts = [project.path.name] if project.path else []
        if name is not None:
            parts.append(f"editing model {name}")
        self.project_label.setText("   ".join(parts))

    def _show_scene(self):
        scene, docks = self.project_doc.scene, self.window.docks
        docks["Scene"].setWindowTitle(f"Scene · {scene.name}" if scene else "Scene")
        if scene is not None:
            docks["Scene"].setAsCurrentTab()
        if self.project_doc.instance is not None:
            docks["Transform"].setAsCurrentTab()

    # --- the render ---------------------------------------------------------------------------
    def _render_scene(self, on: bool):
        """The Render dock follows the view shown last: the scene (Scene dock) or the model (3D edit)."""
        self.render_scene = on

    def scene_model(self):
        """The scene shown, merged into one Model for the Render dock (rebuilt when an instance moves or a
        part is edited); None while the render shows the model being edited, or the scene is empty."""
        project, scene = self.project_doc.project, self.project_doc.scene
        if not self.render_scene or scene is None or not scene.instances:
            return None
        key = (id(project), id(scene), tuple((i.model, i.position, i.orient) for i in scene.instances),
               tuple((name, id(m), m.version) for name, m in project.models.items()))
        if key != self._scene_key:
            colour, material, _, local = project.merged(scene)
            model = self._scene_model or Model()
            model.table, model.materials = project.table, self.doc.model.materials
            model._replace(np.ascontiguousarray(colour), np.ascontiguousarray(material))
            model.local = {m["id"]: m for m in local}
            self._scene_model, self._scene_key = model, key
        return self._scene_model

    # --- undo ---------------------------------------------------------------------------------
    def scene_has_focus(self) -> bool:
        focus = QtWidgets.QApplication.focusWidget()
        return focus is not None and any(w is focus or w.isAncestorOf(focus)
                                         for w in (self.scene_view, self.outliner, self.transform))

    def undo(self):
        if not (self.scene_has_focus() and self.project_doc.undo()):
            self.doc.undo()

    def redo(self):
        if not (self.scene_has_focus() and self.project_doc.redo()):
            self.doc.redo()
