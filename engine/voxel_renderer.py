"""The renderer (a Vulkan path tracer, with DLSS Ray Reconstruction when available) through ctypes.

It ships as a binary, VoxelRenderer.dll with its shaders; older builds call it
SpellRenderer.dll, which loads too. This wraps its C API (renderer_api.h). The
DLL's folder is renderer_path in editor/editor.local.json, or editor/renderer
(local_config.py).
"""
from __future__ import annotations

import ctypes
import json
import os
import sys
from pathlib import Path

import numpy as np

import local_config

ROOT = Path(__file__).resolve().parent.parent
SCALE = 1 / 32  # world units per voxel
TABLE_TOP = -0.3125

# Material styles (renderer_api.h); every other material goes as style 0 with its
# roughness, metal, emission and transmission.
STYLE_BY_NAME = {"staff field": 2, "water": 3, "mirror metal": 6}
STYLE_BY_GROUP = {"subsurface": 5}
# Magic lights (materials.json "light"): animated emissive styles 8-13.
LIGHT_STYLE = {"fire": 8, "pulse": 9, "flash": 10, "sickly": 11, "unnatural": 12, "arcane": 13}
GEM_VOXELS = 128  # at most this many staff-field voxels get the staff's point light


def style_of(m: dict) -> int:
    """A material's renderer style; anything that scatters inside (sss > 0: skin, jade, ice) is subsurface."""
    if m.get("light"):
        return LIGHT_STYLE[m["light"]]
    if m["name"] in STYLE_BY_NAME:
        return STYLE_BY_NAME[m["name"]]
    return 5 if m["sss"] > 0 else STYLE_BY_GROUP.get(m["group"], 0)

_F, _I, _B = ctypes.c_float, ctypes.c_int, ctypes.c_bool


def material_fields(m: dict) -> list[float]:
    """A material's fields in renderer_set_voxel_material_fields' order: roughness, metal,
    emission, transmission, ior, sss, subsurface,
    density, sheen, and a 0 where the renderer once took "thin" (a field no material sets now).
    Tables without the newer fields get their defaults."""
    return [float(m["roughness"]), float(m["metal"]), float(m["emission"]), float(m["transmission"]),
            float(m.get("ior", 1.5)), float(m.get("sss", 0)),
            float(m.get("subsurface", 1 if m.get("sss", 0) > 0 or m.get("group") == "subsurface" else 0)),
            float(m.get("density", 4)), float(m.get("sheen", 0)), 0.0]


DLL_NAMES = ("VoxelRenderer.dll", "SpellRenderer.dll")  # the second: builds before the neutral name
# MSVC's exception code: a C++ exception left a renderer build from before renderer_last_error.
CPP_EXCEPTION = 0xE06D7363
REQUIREMENTS = ("The renderer needs a GPU with hardware ray tracing under Vulkan 1.3 (NVIDIA RTX 20 or newer, "
                "AMD RX 6000 or newer, Intel Arc) and a current graphics driver.")


