r"""Render a .vx2 with the path tracer (VoxelRenderer.dll).

    .venv\Scripts\python.exe engine\render_vx2.py assets\alchemist.vx2 --out engine\alchemist.png

The model stands on a wooden table under the golden-hour sun; the
camera orbits its centre (--yaw 0 looks at its front from -y).
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "pipeline"))
import vx2  # noqa: E402
from voxel_renderer import VoxelRenderer, load_tables  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("vx2", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--size", type=int, nargs=2, default=[960, 720], metavar=("W", "H"))
    parser.add_argument("--yaw", type=float, nargs="+", default=[-25.0], help="one or more views")
    parser.add_argument("--pitch", type=float, default=12.0)
    parser.add_argument("--samples", type=int, default=64)
    args = parser.parse_args()

    own = vx2.find_colours(vx2.read_fingerprints(args.vx2)[0], [args.vx2.parent])  # a project's colours
    colors, materials = vx2.load_colours(own) if own else load_tables()[0], load_tables()[1]
    colour, material, _ = vx2.read_model(args.vx2, colors=colors)
    start = time.perf_counter()
    renderer = VoxelRenderer()
    pairs = renderer.show(colour, material, materials, colors)
    print(f"engine up and model loaded in {time.perf_counter() - start:.1f} s ({pairs} colour-material pairs)")
    frames = []
    for yaw in args.yaw:
        start = time.perf_counter()
        frames.append(Image.fromarray(renderer.render(*args.size, yaw_deg=yaw, pitch_deg=args.pitch,
                                                      samples=args.samples)).convert("RGB"))
        print(f"yaw {yaw:g}: {args.samples} samples in {time.perf_counter() - start:.1f} s")
    renderer.close()
    sheet = Image.new("RGB", (args.size[0] * len(frames), args.size[1]))
    for i, frame in enumerate(frames):
        sheet.paste(frame, (i * args.size[0], 0))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(args.out)
    print(args.out)


if __name__ == "__main__":
    main()
