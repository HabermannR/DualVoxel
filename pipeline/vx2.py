r"""The internal voxel format: two bytes per voxel (colour slot, material). .vox is only import/export.

    .venv\Scripts\python.exe pipeline\vx2.py info assets\alchemist.vx2
    .venv\Scripts\python.exe pipeline\vx2.py to-vox assets\alchemist.vx2 export\alchemist.vox [--lossy]
    .venv\Scripts\python.exe pipeline\vx2.py restamp assets\*.vx2

File layout, little-endian:
    4 bytes   magic b"VX2\0"
    uint32    version (1, or 2 with the model's own materials)
    uint32 x3 size x, y, z
    8 bytes   colour table fingerprint (palette/colors.json, or a project's <name>.colors.json)
    8 bytes   material table fingerprint (palette/materials.json)
    x*y*z     colour plane: slot 1-255, 0 = empty
    x*y*z     material plane: id in materials.json, or 128-255 for one of the model's
              own materials (ignored where the colour is 0)
    version 2 only:
    4 bytes   b"MATS"
    uint32    n, then n bytes of UTF-8 JSON {"materials": [...]}: the model's own materials,
              ids 128-255, with the same fields as materials.json
A model's own materials travel with it: they are saved, opened and rendered with the
model and never touch the shared table. A file without them stays version 1, the
simpler format other readers may expect; version 2 adds them.
Both planes run x fastest, then y, then z (index z*x*y + y*x + x), as the renderer's
voxel arrays do. The fingerprints say which tables a file was made with; a
mismatch means its numbers point into a different table. After a table change
that keeps every number's meaning (new materials at the end, a tuned strength),
"restamp" writes the current fingerprints into existing files.

Colours: the default table is palette/colors.json (palette/build_colors.py builds
it); a project keeps its own, <project>.colors.json beside its .project.json,
which starts as a copy of the default and is changed in the editor's Colours
dock. A file's colour fingerprint names the table its slots mean: find_colours()
looks for it among palette/colors.json and the *.colors.json files of the
folders given, and restamp keeps a file on the project table it was made with.

.vox export: lossless keeps every (colour, material) pair as one palette entry
whose RGBA is the table colour and whose MATL chunk carries _spell_color and
_spell_material (at most 255 pairs per model); --lossy keeps colours only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
MAGIC, VERSION = b"VX2\0", 1
LOCAL_VERSION, LOCAL_MAGIC, LOCAL_FIRST = 2, b"MATS", 128  # the model's own materials: ids 128-255
HEADER = struct.Struct("<4sI3I8s8s")
CHUNK = struct.Struct("<4sI")
DEFAULT_COLOURS = ROOT / "palette" / "colors.json"
COLOURS_SUFFIX = ".colors.json"  # a project's own colour table: <project>.colors.json


def load_colours(path: Path) -> list[dict]:
    """A colour table's slots: palette/colors.json, or a project's <name>.colors.json, whose lines
    carry only id, hex, band and name (rgb is filled in from hex)."""
    colors = json.loads(Path(path).read_text(encoding="utf-8"))["colors"]
    for c in colors:
        c.setdefault("rgb", [int(c["hex"][i:i + 2], 16) for i in (1, 3, 5)])
    if [c["id"] for c in colors] != list(range(1, len(colors) + 1)) or len(colors) > 255:
        raise ValueError(f"{Path(path).name}: the slots must be numbered from 1, at most 255")
    return colors


def load_tables():
    """(the default colour table, the shared material table)."""
    materials = json.loads((ROOT / "palette" / "materials.json").read_text(encoding="utf-8"))["materials"]
    return load_colours(DEFAULT_COLOURS), materials


def colour_fingerprint(colors: list[dict]) -> bytes:
    """What the colour slots mean: slot -> rgb."""
    key = json.dumps([[c["id"], list(c["rgb"])] for c in colors], separators=(",", ":"))
    return hashlib.sha256(key.encode()).digest()[:8]


def fingerprints(colors: list[dict], materials: list[dict]) -> tuple[bytes, bytes]:
    """Content hashes of what the numbers mean: slot -> rgb, and each material's parameters."""
    material_key = json.dumps(materials, sort_keys=True, separators=(",", ":"))
    return colour_fingerprint(colors), hashlib.sha256(material_key.encode()).digest()[:8]


