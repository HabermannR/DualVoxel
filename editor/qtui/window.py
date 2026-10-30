"""The main window: every view a movable dock (Qt Advanced Docking System) over one Document."""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import PySide6QtAds as QtAds
from PySide6 import QtCore, QtGui, QtWidgets

from core.model import ROOT, SAVE_ROOT
from core.scene import SUFFIX as PROJECT_SUFFIX
from local_config import send_targets  # engine/, on the path through core.model
from qtui.assistant_link import AssistantLink
from qtui.document import Document
from qtui.edit_view import EditView
from qtui.material_editor import MaterialEditor
from qtui.material_panel import MaterialPanel
from qtui import keymap
from qtui.brush import KINDS
from qtui.document import TOOLS
from qtui.palette_panel import PalettePanel
from qtui.brush_panel import install_brush_panel
from qtui.export_panel import install_export_panel
from qtui.light_panel import install_light_panel
from qtui.render_setup_panel import install_render_setup_panel
from qtui.model_panel import install_model_panel
from qtui.noise_panel import install_noise_panel
from qtui.render_view import RenderView
from qtui.scene_docks import install_scenes
from qtui.slice_view import SliceView
from qtui.voxel_png_menu import install_voxel_png

LAYOUT_VERSION = 11
NEW_STARTS = ("Filled", "Floor", "Empty")  # how File > New starts a model; Filled first, as MagicaVoxel
RECENT_MAX = 10  # files File > Open recent lists, newest first
DROPPABLE = (".vx2", ".vox", PROJECT_SUFFIX)  # files the window opens when dropped on it


