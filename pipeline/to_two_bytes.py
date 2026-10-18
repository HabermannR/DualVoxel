r"""Fit step: a .vox to the internal two-byte format (colour slot + material), plus a lossless .vox export.

    .venv\Scripts\python.exe pipeline\to_two_bytes.py figure C:\...\figure.vox --material 23=18

Each palette entry of the written file stands for one (colour, material) pair:
its RGBA is the colour table's colour (palette/colors.json), and its MATL chunk
carries `_spell_color` (slot 1-255) and `_spell_material` (palette/materials.json
id) next to MagicaVoxel's own keys, so MagicaVoxel and our editor still show it
roughly right. Colours snap to the nearest table colour by CIEDE2000. Materials
come from --material overrides (source palette index = material id), else from
the file's own MagicaVoxel MATL type, else 0 (matte). Writes export/<name>.vox
and export/<name>.json (every source colour, its slot, the shift and the material);
the internal asset is assets/<name>.vx2 (see pipeline/vx2.py).
The source .vox is only read.
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "palette"))
sys.path.insert(0, str(ROOT / "pipeline"))
from colour_math import de2000, srgb_to_lab  # noqa: E402
import vx2  # noqa: E402

EXPORT = ROOT / "export"
ASSETS = ROOT / "assets"


def _dict(content: bytes, pos: int) -> tuple[dict, int]:
    """A .vox DICT (count, then key and value strings) at pos; returns it and the position after it."""
    entry, count, pos = {}, struct.unpack_from("<I", content, pos)[0], pos + 4
    for _ in range(count):
        key_len = struct.unpack_from("<I", content, pos)[0]
        key = content[pos + 4:pos + 4 + key_len].decode("latin1")
        pos += 4 + key_len
        value_len = struct.unpack_from("<I", content, pos)[0]
        entry[key] = content[pos + 4:pos + 4 + value_len].decode("latin1")
        pos += 4 + value_len
    return entry, pos


def _rotation(byte: int) -> tuple:
    """MagicaVoxel's packed rotation (_r) as a signed permutation matrix, rows = scene axes."""
    first, second = byte & 3, (byte >> 2) & 3
    third = 3 - first - second
    m = [[0, 0, 0] for _ in range(3)]
    for row, (col, bit) in enumerate(((first, 4), (second, 5), (third, 6))):
        m[row][col] = -1 if byte >> bit & 1 else 1
    return tuple(tuple(r) for r in m)


def _mul(a, b) -> tuple:
    return tuple(tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)) for i in range(3))


IDENTITY3 = ((1, 0, 0), (0, 1, 0), (0, 0, 1))