def read_fingerprints(path: Path) -> tuple[bytes, bytes]:
    """(colour, material) fingerprints from a .vx2 file's header."""
    with open(path, "rb") as f:
        magic, _, _, _, _, colour_fp, material_fp = HEADER.unpack(f.read(HEADER.size))
    if magic != MAGIC:
        raise ValueError(f"{path} is not a .vx2 file")
    return colour_fp, material_fp


def find_colours(fingerprint: bytes, folders=()) -> Path | None:
    """The colour table with this fingerprint: palette/colors.json, or a *.colors.json in the folders."""
    seen = set()
    for path in [DEFAULT_COLOURS, *(p for f in folders for p in sorted(Path(f).glob(f"*{COLOURS_SUFFIX}")))]:
        if path.resolve() in seen:
            continue
        seen.add(path.resolve())
        try:
            if colour_fingerprint(load_colours(path)) == fingerprint:
                return path
        except (OSError, ValueError, KeyError):
            continue
    return None


def write(path: Path, colour: np.ndarray, material: np.ndarray, local: list[dict] | None = None,
          colors: list[dict] | None = None) -> None:
    """colour and material: uint8 arrays shaped (z, y, x); local: the model's own materials
    (ids 128-255), saved with it (version 2); without them the file stays version 1. colors: the
    colour table its slots mean (a project's), by default palette/colors.json."""
    if colour.shape != material.shape or colour.ndim != 3:
        raise ValueError("colour and material planes must be the same (z, y, x) shape")
    default_colors, materials = load_tables()
    colors = default_colors if colors is None else colors
    local = sorted(local or [], key=lambda m: m["id"])
    local_ids = [m["id"] for m in local]
    if any(not LOCAL_FIRST <= i <= 255 for i in local_ids) or len(set(local_ids)) != len(local_ids):
        raise ValueError("a model's own materials have distinct ids 128-255")
    used = np.unique(material[colour > 0])
    if colour.max(initial=0) > len(colors) or any(m >= len(materials) and int(m) not in local_ids for m in used):
        raise ValueError("a voxel points outside the colour or material table")
    sz, sy, sx = colour.shape
    body = (np.ascontiguousarray(colour, dtype=np.uint8).tobytes()
            + np.ascontiguousarray(np.where(colour > 0, material, 0), dtype=np.uint8).tobytes())
    tail = b""
    if local:
        text = json.dumps({"materials": local}, ensure_ascii=False).encode("utf-8")
        tail = CHUNK.pack(LOCAL_MAGIC, len(text)) + text
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(HEADER.pack(MAGIC, LOCAL_VERSION if local else VERSION, sx, sy, sz, *fingerprints(colors, materials))
                     + body + tail)


def read_model(path: Path, check_tables: bool = True,
               colors: list[dict] | None = None) -> tuple[np.ndarray, np.ndarray, list[dict]]:
    """(colour plane, material plane, the model's own materials) of a version 1 or 2 file; check_tables:
    made with the colour table `colors` (by default palette/colors.json) and the material table."""
    data = path.read_bytes()
    magic, version, sx, sy, sz, colour_fp, material_fp = HEADER.unpack_from(data)
    if magic != MAGIC or version not in (VERSION, LOCAL_VERSION):
        raise ValueError(f"{path} is not a version {VERSION} or {LOCAL_VERSION} .vx2 file")
    n = sx * sy * sz
    end = HEADER.size + 2 * n
    local = []
    if version == LOCAL_VERSION:
        tag, length = CHUNK.unpack_from(data, end)
        if tag != LOCAL_MAGIC or len(data) != end + CHUNK.size + length:
            raise ValueError(f"{path}: a broken material section")
        local = json.loads(data[end + CHUNK.size:].decode("utf-8"))["materials"]
    elif len(data) != end:
        raise ValueError(f"{path}: expected {end} bytes, found {len(data)}")
    if check_tables:
        default_colors, materials = load_tables()
        if (colour_fp, material_fp) != fingerprints(default_colors if colors is None else colors, materials):
            raise ValueError(f"{path} was made with different colour or material tables")
    planes = np.frombuffer(data, dtype=np.uint8, offset=HEADER.size, count=2 * n).reshape(2, sz, sy, sx)
    return planes[0].copy(), planes[1].copy(), local