def dropped_files(mime: QtCore.QMimeData) -> list[str]:
    """The local files in a drag the window can open: models (.vx2, .vox) and projects."""
    if not mime.hasUrls():
        return []
    paths = [url.toLocalFile() for url in mime.urls() if url.isLocalFile()]
    return [p for p in paths if p.lower().endswith(DROPPABLE)]


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
        self.light_panel = install_light_panel(self)  # the render's sun and sky
        self.setup_panel = install_render_setup_panel(self)  # surroundings, floor, tilt blur, pause
        self.export_panel = install_export_panel(self)  # pictures and orbit videos
        self.export_panel.picture_requested.connect(self.render_picture_dialog)
        self.voxel_png = install_voxel_png(self)  # File > Export / Import voxel PNG…
        view = next(m for m in self.menuBar().findChildren(QtWidgets.QMenu) if m.title() == "&View")
        first_separator = next((a for a in view.actions() if a.isSeparator()), None)  # after the docks listed
        for title in ("Brush", "Light", "Render setup", "Export"):  # docks made after the menus
            view.insertAction(first_separator, self.docks[title].toggleViewAction())
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
        self.edit_view.set_ortho(self.settings.value("edit_ortho", False, type=bool))
        self.edit_view.ortho_box.toggled.connect(lambda on: self.settings.setValue("edit_ortho", bool(on)))
        self.edit_view.set_background(self.settings.value("edit_background", "Dark", type=str))
        self.edit_view.background_changed.connect(lambda name: self.settings.setValue("edit_background", name))
        self.link_action.setChecked(self.settings.value("assistant_link", True, type=bool))
        self.set_assistant_link(self.link_action.isChecked())
        self.update_info()
        self.setAcceptDrops(True)  # a .vx2, .vox or project dropped anywhere on the window opens

    # --- drag and drop ---------------------------------------------------------------------
    def dragEnterEvent(self, event):
        if dropped_files(event.mimeData()):
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if dropped_files(event.mimeData()):
            event.acceptProposedAction()

    def dropEvent(self, event):
        """Open the first model or project dropped, as File > Open recent does (asking first about unsaved work);
        after the drop has finished, so a question does not hold up the program the file came from."""
        paths = dropped_files(event.mimeData())
        if not paths:
            return
        event.acceptProposedAction()
        if len(paths) > 1:
            self.statusBar().showMessage(f"Opened {Path(paths[0]).name}; one file at a time "
                                         f"({len(paths) - 1} more dropped)", 6000)
        QtCore.QTimer.singleShot(0, lambda: self.open_recent(paths[0]))

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
    def _action(self, menu, text, slot, key=None):
        """A menu entry; key: its action in qtui.keymap, whose keys it takes (anywhere in the window)."""
        action = QtGui.QAction(text, self)
        if key:
            self.key_actions[key] = action
            action.setShortcutContext(QtCore.Qt.ShortcutContext.ApplicationShortcut)
            action.setShortcuts(keymap.sequences(key))
        action.triggered.connect(slot)
        menu.addAction(action)
        return action

    def apply_keys(self):
        """The keys as keymap has them now (after Edit > Keys…), on every menu entry."""
        for key, action in self.key_actions.items():
            action.setShortcuts(keymap.sequences(key))
        self.brush_panel.refresh_tips()

    def toggle_behind(self):
        """Every slice's Behind box the other way from the Front slice's."""
        on = not self.slices["Front"].ghost_box.isChecked()
        for view in self.slices.values():
            view.ghost_box.setChecked(on)

    def keys_dialog(self):
        if keymap.KeysDialog(self).exec() == QtWidgets.QDialog.DialogCode.Accepted:
            self.apply_keys()

    def _menus(self):
        self.key_actions = {}
        bar = self.menuBar()
        file = bar.addMenu("&File")
        self._action(file, "New…", self.new_dialog, "new")
        self._action(file, "Open…", self.open_dialog, "open")
        self.recent_menu = file.addMenu("Open recent")
        self.recent_menu.aboutToShow.connect(self.rebuild_recent_menu)
        self._action(file, "Save", self.save, "save")
        self._action(file, "Save as…", self.save_as, "save_as")
        file.addSeparator()
        self._action(file, "Render picture…", self.render_picture_dialog, "render_picture")
        self._action(file, "Render video…", self.render_video, "render_video")
        file.addSeparator()
        targets = send_targets()
        for name, path in targets:
            self._action(file, f"Send tables to {name}…", lambda _=False, n=name, p=path: self.send_tables(n, p))
        if targets:
            file.addSeparator()
        self._action(file, "Quit", self.close, "quit")
        edit = bar.addMenu("&Edit")
        self._action(edit, "Undo", self.doc.undo, "undo")
        self._action(edit, "Redo", self.doc.redo, "redo")
        edit.addSeparator()
        self._action(edit, "Keys…", self.keys_dialog, "keys")
        edit.addSeparator()
        tools = bar.addMenu("&Tools")
        for tool in TOOLS:
            self._action(tools, tool.capitalize(), lambda _=False, t=tool: self.brush_panel.set_mode(t), f"tool_{tool}")
        tools.addSeparator()
        brush = tools.addMenu("Brush")
        for kind in KINDS:
            self._action(brush, kind.capitalize(), lambda _=False, k=kind: self.brush_panel.set_kind(k),
                         f"brush_{kind}")
        brush.addSeparator()
        b = self.edit_view.brush
        self._action(brush, "Size down", lambda: b.set(size=b.size - 1), "size_down")
        self._action(brush, "Size up", lambda: b.set(size=b.size + 1), "size_up")
        self._action(brush, "Square or circle", lambda: b.set(round=not b.round), "round")
        self._action(brush, "2D or 3D", lambda: b.set(volume=not b.volume), "volume")
        for a, axis in enumerate("xyz"):
            self._action(brush, f"Mirror {axis}", lambda _=False, a=a: b.set(
                mirror=[on != (i == a) for i, on in enumerate(b.mirror)]), f"mirror_{axis}")
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
                     "pause_render")
        self._action(view, "Behind in the slices", self.toggle_behind, "behind")
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
            return
        self.remember_recent(path)

    # --- recent files: models and projects, newest first (in the settings) ----------------------
    def recent_files(self) -> list[str]:
        value = self.settings.value("recent_files", [])
        if isinstance(value, str):  # an INI file gives a list of one back as a string
            value = [value]
        return [str(p) for p in value or []]

    def remember_recent(self, path) -> None:
        """Put a file opened or saved at the top of File > Open recent (once, at most RECENT_MAX)."""
        path = str(Path(path).resolve())
        key = os.path.normcase(path)
        kept = [p for p in self.recent_files() if os.path.normcase(p) != key]
        self.settings.setValue("recent_files", [path, *kept][:RECENT_MAX])

    def forget_recent(self, path=None) -> None:
        """Take a file off the list, or clear it (path None)."""
        kept = [] if path is None else [p for p in self.recent_files()
                                        if os.path.normcase(p) != os.path.normcase(str(path))]
        self.settings.setValue("recent_files", kept)

    def rebuild_recent_menu(self) -> None:
        """name — folder for each file (the whole path as its tip); a file gone since says so."""
        menu = self.recent_menu
        menu.clear()
        paths = self.recent_files()
        for path in paths:
            p = Path(path)
            missing = not p.exists()
            action = menu.addAction(f"{p.name} — {p.parent.name or p.parent}" + ("  (missing)" if missing else ""))
            action.setToolTip(path)
            action.triggered.connect(lambda _=False, f=path: self.open_recent(f))
        if not paths:
            menu.addAction("(none yet)").setEnabled(False)
        menu.addSeparator()
        clear = menu.addAction("Clear list", lambda: self.forget_recent())
        clear.setEnabled(bool(paths))
        menu.setToolTipsVisible(True)

    def open_recent(self, path) -> None:
        """Open a recent model or project, after the ask about unsaved work it would replace; a missing file
        can be taken off the list."""
        if not Path(path).exists():
            Button = QtWidgets.QMessageBox.StandardButton
            if QtWidgets.QMessageBox.question(self, "Open recent", f"{path}\nis no longer there. Take it off "
                                              "the list?") == Button.Yes:
                self.forget_recent(path)
            return
        question = f"Save before opening {Path(path).name}?"
        if str(path).endswith(PROJECT_SUFFIX):  # replaces the project and the model docks
            go_on = self.ask_save(self.unsaved(), question)
        else:  # replaces only the model (a project's part stays in its project)
            go_on = self.ask_save(self.unsaved()[:1] if self.model_unsaved() else [], question, model_only=True)
        if go_on:
            self.open_path(path)

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
        self.remember_recent(target)
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
        path, width, height, samples, look, ortho = read()
        if not path:
            return
        problem = self.render_view.render_still(path, width, height, samples, look, ortho)
        if problem:
            QtWidgets.QMessageBox.warning(self, "Render picture", problem)
        else:
            self.docks["Render"].toggleView(True)
            self.statusBar().showMessage(f"Rendering a {width} x {height} picture…", 4000)

    def picture_form(self):
        """(the Render picture dialog, a function reading (path, width, height, samples, look, ortho) from it)."""
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
        ortho_box = QtWidgets.QCheckBox("Orthographic (no perspective)")
        ortho_box.setChecked(view.camera.ortho)  # as the Render dock draws, by default
        ortho_box.setEnabled(view.has_ortho)
        ortho_box.setToolTip("Parallel rays: parallel edges stay parallel, the model as large as in the dock"
                             if view.has_ortho else "The orthographic view needs a newer renderer")
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
        form.addRow("Projection", ortho_box)
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
            return (path, width_box.value(), height_box.value(), samples_box.value(), look_box.currentText(),
                    ortho_box.isChecked())
        dialog.widgets = {"width": width_box, "height": height_box, "keep": keep, "samples": samples_box,
                          "look": look_box, "ortho": ortho_box, "path": path_box}  # for tests
        return dialog, read

    def render_video(self):
        """File > Render video…: the Export dock's orbit video with its settings, after asking for the file."""
        self.docks["Export"].toggleView(True)
        path = self.export_panel.render_video()
        if path:
            self.docks["Render"].toggleView(True)
            self.statusBar().showMessage(f"Rendering an orbit video to {Path(path).name}…", 4000)

    def _picture_done(self, path: str, message: str):
        if path:
            self.statusBar().showMessage(message, 10000)
        elif message not in ("Picture cancelled.", "Animation cancelled."):
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
        return self.ask_save(self.unsaved(), "Save before closing?")

    def ask_save(self, lines: list[str], question: str, model_only: bool = False) -> bool:
        """Whether to go on, asking first when `lines` (unsaved's) name work that would be lost. Save saves
        all of it, or with model_only the model alone (Ctrl+S's save)."""
        if not lines:
            return True
        Button = QtWidgets.QMessageBox.StandardButton
        answer = QtWidgets.QMessageBox.warning(
            self, "Unsaved changes", question + "\n\n" + "\n".join(lines),
            Button.Save | Button.Discard | Button.Cancel, Button.Save)
        if answer == Button.Save:
            if model_only:
                self.save()
                return not self.model_unsaved()
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
        # its keys are the application's (_action): a closed window that lives on (macOS's menu bar keeps its
        # actions) would make every key it shares with a newer window ambiguous, and Qt then runs neither
        for action in self.key_actions.values():
            action.setShortcuts([])
        super().closeEvent(event)