def read_vox_scene(path: Path) -> dict:
    """Every model of a .vox and where its scene places them.

    Returns {"models": [(size, voxels N x 4: x, y, z, palette index)], "palette": index -> rgb,
    "materials": index -> MATL dict, "placements": [...], "frames": [[model ids of one animated shape]]}.
    A placement is {"model", "name", "orient" (rows = scene axes), "position" (the low corner in scene
    voxels, z up)}, one per shape in the scene graph at its first frame; hidden nodes are left out.
    A file without a scene graph (version 150) places its one model at the origin."""
    data = path.read_bytes()
    if data[:4] != b"VOX ":
        raise ValueError(f"{path} is not a .vox file")
    models, palette, materials, nodes, offset, size = [], {}, {}, {}, 8, None
    while offset + 12 <= len(data):
        kind = data[offset:offset + 4]
        length, children = struct.unpack_from("<II", data, offset + 4)
        content = data[offset + 12:offset + 12 + length]
        if kind == b"SIZE":
            size = struct.unpack_from("<3I", content)
        elif kind == b"XYZI":
            count = struct.unpack_from("<I", content)[0]
            models.append((size, np.frombuffer(content, dtype=np.uint8, count=count * 4, offset=4).reshape(-1, 4).copy()))
        elif kind == b"RGBA":
            palette = {i + 1: tuple(content[4 * i:4 * i + 3]) for i in range(255)}
        elif kind == b"MATL":
            materials[struct.unpack_from("<I", content)[0]] = _dict(content, 4)[0]
        elif kind in (b"nTRN", b"nGRP", b"nSHP"):
            node = struct.unpack_from("<I", content)[0]
            attrs, pos = _dict(content, 4)
            if kind == b"nTRN":
                child, _, _, frames = struct.unpack_from("<iiiI", content, pos)
                frame = _dict(content, pos + 16)[0] if frames else {}
                nodes[node] = ("trn", attrs, child, frame)
            elif kind == b"nGRP":
                count = struct.unpack_from("<I", content, pos)[0]
                nodes[node] = ("grp", attrs, struct.unpack_from(f"<{count}I", content, pos + 4))
            else:
                shapes, count, pos = [], struct.unpack_from("<I", content, pos)[0], pos + 4
                for _ in range(count):
                    model = struct.unpack_from("<I", content, pos)[0]
                    shape_attrs, pos = _dict(content, pos + 4)
                    shapes.append((model, int(shape_attrs.get("_f", len(shapes)))))
                nodes[node] = ("shp", attrs, sorted(shapes, key=lambda s: s[1]))
        offset += 12 if kind == b"MAIN" else 12 + length + children
    if not models:
        raise ValueError(f"{path} holds no model")
    if not palette:
        raise ValueError(f"{path} has no RGBA palette")

    placements, frames = [], []

    def place(model: int, name: str, orient, t):
        (sx, sy, sz), _ = models[model]
        size3 = (sx, sy, sz)
        position = []
        for i in range(3):  # a voxel v lands at orient (v - size // 2) + t
            j = next(k for k in range(3) if orient[i][k])
            pivot = size3[j] // 2
            position.append(t[i] - pivot if orient[i][j] > 0 else t[i] + pivot - (size3[j] - 1))
        placements.append({"model": model, "name": name, "orient": orient, "position": tuple(position)})

    def walk(node: int, orient, t, name: str):
        kind, attrs, *rest = nodes[node]
        if attrs.get("_hidden") == "1":
            return
        if kind == "trn":
            child, frame = rest
            local = _rotation(int(frame["_r"])) if "_r" in frame else IDENTITY3
            shift = tuple(int(v) for v in frame.get("_t", "0 0 0").split())
            t = tuple(t[i] + sum(orient[i][k] * shift[k] for k in range(3)) for i in range(3))
            walk(child, _mul(orient, local), t, attrs.get("_name", name))
        elif kind == "grp":
            for child in rest[0]:
                walk(child, orient, t, name)
        else:
            shapes = rest[0]
            if len(shapes) > 1:
                frames.append([m for m, _ in shapes])
            place(shapes[0][0], name, orient, t)

    if 0 in nodes:
        walk(0, IDENTITY3, (0, 0, 0), path.stem)
    else:
        placements.append({"model": 0, "name": path.stem, "orient": IDENTITY3, "position": (0, 0, 0)})
    return {"models": models, "palette": palette, "materials": materials, "placements": placements,
            "frames": frames}


def read_vox(path: Path):
    """Size, voxels (N x 4: x, y, z, palette index), palette (index -> rgb) and MATL dicts (index -> dict)
    of a one-model .vox (a scene of several models opens as a project: read_vox_scene)."""
    scene = read_vox_scene(path)
    if len(scene["models"]) != 1:
        raise ValueError(f"{path.name} holds {len(scene['models'])} models; open it as a scene of parts")
    size, voxels = scene["models"][0]
    return size, voxels, scene["palette"], scene["materials"]


def material_from_matl(entry: dict | None) -> int:
    """MagicaVoxel's material type to our table (palette/materials.json)."""
    if not entry:
        return 0
    kind = entry.get("_type", "_diffuse")
    rough = float(entry.get("_rough", 0.5))
    if kind == "_metal":
        return 8 if rough < 0.05 else 7 if rough < 0.35 else 6
    if kind == "_emit":
        return 11 if float(entry.get("_flux", 0)) >= 3 else 10
    if kind == "_glass":
        return 12 if abs(float(entry.get("_ior", 1.5)) - 1.33) < 0.05 else 13
    return 0


def pack(key_values: dict) -> bytes:
    out = struct.pack("<I", len(key_values))
    for key, value in key_values.items():
        for text in (key, str(value)):
            raw = text.encode("ascii")
            out += struct.pack("<I", len(raw)) + raw
    return out


def magica_keys(material: dict) -> dict:
    """MagicaVoxel's own keys, so the file previews roughly right there."""
    if material["emission"]:
        return {"_type": "_emit", "_emit": "1", "_flux": str(min(4, max(1, round(material["emission"] / 6))))}
    if material["metal"]:
        return {"_type": "_metal", "_metal": "1", "_rough": str(material["roughness"])}
    if material["transmission"]:
        return {"_type": "_glass", "_trans": str(material["transmission"]), "_ior": str(material["ior"]),
                "_rough": str(material["roughness"])}
    return {"_type": "_diffuse", "_rough": str(material["roughness"])}


