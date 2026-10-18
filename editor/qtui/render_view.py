"""The model in the path tracer (VoxelRenderer.dll), live, at the dock's size.

Left or right drag orbits, middle drag pans, the wheel zooms, a double click
frames the model. Pause (the Light dock's button, or F9) stops drawing and frees
the GPU; the last picture stays. Tilt blur (the Light dock) switches the
tilt-shift band on and off. A hidden or closed render dock draws nothing either. The engine starts after the
window shows (the first start builds shaders and DLSS and takes about half a
minute).
"""
from __future__ import annotations

import sys
import time

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

from core.camera import OrbitCamera

MAX_WIDTH = 1600  # cap on the render size; the image is scaled to the dock beyond it
RESIZE_DELAY_MS = 250


class RenderView(QtWidgets.QWidget):
    paused_changed = QtCore.Signal(bool)

    def __init__(self, doc):
        super().__init__()
        self.doc = doc
        self.engine = None
        self.message = "Starting the renderer…"
        self.camera = OrbitCamera()
        self.image = None
        self.drag = None  # (button, last position)
        self.moving_until = 0.0
        self.setMinimumSize(160, 120)
        self.setMouseTracking(False)
        self._resize_timer = QtCore.QTimer(self, singleShot=True, interval=RESIZE_DELAY_MS, timeout=self._fit_size)
        self._tick = QtCore.QTimer(self, interval=16, timeout=self.tick)
        self.paused = False
        self.tilt_blur = True
        self.sun, self.sky = 1.0, 1.0  # the built-in daylight; the Light dock sets them
        self.golden = True  # the built-in golden hour, else its daytime light
        self.custom_light = None  # None: the built-in light; else the 18 numbers of renderer_set_light
        doc.reset.connect(self._on_reset)
        doc.material_edited.connect(self._on_material_edited)
        doc.tables_changed.connect(lambda: self._on_material_edited(-1))

    def start(self):
        try:
            from engine_view import EngineView
            w, h = self._wanted_size()
            self.engine = EngineView(w, h)
        except Exception as error:  # the editor works without it, just without the render
            print(f"Engine view unavailable: {error}", file=sys.stderr)
            self.message = f"Renderer unavailable:\n{error}"
            self.update()
            return
        self.message = ""
        self.engine.renderer.tilt_blur(self.tilt_blur)
        self.engine.renderer.daylight(self.sun, self.sky)
        self.engine.renderer.golden_hour(self.golden)
        self.engine.renderer.light(self.custom_light is not None, self.custom_light)
        if not self.paused:
            self._tick.start()

    def set_daylight(self, sun: float, sky: float):
        """The sun's and the sky's strength, 1 each the built-in light, 0 night (to judge glowing
        materials)."""
        self.sun, self.sky = float(sun), float(sky)
        if self.engine is not None:
            self.engine.renderer.daylight(self.sun, self.sky)
            self.engine.samples = 0  # draw the new light even when the old picture had settled

    def set_golden_hour(self, enabled: bool):
        self.golden = bool(enabled)
        if self.engine is not None:
            self.engine.renderer.golden_hour(self.golden)
            self.engine.samples = 0

    def set_light(self, values=None, golden: bool | None = None):
        """A custom light (18 numbers: sun direction, sun radiance, sky horizon, sky zenith, backdrop top
        and bottom), or None for the built-in one; golden: the built-in light underneath."""
        self.custom_light = None if values is None else [float(v) for v in values]
        if golden is not None:
            self.golden = bool(golden)
        if self.engine is not None:
            self.engine.renderer.golden_hour(self.golden)
            self.engine.renderer.light(self.custom_light is not None, self.custom_light)
            self.engine.samples = 0

    def set_tilt_blur(self, enabled: bool):
        self.tilt_blur = enabled
        if self.engine is not None:
            self.engine.renderer.tilt_blur(enabled)
            self.engine.samples = 0  # draw the new picture even when the old one had settled

    def set_paused(self, paused: bool):
        """Stop or resume drawing; while paused, edits, the camera and material changes wait."""
        self.paused = paused
        self.paused_changed.emit(paused)
        if self.engine is not None:
            if paused:
                self._tick.stop()
            else:
                self._tick.start()
        self.update()

    def _wanted_size(self):
        w, h = max(64, self.width()), max(64, self.height())
        if w > MAX_WIDTH:
            w, h = MAX_WIDTH, max(64, int(h * MAX_WIDTH / w))
        return w - w % 2, h - h % 2

    def _fit_size(self):
        if self.engine is None:
            return
        w, h = self._wanted_size()
        if self.engine.rgba.shape[:2] != (h, w):
            self.engine.rgba = np.zeros((h, w, 4), dtype=np.uint8)
            self.engine.samples = 0
            self.engine.last_frame = 0.0

    def _on_reset(self):
        if self.engine is not None:
            self.engine.framed = False
            self.engine.shown_version = -1  # another Model's version may happen to match

    def _on_material_edited(self, material: int):
        """Resend the tables on the next tick (cheap: the voxels are unchanged, only shading is redone),
        which also notices a material that became animated."""
        if self.engine is not None:
            self.engine.shown_version = -1

    @property
    def samples(self) -> int:
        return self.engine.samples if self.engine is not None else 0

    def tick(self):
        if not self.isVisible():
            return  # a hidden or closed dock costs no GPU time
        engine = self.engine
        engine.sync(self.doc.model, self.camera)
        moving = time.perf_counter() < self.moving_until
        if engine.frame(self.camera, moving):
            rgba = engine.rgba
            h, w = rgba.shape[:2]
            self._pixels = rgba.copy()
            self.image = QtGui.QImage(self._pixels.data, w, h, 4 * w, QtGui.QImage.Format.Format_RGBA8888)
            self.update()

    # --- drawing ----------------------------------------------------------------------
    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.fillRect(self.rect(), QtGui.QColor(20, 20, 22))
        if self.image is not None:
            size = self.image.size().scaled(self.size(), QtCore.Qt.AspectRatioMode.KeepAspectRatio)
            target = QtCore.QRect(QtCore.QPoint(0, 0), size)
            target.moveCenter(self.rect().center())
            painter.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform, True)
            painter.drawImage(target, self.image)
            painter.setPen(QtGui.QColor(200, 200, 200, 160))
            painter.drawText(self.rect().adjusted(6, 4, -6, -4),
                             QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignBottom,
                             (f"paused · {self.samples} spp" if self.paused else f"{self.samples} spp")
                             + (" · no DLSS" if self.engine is not None and self.engine.renderer.reconstruction == 0 else ""))
        if self.message:
            painter.setPen(QtGui.QColor(220, 220, 220))
            painter.drawText(self.rect(), QtCore.Qt.AlignmentFlag.AlignCenter, self.message)

    def resizeEvent(self, event):
        self._resize_timer.start()
        super().resizeEvent(event)

    # --- camera -----------------------------------------------------------------------
    def _moved(self):
        self.moving_until = time.perf_counter() + 0.15

    def mousePressEvent(self, event):
        self.drag = (event.button(), event.position())

    def mouseMoveEvent(self, event):
        if self.drag is None:
            return
        button, last = self.drag
        delta = event.position() - last
        if button in (QtCore.Qt.MouseButton.LeftButton, QtCore.Qt.MouseButton.RightButton):
            self.camera.rotate(delta.x(), delta.y())  # grab the model, as in the VTK view
        elif button == QtCore.Qt.MouseButton.MiddleButton:
            self.camera.pan(delta.x(), delta.y())
        self.drag = (button, event.position())
        self._moved()

    def mouseReleaseEvent(self, event):
        self.drag = None

    def mouseDoubleClickEvent(self, event):
        if self.engine is not None:
            self.engine.reframe(self.camera)
            self._moved()

    def wheelEvent(self, event):
        self.camera.zoom(event.angleDelta().y() / 120)
        self._moved()

    def close_engine(self):
        self._tick.stop()
        if self.engine is not None:
            self.engine.close()
            self.engine = None
