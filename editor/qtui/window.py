"""The main window: every view a movable dock (Qt Advanced Docking System) over one Document."""
from __future__ import annotations

from pathlib import Path

import PySide6QtAds as QtAds
from PySide6 import QtCore, QtGui, QtWidgets

from core.model import ROOT, SAVE_ROOT
from local_config import send_targets  # engine/, on the path through core.model
from qtui.assistant_link import AssistantLink
from qtui.document import Document
from qtui.edit_view import EditView
from qtui.material_editor import MaterialEditor
from qtui.material_panel import MaterialPanel
from qtui.palette_panel import TOOL_KEYS, PalettePanel
from qtui.brush_panel import install_brush_panel
from qtui.light_panel import install_light_panel
from qtui.render_view import RenderView
from qtui.scene_docks import install_scenes
from qtui.slice_view import SliceView

LAYOUT_VERSION = 9


class EditorWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DualVoxel")
        self.resize(1700, 1000)
        QtAds.CDockManager.setConfigFlags(
            QtAds.CDockManager.eConfigFlag.DefaultOpaqueConfig
            | QtAds.CDockManager.eConfigFlag.FocusHighlighting
            | QtAds.CDockManager.eConfigFlag.EqualSplitOnInsertion)
        self.dock_manager = QtAds.CDockManager(self)
        self.doc = Document()

        self.slices = {name: SliceView(self.doc, name) for name in ("Front", "Side", "Top")}
        self.edit_view = EditView(self.doc)
        for view in self.slices.values():
            view.set_brush(self.edit_view.brush)  # the slices draw with the Brush dock's brush too
        self.render_view = RenderView(self.doc)
        self.palette = PalettePanel(self.doc)
        self.materials = MaterialPanel(self.doc)
        self.material_editor = MaterialEditor(self.doc)

        self.docks = {}
        edit_area = self._dock("3D edit", self.edit_view, QtAds.DockWidgetArea.CenterDockWidgetArea)
        self._dock("Render", self.render_view, QtAds.DockWidgetArea.RightDockWidgetArea, edit_area)
        front_area = self._dock("Front", self.slices["Front"], QtAds.DockWidgetArea.LeftDockWidgetArea)
        side_area = self._dock("Side", self.slices["Side"], QtAds.DockWidgetArea.BottomDockWidgetArea, front_area)
        self._dock("Top", self.slices["Top"], QtAds.DockWidgetArea.BottomDockWidgetArea, side_area)
        colours_area = self._dock("Colours", self.palette, QtAds.DockWidgetArea.RightDockWidgetArea, scroll=True)
        self._dock("Materials", self.materials, QtAds.DockWidgetArea.BottomDockWidgetArea, colours_area)
        self._dock("Material editor", self.material_editor, QtAds.DockWidgetArea.CenterDockWidgetArea, colours_area,
                   scroll=True)
        self.docks["Colours"].setAsCurrentTab()
        self.default_layout = self.dock_manager.saveState(LAYOUT_VERSION)

        self.hover_label = QtWidgets.QLabel()
        self.info_label = QtWidgets.QLabel()
        self.link_label = QtWidgets.QLabel()
        self.link_label.setToolTip("The live link: an assistant's MCP server (connect_editor) edits this model. "
                                   "Tools > Assistant link turns it on or off; the Protect mode (L) keeps voxels "
                                   "from it")
        self.statusBar().addWidget(self.hover_label, 1)
        self.statusBar().addPermanentWidget(self.link_label)
        self.statusBar().addPermanentWidget(self.info_label)
        self.assistant = AssistantLink(self.doc, self.render_view, lambda path: self.open_path(path), self,
                                       lambda: self.scenes.project_doc)
        self.assistant.status_changed.connect(self.link_label.setText)
        self.assistant.acted.connect(lambda text: self.statusBar().showMessage(text, 6000))
        self.doc.hover_changed.connect(self.hover_label.setText)
        self.doc.changed.connect(self.update_info)
        self.doc.reset.connect(self.update_info)
        self._saved = None  # (model, version) when it was opened or saved: edits since then are unsaved
        self.doc.reset.connect(self._mark_saved)
        self._mark_saved()

        self._menus()
        self.brush_panel = install_brush_panel(self)  # the 3D edit view's brushes
        self.light_panel = install_light_panel(self)  # the render's sun, sky and tilt blur
        self.scenes = install_scenes(self)  # models in scenes: Project, Scene and Transform docks
        self.settings = QtCore.QSettings("VoxelPipeline", "QtEditor")
        saved = self.settings.value("layout")
        self.layout_restored = False
        if saved is not None:
            self.restoreGeometry(self.settings.value("geometry"))
            self.layout_restored = bool(self.dock_manager.restoreState(saved, LAYOUT_VERSION))
        self.link_action.setChecked(self.settings.value("assistant_link", True, type=bool))
        self.set_assistant_link(self.link_action.isChecked())
        self.update_info()

    def default_widths(self):
        """Slices narrow, the 3D and render views wide, the colours a column (equal splits give them half)."""
        width = self.width()
        colours = 470
        slices = int(width * 0.2)
        views = (width - colours - slices) // 2
        # the root splitter holds [slices, (3D edit | render), (colours / materials)]
        root = self.docks["Colours"].dockAreaWidget().parentWidget()
        while isinstance(root.parentWidget(), QtWidgets.QSplitter):
            root = root.parentWidget()
        if root.count() == 3:
            root.setSizes([slices, 2 * views, colours])
        views_splitter = self.docks["3D edit"].dockAreaWidget().parentWidget()
        if views_splitter.count() == 2:
            views_splitter.setSizes([views, views])
        self.default_layout = self.dock_manager.saveState(LAYOUT_VERSION)

    def _dock(self, title, widget, area, target=None, scroll=False, name=None):
        """name: the id saved layouts know the dock by (default from the title), set before the dock manager
        sees it: a later rename leaves the dock out of the layouts."""
        dock = QtAds.CDockWidget(self.dock_manager, title)
        dock.setObjectName(name or f"dock_{title.replace(' ', '_').lower()}")
        mode = QtAds.CDockWidget.eInsertMode.AutoScrollArea if scroll else QtAds.CDockWidget.eInsertMode.ForceNoScrollArea
        dock.setWidget(widget, mode)
        dock.setFeature(QtAds.CDockWidget.DockWidgetFeature.DockWidgetClosable, True)
        self.docks[title] = dock
        if target is None:
            return self.dock_manager.addDockWidget(area, dock)
        return self.dock_manager.addDockWidget(area, dock, target)

    # --- menus ------------------------------------------------------------------------
    def _action(self, menu, text, slot, shortcut=None):
        action = QtGui.QAction(text, self)
        if shortcut:
            action.setShortcut(QtGui.QKeySequence(shortcut))
            action.setShortcutContext(QtCore.Qt.ShortcutContext.ApplicationShortcut)
        action.triggered.connect(slot)
        menu.addAction(action)
        return action

    def _menus(self):
        bar = self.menuBar()
        file = bar.addMenu("&File")
        self._action(file, "New…", self.new_dialog, "Ctrl+N")
        self._action(file, "Open…", self.open_dialog, "Ctrl+O")
        self._action(file, "Save", self.save, "Ctrl+S")
        self._action(file, "Save as…", self.save_as, "Ctrl+Shift+S")
        file.addSeparator()
        targets = send_targets()
        for name, path in targets:
            self._action(file, f"Send tables to {name}…", lambda _=False, n=name, p=path: self.send_tables(n, p))
        if targets:
            file.addSeparator()
        self._action(file, "Quit", self.close, "Ctrl+Q")
        edit = bar.addMenu("&Edit")
        self._action(edit, "Undo", self.doc.undo, "Ctrl+Z")
        self._action(edit, "Redo", self.doc.redo, "Ctrl+Y")
        tools = bar.addMenu("&Tools")
        for tool, key in TOOL_KEYS.items():
            self._action(tools, tool.capitalize(), lambda _=False, t=tool: self.doc.set_tool(t), key)
        tools.addSeparator()
        self._action(tools, "Clear protection", self.doc.clear_protected)
        self.link_action = self._action(tools, "Assistant link", self.set_assistant_link)
        self.link_action.setCheckable(True)
        self.link_action.setToolTip("Let an assistant's MCP server (connect_editor) edit the model open here")
        view = bar.addMenu("&View")
        for dock in self.docks.values():
            view.addAction(dock.toggleViewAction())
        view.addSeparator()
        self._action(view, "Pause / resume render", lambda: self.render_view.set_paused(not self.render_view.paused),
                     "F9")
        self._action(view, "Reset layout", lambda: self.dock_manager.restoreState(self.default_layout, LAYOUT_VERSION))

    # --- files ------------------------------------------------------------------------
    def new_dialog(self):
        """A new model of any size up to 256 a side, optionally with a floor of the current colour and
        material (for a diorama)."""
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("New model")
        form = QtWidgets.QFormLayout(dialog)
        boxes = {}
        for axis, value in (("x", 32), ("y", 32), ("z", 64)):
            box = QtWidgets.QSpinBox()
            box.setRange(1, 256)
            box.setValue(value)
            boxes[axis] = box
            form.addRow(f"{axis} (voxels)", box)
        ground = QtWidgets.QSpinBox()
        ground.setRange(0, 256)
        ground.setToolTip("Layers at the bottom filled with the current colour and material")
        form.addRow("floor layers", ground)
        hint = QtWidgets.QLabel("A small figure is about 32 × 32 × 64.")
        hint.setStyleSheet("color: #888")
        form.addRow(hint)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok
                                             | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            z = boxes["z"].value()
            self.doc.new(boxes["x"].value(), boxes["y"].value(), z, min(ground.value(), z))

    def send_tables(self, name: str, path: Path):
        """Explicit, never automatic: a target (editor.local.json's send_tables) keeps its own copies of
        the tables until this. Only the shared tables go; a model's own materials stay in its .vx2."""
        answer = QtWidgets.QMessageBox.question(
            self, f"Send tables to {name}",
            f"Copy palette/colors.json and materials.json into {path / 'assets' / 'palette'} and restamp "
            f"{name}'s .vx2 files? {name} then draws its models with these materials.")
        if answer != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        try:
            report = self.doc.send_tables_to(path)
        except Exception as error:
            QtWidgets.QMessageBox.warning(self, "Send tables", str(error))
            return
        QtWidgets.QMessageBox.information(self, "Send tables", "Sent. Restamped: "
                                          + (", ".join(p.name for p in report["restamped"]) or "none"))

    def open_path(self, path):
        try:
            self.doc.open(path)
        except Exception as error:
            QtWidgets.QMessageBox.warning(self, "Open", str(error))

    def open_dialog(self):
        start = str(self.doc.model.path.parent if self.doc.model.path else ROOT / "assets")
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Open a model", start, "Voxel models (*.vx2 *.vox)")
        if path:
            self.open_path(path)

    def save(self):
        path = self.doc.model.path
        if path is not None and Path(path).suffix == ".vx2":
            self._save_to(path)
        else:
            self.save_as()

    def save_as(self):
        path = self.doc.model.path
        start = str(Path(path).with_suffix(".vx2") if path else SAVE_ROOT)
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save model", start, "DualVoxel models (*.vx2)")
        if path:
            self._save_to(path)

    def _save_to(self, path):
        """Save the model, its own materials with it (in the .vx2), and a .vox copy."""
        try:
            target = self.doc.model.save_path(path)
        except Exception as error:
            QtWidgets.QMessageBox.warning(self, "Save", str(error))
            return
        self._mark_saved()
        self.statusBar().showMessage(f"Saved {target}", 4000)
        self.update_info()

    def _mark_saved(self):
        self._saved = (self.doc.model, self.doc.model.version)

    def model_unsaved(self) -> bool:
        """The model in the model docks has edits (voxels or its own materials) since it was opened or saved."""
        model = self.doc.model
        return self._saved != (model, model.version) or bool(self.doc.unsaved_materials())

    def unsaved(self) -> list[str]:
        """What closing now would lose, one line each."""
        if not self.model_unsaved():
            return []
        path = self.doc.model.path
        return [f"Model {Path(path).name if path else '(new model, never saved)'}"]

    def save_unsaved(self):
        """Save what `unsaved` lists (the model: Ctrl+S's save)."""
        if self.model_unsaved():
            self.save()

    def confirm_close(self) -> bool:
        """Ask before unsaved work is lost: Save (then close if all of it saved), Discard, or Cancel."""
        lines = self.unsaved()
        if not lines:
            return True
        Button = QtWidgets.QMessageBox.StandardButton
        answer = QtWidgets.QMessageBox.warning(
            self, "Unsaved changes", "Save before closing?\n\n" + "\n".join(lines),
            Button.Save | Button.Discard | Button.Cancel, Button.Save)
        if answer == Button.Save:
            self.save_unsaved()
            return not self.unsaved()  # a save cancelled or failed: stay open
        return answer == Button.Discard

    def update_info(self):
        model = self.doc.model
        x, y, z = self.doc.size
        name = Path(model.path).name if model.path else "new model"
        self.info_label.setText(f"{name}   {x} × {y} × {z}   {int((model.colour > 0).sum())} voxels")
        self.setWindowTitle(f"{name} – DualVoxel")

    def set_assistant_link(self, on: bool):
        """The live link on or off (remembered): off closes any connection and removes the link file."""
        self.settings.setValue("assistant_link", bool(on))
        if on:
            self.assistant.start()
        else:
            self.assistant.stop()

    # --- lifetime ---------------------------------------------------------------------
    def showEvent(self, event):
        super().showEvent(event)
        if self.render_view.engine is None and not getattr(self, "_engine_started", False):
            self._engine_started = True
            if not self.layout_restored:
                QtCore.QTimer.singleShot(0, self.default_widths)
            QtCore.QTimer.singleShot(300, self.render_view.start)

    def closeEvent(self, event):
        if not self.confirm_close():
            event.ignore()
            return
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("layout", self.dock_manager.saveState(LAYOUT_VERSION))
        self.assistant.stop()
        self.settings.setValue("assistant_link", self.link_action.isChecked())
        self.render_view.close_engine()
        self.edit_view.close()
        self.dock_manager.deleteLater()
        super().closeEvent(event)
