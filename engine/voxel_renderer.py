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
# Gas (group "gas"): style 14, or 15-20 with a magic light's pattern in its glow.
GAS_STYLE = 14
GEM_VOXELS = 128  # at most this many staff-field voxels get the staff's point light


def style_of(m: dict) -> int:
    """A material's renderer style; anything that scatters inside (sss > 0: skin, jade, ice) is subsurface."""
    if m.get("group") == "gas":
        return GAS_STYLE + (LIGHT_STYLE[m["light"]] - 7 if m.get("light") else 0)
    if m.get("light"):
        return LIGHT_STYLE[m["light"]]
    if m["name"] in STYLE_BY_NAME:
        return STYLE_BY_NAME[m["name"]]
    return 5 if m["sss"] > 0 else STYLE_BY_GROUP.get(m["group"], 0)

_F, _I, _B = ctypes.c_float, ctypes.c_int, ctypes.c_bool


def material_fields(m: dict) -> list[float]:
    """A material's fields in renderer_set_voxel_material_fields' order: roughness, metal,
    emission, transmission, ior, sss, subsurface, density, sheen and anisotropy (read by gas only,
    in the slot where the renderer once took "thin"). Tables without the newer fields get their defaults."""
    return [float(m["roughness"]), float(m["metal"]), float(m["emission"]), float(m["transmission"]),
            float(m.get("ior", 1.5)), float(m.get("sss", 0)),
            float(m.get("subsurface", 1 if m.get("sss", 0) > 0 or m.get("group") == "subsurface" else 0)),
            float(m.get("density", 4)), float(m.get("sheen", 0)), float(m.get("anisotropy", 0))]


if sys.platform == "win32":
    DLL_NAMES = ("VoxelRenderer.dll", "SpellRenderer.dll")  # the second: builds before the neutral name
else:  # no build for macOS or Linux yet: the editor runs without the Render dock there
    DLL_NAMES = ("libVoxelRenderer.dylib" if sys.platform == "darwin" else "libVoxelRenderer.so",)
# MSVC's exception code: a C++ exception left a renderer build from before renderer_last_error.
CPP_EXCEPTION = 0xE06D7363
REQUIREMENTS = ("The renderer needs a GPU with hardware ray tracing under Vulkan 1.3 (NVIDIA RTX 20 or newer, "
                "AMD RX 6000 or newer, Intel Arc) and a current graphics driver.")


class VoxelRenderer:
    def __init__(self, bin_dir: Path | None = None):
        bin_dir = Path(bin_dir) if bin_dir else local_config.renderer_dir()
        dll = next((bin_dir / name for name in DLL_NAMES if (bin_dir / name).exists()), None)
        if dll is None and sys.platform != "win32":
            raise FileNotFoundError(f"The renderer ships for Windows only so far (no {DLL_NAMES[0]} in "
                                    f"{bin_dir}); everything else in the editor works without it.")
        if dll is None:
            raise FileNotFoundError(f"The renderer is missing: no {DLL_NAMES[0]} in {bin_dir}. Put the "
                                    f"renderer's files there, or set renderer_path in {local_config.CONFIG}.")
        if sys.platform == "win32":
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
        if hasattr(d, "renderer_set_capture_time"):  # renderers from 27 October 2026 on
            d.renderer_set_capture_time.argtypes = [_F]
        if hasattr(d, "renderer_set_floor"):  # with the floors and HDR environments
            d.renderer_set_floor.argtypes = [_I, _F, _F, _F, _F]
            d.renderer_set_environment.argtypes = [ctypes.POINTER(_F), _I, _I]
            d.renderer_set_environment_light.argtypes = [_F, _F]
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

    def floor(self, preset: str = "wood", colour=None, roughness: float | None = None) -> None:
        """The floor under the model: one of FLOORS (wood is the table it has always stood on; none leaves
        it floating), in a linear RGB colour and a roughness of the preset's own unless given."""
        if preset not in FLOORS:
            raise ValueError(f"Unknown floor {preset!r}: one of {', '.join(FLOORS)}.")
        if not hasattr(self.dll, "renderer_set_floor"):
            if preset != "wood":
                raise RuntimeError("This renderer build has only the wooden table; a newer one has floors.")
            return
        r, g, b = colour if colour is not None else (-1, -1, -1)
        self.dll.renderer_set_floor(FLOORS.index(preset), r, g, b, -1 if roughness is None else roughness)

    def environment(self, rgb: np.ndarray | None, strength: float = 1.0, rotation: float = 0.0) -> None:
        """An HDR environment lighting the model instead of the sun and sky (load_environment: linear RGB,
        latitude-longitude, z up), its strength and its turn about z in degrees; None goes back to the
        sun and sky. The renderer samples it by brightness, so a small bright sun in it stays smooth."""
        if not hasattr(self.dll, "renderer_set_environment"):
            if rgb is not None:
                raise RuntimeError("This renderer build has no HDR environments; a newer one has.")
            return
        if rgb is None:
            self.dll.renderer_set_environment(None, 0, 0)
        else:
            rgba = environment_texels(rgb)
            self.dll.renderer_set_environment(rgba.ctypes.data_as(ctypes.POINTER(_F)), rgba.shape[1], rgba.shape[0])
        self.environment_light(strength, rotation)

    def environment_light(self, strength: float = 1.0, rotation: float = 0.0) -> None:
        """The environment's strength (1: as the file has it) and its turn about z in degrees (cheap)."""
        if hasattr(self.dll, "renderer_set_environment_light"):
            self.dll.renderer_set_environment_light(float(strength), float(rotation))

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
        return self.render_camera(width, height, *self.orbit_camera(yaw_deg, pitch_deg, distance), samples)

    def orbit_camera(self, yaw_deg: float = -20, pitch_deg: float = 12, distance: float | None = None):
        """(eye, forward, right, up) looking at the model's centre from yaw and pitch, as render() does."""
        cx, cy, cz = self.centre
        distance = distance or 1.45 * max(self.size)
        yaw, pitch = np.radians(yaw_deg), np.radians(pitch_deg)
        eye = np.array([cx + distance * np.sin(yaw) * np.cos(pitch), cy - distance * np.cos(yaw) * np.cos(pitch),
                        cz + distance * np.sin(pitch)])
        forward = np.array([cx, cy, cz]) - eye
        forward /= np.linalg.norm(forward)
        right = np.cross(forward, [0, 0, 1])
        right /= np.linalg.norm(right)
        up = np.cross(right, forward)
        return eye, forward, right, up

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

    def capture_time(self, seconds: float) -> None:
        """The clock a capture's magic lights, flames and water read (0, the default: their reference phase):
        an animation's frames step it. A renderer from before it keeps them still."""
        if hasattr(self.dll, "renderer_set_capture_time"):
            self.dll.renderer_set_capture_time(float(seconds))

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
            if (getattr(error, "winerror", None) or 0) & 0xFFFFFFFF != CPP_EXCEPTION:
                raise
            raise RuntimeError("The renderer failed; this renderer build does not say why (a newer one does). "
                               + REQUIREMENTS) from None
        if done < 0:
            message = self.dll.renderer_last_error().decode("utf-8", "replace")
            raise RuntimeError(f"{message}\n{REQUIREMENTS}" if "ray tracing" in message else message)
        return done


