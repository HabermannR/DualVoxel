"""Voxel PNGs: a two-byte model as pictures, to edit in any paint program and read back.

Two kinds, each a pair of pictures (colour and material) per sheet or view:

* **Slices**, the whole model, nothing lost: every layer z = 0, 1, ... laid out left to right, then in
  rows, one pixel per voxel, each layer seen from above (x to the right, the back of the model at the
  top). `<name>.slices-<x>x<y>x<z>.colour.png` and `.material.png`: the size in the name lets a sheet be
  read back without anything else, since paint programs often drop a PNG's text chunks.
* **Views**, the surface, to paint on: the model seen straight along an axis (VIEWS), each voxel `scale`
  pixels wide, the first voxel along each line of sight. `<name>.<view>.colour.png` and
  `.material.png`, and `.shaded.png`, the colours with depth (only to look at: nearer voxels brighter, a
  dark line where the depth jumps). Reading views back changes only the voxels whose pixels were
  painted: a colour pixel made transparent erases its voxel; paint where no voxel was is left out (the
  view cannot tell how deep it lies). A voxel that two views show takes the later view's paint.

The colour pictures are indexed: palette entry n is colour slot n of the model's table, 0 transparent
(empty), so a paint program offers just the table's colours. A picture saved back as RGB(A) works too;
a colour not in the table takes the nearest slot (counted in the report). Material pictures are RGBA in
false colours, one per material id (MATERIAL_RGB, the same in every file), transparent where empty.

A "dualvoxel" text chunk records the kind, the size, the tables' fingerprints and, for views, the
view's voxels as exported, so a view only changes what was painted on it even if the model changed
since. Without it (a program dropped it), the view is compared with the model as it is now.
"""
from __future__ import annotations

import base64
import colorsys
import json
import re
import zlib
from pathlib import Path

import numpy as np
from PIL import Image, PngImagePlugin

FORMAT = 1
KEY = "dualvoxel"
# name: (looking along, right, up) as (x, y, z) unit vectors; the model faces -y. "left" looks from -x
# (the figure's right side when it faces you), "right" from +x.
VIEWS = {
    "front": ((0, 1, 0), (1, 0, 0), (0, 0, 1)),
    "back": ((0, -1, 0), (-1, 0, 0), (0, 0, 1)),
    "left": ((1, 0, 0), (0, -1, 0), (0, 0, 1)),
    "right": ((-1, 0, 0), (0, 1, 0), (0, 0, 1)),
    "top": ((0, 0, -1), (1, 0, 0), (0, 1, 0)),
    "bottom": ((0, 0, 1), (1, 0, 0), (0, -1, 0)),
}
SLICES_NAME = re.compile(r"\.slices-(\d+)x(\d+)x(\d+)\.(colour|material)\.png$", re.IGNORECASE)
VIEW_NAME = re.compile(r"\.(" + "|".join(VIEWS) + r")\.(colour|material)\.png$", re.IGNORECASE)
MAX_SCALE = 32


def _material_rgb() -> np.ndarray:
    """A false colour per material id 0-255, the same in every file: 0 (matte) grey, the rest spread
    round the hue circle by the golden angle, in three brightnesses so near ids differ."""
    rgb = np.zeros((256, 3), dtype=np.uint8)
    rgb[0] = (128, 128, 128)
    for i in range(1, 256):
        h = (i * 0.6180339887) % 1.0
        rgb[i] = np.round(np.array(colorsys.hsv_to_rgb(h, 0.75, (0.95, 0.75, 0.55)[i % 3])) * 255)
    return rgb


MATERIAL_RGB = _material_rgb()
assert len({tuple(c) for c in MATERIAL_RGB}) == 256, "material false colours must differ"


# --- pictures in and out --------------------------------------------------------------------
def _meta(info: dict) -> PngImagePlugin.PngInfo:
    meta = PngImagePlugin.PngInfo()
    meta.add_text(KEY, json.dumps({"format": FORMAT, **info}, separators=(",", ":")))
    return meta


def write_colour(path: Path, slots: np.ndarray, table_rgb: np.ndarray, info: dict, scale: int = 1) -> Path:
    """An indexed PNG of colour slots (0 transparent), the table as its palette."""
    pixels = np.repeat(np.repeat(slots, scale, 0), scale, 1)
    image = Image.fromarray(np.ascontiguousarray(pixels, dtype=np.uint8), "P")
    image.putpalette(np.asarray(table_rgb, dtype=np.uint8).reshape(-1).tolist())
    image.save(path, transparency=0, pnginfo=_meta(info))
    return path


