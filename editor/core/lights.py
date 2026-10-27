"""The render's light presets and surroundings, shared by the Light dock and the headless renders (MCP, CLI).

Golden hour and Day are the renderer's built-in light (renderer_set_golden_hour), Noon, Overcast and
Night are custom lights (renderer_set_light's 18 numbers).

The surroundings are what the model stands in: the light's own sun and sky ("sky"), or an HDR
environment (any OpenEXR, latitude-longitude) that lights it instead, with a strength and a turn; and
the floor under it (voxel_renderer.FLOORS: the wooden table, matte, mirror, polished metal, cloth or
none). No environment comes with the editor: it lists the .exr files in folders of one's own (editor.local.json "environments",
local_config.environment_dirs()) and opens any other by its path.
"""
from __future__ import annotations

import functools
import sys
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[2] / "engine"

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
    """Set a VoxelRenderer to the Render dock's light: {"golden", "custom", "sun", "sky", "surroundings"} as
    the editor sends it (an editor from before surroundings: the sun and sky on the wooden table)."""
    renderer.daylight(float(state["sun"]), float(state["sky"]))
    renderer.golden_hour(bool(state["golden"]))
    renderer.light(state["custom"] is not None, state["custom"])
    apply_surroundings(renderer, state.get("surroundings"))


SURROUNDINGS = {"environment": "sky", "strength": 1.0, "rotation": 0.0, "floor": "wood", "floor_colour": None,
                "floor_roughness": None}  # the sun and sky on the wooden table, as always


def _engine():
    if str(ENGINE) not in sys.path:
        sys.path.insert(0, str(ENGINE))


def environment_folders() -> list[Path]:
    _engine()
    from local_config import environment_dirs
    return environment_dirs()


def environment_files() -> list[Path]:
    """The .exr files in the environments folders, by name (a name in two folders: the first folder's)."""
    found = {}
    for folder in environment_folders():
        if folder.is_dir():
            for path in folder.glob("*.exr"):
                found.setdefault(path.name.lower(), path)
    return sorted(found.values(), key=lambda p: p.name.lower())


def environment_path(name) -> Path | None:
    """The EXR for a surroundings name: None for "sky" (the light's own sun and sky), else a path to an
    .exr, or the name of one in the environments folders (with or without .exr)."""
    if not name or name == "sky":
        return None
    path = Path(name)
    if not path.is_file():
        file = name if str(name).lower().endswith(".exr") else f"{name}.exr"
        path = next((folder / file for folder in environment_folders() if (folder / file).is_file()), Path(file))
    if path.suffix.lower() != ".exr" or not path.is_file():
        folders = ", ".join(str(f) for f in environment_folders())
        raise ValueError(f"No HDR environment {name!r}: surroundings are \"sky\", a path to an .exr, or the name "
                         f"of one in {folders} (editor.local.json \"environments\").")
    return path


@functools.lru_cache(maxsize=3)
def _load(path: str, modified: float):
    _engine()
    from voxel_renderer import load_environment
    return load_environment(path)


def check_surroundings(state: dict | None) -> dict:
    """The surroundings with their defaults filled in, checked (before an engine starts)."""
    _engine()
    from voxel_renderer import FLOORS
    state = {**SURROUNDINGS, **(state or {})}
    environment_path(state["environment"])
    if state["floor"] not in FLOORS:
        raise ValueError(f"Unknown floor {state['floor']!r}: one of {', '.join(FLOORS)}.")
    if not 0 <= float(state["strength"]) <= 100:
        raise ValueError("The surroundings' strength is 0-100.")
    return state


def apply_surroundings(renderer, state: dict | None) -> None:
    """Set a VoxelRenderer's surroundings (SURROUNDINGS' keys; missing ones their defaults). An
    environment is read once and sent again only when it changes; the floor likewise."""
    state = check_surroundings(state)
    path = environment_path(state["environment"])
    key = (str(path), path.stat().st_mtime) if path else None
    if getattr(renderer, "_environment_key", "unset") != key:
        renderer.environment(_load(*key) if key else None, float(state["strength"]), float(state["rotation"]))
        renderer._environment_key = key
    else:
        renderer.environment_light(float(state["strength"]), float(state["rotation"]))
    colour = state["floor_colour"]
    floor = (state["floor"], tuple(colour) if colour is not None else None, state["floor_roughness"])
    if getattr(renderer, "_floor_key", None) != floor:
        renderer.floor(*floor)
        renderer._floor_key = floor


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