FLOORS = ("none", "wood", "matte", "mirror", "polished metal", "cloth")  # renderer_set_floor's order


def load_environment(path, max_width: int = 2048) -> np.ndarray:
    """An OpenEXR environment (latitude-longitude) as linear float RGB, (height, width, 3), as the shared
    renderer reads it: no tone mapping; halved by box filtering, which keeps small bright lights' power,
    until it is at most max_width wide (4K maps outgrow some GPUs' storage buffers)."""
    try:
        import OpenEXR
    except ImportError as error:
        raise RuntimeError("HDR environments need the OpenEXR package (uv sync in the editor).") from error
    with OpenEXR.File(str(path)) as image:
        if len(image.parts) != 1:
            raise ValueError("The environment must be a single-part RGB EXR.")
        channels = image.channels()
        channel = channels.get("RGB", channels.get("RGBA"))
        if channel is None:
            raise ValueError("The environment has no RGB channels.")
        rgb = np.array(channel.pixels[..., :3], dtype=np.float32, copy=True)
    if rgb.ndim != 3 or rgb.shape[2] != 3 or not np.isfinite(rgb).all():
        raise ValueError("The environment must hold finite RGB pixels.")
    rgb = np.maximum(rgb, 0)
    while rgb.shape[1] > max_width and rgb.shape[0] % 2 == 0 and rgb.shape[1] % 2 == 0:
        h, w, _ = rgb.shape
        rgb = rgb.reshape(h // 2, 2, w // 2, 2, 3).mean(axis=(1, 3))
    return rgb


def environment_texels(rgb: np.ndarray) -> np.ndarray:
    """The renderer's environment texels, (height, width, 4) float32: the colour, and in alpha the
    cumulative share of the light, by brightness over solid angle, that sampling draws from (a dark
    map is drawn from evenly)."""
    rgb = np.asarray(rgb, dtype=np.float32)
    if rgb.ndim != 3 or rgb.shape[2] != 3 or min(rgb.shape[:2]) < 1 or not np.isfinite(rgb).all() or (rgb < 0).any():
        raise ValueError("An environment is finite, non-negative (height, width, 3) linear RGB.")
    h, w, _ = rgb.shape
    latitude = (np.arange(h) + 0.5) * np.pi / h
    weights = (rgb @ np.array([0.2126, 0.7152, 0.0722], np.float32)) * np.sin(latitude)[:, None]
    cdf = np.cumsum(weights.reshape(-1), dtype=np.float64)
    if cdf[-1] <= 0:
        cdf = np.cumsum(np.repeat(np.sin(latitude), w), dtype=np.float64)
    texels = np.empty((h, w, 4), np.float32)
    texels[..., :3] = rgb
    texels[..., 3] = (cdf / cdf[-1]).reshape(h, w)
    texels[-1, -1, 3] = 1
    return np.ascontiguousarray(texels)


def load_tables():
    colors = json.loads((ROOT / "palette" / "colors.json").read_text(encoding="utf-8"))["colors"]
    materials = json.loads((ROOT / "palette" / "materials.json").read_text(encoding="utf-8"))["materials"]
    return colors, materials