def write_material(path: Path, ids: np.ndarray, solid: np.ndarray, info: dict, scale: int = 1) -> Path:
    """An RGBA PNG of material ids in false colours, transparent where there is no voxel."""
    rgba = np.zeros((*ids.shape, 4), dtype=np.uint8)
    rgba[..., :3] = MATERIAL_RGB[ids]
    rgba[..., 3] = np.where(solid, 255, 0)
    rgba = np.repeat(np.repeat(rgba, scale, 0), scale, 1)
    Image.fromarray(rgba, "RGBA").save(path, pnginfo=_meta(info))
    return path


def read_info(path: Path) -> dict | None:
    """The dualvoxel text chunk of a PNG, or None (never written, or dropped by a paint program)."""
    with Image.open(path) as image:
        text = image.text.get(KEY) if hasattr(image, "text") else None
    try:
        return json.loads(text) if text else None
    except ValueError:
        return None


def _rgba(path: Path) -> np.ndarray:
    with Image.open(path) as image:
        return np.asarray(image.convert("RGBA"))


def _blocks(values: np.ndarray, scale: int, shape) -> np.ndarray:
    """Each scale x scale block's most common value (paint strokes rarely fill a block exactly)."""
    h, w = shape
    if values.shape[:2] != (h * scale, w * scale):
        raise ValueError(f"the picture is {values.shape[1]} x {values.shape[0]} pixels; expected "
                         f"{w * scale} x {h * scale} ({w} x {h} voxels at {scale} pixels each)")
    if scale == 1:
        return values
    cells = values.reshape(h, scale, w, scale).transpose(0, 2, 1, 3).reshape(h, w, scale * scale)
    out = np.empty((h, w), dtype=values.dtype)
    flat = cells.reshape(-1, scale * scale)
    for i, row in enumerate(flat):  # small pictures: a few thousand blocks
        found, counts = np.unique(row, return_counts=True)
        out.flat[i] = found[counts.argmax()]
    return out


def colours_to_slots(rgba: np.ndarray, table) -> tuple[np.ndarray, int]:
    """Slots for an RGBA picture (alpha under 128 empty): exact table colours, else the nearest slot.
    Returns the slots and how many pixels needed the nearest."""
    rgb = rgba[..., :3].reshape(-1, 3)
    opaque = rgba[..., 3].reshape(-1) >= 128
    key = rgb.astype(np.uint32) @ np.array([65536, 256, 1], dtype=np.uint32)
    exact = {}
    for c in table.colors:
        r, g, b = (int(v) for v in c["rgb"])
        exact.setdefault(r * 65536 + g * 256 + b, c["id"])
    slots = np.zeros(len(key), dtype=np.uint8)
    snapped = 0
    for value in np.unique(key[opaque]):
        where = opaque & (key == value)
        slot = exact.get(int(value))
        if slot is None:
            slot = table.nearest_slot([(value >> 16) & 255, (value >> 8) & 255, value & 255])
            snapped += int(where.sum())
        slots[where] = slot
    return slots.reshape(rgba.shape[:2]), snapped


def colours_to_materials(rgba: np.ndarray, known) -> tuple[np.ndarray, np.ndarray]:
    """Material ids for an RGBA material picture: (ids, which pixels are solid). A colour that is no
    material's false colour, or a material the model does not have, raises."""
    rgb = rgba[..., :3].reshape(-1, 3)
    opaque = rgba[..., 3].reshape(-1) >= 128
    key = rgb.astype(np.int64) @ np.array([65536, 256, 1])
    lookup = {int(k): i for i, k in enumerate(MATERIAL_RGB.astype(np.int64) @ np.array([65536, 256, 1]))}
    ids = np.zeros(len(key), dtype=np.uint8)
    for value in np.unique(key[opaque]):
        mid = lookup.get(int(value))
        if mid is None:
            raise ValueError(f"#{int(value):06x} in the material picture is no material's colour: paint with the "
                             "colours the exported picture uses (one per material)")
        if not known(mid):
            raise ValueError(f"material {mid} (#{int(value):06x}) is not in this model's materials")
        ids[opaque & (key == value)] = mid
    return ids.reshape(rgba.shape[:2]), opaque.reshape(rgba.shape[:2])


# --- slices: the whole model ------------------------------------------------------------------
def _sheet_layout(size_xyz, per_row=None) -> tuple[int, int]:
    """(layers per row, rows) for a slice sheet: about square."""
    x, y, z = size_xyz
    per_row = per_row or max(1, min(z, int(np.ceil(np.sqrt(z * y / x)))))
    return per_row, int(np.ceil(z / per_row))


