"""The model in the path tracer (VoxelRenderer.dll), live, at the dock's size.

Left or right drag orbits, middle drag pans, the wheel zooms, a double click
frames the model. Pause (the Light dock's button, or F9) stops drawing and frees
the GPU; the last picture stays. Tilt blur (the Light dock) switches the
tilt-shift band on and off. A hidden or closed render dock draws nothing either. The engine starts after the
window shows (the first start builds shaders and DLSS and takes about half a
minute). render_still draws a picture of any size from the dock's camera and light into a file, in
steps (the window stays responsive), showing its progress here.
"""
from __future__ import annotations

import sys
import time

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

from core.camera import OrbitCamera

MAX_WIDTH = 1600  # cap on the render size; the image is scaled to the dock beyond it
RESIZE_DELAY_MS = 250
STILL_LIMITS = (8192, 8192, 4096)  # width, height, samples of a picture render_still draws
STILL_SHOW_INTERVAL = 0.25  # seconds between showing a still's progress in the dock


class RenderView(QtWidgets.QWidget):
    paused_changed = QtCore.Signal(bool)
    still_changed = QtCore.Signal(bool)  # a picture started (True) or ended
    still_finished = QtCore.Signal(str, str)  # the saved file ("" when it failed or was cancelled), a message

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
        self.source = None  # None: the model being edited; else a callable giving the Model to draw (a scene)
        self._drawn = None  # the Model drawn last, to reframe when another one takes its place
        self.still = None  # the picture render_still is drawing: its file, size, camera, samples so far
        doc.reset.connect(self._on_reset)
        doc.resized.connect(self._on_reset)
        doc.material_edited.connect(self._on_material_edited)
        doc.tables_changed.connect(lambda: self._on_material_edited(-1))
        doc.colours_changed.connect(lambda: self._on_material_edited(-1))  # the colours go with the tables

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

    def drawn_model(self):
        """What the render shows: the source's Model (a scene) when it gives one, else the model being edited."""
        model = self.source() if self.source is not None else None
        return model if model is not None else self.doc.model

    @property
    def samples(self) -> int:
        return self.engine.samples if self.engine is not None else 0

    # --- pictures of any size ------------------------------------------------------------
    def render_still(self, path, width: int, height: int, samples: int, look: str = "none") -> str | None:
        """Start a picture of what the dock shows (its camera, light and tilt blur, the model as it is now)
        at width x height, `samples` per pixel, saved as the PNG `path` with a finish from
        postprocess.LOOKS. It draws in steps on this dock's ticks, while pausing and edits wait. Returns
        why it cannot start, else None; still_finished tells how it ended."""
        from postprocess import LOOKS
        max_width, max_height, max_samples = STILL_LIMITS
        if self.engine is None:
            return "The renderer is not running."
        if self.still is not None:
            return "A picture is already rendering."
        if not (16 <= width <= max_width and 16 <= height <= max_height and 1 <= samples <= max_samples):
            return f"Width 16-{max_width}, height 16-{max_height}, samples 1-{max_samples}."
        if look not in LOOKS:
            return f"Unknown finish {look!r}: one of {', '.join(LOOKS)}."
        self.engine.sync(self.drawn_model(), self.camera, force=True)
        cam = self.camera
        self.still = {"path": str(path), "look": look, "samples": int(samples), "done": 0, "shown": 0.0,
                      "rgba": np.zeros((height, width, 4), dtype=np.uint8),
                      "view": [np.array(v, dtype=float) for v in (cam.pos, cam.fwd, cam.right, cam.up)]}
        self.engine.renderer.capture(int(samples))
        self._tick.start()  # also while paused: the picture was asked for
        self.still_changed.emit(True)
        self.update()
        return None

    def cancel_still(self):
        if self.still is not None:
            self._end_still("", "Picture cancelled.")

    def _still_step(self):
        still = self.still
        try:
            still["done"] = self.engine.renderer.frame(still["rgba"], *still["view"], False)
        except Exception as error:  # a size the GPU cannot hold, a lost device
            self._end_still("", f"The picture failed: {error}")
            return
        now = time.perf_counter()
        finished = still["done"] >= still["samples"]
        if finished or now - still["shown"] >= STILL_SHOW_INTERVAL:
            still["shown"] = now
            self._show(still["rgba"])
        if finished:
            self._save_still()

    def _save_still(self):
        from PIL import Image
        from postprocess import finish
        still = self.still
        try:
            Image.fromarray(finish(still["rgba"][..., :3].copy(), still["look"])).save(still["path"], format="PNG")
        except (OSError, ValueError) as error:
            self._end_still("", f"The picture could not be saved: {error}")
            return
        h, w = still["rgba"].shape[:2]
        self._end_still(still["path"], f"Saved a {w} x {h} picture ({still['samples']} spp) to {still['path']}")

    def _end_still(self, path: str, message: str):
        self.still = None
        if self.engine is not None:
            self.engine.renderer.capture(0)
            self.engine.samples = 0  # the live picture draws again at the dock's size
            self.engine.last_frame = 0.0
            self.engine.shown_version = -1  # and catches up with edits made meanwhile
        if self.paused:
            self._tick.stop()
        self.still_changed.emit(False)
        self.still_finished.emit(path, message)
        self.update()

    def _show(self, rgba):
        h, w = rgba.shape[:2]
        self._pixels = rgba.copy()
        self.image = QtGui.QImage(self._pixels.data, w, h, 4 * w, QtGui.QImage.Format.Format_RGBA8888)
        self.update()

    def tick(self):
        if self.still is not None:
            self._still_step()  # also hidden: the picture was asked for
            return
        engine = self.engine
        if engine is None or not self.isVisible():
            return  # a stopped renderer, or a hidden or closed dock: no GPU time
        model = self.drawn_model()
        if model is not self._drawn:
            self._drawn = model
            self._on_reset()
        try:
            engine.sync(model, self.camera)
            moving = time.perf_counter() < self.moving_until
            drawn = engine.frame(self.camera, moving)
        except Exception as error:  # the first frame makes the GPU device: a GPU it cannot use fails here
            self._stop_engine(error)
            return
        if drawn:
            self._show(engine.rgba)

    def _stop_engine(self, error):
        """The renderer failed: say why in the dock and stop asking it for frames; the editor goes on."""
        print(f"Engine view stopped: {error}", file=sys.stderr)
        self._tick.stop()
        try:
            self.engine.close()
        except Exception:
            pass
        self.engine = None
        self.image = None
        self.message = f"Renderer unavailable:\n{error}"
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
            if self.still is not None:
                h, w = self.still["rgba"].shape[:2]
                status = f"picture {w} x {h} · {self.still['done']} / {self.still['samples']} spp"
            else:
                status = f"paused · {self.samples} spp" if self.paused else f"{self.samples} spp"
            painter.drawText(self.rect().adjusted(6, 4, -6, -4),
                             QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignBottom,
                             status + (" · no DLSS" if self.engine is not None
                                       and self.engine.renderer.reconstruction == 0 else ""))
        if self.message:
            painter.setPen(QtGui.QColor(220, 220, 220))
            # Wrapped anywhere: the message can hold a long folder path without spaces.
            painter.drawText(self.rect().adjusted(16, 16, -16, -16),
                             int(QtCore.Qt.AlignmentFlag.AlignCenter) | int(QtCore.Qt.TextFlag.TextWrapAnywhere),
                             self.message)

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
        self.cancel_still()
        self._tick.stop()
        if self.engine is not None:
            self.engine.close()
            self.engine = None
