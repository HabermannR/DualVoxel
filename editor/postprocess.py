"""Finishing for path-traced pictures: bloom, a filmic tone curve, a split grade, vignette and grain.

The path tracer gives a plain image; these looks make glowing materials bleed light, deepen the blacks
and separate cool shadows from warm lights. `finish(rgb, look)` takes and returns an 8-bit RGB array
(height, width, 3). Sizes scale with the picture, so a look reads the same at 640 or 1920 pixels.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.ndimage import gaussian_filter

LUMA = np.array([0.2126, 0.7152, 0.0722], np.float32)


@dataclass(frozen=True)
class Look:
    bloom: float = 0.0              # how much light bright and glowing parts spill
    bloom_threshold: float = 0.18   # linear luminance above which a pixel blooms
    bloom_red: float = 0.0          # extra bloom for saturated reds (emissive flesh, embers)
    exposure: float = 1.0
    tone: bool = False              # filmic S-curve: deep blacks, soft highlights
    saturation: float = 1.0
    shadow_tint: tuple = (0.0, 0.0, 0.0)     # multiplies the dark mid-tones (pure black stays black)
    highlight_tint: tuple = (0.0, 0.0, 0.0)  # added to the bright parts
    black_crush: float = 0.0
    vignette: float = 0.0
    grain: float = 0.0


LOOKS = {
    "none": Look(),
    "film": Look(bloom=0.5, bloom_threshold=0.35, exposure=1.05, tone=True, saturation=1.05, vignette=0.3,
                 grain=0.006),
    "night": Look(bloom=0.9, bloom_red=0.8, exposure=1.15, tone=True, saturation=1.15,
                  shadow_tint=(-0.15, 0.0, 0.25), highlight_tint=(0.03, 0.01, -0.02), black_crush=0.012,
                  vignette=0.55, grain=0.012),
}


def look_names() -> list[str]:
    return list(LOOKS)


def finish(rgb: np.ndarray, look: str | Look = "none", seed: int = 7) -> np.ndarray:
    """The picture with a look applied (a name from LOOKS or a Look); "none" returns it unchanged."""
    if isinstance(look, str):
        if look not in LOOKS:
            raise ValueError(f"Unknown look {look!r}: one of {', '.join(LOOKS)}.")
        look = LOOKS[look]
    if look == Look():
        return rgb
    h, w = rgb.shape[:2]
    lin = (rgb[..., :3].astype(np.float32) / 255.0) ** 2.2

    if look.bloom > 0:
        lum = lin @ LUMA
        red = np.clip(lin[..., 0] - np.maximum(lin[..., 1], lin[..., 2]), 0, None)
        source = (np.clip((lum - look.bloom_threshold) / 0.5, 0, 1)
                  + np.clip(red * look.bloom_red, 0, 1))[..., None] * lin
        bloom = np.zeros_like(lin)
        for fraction, weight in ((0.0028, 0.18), (0.013, 0.4), (0.042, 0.4)):  # of the picture's height
            sigma = max(1.0, fraction * h)
            bloom += weight * np.stack([gaussian_filter(source[..., c], sigma) for c in range(3)], -1)
        lin = lin + bloom * look.bloom

    lin = lin * look.exposure
    if look.tone:  # ACES-like curve (Narkowicz)
        lin = (lin * (2.51 * lin + 0.03)) / (lin * (2.43 * lin + 0.59) + 0.14)
    out = np.clip(lin, 0, 1) ** (1 / 2.2)

    grey = (out @ np.array([0.299, 0.587, 0.114], np.float32))[..., None]
    if any(look.shadow_tint):
        shadow = np.clip(1 - grey * 2.2, 0, 1) * np.clip(grey * 12, 0, 1)
        out = out * (1 + shadow * np.array(look.shadow_tint, np.float32))
    if any(look.highlight_tint):
        out = out + np.clip(grey - 0.6, 0, 1) * np.array(look.highlight_tint, np.float32)
    if look.saturation != 1.0:
        out = grey + (out - grey) * look.saturation
    if look.black_crush:
        out = np.clip(out - look.black_crush, 0, 1) / (1 - look.black_crush)

    if look.vignette:
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        r = np.sqrt(((xx - w * 0.5) / (w * 0.62)) ** 2 + ((yy - h * 0.45) / (h * 0.62)) ** 2)
        out = out * (1 - look.vignette * np.clip(r - 0.35, 0, 1) ** 1.6)[..., None]
    if look.grain:
        noise = np.random.default_rng(seed).normal(0, look.grain, (h, w, 1)).astype(np.float32)
        out = out + noise
    return (np.clip(out, 0, 1) * 255 + 0.5).astype(np.uint8)