def slice_sheet(plane: np.ndarray, per_row=None) -> np.ndarray:
    """A (z, y, x) plane as one sheet: layer z at column z % per_row, row z // per_row, each seen from
    above with the back (high y) at the top."""
    z, y, x = plane.shape
    per_row, rows = _sheet_layout((x, y, z), per_row)
    sheet = np.zeros((rows * y, per_row * x), dtype=plane.dtype)
    for k in range(z):
        r, c = divmod(k, per_row)
        sheet[r * y:(r + 1) * y, c * x:(c + 1) * x] = plane[k, ::-1, :]
    return sheet


def sheet_planes(sheet: np.ndarray, size_xyz) -> np.ndarray:
    """slice_sheet backwards: the (z, y, x) plane."""
    x, y, z = size_xyz
    per_row, rows = _sheet_layout((x, y, z))
    if sheet.shape[:2] != (rows * y, per_row * x):
        raise ValueError(f"a sheet of {x} x {y} x {z} voxels is {per_row * x} x {rows * y} pixels, "
                         f"this one {sheet.shape[1]} x {sheet.shape[0]}")
    plane = np.zeros((z, y, x), dtype=sheet.dtype)
    for k in range(z):
        r, c = divmod(k, per_row)
        plane[k] = sheet[r * y:(r + 1) * y, c * x:(c + 1) * x][::-1, :]
    return plane


def export_slices(colour: np.ndarray, material: np.ndarray, table, base: Path, fingerprints=("", "")) -> list[Path]:
    """`<base>.slices-XxYxZ.colour.png` and `.material.png`. base: a path without the suffixes."""
    z, y, x = colour.shape
    stem = f"{base}.slices-{x}x{y}x{z}"
    per_row, rows = _sheet_layout((x, y, z))
    info = {"kind": "slices", "size": [x, y, z], "per_row": per_row, "colours": fingerprints[0],
            "materials": fingerprints[1]}
    Path(stem).parent.mkdir(parents=True, exist_ok=True)
    return [write_colour(Path(f"{stem}.colour.png"), slice_sheet(colour), table.rgb, {**info, "plane": "colour"}),
            write_material(Path(f"{stem}.material.png"), slice_sheet(material), slice_sheet(colour > 0),
                           {**info, "plane": "material"})]


def slices_size(path: Path) -> tuple[int, int, int]:
    """(x, y, z) of a slice sheet, from its text chunk or its name."""
    info = read_info(path)
    if info and info.get("kind") == "slices":
        return tuple(info["size"])
    found = SLICES_NAME.search(Path(path).name)
    if not found:
        raise ValueError(f"{Path(path).name}: not a slice sheet (named <name>.slices-<x>x<y>x<z>.colour.png)")
    return tuple(int(v) for v in found.groups()[:3])


def import_slices(path: Path, table, known) -> tuple[np.ndarray, np.ndarray, dict]:
    """A slice sheet back as (colour, material) planes (z, y, x). path: the colour sheet (the material
    sheet beside it is read too, if there; else every voxel is matte). known(id): whether the model
    can have that material."""
    path = Path(path)
    x, y, z = slices_size(path)
    if not all(1 <= v <= 256 for v in (x, y, z)):
        raise ValueError("each side must be 1-256 voxels")
    slots, snapped = colours_to_slots(_rgba(path), table)
    colour = sheet_planes(slots, (x, y, z))
    material = np.zeros_like(colour)
    material_path = Path(re.sub(r"\.colour\.png$", ".material.png", str(path), flags=re.IGNORECASE))
    report = {"size": [x, y, z], "voxels": int((colour > 0).sum()), "snapped_pixels": snapped,
              "material_sheet": material_path.is_file()}
    if material_path.is_file():
        ids, _ = colours_to_materials(_rgba(material_path), known)
        material = np.where(colour > 0, sheet_planes(ids, (x, y, z)), 0).astype(np.uint8)
    return colour, material, report


# --- views: the surface --------------------------------------------------------------------------
def _frame(view: str):
    """How to turn a (x, y, z) array into (up, right, depth) with up decreasing down the picture, right
    increasing to the right, depth increasing away from the eye: (axes, flips)."""
    forward, right, up = (np.array(v) for v in VIEWS[view])
    axes = [int(np.flatnonzero(v)[0]) for v in (up, right, forward)]
    flips = [up[axes[0]] > 0, right[axes[1]] < 0, forward[axes[2]] < 0]
    return axes, flips


