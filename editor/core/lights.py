"""The render's light presets, shared by the Light dock and the headless renders (MCP, CLI).

Golden hour and Day are the renderer's built-in light (renderer_set_golden_hour), Noon, Overcast and
Night are custom lights (renderer_set_light's 18 numbers).
"""
from __future__ import annotations

# name: (built in: golden flag or None for a custom light, sun direction, sun radiance, horizon, zenith,
#        backdrop top, backdrop bottom); the first two are the shader's own values (trace.comp)
PRESETS = {
    "Golden hour": (True, (-0.86, 0.42, 0.30), (13, 7.2, 2.6), (0.95, 0.62, 0.42), (0.26, 0.32, 0.55),
                    (0.20, 0.22, 0.36), (1.10, 0.66, 0.36)),
    "Day": (False, (-0.62, -0.42, 0.62), (8.4, 6.15, 3.45), (0.75, 1, 1.45), (0.3, 0.5, 0.9),
            (0.045, 0.065, 0.14), (0.09, 0.14, 0.19)),
    "Noon": (None, (-0.30, 0.17, 0.94), (10, 9.6, 8.8), (0.70, 0.85, 1.10), (0.25, 0.45, 0.95),
             (0.25, 0.42, 0.75), (0.55, 0.68, 0.85)),
    "Overcast": (None, (-0.40, -0.30, 0.87), (1.6, 1.6, 1.7), (1.30, 1.30, 1.35), (1.0, 1.02, 1.08),
                 (0.55, 0.57, 0.60), (0.75, 0.76, 0.78)),
    "Night": (None, (0.60, -0.45, 0.66), (0.35, 0.42, 0.60), (0.06, 0.08, 0.14), (0.02, 0.03, 0.07),
              (0.01, 0.015, 0.04), (0.04, 0.05, 0.09)),
}


def preset_name(name: str) -> str:
    """The preset's own name for any spelling: "golden hour", "golden_hour", "OVERCAST"."""
    wanted = name.strip().lower().replace("_", " ").replace("-", " ")
    for known in PRESETS:
        if known.lower() == wanted:
            return known
    raise ValueError(f"Unknown light {name!r}; use one of: {', '.join(PRESETS)}.")


def apply_state(renderer, state: dict) -> None:
    """Set a VoxelRenderer to the Render dock's light: {"golden", "custom", "sun", "sky"} as the editor sends it."""
    renderer.daylight(float(state["sun"]), float(state["sky"]))
    renderer.golden_hour(bool(state["golden"]))
    renderer.light(state["custom"] is not None, state["custom"])


def apply_preset(renderer, name: str) -> None:
    """Set a VoxelRenderer to a preset, at full sun and sky."""
    golden, *colours = PRESETS[preset_name(name)]
    renderer.daylight(1.0, 1.0)
    if golden is None:
        renderer.golden_hour(False)
        renderer.light(True, [v for triple in colours for v in triple])
    else:
        renderer.golden_hour(golden)
        renderer.light(False)