def read(path: Path, check_tables: bool = True) -> tuple[np.ndarray, np.ndarray]:
    """(colour plane, material plane); read_model() also gives the model's own materials."""
    colour, material, _ = read_model(path, check_tables)
    return colour, material


def to_vox(colour: np.ndarray, material: np.ndarray, out: Path, lossy: bool = False,
           local: list[dict] | None = None, colors: list[dict] | None = None) -> int:
    """Write a .vox; returns the number of palette entries used. local: the model's own materials;
    colors: the colour table (a project's), by default palette/colors.json."""
    from to_two_bytes import magica_keys, write_vox  # one .vox writer for the pipeline
    default_colors, shared = load_tables()
    colors = default_colors if colors is None else colors
    materials = {m["id"]: m for m in [*shared, *(local or [])]}
    by_id = {c["id"]: c for c in colors}
    z, y, x = np.nonzero(colour)
    keys = list(zip(colour[z, y, x].tolist(), ([0] * len(z) if lossy else material[z, y, x].tolist())))
    pairs = sorted(set(keys))
    if len(pairs) > 255:
        raise ValueError(f"{len(pairs)} colour-material pairs; a .vox palette holds 255")
    index = {pair: i + 1 for i, pair in enumerate(pairs)}
    voxels = np.stack([x, y, z, [index[k] for k in keys]], axis=1).astype(np.uint8)
    entries = [(tuple(by_id[c]["rgb"]),
                {} if lossy else {"_spell_color": c, "_spell_material": m, **magica_keys(materials[m])})
               for c, m in pairs]
    write_vox(out, colour.shape[::-1], voxels, entries)
    return len(pairs)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    info = sub.add_parser("info")
    info.add_argument("vx2", type=Path)
    export = sub.add_parser("to-vox")
    export.add_argument("vx2", type=Path)
    export.add_argument("out", type=Path)
    export.add_argument("--lossy", action="store_true", help="colours only, no materials")
    restamp = sub.add_parser("restamp", help="write the current table fingerprints into files")
    restamp.add_argument("files", type=Path, nargs="+")
    args = parser.parse_args()
    if args.command == "restamp":
        for path in args.files:
            colour, material, local = read_model(path, check_tables=False)
            own = find_colours(read_fingerprints(path)[0], [path.parent])  # a project's table stays its own
            write(path, colour, material, local, load_colours(own) if own else None)  # checks every number fits
            print(f"{path}: restamped" + (f" (colours: {own.name})" if own and own != DEFAULT_COLOURS else ""))
        return
    own = find_colours(read_fingerprints(args.vx2)[0], [args.vx2.parent])
    colors = load_colours(own) if own else None
    colour, material, local = read_model(args.vx2, colors=colors)
    if args.command == "info":
        materials = {m["id"]: m for m in [*load_tables()[1], *local]}
        solid = colour > 0
        used = {materials[m]["name"]: int(n) for m, n in zip(*np.unique(material[solid], return_counts=True))}
        print(f"{args.vx2}: {colour.shape[::-1]} (x, y, z), {int(solid.sum())} voxels, "
              f"{len(np.unique(colour[solid]))} colours, materials {used}")
    else:
        entries = to_vox(colour, material, args.out, args.lossy, local, colors)
        print(f"{args.out}: {entries} palette entries ({'lossy' if args.lossy else 'lossless'})")


if __name__ == "__main__":
    main()