def view_hits(colour: np.ndarray, view: str):
    """For each pixel of a view: the (x, y, z) of the first voxel along its line of sight, whether there is
    one, and how deep it lies (voxels from the near side of the box). Shapes (rows, columns)."""
    if view not in VIEWS:
        raise ValueError(f"view is one of {', '.join(VIEWS)}")
    axes, flips = _frame(view)
    solid = np.transpose(colour.transpose(2, 1, 0) > 0, axes)  # (up, right, depth)
    for axis, flip in enumerate(flips):
        if flip:
            solid = np.flip(solid, axis)
    found = solid.any(axis=2)
    depth = solid.argmax(axis=2)
    rows, cols = np.indices(found.shape)
    sizes = [solid.shape[i] for i in range(3)]
    idx = [rows, cols, depth]
    xyz = [None, None, None]
    for k, axis in enumerate(axes):
        xyz[axis] = sizes[k] - 1 - idx[k] if flips[k] else idx[k]
    return np.stack(xyz, axis=-1), found, depth


def view_planes(colour: np.ndarray, material: np.ndarray, view: str):
    """A view's colour slots and material ids (0 where empty), its hits and depth."""
    xyz, found, depth = view_hits(colour, view)
    x, y, z = xyz[..., 0], xyz[..., 1], xyz[..., 2]
    slots = np.where(found, colour[z, y, x], 0).astype(np.uint8)
    ids = np.where(found, material[z, y, x], 0).astype(np.uint8)
    return slots, ids, xyz, found, depth


def shaded(slots: np.ndarray, found: np.ndarray, depth: np.ndarray, table_rgb: np.ndarray,
           background=(219, 219, 219)) -> np.ndarray:
    """The colours with depth to see the shape by: nearer voxels brighter, a dark line where it jumps."""
    rgb = table_rgb[slots].astype(np.float64)
    if found.any():
        near, far = depth[found].min(), depth[found].max()
        rgb *= (1.0 - 0.35 * (depth - near) / max(far - near, 1))[..., None]
        d = np.where(found, depth, far + 2).astype(np.int64)
        edge = np.zeros_like(found)
        edge[:, 1:] |= np.abs(np.diff(d, axis=1)) > 1
        edge[:, :-1] |= np.abs(np.diff(d, axis=1)) > 1
        edge[1:, :] |= np.abs(np.diff(d, axis=0)) > 1
        edge[:-1, :] |= np.abs(np.diff(d, axis=0)) > 1
        rgb = np.where((edge & found)[..., None], rgb * 0.6, rgb)
    out = np.where(found[..., None], rgb, np.array(background, dtype=np.float64))
    return np.clip(out + 0.5, 0, 255).astype(np.uint8)


