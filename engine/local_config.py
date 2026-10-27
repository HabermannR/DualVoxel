r"""This machine's own settings: editor\editor.local.json (gitignored; editor.local.example.json shows it).

    {
      "renderer_path": "C:\\path\\to\\renderer",
      "environments": ["environments", "C:\\path\\to\\more\\hdr"],
      "send_tables": [{"name": "MyGame", "path": "C:\\path\\to\\MyGame"}]
    }

renderer_path: the folder with VoxelRenderer.dll and its files (trace.spv, rr_io.spv and,
optionally, NVIDIA's DLSS DLLs); without it, editor\renderer. environments: a folder of HDR
environments (.exr) the Light dock lists (core/lights.py), or a list of them; without it,
editor\environments.
send_tables: projects that keep
their own copies of the colour and material tables in <path>\assets\palette; the editor's File
menu offers "Send tables to <name>…" for each. Relative paths are relative to the editor folder.
Without the file there is nothing to send to.
"""
from __future__ import annotations

import json
from pathlib import Path

EDITOR = Path(__file__).resolve().parent.parent / "editor"
CONFIG = EDITOR / "editor.local.json"
DEFAULT_RENDERER = EDITOR / "renderer"


def load() -> dict:
    if not CONFIG.exists():
        return {}
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"{CONFIG} is not valid JSON: {error}") from error


def _path(value: str) -> Path:
    return (EDITOR / Path(value).expanduser()).resolve()


def renderer_dir() -> Path:
    """The folder that holds VoxelRenderer.dll."""
    value = load().get("renderer_path")
    return _path(value) if value else DEFAULT_RENDERER


def environment_dirs() -> list[Path]:
    """The folders of HDR environments (.exr) the Light dock lists, the first one first."""
    value = load().get("environments")
    if not value:
        return [EDITOR / "environments"]
    return [_path(v) for v in ([value] if isinstance(value, str) else value)]


def send_targets() -> list[tuple[str, Path]]:
    """(name, project folder) for each configured "send tables" target."""
    return [(t["name"], _path(t["path"])) for t in load().get("send_tables", [])]