def write_vox(path: Path, size, voxels: np.ndarray, entries: list[tuple[tuple[int, int, int], dict]]) -> None:
    def chunk(name: bytes, content: bytes) -> bytes:
        return name + struct.pack("<II", len(content), 0) + content
    rgba = np.zeros((256, 4), dtype=np.uint8)
    rgba[:, 3] = 255
    for i, (rgb, _) in enumerate(entries):
        rgba[i, :3] = rgb
    body = (chunk(b"SIZE", struct.pack("<3I", *size))
            + chunk(b"XYZI", struct.pack("<I", len(voxels)) + voxels.astype(np.uint8).tobytes())
            + chunk(b"RGBA", rgba.tobytes()))
    for i, (_, keys) in enumerate(entries):
        body += chunk(b"MATL", struct.pack("<I", i + 1) + pack(keys))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"VOX " + struct.pack("<I", 150) + b"MAIN" + struct.pack("<II", 0, len(body)) + body)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("name", help="output name, e.g. alchemist")
    parser.add_argument("vox", type=Path)
    parser.add_argument("--material", action="append", default=[], metavar="INDEX=MATERIAL",
                        help="source palette index to material id, e.g. 23=18; repeatable")
    args = parser.parse_args()

    colors = json.loads((ROOT / "palette" / "colors.json").read_text(encoding="utf-8"))["colors"]
    materials = json.loads((ROOT / "palette" / "materials.json").read_text(encoding="utf-8"))["materials"]
    overrides = {int(k): int(v) for k, v in (m.split("=") for m in args.material)}
    for mid in overrides.values():
        if not 0 <= mid < len(materials):
            raise SystemExit(f"material {mid} is not in materials.json")
    table_labs = np.array([c["lab"] for c in colors])

    size, voxels, palette, matl = read_vox(args.vox)
    used, counts = np.unique(voxels[:, 3], return_counts=True)
    source_labs = srgb_to_lab(np.array([palette[int(i)] for i in used]))
    distances = de2000(source_labs[:, None, :], table_labs[None, :, :])
    pairs, remap, report = [], {}, []
    for k, index in enumerate(used.tolist()):
        slot = colors[int(distances[k].argmin())]
        material = overrides.get(index, material_from_matl(matl.get(index)))
        pair = (slot["id"], material)
        if pair not in pairs:
            pairs.append(pair)
        remap[index] = pairs.index(pair) + 1
        report.append({"source_index": index, "source_hex": "#%02x%02x%02x" % palette[index], "voxels": int(counts[k]),
                       "slot": slot["id"], "slot_hex": slot["hex"], "delta_e2000": round(float(distances[k].min()), 2),
                       "material": material, "material_name": materials[material]["name"]})
    if len(pairs) > 255:
        raise SystemExit(f"{len(pairs)} colour-material pairs; a .vox palette holds 255")

    # The internal two-byte asset: colour and material planes, (z, y, x).
    expected = {row["source_index"]: (row["slot"], row["material"]) for row in report}
    colour = np.zeros(size[::-1], dtype=np.uint8)
    material = np.zeros(size[::-1], dtype=np.uint8)
    x, y, z, index = (voxels[:, i].astype(int) for i in range(4))
    colour[z, y, x] = [expected[i][0] for i in index]
    material[z, y, x] = [expected[i][1] for i in index]
    EXPORT.mkdir(exist_ok=True)
    vx2.write(ASSETS / f"{args.name}.vx2", colour, material)
    entries = vx2.to_vox(colour, material, EXPORT / f"{args.name}.vox")

    # Read both back: the same voxels, each with the pair the report names.
    colour2, material2 = vx2.read(ASSETS / f"{args.name}.vx2")
    assert np.array_equal(colour2, colour) and np.array_equal(material2, material), "vx2 round trip mismatch"
    size2, voxels2, _, matl2 = read_vox(EXPORT / f"{args.name}.vox")
    assert tuple(size2) == tuple(size) and len(voxels2) == len(voxels) and entries == len(pairs)
    back = {i: (int(matl2[i]["_spell_color"]), int(matl2[i]["_spell_material"])) for i in matl2}
    for vx, vy, vz, i in voxels2.astype(int):
        assert back[i] == (colour[vz, vy, vx], material[vz, vy, vx]), "vox export mismatch"

    shifts = np.array([r["delta_e2000"] for r in report])
    weights = np.array([r["voxels"] for r in report])
    summary = {"source": str(args.vox), "size": list(size), "voxels": int(len(voxels)),
               "source_colours": len(used), "pairs": len(pairs),
               "materials": {materials[m]["name"]: int(sum(r["voxels"] for r in report if r["material"] == m))
                             for m in sorted({r["material"] for r in report})},
               "shift_dE2000": {"max": round(float(shifts.max()), 2),
                                "voxel_weighted_mean": round(float((shifts * weights).sum() / weights.sum()), 2)}}
    (EXPORT / f"{args.name}.json").write_text(json.dumps({"summary": summary, "colours": report}, indent=1),
                                              encoding="utf-8")
    print(f"{args.name}: {summary['voxels']} voxels, {summary['source_colours']} colours -> {summary['pairs']} pairs, "
          f"materials {summary['materials']}, shift dE2000 max {summary['shift_dE2000']['max']}, "
          f"mean {summary['shift_dE2000']['voxel_weighted_mean']}")


if __name__ == "__main__":
    main()
