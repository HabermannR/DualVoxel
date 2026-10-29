"""Inspect, preview, render or edit a two-byte model with the editor's headless API.

    .venv\\Scripts\\python.exe editor_cli.py inspect  C:\\...\\assets\\corpse.vx2
    .venv\\Scripts\\python.exe editor_cli.py preview  C:\\...\\assets\\corpse.vx2 --output corpse.png
    .venv\\Scripts\\python.exe editor_cli.py render   C:\\...\\assets\\corpse.vx2 --output corpse-render.png --light Overcast
    .venv\\Scripts\\python.exe editor_cli.py edit     C:\\...\\assets\\corpse.vx2 --operations ops.json --save corpse-skin
    .venv\\Scripts\\python.exe editor_cli.py views    C:\\...\\assets\\corpse.vx2 --output corpse [--scale 8] [--render]
    .venv\\Scripts\\python.exe editor_cli.py paint    C:\\...\\assets\\corpse.vx2 --pictures outputs\\corpse.front.colour.png ... --save corpse
    .venv\\Scripts\\python.exe editor_cli.py slices   C:\\...\\assets\\corpse.vx2 --output corpse
    .venv\\Scripts\\python.exe editor_cli.py unslice  outputs\\corpse.slices-33x21x64.colour.png --save corpse-2

Operations are a JSON list of {"operation": name, "arguments": {...}} with the
names paint_box, erase_box, shape_slice, set_material_box,
set_material_for_colour, replace_colour, protect_box, clear_protection, undo, redo.
views and slices write voxel PNGs into outputs/ (core/voxel_png.py); paint reads
painted views back onto the model, unslice a slice sheet as a model.
"""
import argparse
import json
from pathlib import Path

from core.lights import PRESETS
from headless_api import VoxelEditor

EDITS = {"paint_box", "erase_box", "shape_slice", "set_material_box", "set_material_for_colour", "replace_colour",
         "speckle", "noise_terrain", "erode_surface", "scatter", "protect_box", "clear_protection", "undo", "redo"}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["inspect", "preview", "render", "edit", "views", "paint", "slices",
                                            "unslice"])
    parser.add_argument("model", help="a .vx2 or .vox (unslice: a slice sheet's .colour.png)")
    parser.add_argument("--output", help="picture name inside outputs/")
    parser.add_argument("--operations", type=Path)
    parser.add_argument("--save", help="for edit, paint, unslice: save as assets/<name>.vx2 (plus export/<name>.vox)")
    parser.add_argument("--yaw", type=float, default=-25.0)
    parser.add_argument("--light", default="Golden hour", help="for render: " + ", ".join(PRESETS))
    parser.add_argument("--scale", type=int, default=8, help="for views: pixels per voxel")
    parser.add_argument("--render", action="store_true", help="for views: also the path tracer's picture of each")
    parser.add_argument("--pictures", nargs="+", help="for paint: the painted view pictures")
    args = parser.parse_args()

    editor = VoxelEditor()
    try:
        if args.command == "unslice":
            if not args.save:
                parser.error("unslice needs --save")
            result = editor.import_slices(args.model)
            print(json.dumps({k: result[k] for k in ("size", "voxels", "snapped_pixels", "material_sheet")}))
            print(json.dumps(editor.save_model(args.save)["path"]))
            return
        editor.open_model(args.model)
        if args.command == "views":
            print("\n".join(editor.export_views(editor.output_base(args.output or Path(args.model).stem),
                                                scale=args.scale, render=args.render)["files"]))
            return
        if args.command == "slices":
            print("\n".join(editor.export_slices(editor.output_base(args.output or Path(args.model).stem))["files"]))
            return
        if args.command == "paint":
            if not args.pictures or not args.save:
                parser.error("paint needs --pictures and --save")
            result = editor.import_views(args.pictures)
            print(json.dumps({"views": result["views"], "changed_voxels": result["changed_voxels"],
                              "snapped_pixels": result["snapped_pixels"]}, indent=2))
            print(json.dumps(editor.save_model(args.save)["path"]))
            return
        if args.command == "inspect":
            print(json.dumps(editor.info(), indent=2))
        elif args.command == "preview":
            print(editor.save_preview(args.output or "preview.png"))
        elif args.command == "render":
            print(editor.save_render(args.output or "render.png", yaw=args.yaw, light=args.light))
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
