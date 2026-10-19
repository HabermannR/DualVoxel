"""The main window: every view a movable dock (Qt Advanced Docking System) over one Document."""
from __future__ import annotations

from pathlib import Path

import numpy as np
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
from qtui.model_panel import install_model_panel
from qtui.noise_panel import install_noise_panel
from qtui.render_view import RenderView
from qtui.scene_docks import install_scenes
from qtui.slice_view import SliceView

LAYOUT_VERSION = 11
NEW_STARTS = ("Filled", "Floor", "Empty")  # how File > New starts a model; Filled first, as MagicaVoxel


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
        self._info_soon = QtCore.QTimer(self, singleShot=True, interval=30, timeout=self.update_info)
        self.doc.changed.connect(lambda: self._info_soon.isActive() or self._info_soon.start())  # once a stroke
        self.doc.reset.connect(self.update_info)
        self._saved = None  # (model, version) when it was opened or saved: edits since then are unsaved
        self.doc.reset.connect(self._mark_saved)
        self._mark_saved()

        self._menus()
        self.brush_panel = install_brush_panel(self)  # the 3D edit view's brushes
        self.light_panel = install_light_panel(self)  # the render's sun, sky and tilt blur
        self.light_panel.picture_requested.connect(self.render_picture_dialog)
        self.render_view.still_finished.connect(self._picture_done)
        self.noise_panel = install_noise_panel(self)  # speckle, terrain, erode, scatter on a box
        self.model_panel = install_model_panel(self)  # the model's box: size, fit, shift, turn, flip
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
        self._action(file, "Render picture…", self.render_picture_dialog, "Ctrl+Shift+R")
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
        """A new model of any size up to 256 a side, starting Filled (as MagicaVoxel does: carve and paint
        at any height), with a Floor of some layers (a diorama), or Empty; filled voxels take the current
        colour and material."""
        dialog, read = self.new_model_form()
        if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            self.new_model(*read())

    def new_model_form(self):
        """(the New model dialog, a function reading (x, y, z, start, floor layers) from it)."""
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
        start = QtWidgets.QComboBox()
        start.addItems(NEW_STARTS)
        start.setCurrentText("Filled")
        start.setToolTip("Filled: the whole box, to carve and paint at any height (as MagicaVoxel starts).\n"
                         "Floor: some layers at the bottom (a diorama). Empty: nothing, attach from the floor.\n"
                         "Filled voxels take the current colour and material.")
        form.addRow("start", start)
        ground = QtWidgets.QSpinBox()
        ground.setRange(1, 256)
        ground.setValue(4)
        ground.setToolTip("Layers at the bottom filled with the current colour and material")
        form.addRow("floor layers", ground)
        start.currentTextChanged.connect(lambda text: ground.setEnabled(text == "Floor"))
        ground.setEnabled(False)
        hint = QtWidgets.QLabel("A small figure is about 32 × 32 × 64.")
        hint.setStyleSheet("color: #888")
        form.addRow(hint)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok
                                             | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        dialog.boxes, dialog.start, dialog.ground = boxes, start, ground  # for tests
        return dialog, lambda: (boxes["x"].value(), boxes["y"].value(), boxes["z"].value(),
                                start.currentText(), ground.value())

    def new_model(self, x: int, y: int, z: int, start: str = "Filled", floor: int = 0):
        """A new model: start "Filled" (every voxel), "Floor" (`floor` layers) or "Empty"."""
        if start not in NEW_STARTS:
            raise ValueError(f"start is one of {', '.join(NEW_STARTS)}")
        self.doc.new(x, y, z, {"Filled": z, "Floor": min(floor, z), "Empty": 0}[start])

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

    # --- pictures -----------------------------------------------------------------------
    def render_picture_dialog(self):
        """A high-resolution picture of the Render dock's view (its camera and light) as a PNG: size,
        samples and finish asked here, drawn in the dock with its progress (Cancel picture in the Light
        dock stops it)."""
        if self.render_view.still is not None:
            QtWidgets.QMessageBox.information(self, "Render picture", "A picture is already rendering.")
            return
        dialog, read = self.picture_form()
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        path, width, height, samples, look = read()
        if not path:
            return
        problem = self.render_view.render_still(path, width, height, samples, look)
        if problem:
            QtWidgets.QMessageBox.warning(self, "Render picture", problem)
        else:
            self.docks["Render"].toggleView(True)
            self.statusBar().showMessage(f"Rendering a {width} x {height} picture…", 4000)

    def picture_form(self):
        """(the Render picture dialog, a function reading (path, width, height, samples, look) from it)."""
        from postprocess import LOOKS
        from qtui.render_view import STILL_LIMITS
        max_width, max_height, max_samples = STILL_LIMITS
        view = self.render_view
        aspect = max(view.width(), 1) / max(view.height(), 1)  # the dock's shape, kept by default
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Render picture")
        form = QtWidgets.QFormLayout(dialog)
        width_box, height_box = QtWidgets.QSpinBox(), QtWidgets.QSpinBox()
        width_box.setRange(16, max_width)
        height_box.setRange(16, max_height)
        width_box.setValue(min(max_width, 3840 if aspect >= 1 else round(2700 * aspect)))
        keep = QtWidgets.QCheckBox("Keep the Render dock's shape")
        keep.setChecked(True)

        def kept_height():
            return max(16, min(max_height, round(width_box.value() / aspect)))

        def fit_height():
            if keep.isChecked():
                height_box.setValue(kept_height())

        def height_typed():  # a height of one's own leaves the dock's shape
            if keep.isChecked() and height_box.value() != kept_height():
                keep.setChecked(False)
        width_box.valueChanged.connect(fit_height)
        keep.toggled.connect(fit_height)
        height_box.valueChanged.connect(height_typed)
        fit_height()
        samples_box = QtWidgets.QSpinBox()
        samples_box.setRange(1, max_samples)
        samples_box.setValue(512)
        samples_box.setToolTip("Samples per pixel: more is smoother and slower (512-1024 for a final picture)")
        look_box = QtWidgets.QComboBox()
        look_box.addItems(list(LOOKS))
        look_box.setToolTip("none: as traced. film: tone curve, soft bloom, vignette. night: strong bloom on "
                            "glows and reds, cool shadows, grain")
        model_path = self.doc.model.path
        stem = Path(model_path).stem if model_path else "picture"
        path_box = QtWidgets.QLineEdit(str(ROOT / "editor" / "outputs" / f"{stem}.png"))
        browse = QtWidgets.QPushButton("…")

        def choose_file():
            chosen, _ = QtWidgets.QFileDialog.getSaveFileName(dialog, "Save picture", path_box.text(),
                                                              "PNG pictures (*.png)")
            if chosen:
                path_box.setText(chosen)
        browse.clicked.connect(choose_file)
        file_row = QtWidgets.QHBoxLayout()
        file_row.addWidget(path_box, 1)
        file_row.addWidget(browse)
        form.addRow("Width", width_box)
        form.addRow("Height", height_box)
        form.addRow("", keep)
        form.addRow("Samples", samples_box)
        form.addRow("Finish", look_box)
        form.addRow("File", file_row)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok
                                             | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)

        def read():
            path = path_box.text().strip()
            if path and not path.lower().endswith(".png"):
                path += ".png"
            if path:
                Path(path).parent.mkdir(parents=True, exist_ok=True)
            return path, width_box.value(), height_box.value(), samples_box.value(), look_box.currentText()
        dialog.widgets = {"width": width_box, "height": height_box, "keep": keep, "samples": samples_box,
                          "look": look_box, "path": path_box}  # for tests
        return dialog, read

    def _picture_done(self, path: str, message: str):
        if path:
            self.statusBar().showMessage(message, 10000)
        elif message != "Picture cancelled.":
            QtWidgets.QMessageBox.warning(self, "Render picture", message)
        else:
            self.statusBar().showMessage(message, 4000)

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
        self.info_label.setText(f"{name}   {x} × {y} × {z}   {np.count_nonzero(model.colour)} voxels")
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
