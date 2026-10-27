"""The Export dock: pictures and orbit videos of the Render dock's view, drawn in the Render dock.

Picture: Render picture… asks for the size, samples, finish and file (the
window's picture_form) and draws a still. Orbit video (animation.py): the
camera turns about what the Render dock looks at, by an angle (360 once round,
less an arc centred on the view), optionally swung out and back so it loops,
over a length at a frame rate, each frame a picture of a size, samples and
finish. Preview orbit swings the live view the same way; Render video… asks
only for the file. While one draws, its button cancels it.
"""
from __future__ import annotations

from pathlib import Path

import PySide6QtAds as QtAds
from PySide6 import QtCore, QtWidgets


def install_export_panel(window) -> "ExportPanel":
    panel = ExportPanel(window.render_view)
    window._dock("Export", panel, QtAds.DockWidgetArea.CenterDockWidgetArea, window.docks["Brush"].dockAreaWidget(),
                 scroll=True)
    window.docks["Brush"].setAsCurrentTab()
    return panel


class ExportPanel(QtWidgets.QWidget):
    picture_requested = QtCore.Signal()  # Render picture… (the window asks for size, samples, finish, file)

    def __init__(self, render_view):
        super().__init__()
        self.render_view = render_view
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        picture = QtWidgets.QGroupBox("Picture")
        row = QtWidgets.QHBoxLayout(picture)
        note = QtWidgets.QLabel("A still of the Render dock's view, up to 8192 a side.")
        note.setWordWrap(True)
        self.picture_button = QtWidgets.QPushButton("Render picture…")
        self.picture_button.setToolTip("A high-resolution picture of the Render dock's view, saved as a PNG "
                                       "(File > Render picture…)")
        self.picture_button.clicked.connect(self._picture_clicked)
        row.addWidget(note, 1)
        row.addWidget(self.picture_button)
        layout.addWidget(picture)
        layout.addWidget(self._orbit_box())
        hint = QtWidgets.QLabel("Both draw in the Render dock, with its camera, light and setup.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #888")
        layout.addWidget(hint)
        layout.addStretch(1)
        render_view.still_changed.connect(self._show_still)
        render_view.preview_changed.connect(self._show_preview)

    # --- the orbit video --------------------------------------------------------------------
    def _orbit_box(self) -> QtWidgets.QGroupBox:
        import animation
        from postprocess import LOOKS
        max_width, max_height, max_samples, max_frames = animation.ORBIT_LIMITS
        box = QtWidgets.QGroupBox("Orbit video")
        form = QtWidgets.QFormLayout(box)

        def spin(low, high, value, step=1, suffix="", decimals=0, tip=""):
            widget = QtWidgets.QDoubleSpinBox() if decimals else QtWidgets.QSpinBox()
            widget.setRange(low, high)
            widget.setSingleStep(step)
            if decimals:
                widget.setDecimals(decimals)
            widget.setValue(value)
            widget.setSuffix(suffix)
            widget.setToolTip(tip)
            widget.setKeyboardTracking(False)
            return widget
        self.angle_box = spin(-3600, 3600, 60, 15, "\u00b0", 1, "How far the camera turns: 360 goes once round "
                              "from the view, less sweeps an arc centred on it; below 0 turns the other way")
        self.swing_box = QtWidgets.QCheckBox("Swing out and back")
        self.swing_box.setChecked(True)
        self.swing_box.setToolTip("Out to one end of the arc, back through the view to the other end and home, "
                                  "slowing at the ends: loops at any angle. Off: one sweep from end to end")
        self.seconds_box = spin(0.5, 600, 10, 1, " s", 1, "How long the video runs: for the same angle, longer "
                                "is a slower, calmer camera")
        self.fps_box = spin(1, 120, 30, 1, " fps", 0, "Frames per second")
        self.frames_label = QtWidgets.QLabel()
        self.width_box = spin(16, max_width, 1080, 10, "", 0, "Width in pixels")
        self.height_box = spin(16, max_height, 1350, 10, "", 0, "Height in pixels")
        self.shape_box = QtWidgets.QCheckBox("Dock's shape")
        self.shape_box.setChecked(True)
        self.shape_box.setToolTip("The height follows the width in the Render dock's shape")
        self.samples_box = spin(1, max_samples, 128, 16, " spp", 0, "Samples per pixel of each frame: 128 is "
                                "smooth for most models, more for glass and gas; each frame takes as long as a picture")
        self.finish_box = QtWidgets.QComboBox()
        self.finish_box.addItems(list(LOOKS))
        self.finish_box.setToolTip("none: as traced. film: tone curve, soft bloom, vignette. night: strong bloom on "
                                   "glows and reds, cool shadows, grain")
        self.preview_button = QtWidgets.QPushButton("Preview orbit", checkable=True)
        self.preview_button.setToolTip("Swing the live view as the video will, over and over; grabbing the view "
                                       "stops it")
        self.preview_button.toggled.connect(self._preview_toggled)
        self.video_button = QtWidgets.QPushButton("Render video…")
        self.video_button.setToolTip("Render the orbit as MP4 (needs ffmpeg), WebP or GIF; it draws in the Render "
                                     "dock (File > Render video…)")
        self.video_button.clicked.connect(self._video_clicked)
        def row(*widgets):
            line = QtWidgets.QHBoxLayout()
            for widget in widgets:
                line.addWidget(QtWidgets.QLabel(widget) if isinstance(widget, str) else widget)
            line.addStretch(1)
            return line
        form.addRow("Angle", row(self.angle_box))
        form.addRow("", row(self.swing_box))
        form.addRow("Length", row(self.seconds_box, self.fps_box))
        form.addRow("", row(self.frames_label))
        form.addRow("Size", row(self.width_box, "\u00d7", self.height_box))
        form.addRow("", row(self.shape_box))
        form.addRow("Samples", row(self.samples_box))
        form.addRow("Finish", row(self.finish_box))
        buttons = QtWidgets.QHBoxLayout()
        buttons.addWidget(self.preview_button)
        buttons.addStretch(1)
        buttons.addWidget(self.video_button)
        form.addRow(buttons)
        for widget in (self.angle_box, self.seconds_box):
            widget.valueChanged.connect(self._orbit_changed)
        self.swing_box.toggled.connect(self._orbit_changed)
        self.fps_box.valueChanged.connect(self._orbit_changed)
        self.width_box.valueChanged.connect(self._fit_height)
        self.shape_box.toggled.connect(self._fit_height)
        self.height_box.valueChanged.connect(self._height_typed)
        self._fit_height()
        self._orbit_changed()
        return box

    def orbit_settings(self) -> dict:
        """The video as the section sets it: render_orbit's arguments but the file."""
        self._fit_height()
        return {"width": self.width_box.value(), "height": self.height_box.value(),
                "samples": self.samples_box.value(), "look": self.finish_box.currentText(),
                "frames": max(2, round(self.seconds_box.value() * self.fps_box.value())),
                "fps": self.fps_box.value(), "degrees": self.angle_box.value(), "swing": self.swing_box.isChecked()}

    def _kept_height(self) -> int:
        view = self.render_view
        aspect = max(view.width(), 1) / max(view.height(), 1)
        return max(16, min(self.height_box.maximum(), round(self.width_box.value() / aspect)))

    def _fit_height(self, *_) -> None:
        if self.shape_box.isChecked() and self.height_box.value() != self._kept_height():
            self.height_box.blockSignals(True)
            self.height_box.setValue(self._kept_height())
            self.height_box.blockSignals(False)

    def _height_typed(self, *_) -> None:  # a height of one's own lets go of the dock's shape
        if self.shape_box.isChecked() and self.height_box.value() != self._kept_height():
            self.shape_box.setChecked(False)

    def _orbit_changed(self, *_) -> None:
        frames = max(2, round(self.seconds_box.value() * self.fps_box.value()))
        self.frames_label.setText(f"{frames} frames")
        if self.render_view.preview is not None:  # the preview follows the settings
            self._preview_toggled(True)

    def _preview_toggled(self, on: bool) -> None:
        settings = self.orbit_settings()
        self.render_view.preview_orbit({"degrees": settings["degrees"], "swing": settings["swing"],
                                        "seconds": self.seconds_box.value()} if on else None)

    def _show_preview(self, on: bool) -> None:
        self.preview_button.blockSignals(True)
        self.preview_button.setChecked(on)
        self.preview_button.blockSignals(False)

    def _video_clicked(self) -> None:
        if self.render_view.still is not None:
            self.render_view.cancel_still()
        else:
            self.render_video()

    def render_video(self, path: str | None = None) -> str | None:
        """Ask for the file (unless given) and start the orbit video with the section's settings. Returns
        the file it started, or None (cancelled, or a message said why not)."""
        import animation
        from core.model import ROOT
        if self.render_view.still is not None:
            QtWidgets.QMessageBox.information(self, "Render video", "A picture or video is already rendering.")
            return None
        if path is None:
            model_path = self.render_view.drawn_model().path
            stem = Path(model_path).stem if model_path else "model"
            suffix = ".mp4" if animation.ffmpeg() else ".webp"
            path, _ = QtWidgets.QFileDialog.getSaveFileName(
                self, "Render video", str(ROOT / "editor" / "outputs" / f"{stem}-orbit{suffix}"),
                "Video (*.mp4);;Animated WebP (*.webp);;Animated GIF (*.gif)")
            if not path:
                return None
            if Path(path).suffix.lower() not in animation.FORMATS:
                path += suffix
        problem = self.render_view.render_orbit(path, **self.orbit_settings())
        if problem:
            QtWidgets.QMessageBox.warning(self, "Render video", problem)
            return None
        return path

    def _picture_clicked(self) -> None:
        if self.render_view.still is not None:
            self.render_view.cancel_still()
        else:
            self.picture_requested.emit()

    def _show_still(self, rendering: bool) -> None:
        video = rendering and "orbit" in (self.render_view.still or {})
        self.picture_button.setText("Cancel picture" if rendering and not video else "Render picture…")
        self.video_button.setText("Cancel video" if video else "Render video…")
        self.picture_button.setEnabled(not video)
        self.video_button.setEnabled(not rendering or video)
        self.preview_button.setEnabled(not rendering)
