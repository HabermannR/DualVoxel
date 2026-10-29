"""Brushes for the 3D edit view, as in MagicaVoxel: which voxels a click touches.

The voxel brush is a shape and a size (its width in voxels; 1 is a single
voxel): cube and sphere are volumes, square and circle are flat, lying across
the clicked face (perpendicular to its normal); offsets are centred on the
anchor voxel (an even size reaches one further to the low side). The face brush
takes the clicked face's connected flat area, the box brush a rectangle between
two voxels in one layer, the ellipsoid brush the ellipsoid over such a rectangle,
standing up from it. The line brush draws a straight line between two voxels with
the voxel brush's shape and size; the fill brush takes a connected area (region_labels).
Mirroring repeats the voxels across the model's centre,
or across a plane of one's own per axis (through a voxel or between two).
"""
from __future__ import annotations

import numpy as np

SHAPES = ("cube", "sphere", "square", "circle")
FLAT = ("square", "circle")
MAX_SIZE = 32


def offsets(shape: str, size: int, normal_axis: int = 2) -> np.ndarray:
    """(n, 3) integer (x, y, z) offsets of the brush's voxels around its anchor."""
    size = max(1, min(MAX_SIZE, int(size)))
    k = np.arange(-(size // 2), size - size // 2)
    centre = (size - 1) / 2 - size // 2  # 0 for odd sizes, -0.5 for even ones
    ranges = [k, k, k]
    if shape in FLAT:
        ranges[normal_axis] = np.array([0])
    grid = np.stack(np.meshgrid(*ranges, indexing="ij"), axis=-1).reshape(-1, 3)
    if shape in ("sphere", "circle"):
        d = grid - centre
        if shape == "circle":
            d[:, normal_axis] = 0
        grid = grid[(d ** 2).sum(axis=1) <= (size / 2) ** 2]
    elif shape not in ("cube", "square"):
        raise ValueError(f"brush shapes: {', '.join(SHAPES)}")
    return grid


def placed(shape: str, size: int, anchor, normal, against: bool = False) -> np.ndarray:
    """The brush's voxels at an anchor voxel. `normal` is the clicked face's outward normal (the floor's is +z).
    With `against` (attach) a volume shape moves out along the normal so it rests on the face instead of
    being centred in it."""
    normal = np.asarray(normal)
    axis = int(np.argmax(np.abs(normal)))
    pts = offsets(shape, size, axis)
    if against and shape not in FLAT:
        pts = pts.copy()
        pts[:, axis] -= pts[:, axis].min() if normal[axis] > 0 else pts[:, axis].max()
    return pts + np.asarray(anchor, dtype=int)


def face_region(solid_zyx: np.ndarray, hit, normal) -> np.ndarray:
    """The clicked face's flat area: the solid voxels in the hit voxel's layer whose face on the normal's side
    is open, connected (edge to edge) to the hit voxel. (x, y, z) points."""
    from scipy.ndimage import label
    solid = solid_zyx.transpose(2, 1, 0)  # (x, y, z)
    normal = np.asarray(normal)
    axis = int(np.argmax(np.abs(normal)))
    sign = int(normal[axis])
    layer = int(hit[axis])
    beside = layer + sign
    plane = np.take(solid, layer, axis=axis)
    if 0 <= beside < solid.shape[axis]:
        plane = plane & ~np.take(solid, beside, axis=axis)
    labels, _ = label(plane)
    others = [a for a in range(3) if a != axis]
    own = labels[hit[others[0]], hit[others[1]]]
    if not own:  # the hit voxel's face is not open on that side
        return np.array([hit], dtype=int)
    u, v = np.nonzero(labels == own)
    pts = np.zeros((len(u), 3), dtype=int)
    pts[:, others[0]], pts[:, others[1]], pts[:, axis] = u, v, layer
    return pts


def box(start, end, normal) -> np.ndarray:
    """The rectangle between two voxels, in the start voxel's layer across the normal (a flat box)."""
    normal = np.asarray(normal)
    axis = int(np.argmax(np.abs(normal)))
    lo, hi = np.minimum(start, end), np.maximum(start, end)
    lo[axis] = hi[axis] = start[axis]
    ranges = [np.arange(lo[a], hi[a] + 1) for a in range(3)]
    return np.stack(np.meshgrid(*ranges, indexing="ij"), axis=-1).reshape(-1, 3)


def ellipsoid(start, end, normal, height: int = 0, outward: bool = True, centred: bool = False) -> np.ndarray:
    """The ellipsoid filling the box over the rectangle between two voxels: across the normal it spans the
    rectangle (in the start voxel's layer), along it `height` layers (0: the rectangle's shorter side) from
    the start layer, out along the normal (attach: resting on the face) or into the surface; `centred` puts
    the start layer in its middle (a slice). As the assistant's fill_shape: voxel centres inside it."""
    normal = np.asarray(normal)
    axis = int(np.argmax(np.abs(normal)))
    lo, hi = np.minimum(start, end), np.maximum(start, end)
    across = [a for a in range(3) if a != axis]
    height = max(1, min(MAX_SIZE, int(height))) if height else int(min(hi[a] - lo[a] + 1 for a in across))
    layer = int(start[axis])
    if centred:
        lo[axis] = layer - (height - 1) // 2
    elif outward == (normal[axis] > 0):
        lo[axis] = layer
    else:
        lo[axis] = layer - height + 1
    hi[axis] = lo[axis] + height - 1
    ranges = [np.arange(lo[a], hi[a] + 1) for a in range(3)]
    grid = np.stack(np.meshgrid(*ranges, indexing="ij"), axis=-1).reshape(-1, 3)
    d = (grid + 0.5 - lo) / ((hi - lo + 1) / 2) - 1  # -1..1 across the box
    return grid[(d ** 2).sum(axis=1) <= 1]


def line(start, end) -> np.ndarray:
    """The voxels on the straight line from start to end, both ends included: one per step along the axis it
    goes furthest on (as the assistant's draw_line). (n, 3) x, y, z points."""
    start, end = np.asarray(start, dtype=int), np.asarray(end, dtype=int)
    steps = int(np.abs(end - start).max()) + 1
    return np.rint(np.linspace(start, end, steps)).astype(int)


def thick_line(start, end, shape: str, size: int, normal_axis: int = 2) -> np.ndarray:
    """The line from start to end drawn with a voxel brush of this shape and size at each of its voxels (a flat
    shape lies across normal_axis)."""
    pts = line(start, end)
    if size <= 1:
        return pts
    return np.unique((pts[:, None, :] + offsets(shape, size, normal_axis)[None]).reshape(-1, 3), axis=0)


def region_labels(mask_zyx: np.ndarray, seed, axis: int | None = None, diagonal: bool = False) -> np.ndarray:
    """Connected areas of a bool plane (z, y, x), numbered: in 3D (axis None, an (x, y, z) array), or only in the
    seed's layer across `axis` (a 2D array of that layer's other two axes, in order). Cells touch face to face,
    or with `diagonal` edge and corner to corner too. The fill brush keeps these between hovers."""
    from scipy.ndimage import generate_binary_structure, label
    mask = mask_zyx.transpose(2, 1, 0)  # (x, y, z)
    if axis is None:
        return label(mask, generate_binary_structure(3, 3 if diagonal else 1))[0]
    plane = np.take(mask, int(seed[axis]), axis=axis)
    return label(plane, generate_binary_structure(2, 2 if diagonal else 1))[0]


def labelled_region(labels: np.ndarray, seed, axis: int | None = None) -> np.ndarray:
    """The cells of the seed's area in region_labels' numbering, as (x, y, z) points (none when the seed is not
    in the mask)."""
    seed = np.asarray(seed, dtype=int)
    if axis is None:
        own = labels[tuple(seed)]
        return np.argwhere(labels == own) if own else np.zeros((0, 3), dtype=int)
    others = [a for a in range(3) if a != axis]
    own = labels[seed[others[0]], seed[others[1]]]
    if not own:
        return np.zeros((0, 3), dtype=int)
    u, v = np.nonzero(labels == own)
    pts = np.zeros((len(u), 3), dtype=int)
    pts[:, others[0]], pts[:, others[1]], pts[:, axis] = u, v, seed[axis]
    return pts


def enclosed(points, size, axis: int | None = None) -> bool:
    """Whether an empty area keeps off the box's sides, so filling it fills a hollow and not the space around
    the model: on every axis it spreads along (all but `axis` for a layer). The floor (z = 0) closes it."""
    pts = np.asarray(points).reshape(-1, 3)
    for a in range(3):
        if a == axis or not len(pts):
            continue
        if (pts[:, a] == size[a] - 1).any() or (a != 2 and (pts[:, a] == 0).any()):
            return False
    return True


FILL_SCOPES = ("connected", "layer", "model")  # the fill's reach: connected in 3D, in the seed's layer, all
FILL_MATCHES = ("colour", "colour and material", "solid")  # which voxels a fill of solid voxels spreads through
NOTHING = np.zeros((0, 3), dtype=int)


def flood(colour_zyx: np.ndarray, material_zyx: np.ndarray, seed, empty: bool, scope: str = "connected",
          axis: int = 2, match: str = "colour", diagonal: bool = False, labs=None, tolerance: float = 0,
          cache: dict | None = None, version=None) -> np.ndarray:
    """The fill brush's voxels from a seed voxel, (x, y, z) points (none: nothing to fill). empty (attach)
    floods the empty cells connected to an empty seed, but only an enclosed hollow (enclosed); otherwise the
    solid voxels connected to a solid seed that match it: match "colour" (its colour, or with labs, the colour
    table's Lab values by slot - 1, any colour within `tolerance` ΔE of it), "colour and material", or "solid"
    (any). scope: "connected" in 3D, "layer" (connected in the seed's layer across `axis`) or "model" (every
    matching voxel, connected or not; an empty fill stays connected). cache: a dict that keeps the last
    numbering of areas (region_labels), valid while `version` (the caller's: which model, which edit) holds."""
    sz, sy, sx = colour_zyx.shape
    x, y, z = (int(v) for v in seed)
    if not (0 <= x < sx and 0 <= y < sy and 0 <= z < sz) or empty != (colour_zyx[z, y, x] == 0):
        return NOTHING
    if scope not in FILL_SCOPES or match not in FILL_MATCHES:
        raise ValueError(f"fill scopes: {', '.join(FILL_SCOPES)}; matches: {', '.join(FILL_MATCHES)}")
    if empty or match == "solid":
        key = ("empty",) if empty else ("solid",)
        mask = (lambda: colour_zyx == 0) if empty else (lambda: colour_zyx > 0)
    else:
        c, m = int(colour_zyx[z, y, x]), int(material_zyx[z, y, x])
        slots = [c]
        if tolerance > 0 and labs is not None:
            from colour_math import de2000  # palette/, on the path through core.model
            slots = (np.nonzero(de2000(np.asarray(labs)[c - 1][None, :], np.asarray(labs)) <= tolerance)[0]
                     + 1).tolist()
        same_material = match == "colour and material"
        key = ("colour", tuple(slots), m if same_material else None)
        mask = (lambda: np.isin(colour_zyx, slots) & (material_zyx == m)) if same_material else \
            (lambda: np.isin(colour_zyx, slots))
    if scope == "model" and not empty:
        z_, y_, x_ = np.nonzero(mask())
        return np.stack([x_, y_, z_], axis=1)
    layer = axis if scope == "layer" else None
    where = (version, colour_zyx.shape, key, diagonal, layer, None if layer is None else (x, y, z)[layer])
    labels = cache.get(where) if cache is not None and version is not None else None
    if labels is None:
        labels = region_labels(mask(), (x, y, z), layer, diagonal)
        if cache is not None and version is not None:
            cache.clear()  # one at a time: a 256-a-side model's numbering is 64 MB
            cache[where] = labels
    points = labelled_region(labels, (x, y, z), layer)
    if empty and not enclosed(points, (sx, sy, sz), layer):
        return NOTHING  # the space around the model, not a hollow
    return points


def mirror_sum(size, planes, axis: int) -> int:
    """The mirror plane on an axis in doubled voxel coordinates: a voxel p mirrors to sum - p. planes[axis]
    None (or planes None) is the model's centre, size - 1; an even sum lies through a voxel's centre, an odd
    one between two voxels."""
    plane = None if planes is None else planes[axis]
    return size[axis] - 1 if plane is None else int(plane)


def mirrored(points, size, axes, planes=None):
    """The points and their mirror images on each axis in `axes` (x, y, z flags), across the model's centre or
    `planes` (per axis, doubled: mirror_sum), each once: (points, index of the original point each came from).
    Images outside the model are left for the caller to drop."""
    pts = np.asarray(points, dtype=int).reshape(-1, 3)
    source = np.arange(len(pts))
    for a, on in enumerate(axes):
        if on:
            flipped = pts.copy()
            flipped[:, a] = mirror_sum(size, planes, a) - flipped[:, a]
            pts, source = np.concatenate([pts, flipped]), np.concatenate([source, source])
    _, first = np.unique(pts, axis=0, return_index=True)
    first.sort()
    return pts[first], source[first]


# --- sculpting: smooth, erode and grow within the brush's area ---------------------------------------------
SCULPT_OPS = ("smooth", "erode", "grow")
_FACES = np.array([(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)])
_AROUND = np.array([(dx, dy, dz) for dx in (-1, 0, 1) for dy in (-1, 0, 1) for dz in (-1, 0, 1)
                    if (dx, dy, dz) != (0, 0, 0)])


def sculpt(colour_zyx: np.ndarray, material_zyx: np.ndarray, region, op: str):
    """Reshape the model inside `region` ((n, 3) x, y, z points): erode removes solid voxels with an open face,
    grow fills empty voxels touching a solid one, smooth makes each voxel what most of its 3 x 3 x 3
    neighbourhood is (14 of 27 solid: solid). A voxel that appears takes the commonest colour among its solid
    neighbours, with that neighbour's material. Returns (points, colours, materials) of the voxels that change
    (colour 0: removed), or None."""
    if op not in SCULPT_OPS:
        raise ValueError(f"sculpt operations: {', '.join(SCULPT_OPS)}")
    sz, sy, sx = colour_zyx.shape
    pts = np.unique(np.asarray(region, dtype=int).reshape(-1, 3), axis=0)
    pts = pts[(pts >= 0).all(axis=1) & (pts[:, 0] < sx) & (pts[:, 1] < sy) & (pts[:, 2] < sz)]
    if not len(pts):
        return None
    solid = colour_zyx > 0

    def solid_at(points):
        x, y, z = points[..., 0], points[..., 1], points[..., 2]
        inside = (x >= 0) & (y >= 0) & (z >= 0) & (x < sx) & (y < sy) & (z < sz)
        out = np.zeros(x.shape, dtype=bool)
        out[inside] = solid[z[inside], y[inside], x[inside]]
        return out

    here = solid_at(pts)
    if op == "erode":
        exposed = ~solid_at(pts[:, None, :] + _FACES[None]).all(axis=1)
        change = here & exposed
    elif op == "grow":
        change = ~here & solid_at(pts[:, None, :] + _FACES[None]).any(axis=1)
    else:
        count = solid_at(pts[:, None, :] + _AROUND[None]).sum(axis=1) + here
        change = (count >= 14) != here
    pts, appear = pts[change], ~here[change]
    if not len(pts):
        return None
    colours = np.zeros(len(pts), dtype=np.uint8)
    materials = np.zeros(len(pts), dtype=np.uint8)
    for i in np.nonzero(appear)[0]:
        near = pts[i] + _AROUND
        ok = (near >= 0).all(axis=1) & (near[:, 0] < sx) & (near[:, 1] < sy) & (near[:, 2] < sz)
        near = near[ok]
        c = colour_zyx[near[:, 2], near[:, 1], near[:, 0]]
        m = material_zyx[near[:, 2], near[:, 1], near[:, 0]]
        if (c > 0).any():
            values, counts = np.unique(c[c > 0], return_counts=True)
            colours[i] = values[np.argmax(counts)]
            materials[i] = m[np.argmax(c == colours[i])]
    keep = ~appear | (colours > 0)  # a voxel with no solid neighbour to take a colour from does not appear
    return (pts[keep], colours[keep], materials[keep]) if keep.any() else None


def layer_region(colour_zyx: np.ndarray, point, axis: int) -> np.ndarray:
    """The cells connected (edge to edge) to `point` in its layer across `axis` that have its colour (or are
    empty like it): a slice's flood fill. (x, y, z) points."""
    from scipy.ndimage import label
    colour = colour_zyx.transpose(2, 1, 0)  # (x, y, z)
    point = np.asarray(point, dtype=int)
    plane = np.take(colour, point[axis], axis=axis)
    others = [a for a in range(3) if a != axis]
    labels, _ = label(plane == plane[point[others[0]], point[others[1]]])
    u, v = np.nonzero(labels == labels[point[others[0]], point[others[1]]])
    pts = np.zeros((len(u), 3), dtype=int)
    pts[:, others[0]], pts[:, others[1]], pts[:, axis] = u, v, point[axis]
    return pts
