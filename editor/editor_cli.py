"""Inspect, preview, render or edit a two-byte model with the editor's headless API.

    .venv\\Scripts\\python.exe editor_cli.py inspect  C:\\...\\assets\\corpse.vx2
    .venv\\Scripts\\python.exe editor_cli.py preview  C:\\...\\assets\\corpse.vx2 --output corpse.png
    .venv\\Scripts\\python.exe editor_cli.py render   C:\\...\\assets\\corpse.vx2 --output corpse-render.png
    .venv\\Scripts\\python.exe editor_cli.py edit     C:\\...\\assets\\corpse.vx2 --operations ops.json --save corpse-skin

Operations are a JSON list of {"operation": name, "arguments": {...}} with the
names paint_box, erase_box, shape_slice, set_material_box,
set_material_for_colour, replace_colour, protect_box, clear_protection, undo, redo.
"""
import argparse
import json
from pathlib import Path

from headless_api import VoxelEditor

EDITS = {"paint_box", "erase_box", "shape_slice", "set_material_box", "set_material_for_colour", "replace_colour",
         "protect_box", "clear_protection", "undo", "redo"}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["inspect", "preview", "render", "edit"])
    parser.add_argument("model", help="a .vx2 or .vox")
    parser.add_argument("--output", help="picture name inside outputs/")
    parser.add_argument("--operations", type=Path)
    parser.add_argument("--save", help="for edit: save as assets/<name>.vx2 (plus export/<name>.vox)")
    parser.add_argument("--yaw", type=float, default=-25.0)
    args = parser.parse_args()

    editor = VoxelEditor()
    editor.open_model(args.model)
    try:
        if args.command == "inspect":
            print(json.dumps(editor.info(), indent=2))
        elif args.command == "preview":
            print(editor.save_preview(args.output or "preview.png"))
        elif args.command == "render":
            print(editor.save_render(args.output or "render.png", yaw=args.yaw))
        else:
            if not args.operations or not args.save:
                parser.error("edit needs --operations and --save")
            for step in json.loads(args.operations.read_text(encoding="utf-8-sig")):
                if step["operation"] not in EDITS:
                    raise ValueError(f"Unsupported operation: {step['operation']}")
                getattr(editor, step["operation"])(**step.get("arguments", {}))
            print(json.dumps(editor.save_model(args.save), indent=2))
            if args.output:
                print(editor.save_preview(args.output))
    finally:
        editor.close()


if __name__ == "__main__":
    main()