class VoxelRenderer:
    def __init__(self, bin_dir: Path | None = None):
        bin_dir = Path(bin_dir) if bin_dir else local_config.renderer_dir()
        dll = next((bin_dir / name for name in DLL_NAMES if (bin_dir / name).exists()), None)
        if dll is None:
            raise FileNotFoundError(f"The renderer is missing: no {DLL_NAMES[0]} in {bin_dir}. Put the "
                                    f"renderer's files there, or set renderer_path in {local_config.CONFIG}.")
        os.add_dll_directory(str(bin_dir))
        self.dll = ctypes.CDLL(str(dll))
        d = self.dll
        d.render_frame.restype = _I
        if hasattr(d, "renderer_last_error"):
            d.renderer_last_error.restype = ctypes.c_char_p
        d.render_frame.argtypes = [ctypes.POINTER(ctypes.c_uint8), _I, _I] + [_F] * 12 + [_B]
        d.renderer_load_asset.argtypes = [_I, ctypes.POINTER(ctypes.c_uint8), _I, _I, _I]
        d.renderer_update_entity.argtypes = [_I, _I, _F, _F, _F, _I]
        d.renderer_remove_entity.argtypes = [_I]
        d.renderer_set_focus_entity.argtypes = [_I]
        d.renderer_set_material.argtypes = [_I, _I, _I, _I, _I]
        d.renderer_load_asset2.argtypes = [_I, ctypes.POINTER(ctypes.c_uint8), ctypes.POINTER(ctypes.c_uint8), _I, _I, _I]
        d.renderer_set_colour.argtypes = [_I, _I, _I, _I]
        d.renderer_set_voxel_material.argtypes = [_I, _I, _F, _F, _F, _F]
        d.renderer_set_voxel_material2.argtypes = [_I, _I, _F, _F, _F, _F, _F, _F, _B]
        d.renderer_set_voxel_material_fields.argtypes = [_I, _I, ctypes.POINTER(_F), _I]
        d.renderer_set_table.argtypes = [_F, _F, _F, _F]
        d.renderer_set_staff_light.argtypes = [_F, _F, _F]
        d.renderer_set_daylight.argtypes = [_F, _F]
        d.renderer_set_tilt_blur.argtypes = [_B]
        d.renderer_set_light.argtypes = [_B, ctypes.POINTER(_F), _I]
        for name in ("renderer_set_golden_hour", "renderer_set_flask_enabled", "renderer_set_denoise",
                     "renderer_set_upscale", "renderer_set_sun_rays_enabled", "renderer_set_traced_caustics"):
            getattr(d, name).argtypes = [_B]
        d.renderer_set_capture_samples.argtypes = [_I]
        d.renderer_set_sickle.argtypes = [_B, ctypes.POINTER(_F)]
        d.renderer_set_lens.argtypes = [_B, ctypes.POINTER(_F)]
        d.init_renderer()
        hidden = (_F * 12)(*([0.0] * 12))
        d.renderer_set_sickle(False, hidden)
        d.renderer_set_lens(False, hidden)
        d.renderer_set_flask_enabled(False)
        d.renderer_set_golden_hour(True)
        d.renderer_set_denoise(True)
        d.renderer_set_upscale(False)
        d.renderer_set_table(-4, -4, 4, 4)

    def close(self) -> None:
        self.dll.shutdown_renderer()

    @property
    def reconstruction(self) -> int:
        """1 DLSS Ray Reconstruction runs; 0 it could not start (no NVIDIA RTX card or driver), so the
        noisy path draws and a still view accumulates; -1 no frame yet, or a DLL from before the fallback."""
        available = getattr(self.dll, "renderer_reconstruction_available", None)
        return int(available()) if available is not None else -1

    def daylight(self, sun: float = 1.0, sky: float = 1.0) -> None:
        """The sun's and the sky's strength (1 = the built-in light); dim them to judge glowing materials."""
        self.dll.renderer_set_daylight(sun, sky)

    def light(self, custom: bool, values=None) -> None:
        """A custom light: 18 numbers, three each: the direction towards the sun, the sun's radiance
        (linear RGB), the sky's horizon and zenith, the backdrop's top and bottom. custom=False goes back
        to the built-in golden-hour or daytime light."""
        values = list(values or [])
        self.dll.renderer_set_light(custom, (_F * max(len(values), 1))(*values), len(values))

    def golden_hour(self, enabled: bool) -> None:
        """The built-in golden-hour light (a low, warm sun; on by default) or its daytime light."""
        self.dll.renderer_set_golden_hour(enabled)

    def tilt_blur(self, enabled: bool) -> None:
        """The tilt-shift blur above and below the model (on by default)."""
        self.dll.renderer_set_tilt_blur(enabled)

    def show(self, colour: np.ndarray, material: np.ndarray, materials: list[dict], colors: list[dict],
             asset: int = 1, entity: int = 1) -> int:
        """Put a two-byte model (planes shaped (z, y, x)) on the table: the renderer gets the colour
        table, the material table and both planes. Returns how many colour-material pairs it uses."""
        for c in colors:
            self.dll.renderer_set_colour(c["id"], *c["rgb"])
        for m in materials:
            values = material_fields(m)
            self.dll.renderer_set_voxel_material_fields(m["id"], style_of(m), (_F * len(values))(*values), len(values))
        colour = np.ascontiguousarray(colour, dtype=np.uint8)
        material = np.ascontiguousarray(np.where(colour > 0, material, 0), dtype=np.uint8)
        sz, sy, sx = colour.shape
        as_bytes = ctypes.POINTER(ctypes.c_uint8)
        self.dll.renderer_load_asset2(asset, colour.ctypes.data_as(as_bytes), material.ctypes.data_as(as_bytes), sx, sy, sz)
        self.origin = (-sx / 2 * SCALE, -sy / 2 * SCALE, TABLE_TOP)
        self.size = (sx * SCALE, sy * SCALE, sz * SCALE)
        self.dll.renderer_update_entity(entity, asset, *self.origin, 0)
        self.dll.renderer_set_focus_entity(entity)  # the miniature focus band follows this model
        solid = colour > 0
        # The renderer's cyan point light stands in for a small gem's light (about 40 voxels),
        # so it sits in a gem-sized group of staff-field voxels. A bigger
        # glowing body lights by its own emission, and a model without them gets none (the
        # light parked far beyond its 3-unit reach).
        field = [m["id"] for m in materials if STYLE_BY_NAME.get(m["name"]) == 2]
        z, y, x = np.nonzero(solid & np.isin(material, field))
        if 0 < len(x) <= GEM_VOXELS:
            self.dll.renderer_set_staff_light(self.origin[0] + x.mean() * SCALE, self.origin[1] + y.mean() * SCALE,
                                              self.origin[2] + z.mean() * SCALE)
        else:
            self.dll.renderer_set_staff_light(0, 0, -1000)
        return len(np.unique(colour[solid].astype(np.uint16) * 256 + material[solid]))

    def render(self, width: int, height: int, yaw_deg: float = -20, pitch_deg: float = 12,
               distance: float | None = None, samples: int = 64) -> np.ndarray:
        """Orbit camera around the model's centre; yaw 0 looks from -y (the model's front). Returns RGBA."""
        cx, cy, cz = (self.origin[0] + self.size[0] / 2, self.origin[1] + self.size[1] / 2,
                      self.origin[2] + self.size[2] / 2)
        distance = distance or 1.45 * max(self.size)
        yaw, pitch = np.radians(yaw_deg), np.radians(pitch_deg)
        eye = np.array([cx + distance * np.sin(yaw) * np.cos(pitch), cy - distance * np.cos(yaw) * np.cos(pitch),
                        cz + distance * np.sin(pitch)])
        forward = np.array([cx, cy, cz]) - eye
        forward /= np.linalg.norm(forward)
        right = np.cross(forward, [0, 0, 1])
        right /= np.linalg.norm(right)
        up = np.cross(right, forward)
        return self.render_camera(width, height, eye, forward, right, up, samples)

    def render_camera(self, width: int, height: int, eye, forward, right, up, samples: int = 64) -> np.ndarray:
        """A still from a given camera (world units, as the editor's Render dock holds it). Returns RGBA."""
        out = np.zeros((height, width, 4), dtype=np.uint8)
        pointer = out.ctypes.data_as(ctypes.POINTER(ctypes.c_uint8))
        self.capture(samples)
        done = 0
        for _ in range(100000):
            done = self._render_frame(pointer, width, height, *eye, *forward, *right, *up, False)
            if done >= samples:
                break
        self.capture(0)
        return out

    def capture(self, samples: int) -> None:
        """Make each frame() accumulate a still towards `samples` (render_camera in steps, for a window that
        stays responsive); 0 goes back to live frames."""
        self.dll.renderer_set_capture_samples(samples)

    @property
    def centre(self):
        return (self.origin[0] + self.size[0] / 2, self.origin[1] + self.size[1] / 2, self.origin[2] + self.size[2] / 2)

    def frame(self, out: np.ndarray, eye, forward, right, up, moving: bool) -> int:
        """One live frame into `out` (height x width x 4 uint8): as many samples as fit the renderer's
        frame budget, accumulating while the camera and model stay still. Returns the samples so far."""
        height, width = out.shape[:2]
        return self._render_frame(out.ctypes.data_as(ctypes.POINTER(ctypes.c_uint8)), width, height,
                                  *map(float, eye), *map(float, forward), *map(float, right), *map(float, up),
                                  bool(moving))

    def _render_frame(self, *args) -> int:
        """render_frame, its failure raised as a RuntimeError with the renderer's own message. The first
        frame makes the Vulkan device, so a GPU the renderer cannot use fails here, not at load."""
        try:
            done = self.dll.render_frame(*args)
        except OSError as error:
            if (error.winerror or 0) & 0xFFFFFFFF != CPP_EXCEPTION:
                raise
            raise RuntimeError("The renderer failed; this renderer build does not say why (a newer one does). "
                               + REQUIREMENTS) from None
        if done < 0:
            message = self.dll.renderer_last_error().decode("utf-8", "replace")
            raise RuntimeError(f"{message}\n{REQUIREMENTS}" if "ray tracing" in message else message)
        return done


def load_tables():
    colors = json.loads((ROOT / "palette" / "colors.json").read_text(encoding="utf-8"))["colors"]
    materials = json.loads((ROOT / "palette" / "materials.json").read_text(encoding="utf-8"))["materials"]
    return colors, materials