def framed(picture: np.ndarray, found: np.ndarray, size=(864, 1152), background=(219, 219, 219),
           fill: float = 0.82) -> Image.Image:
    """A view cropped to the model and scaled up in whole voxels to about `fill` of a canvas's height (and
    at most 90% of its width), centred on `background`: a reference picture, sized like a concept image."""
    rows, cols = np.nonzero(found)
    if not len(rows):
        raise ValueError("The view shows no voxels.")
    picture = picture[rows.min():rows.max() + 1, cols.min():cols.max() + 1]
    h, w = picture.shape[:2]
    scale = max(1, int(min(fill * size[1] / h, 0.9 * size[0] / w)))
    picture = np.repeat(np.repeat(picture, scale, 0), scale, 1)
    canvas = Image.new("RGB", size, background)
    canvas.paste(Image.fromarray(picture), ((size[0] - picture.shape[1]) // 2, (size[1] - picture.shape[0]) // 2))
    return canvas


def _pack(values: np.ndarray) -> str:
    return base64.b64encode(zlib.compress(np.ascontiguousarray(values, dtype=np.uint8).tobytes())).decode()


def _unpack(text: str, shape) -> np.ndarray:
    return np.frombuffer(zlib.decompress(base64.b64decode(text)), dtype=np.uint8).reshape(shape).copy()


def export_views(colour: np.ndarray, material: np.ndarray, table, base: Path, views=tuple(VIEWS), scale: int = 8,
                 fingerprints=("", "")) -> list[Path]:
    """For each view: `<base>.<view>.colour.png`, `.material.png` and `.shaded.png`."""
    if type(scale) is not int or not 1 <= scale <= MAX_SCALE:
        raise ValueError(f"scale is 1-{MAX_SCALE} pixels per voxel")
    z, y, x = colour.shape
    Path(base).parent.mkdir(parents=True, exist_ok=True)
    written = []
    for view in views:
        slots, ids, _, found, depth = view_planes(colour, material, view)
        info = {"kind": "view", "view": view, "size": [x, y, z], "scale": scale, "colours": fingerprints[0],
                "materials": fingerprints[1], "shape": list(slots.shape), "slots": _pack(slots), "ids": _pack(ids)}
        written.append(write_colour(Path(f"{base}.{view}.colour.png"), slots, table.rgb, {**info, "plane": "colour"},
                                    scale))
        written.append(write_material(Path(f"{base}.{view}.material.png"), ids, found, {**info, "plane": "material"},
                                      scale))
        picture = shaded(slots, found, depth, table.rgb)
        picture = np.repeat(np.repeat(picture, scale, 0), scale, 1)
        target = Path(f"{base}.{view}.shaded.png")
        Image.fromarray(picture, "RGB").save(target, pnginfo=_meta({"kind": "shaded", "view": view, "scale": scale}))
        written.append(target)
    return written


def view_of(path: Path) -> tuple[str, str]:
    """(view, plane) of a view picture, from its text chunk or its name."""
    info = read_info(path)
    if info and info.get("kind") == "view":
        return info["view"], info["plane"]
    found = VIEW_NAME.search(Path(path).name)
    if not found:
        raise ValueError(f"{Path(path).name}: not a view picture (named <name>.<view>.colour.png or "
                         f".material.png, view one of {', '.join(VIEWS)})")
    return found.group(1).lower(), found.group(2).lower()


def import_views(colour: np.ndarray, material: np.ndarray, paths, table, known):
    """What painted view pictures change: (points (n, 3) x y z, colours, materials, report). Pictures of
    one view (its colour and material) are read together; views apply in the order given, a later one
    winning where two show the same voxel. The planes are only read."""
    z, y, x = colour.shape
    order, pictures = [], {}
    for path in paths:
        view, plane = view_of(Path(path))
        if view not in pictures:
            order.append(view)
        pictures.setdefault(view, {})[plane] = Path(path)
    new_c, new_m = colour.copy(), material.copy()
    report = {"views": {}, "snapped_pixels": 0}
    for view in order:
        slots_now, ids_now, xyz, found, _ = view_planes(colour, material, view)
        rows, cols = found.shape
        any_path = next(iter(pictures[view].values()))
        info = read_info(any_path)
        if info and info.get("kind") == "view" and info.get("size") != [x, y, z]:
            raise ValueError(f"{any_path.name} shows a model of {info['size'][0]} x {info['size'][1]} x "
                             f"{info['size'][2]}; this one is {x} x {y} x {z}")
        if info and info.get("kind") == "view" and info.get("shape") == [rows, cols]:
            slots_then, ids_then = _unpack(info["slots"], (rows, cols)), _unpack(info["ids"], (rows, cols))
        else:  # no record of the export: compare with the model as it is
            slots_then, ids_then = slots_now, ids_now
        counts = {"recoloured": 0, "erased": 0, "rematerialed": 0, "outside": 0}
        vx, vy, vz = xyz[..., 0], xyz[..., 1], xyz[..., 2]
        if "colour" in pictures[view]:
            rgba = _rgba(pictures[view]["colour"])
            scale = rgba.shape[1] // cols if cols else 1
            painted, snapped = colours_to_slots(rgba, table)
            painted = _blocks(painted, max(scale, 1), (rows, cols))
            report["snapped_pixels"] += snapped
            touched = painted != slots_then
            counts["outside"] += int((touched & ~found).sum())
            hit = touched & found
            erase = hit & (painted == 0)
            paint = hit & (painted > 0)
            new_c[vz[paint], vy[paint], vx[paint]] = painted[paint]
            new_c[vz[erase], vy[erase], vx[erase]] = 0
            new_m[vz[erase], vy[erase], vx[erase]] = 0
            counts["recoloured"], counts["erased"] = int(paint.sum()), int(erase.sum())
        if "material" in pictures[view]:
            rgba = _rgba(pictures[view]["material"])
            scale = rgba.shape[1] // cols if cols else 1
            ids, solid = colours_to_materials(rgba, known)
            ids = _blocks(ids, max(scale, 1), (rows, cols))
            solid = _blocks(solid, max(scale, 1), (rows, cols))
            touched = solid & (ids != ids_then)
            counts["outside"] += int((touched & ~found).sum())
            hit = touched & found
            keep = hit & (new_c[vz, vy, vx] > 0)
            new_m[vz[keep], vy[keep], vx[keep]] = ids[keep]
            counts["rematerialed"] = int(keep.sum())
        report["views"][view] = counts
    changed = (new_c != colour) | (new_m != material)
    pz, py, px = np.nonzero(changed)
    report["changed_voxels"] = len(pz)
    return np.stack([px, py, pz], axis=1), new_c[pz, py, px], new_m[pz, py, px], report
