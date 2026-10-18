"""Python access to the editor's two-byte model, without the window: the base of the MCP server and the CLI.

Coordinates are (x, y, z) integers, z up, box ends inclusive. Colours are slots
1-255 in VoxelPipeline/palette/colors.json (0 erases), materials ids in
materials.json. Protected boxes are restored after every edit. `render` draws
with the path tracer (VoxelRenderer.dll), loaded on first use.
"""
from __future__ import annotations

import io
import sys
import threading
from functools import wraps
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from core.model import Model, ROOT as PIPELINE  # noqa: E402
from logic.tools import commit_shape  # noqa: E402
from voxel_preview import render_preview  # noqa: E402

OUTPUTS = ROOT / "outputs"


def synchronized(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return call


class VoxelEditor:
    def __init__(self):
        self._lock = threading.RLock()
        self.model = Model()
        self._engine = None
        self._engine_version = -1
        self.palette = np.zeros((256, 4), dtype=np.uint8)
        for c in self.model.colors:
            self.palette[c["id"]] = [*c["rgb"], 255]
        self.new_model()

    # --- files -----------------------------------------------------------------------
    @synchronized
    def new_model(self, x=32, y=32, z=64):
        for d in (x, y, z):
            if type(d) is not int:
                raise ValueError("Each dimension must be an integer.")
        self.model.new(x, y, z)
        self._protected = np.zeros(self.model.colour.shape, dtype=bool)
        return self.info()

    @synchronized
    def open_model(self, path, material_overrides=None):
        overrides = {int(k): int(v) for k, v in (material_overrides or {}).items()}
        self.model.open(path, overrides)
        self._protected = np.zeros(self.model.colour.shape, dtype=bool)
        return self.info()

    @synchronized
    def save_model(self, name, export_vox=True):
        target = self.model.save(name, export_vox)
        return {"path": str(target), "export": str(PIPELINE / "export" / f"{target.stem}.vox") if export_vox else None,
                **self.info()}

    # --- questions ---------------------------------------------------------------------
    @synchronized
    def info(self):
        info = self.model.info()
        solid = np.argwhere(self.model.colour > 0)
        info["bounds"] = [solid.min(axis=0)[::-1].tolist(), solid.max(axis=0)[::-1].tolist()] if len(solid) else None
        info["protected_voxels"] = int((self._protected & (self.model.colour > 0)).sum())
        return info

    @synchronized
    def colour_table(self, family=None):
        rows = [{"slot": c["id"], "hex": c["hex"], "family": c["band"]} for c in self.model.colors]
        return [r for r in rows if not family or family.lower() in r["family"].lower()]

    @synchronized
    def nearest_colours(self, hex_value, count=5):
        return self.model.nearest_colours(hex_value, count)

    @synchronized
    def materials(self):
        return [{k: m[k] for k in ("id", "name", "group", "engine", "note")} for m in self.model.all_materials()]

    # --- edits ---------------------------------------------------------------------------
    def _finish(self, changed):
        """Restore protected voxels from before the edit; report what really changed."""
        if changed and self._protected.any():
            before_c, before_m = self.model.undo_stack[-1]
            self.model.colour[self._protected] = before_c[self._protected]
            self.model.material[self._protected] = before_m[self._protected]
            changed = int(((self.model.colour != before_c) | (self.model.material != before_m)).sum())
            if not changed:
                self.model.undo_stack.pop()
            self.model.version += 1
        return {"changed_voxels": changed, **self.info()}

    @staticmethod
    def _check_box(start, end):
        if len(start) != 3 or len(end) != 3 or any(type(v) is not int for v in [*start, *end]):
            raise ValueError("Boxes need two corners of three integers: [x, y, z].")

    def _check_inside(self, start, end):
        sz, sy, sx = self.model.colour.shape
        if any(a < 0 or b < a or b >= dim for a, b, dim in zip(start, end, (sx, sy, sz))):
            raise ValueError(f"Inclusive box is outside the model ({sx} x {sy} x {sz}) or reversed.")

    @synchronized
    def paint_box(self, start, end, colour, material=0):
        self._check_box(start, end)
        self._check_inside(start, end)
        if colour == 0:
            return self._finish(self.model.erase_box(start, end))
        return self._finish(self.model.paint_box(start, end, colour, material))

    @synchronized
    def erase_box(self, start, end):
        self._check_box(start, end)
        self._check_inside(start, end)
        return self._finish(self.model.erase_box(start, end))

    @synchronized
    def shape_slice(self, axis, depth, start, end, colour, material=0, shape="Rect"):
        """The slice views' Rect/Circle tool in an x, y or z plane; colour 0 erases."""
        axes = {"x": (1, 2, 0), "y": (0, 2, 1), "z": (0, 1, 2)}
        if axis not in axes or shape not in ("Rect", "Circle") or len(start) != 2 or len(end) != 2:
            raise ValueError("Use axis x/y/z, two [u, v] corners, and Rect or Circle.")
        u, v, d = axes[axis]
        first, last = [0, 0, 0], [0, 0, 0]
        first[u], first[v], first[d] = start[0], start[1], depth
        last[u], last[v], last[d] = end[0], end[1], depth
        self._check_inside([min(a, b) for a, b in zip(first, last)], [max(a, b) for a, b in zip(first, last)])
        self.model._check_colour(colour, allow_empty=True)
        self.model._check_material(material)
        cfg = {"u": u, "v": v, "d": d, "inv_u": False, "inv_v": False}
        grid, mat = self.model.colour.transpose(2, 1, 0), self.model.material.transpose(2, 1, 0)
        self.model.checkpoint()
        before = self.model.undo_stack[-1]
        commit_shape(grid, cfg, *start, *end, depth, shape, colour,
                     coord_func=lambda c, a, b, dep: _coord(c, a, b, dep), mat_grid=mat, mat_val=material)
        self.model.touched()
        changed = int(((self.model.colour != before[0]) | (self.model.material != before[1])).sum())
        if not changed:
            self.model.undo_stack.pop()
        return self._finish(changed)

    @synchronized
    def set_material_box(self, start, end, material):
        self._check_box(start, end)
        self._check_inside(start, end)
        return self._finish(self.model.set_material_box(start, end, material))

    @synchronized
    def set_material_for_colour(self, colour, material):
        return self._finish(self.model.set_material_for_colour(colour, material))

    @synchronized
    def replace_colour(self, old, new, material=None):
        return self._finish(self.model.replace_colour(old, new, material))

    @synchronized
    def protect_box(self, start, end):
        self._check_box(start, end)
        self._check_inside(start, end)
        z, y, x = self.model._box(start, end)
        self._protected[z, y, x] = True
        return self.info()

    @synchronized
    def clear_protection(self):
        self._protected[:] = False
        return self.info()

    @synchronized
    def undo(self):
        return {"changed": self.model.undo(), **self.info()}

    @synchronized
    def redo(self):
        return {"changed": self.model.redo(), **self.info()}

    # --- pictures ------------------------------------------------------------------------
    @synchronized
    def preview_png(self):
        """Flat editing views (front, back, right, isometric) of the voxel colours; fast, no lighting."""
        image = render_preview(self.model.colour.transpose(2, 1, 0), self.palette)
        out = io.BytesIO()
        image.save(out, format="PNG")
        return out.getvalue()

    @synchronized
    def render_png(self, yaw=-25.0, pitch=10.0, width=640, height=640, samples=64):
        """The model in the path tracer: on the wooden table under the golden-hour sun."""
        if not (16 <= width <= 1920 and 16 <= height <= 1080 and 1 <= samples <= 1024):
            raise ValueError("width 16-1920, height 16-1080, samples 1-1024")
        if not (self.model.colour > 0).any():
            raise ValueError("The model is empty.")
        if self._engine is None:
            sys.path.insert(0, str(PIPELINE / "engine"))
            from voxel_renderer import VoxelRenderer
            self._engine = VoxelRenderer()
        if self._engine_version != self.model.version:
            self._engine.show(self.model.colour, self.model.material, self.model.all_materials(), self.model.colors)
            self._engine_version = self.model.version
        from PIL import Image
        rgba = self._engine.render(width, height, yaw_deg=yaw, pitch_deg=pitch, samples=samples)
        out = io.BytesIO()
        Image.fromarray(rgba[..., :3].copy()).save(out, format="PNG")
        return out.getvalue()

    @staticmethod
    def output_path(name):
        target = (OUTPUTS / name).resolve()
        if not target.is_relative_to(OUTPUTS.resolve()) or target.suffix.lower() != ".png":
            raise ValueError("Pictures are saved as .png inside the editor's outputs folder.")
        target.parent.mkdir(parents=True, exist_ok=True)
        return target

    def save_preview(self, name="preview.png"):
        target = self.output_path(name)
        target.write_bytes(self.preview_png())
        return str(target)

    def save_render(self, name="render.png", **options):
        target = self.output_path(name)
        target.write_bytes(self.render_png(**options))
        return str(target)

    def close(self):
        if self._engine is not None:
            self._engine.close()
            self._engine = None


def _coord(cfg, u, v, depth):
    c = [0, 0, 0]
    c[cfg["u"]], c[cfg["v"]], c[cfg["d"]] = u, v, depth
    return tuple(c)
