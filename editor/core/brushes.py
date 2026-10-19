"""Brushes for the 3D edit view, as in MagicaVoxel: which voxels a click touches.

The voxel brush is a shape and a size (its width in voxels; 1 is a single
voxel): cube and sphere are volumes, square and circle are flat, lying across
the clicked face (perpendicular to its normal); offsets are centred on the
anchor voxel (an even size reaches one further to the low side). The face brush
takes the clicked face's connected flat area, the box brush a rectangle between
two voxels in one layer, the ellipsoid brush the ellipsoid over such a rectangle,
standing up from it. Mirroring repeats the voxels across the model's centre.
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


def mirrored(points, size, axes):
    """The points and their mirror images across the model's centre on each axis in `axes` (x, y, z flags),
    each once: (points, index of the original point each came from)."""
    pts = np.asarray(points, dtype=int).reshape(-1, 3)
    source = np.arange(len(pts))
    for a, on in enumerate(axes):
        if on:
            flipped = pts.copy()
            flipped[:, a] = size[a] - 1 - flipped[:, a]
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
