"""The editor's 3D view: the path tracer (VoxelRenderer.dll), live.

The model goes to the engine only when it changed (and at most every
RELOAD_INTERVAL seconds while painting); frames accumulate samples while
nothing moves and stop once the picture has settled, unless the model has
animated materials (water, the staff field, magic lights): those keep drawing
at ANIMATED_FPS, so they move without holding the GPU at full load.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine"))
from voxel_renderer import VoxelRenderer, style_of  # noqa: E402

RELOAD_INTERVAL = 0.12
SETTLED_SAMPLES = 256
ANIMATED_FPS = 15
# staff field, water, the magic lights, and gas glowing in a magic light's pattern (the flame)
ANIMATED_STYLES = {2, 3, 8, 9, 10, 11, 12, 13, 15, 16, 17, 18, 19, 20}


class EngineView:
    def __init__(self, width: int, height: int):
        self.renderer = VoxelRenderer()
        self.rgba = np.zeros((height, width, 4), dtype=np.uint8)
        self.shown_version = -1
        self.last_reload = 0.0
        self.samples = 0
        self.framed = False
        self.animated = False
        self.last_frame = 0.0

    def sync(self, model, camera, force: bool = False) -> bool:
        """Reload the model into the engine if it changed; frames the camera the first time."""
        if model.version == self.shown_version:
            return False
        now = time.perf_counter()
        if not force and now - self.last_reload < RELOAD_INTERVAL:
            return False
        if (model.colour > 0).any():
            self.renderer.show(model.colour, model.material, model.all_materials(), model.colors)
            used = np.unique(model.material[model.colour > 0])
            self.animated = any(style_of(model.material_info(m)) in ANIMATED_STYLES for m in used)
            if not self.framed:
                camera.frame(self.renderer.centre, max(self.renderer.size))
                self.framed = True
        self.shown_version = model.version
        self.last_reload = now
        self.samples = 0
        return True

    def reframe(self, camera) -> None:
        if self.shown_version >= 0 and hasattr(self.renderer, "origin"):
            camera.frame(self.renderer.centre, max(self.renderer.size))

    def frame(self, camera, moving: bool) -> bool:
        """Render one frame; False when the picture has settled and nothing new was drawn."""
        now = time.perf_counter()
        if not moving and self.samples >= SETTLED_SAMPLES and (
                not self.animated or now - self.last_frame < 1 / ANIMATED_FPS):
            return False
        self.last_frame = now
        self.renderer.projection(camera.ortho, camera.ortho_height)  # cheap; a change starts the picture afresh
        self.samples = self.renderer.frame(self.rgba, camera.pos, camera.fwd, camera.right, camera.up, moving)
        return True

    def close(self) -> None:
        self.renderer.close()
