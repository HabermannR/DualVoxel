"""File > Export voxel PNG… and Import voxel PNG…: the model as pictures for a paint program (core/voxel_png.py).

Export writes slice sheets (the whole model) or views (the surface, to paint on). Import reads either back:
a slice sheet as a new model (asking first about unsaved work), painted views onto the model shown as one
undo step.
"""
from __future__ import annotations

import re
from pathlib import Path

from PySide6 import QtWidgets

from core import voxel_png
from core.model import vx2

OUTPUTS = Path(__file__).resolve().parents[1] / "outputs"
KINDS = ("Views: the surface, to paint on", "Slices: the whole model, every layer")


def install_voxel_png(window) -> "VoxelPngMenu":
    return VoxelPngMenu(window)


class VoxelPngMenu:
    def __init__(self, window):
        self.window, self.doc = window, window.doc
        file = next(m for m in window.menuBar().findChildren(QtWidgets.QMenu) if m.title() == "&File")
        save_as = next(a for a in file.actions() if a.text() == "Save as…")
        after = file.actions()[file.actions().index(save_as) + 1]  # the separator before the pictures
        self.export_action = window._action(file, "Export voxel PNG…", self.export_dialog)
        self.import_action = window._action(file, "Import voxel PNG…", self.import_dialog)
        file.insertSeparator(after)
        for action in (self.export_action, self.import_action):
            file.removeAction(action)
            file.insertAction(after, action)

    # --- export -----------------------------------------------------------------------------
    def export_form(self):
        """The dialog and a function reading (kind index, scale, views, base path)."""
        dialog = QtWidgets.QDialog(self.window)
        dialog.setWindowTitle("Export voxel PNG")
        form = QtWidgets.QFormLayout(dialog)
        kind = QtWidgets.QComboBox()
        kind.addItems(KINDS)
        kind.setToolTip("Views: each side seen straight on, one block of pixels per voxel, to paint in any paint "
                        "program and import again. Slices: every layer side by side, one pixel per voxel; "
                        "nothing is lost")
        scale = QtWidgets.QSpinBox()
        scale.setRange(1, voxel_png.MAX_SCALE)
        scale.setValue(8)
        scale.setSuffix(" pixels per voxel")
        views = {}
        row = QtWidgets.QHBoxLayout()
        for name in voxel_png.VIEWS:
            box = QtWidgets.QCheckBox(name.capitalize())
            box.setChecked(True)
            views[name] = box
            row.addWidget(box)
        views["left"].setToolTip("From -x: the figure's right side when it faces you")
        views["right"].setToolTip("From +x: the figure's left side when it faces you")
        stem = Path(self.doc.model.path).stem if self.doc.model.path else "model"
        path_box = QtWidgets.QLineEdit(str(OUTPUTS / stem))
        browse = QtWidgets.QPushButton("…")
        browse.setFixedWidth(30)
        file_row = QtWidgets.QHBoxLayout()
        file_row.addWidget(path_box, 1)
        file_row.addWidget(browse)

        def choose():
            chosen, _ = QtWidgets.QFileDialog.getSaveFileName(dialog, "Name the pictures", path_box.text(),
                                                              "PNG pictures (*.png)")
            if chosen:
                path_box.setText(re.sub(r"(\.(colour|material|shaded))?\.png$", "", chosen, flags=re.IGNORECASE))
        browse.clicked.connect(choose)

        def kind_changed(index):
            scale.setEnabled(index == 0)
            for box in views.values():
                box.setEnabled(index == 0)
        kind.currentIndexChanged.connect(kind_changed)
        form.addRow("Kind", kind)
        form.addRow("Size", scale)
        form.addRow("Views", row)
        form.addRow("Name", file_row)
        note = QtWidgets.QLabel("Each view: .colour.png (the colour table as palette), .material.png (a colour per "
                                "material) and .shaded.png (to look at). Paint on the first two, then File > "
                                "Import voxel PNG…")
        note.setWordWrap(True)
        note.setStyleSheet("color: #888")
        form.addRow(note)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok
                                             | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        dialog.kind, dialog.scale, dialog.views, dialog.path_box = kind, scale, views, path_box  # for tests
        return dialog, lambda: (kind.currentIndex(), scale.value(), [n for n, b in views.items() if b.isChecked()],
                                Path(path_box.text().strip()))

    def export_dialog(self):
        if not (self.doc.model.colour > 0).any():
            QtWidgets.QMessageBox.information(self.window, "Export voxel PNG", "The model is empty.")
            return
        dialog, read = self.export_form()
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        kind, scale, views, base = read()
        try:
            files = self.export(kind, scale, views, base)
        except Exception as error:
            QtWidgets.QMessageBox.warning(self.window, "Export voxel PNG", str(error))
            return
        self.window.statusBar().showMessage(f"{len(files)} pictures in {base.parent}", 6000)

    def export(self, kind: int, scale: int, views: list[str], base: Path) -> list[Path]:
        model = self.doc.model
        prints = tuple(f.hex() for f in vx2.fingerprints(model.colors, model.materials))
        if kind == 1:
            return voxel_png.export_slices(model.colour, model.material, model.table, base, prints)
        if not views:
            raise ValueError("Choose at least one view.")
        return voxel_png.export_views(model.colour, model.material, model.table, base, views, scale, prints)

    # --- import -----------------------------------------------------------------------------
    def import_dialog(self):
        start = str(OUTPUTS if OUTPUTS.is_dir() else Path.home())
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self.window, "Import voxel PNG: a slice sheet, or painted views", start,
            "Voxel PNGs (*.colour.png *.material.png);;All PNG pictures (*.png)")
        if paths:
            self.import_paths([Path(p) for p in paths])

    def import_paths(self, paths: list[Path]) -> dict | None:
        """Slice sheets open as a new model; views paint onto the shown one. Returns the report, or None."""
        sheets = [p for p in paths if voxel_png.SLICES_NAME.search(p.name)
                  or (voxel_png.read_info(p) or {}).get("kind") == "slices"]
        try:
            if sheets:
                return self._import_slices(sheets[0] if len(sheets) == 1 else None, paths)
            return self._import_views(paths)
        except Exception as error:
            QtWidgets.QMessageBox.warning(self.window, "Import voxel PNG", str(error))
            return None

    def _import_slices(self, sheet: Path | None, paths: list[Path]) -> dict | None:
        if sheet is None or len(paths) > 2:
            raise ValueError("Import one slice sheet at a time (its .colour.png; the .material.png beside it is "
                             "read too).")
        if sheet.name.lower().endswith(".material.png"):
            sheet = sheet.with_name(re.sub(r"\.material\.png$", ".colour.png", sheet.name, flags=re.IGNORECASE))
        w = self.window
        if not w.ask_save(w.unsaved()[:1] if w.model_unsaved() else [], f"Save before opening {sheet.name}?",
                          model_only=True):
            return None
        known = lambda mid: 0 <= mid < len(self.doc.model.materials)  # noqa: E731  (a new model has none of its own)
        colour, material, report = voxel_png.import_slices(sheet, self.doc.model.table, known)
        self.doc.load_planes(colour, material)
        note = f", {report['snapped_pixels']} pixels to the nearest table colour" if report["snapped_pixels"] else ""
        w.statusBar().showMessage(f"{sheet.name}: {report['voxels']} voxels, a new model (unsaved){note}", 8000)
        return report

    def _import_views(self, paths: list[Path]) -> dict | None:
        looks = [p for p in paths if p.name.lower().endswith((".shaded.png", ".render.png"))]
        paths = [p for p in paths if p not in looks]
        if not paths:
            raise ValueError("The .shaded.png and .render.png pictures are only to look at: import the "
                             ".colour.png and .material.png you painted.")
        model = self.doc.model
        points, colours, materials, report = voxel_png.import_views(model.colour, model.material, paths,
                                                                    model.table, model.has_material)
        changed = self.doc.set_voxel_values(points, colours, materials) if len(points) else 0
        outside = sum(v["outside"] for v in report["views"].values())
        parts = [f"{changed} voxels changed from {', '.join(report['views'])}"]
        if outside:
            parts.append(f"{outside} painted pixels showed no voxel and were left out")
        if report["snapped_pixels"]:
            parts.append(f"{report['snapped_pixels']} pixels took the nearest table colour")
        self.window.statusBar().showMessage("; ".join(parts), 10000)
        return {**report, "changed_voxels": changed}
