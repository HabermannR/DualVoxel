"""Python access to the editor's two-byte model, without the window: the base of the MCP server and the CLI.

Coordinates are (x, y, z) integers, z up, box ends inclusive. Colours are slots
1-255 in the model's colour table (0 erases): its project's <name>.colors.json, or
VoxelPipeline/palette/colors.json (`colour_table` lists them), materials ids in
materials.json. Protected boxes are restored after every edit. `render` draws
with the path tracer (VoxelRenderer.dll), loaded on first use.
"""
from __future__ import annotations

import io
import sys
import threading
from functools import wraps
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from core import noise  # noqa: E402
from core.lights import apply_preset, apply_state, preset_name  # noqa: E402
from core.model import ANCHORS, Model, ROOT as PIPELINE, transform_plane  # noqa: E402
from logic.tools import commit_shape  # noqa: E402
# here, on the main thread: loaded first on the MCP server's worker thread, scipy's DLLs hang on Windows
from postprocess import LOOKS, finish  # noqa: E402
from voxel_preview import render_preview  # noqa: E402

OUTPUTS = ROOT / "outputs"
PICTURE_LIMITS = (1920, 1080, 1024)  # width, height, samples of a picture handed back (render, user_view)
FILE_LIMITS = (8192, 8192, 4096)  # the same for a picture saved to a file (save_render): print sizes


def synchronized(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return call


class VoxelEditor:
    def __init__(self, model: Model | None = None):
        """A new empty model of its own, or edits on `model` (the open editor's, through the live link)."""
        self._lock = threading.RLock()
        self.model = model or Model()
        self._engine = None
        self._engine_shown = (None, -1)  # (model, version) last loaded into the engine
        if model is None:
            self.new_model()
        else:
            self._unprotect_all()

    def _unprotect_all(self) -> None:
        """No protected boxes (another model, or its size changed beyond following)."""
        self._protected = np.zeros(self.model.colour.shape, dtype=bool)
        self._seen = self.model.transform_count

    def _follow(self) -> None:
        """Move the protected boxes with each whole-model transform since they were last moved (their undo
        and redo too, and the window's own over the live link)."""
        for _, op, old_size, _ in self.model.transforms_since(self._seen) or []:
            if self._protected.shape == tuple(old_size[::-1]):
                self._protected = transform_plane(self._protected, op)
        self._seen = self.model.transform_count
        if self._protected.shape != self.model.colour.shape:
            self._unprotect_all()

    # --- files -----------------------------------------------------------------------
    @synchronized
    def new_model(self, x=32, y=32, z=64):
        for d in (x, y, z):
            if type(d) is not int:
                raise ValueError("Each dimension must be an integer.")
        self.model.new(x, y, z)
        self._unprotect_all()
        return self.info()

    @synchronized
    def open_model(self, path, material_overrides=None):
        overrides = {int(k): int(v) for k, v in (material_overrides or {}).items()}
        self.model.open(path, overrides)
        self._unprotect_all()
        return self.info()

    @synchronized
    def save_model(self, name, export_vox=True):
        target = self.model.save(name, export_vox)
        return {"path": str(target), "export": str(PIPELINE / "export" / f"{target.stem}.vox") if export_vox else None,
                **self.info()}

    # --- questions ---------------------------------------------------------------------
    @synchronized
    def info(self):
        info = self.model.info()
        solid = np.argwhere(self.model.colour > 0)
        info["bounds"] = [solid.min(axis=0)[::-1].tolist(), solid.max(axis=0)[::-1].tolist()] if len(solid) else None
        info["protected_voxels"] = int((self._protected & (self.model.colour > 0)).sum())
        return info

    @staticmethod
    def palette(model) -> np.ndarray:
        """Slot -> RGBA for the flat previews, from the model's colour table."""
        rgba = np.full((256, 4), 255, dtype=np.uint8)
        rgba[:, :3] = model.table.rgb
        rgba[0] = 0
        return rgba

    @synchronized
    def colour_table(self, family=None):
        rows = [{"slot": c["id"], "hex": c["hex"], "family": c["band"]} for c in self.model.colors]
        return [r for r in rows if not family or family.lower() in r["family"].lower()]

    @synchronized
    def nearest_colours(self, hex_value, count=5):
        return self.model.nearest_colours(hex_value, count)

    @synchronized
    def materials(self):
        return [{k: m[k] for k in ("id", "name", "group", "engine", "note")} for m in self.model.all_materials()]

    # --- edits ---------------------------------------------------------------------------
    def _locked(self):
        """Voxels protected by someone else (the user, in the open editor), or None: kept like the
        protected boxes, and never cleared from here."""
        return None

    def _finish(self, changed):
        """Restore protected voxels from before the edit; report what really changed."""
        keep = self._protected
        locked = self._locked()
        if locked is not None:
            keep = keep | locked
        step = self.model.undo_stack[-1] if changed else None
        if step is not None and keep[step.box].any():
            box, kept = step.box, keep[step.box]
            before_c, before_m = step.values()  # the edit's box as it was
            self.model.undo_stack.pop()
            self.model.colour[box][kept] = before_c[kept]
            self.model.material[box][kept] = before_m[kept]
            changed = self.model.record(before_c, before_m, box)
            self.model.version += 1
        return {"changed_voxels": changed, **self.info()}

    @staticmethod
    def _check_box(start, end):
        if len(start) != 3 or len(end) != 3 or any(type(v) is not int for v in [*start, *end]):
            raise ValueError("Boxes need two corners of three integers: [x, y, z].")

    def _check_inside(self, start, end):
        sz, sy, sx = self.model.colour.shape
        if any(a < 0 or b < a or b >= dim for a, b, dim in zip(start, end, (sx, sy, sz))):
            raise ValueError(f"Inclusive box is outside the model ({sx} x {sy} x {sz}) or reversed.")

    @synchronized
    def paint_box(self, start, end, colour, material=0):
        self._check_box(start, end)
        self._check_inside(start, end)
        if colour == 0:
            return self._finish(self.model.erase_box(start, end))
        return self._finish(self.model.paint_box(start, end, colour, material))

    @synchronized
    def erase_box(self, start, end):
        self._check_box(start, end)
        self._check_inside(start, end)
        return self._finish(self.model.erase_box(start, end))

    @synchronized
    def shape_slice(self, axis, depth, start, end, colour, material=0, shape="Rect"):
        """The slice views' Rect/Circle tool in an x, y or z plane; colour 0 erases."""
        axes = {"x": (1, 2, 0), "y": (0, 2, 1), "z": (0, 1, 2)}
        if axis not in axes or shape not in ("Rect", "Circle") or len(start) != 2 or len(end) != 2:
            raise ValueError("Use axis x/y/z, two [u, v] corners, and Rect or Circle.")
        u, v, d = axes[axis]
        first, last = [0, 0, 0], [0, 0, 0]
        first[u], first[v], first[d] = start[0], start[1], depth
        last[u], last[v], last[d] = end[0], end[1], depth
        self._check_inside([min(a, b) for a, b in zip(first, last)], [max(a, b) for a, b in zip(first, last)])
        self.model._check_colour(colour, allow_empty=True)
        self.model._check_material(material)
        cfg = {"u": u, "v": v, "d": d, "inv_u": False, "inv_v": False}
        grid, mat = self.model.colour.transpose(2, 1, 0), self.model.material.transpose(2, 1, 0)
        before = self.model.colour.copy(), self.model.material.copy()
        commit_shape(grid, cfg, *start, *end, depth, shape, colour,
                     coord_func=lambda c, a, b, dep: _coord(c, a, b, dep), mat_grid=mat, mat_val=material)
        self.model.touched()
        return self._finish(self.model.record(*before))

    @synchronized
    def set_material_box(self, start, end, material):
        self._check_box(start, end)
        self._check_inside(start, end)
        return self._finish(self.model.set_material_box(start, end, material))

    @synchronized
    def set_material_for_colour(self, colour, material):
        return self._finish(self.model.set_material_for_colour(colour, material))

    @synchronized
    def replace_colour(self, old, new, material=None):
        return self._finish(self.model.replace_colour(old, new, material))

    # --- freer drawing: single voxels, round shapes, lines, mirror and copy ---------------------
    def _write(self, mask, colour, material):
        """Set the voxels of a (z, y, x) mask to a colour (0 erases) and material: one undo step."""
        self.model._check_colour(colour, allow_empty=True)
        if colour:
            self.model._check_material(material)
        return self._finish(self.model._edit(lambda c, m: (c.__setitem__(mask, colour),
                                                           m.__setitem__(mask, material if colour else 0))))

    def _shape_mask(self, shape, start, end, hollow=False, axis="z"):
        self._check_box(start, end)
        lo = [min(a, b) for a, b in zip(start, end)]
        hi = [max(a, b) for a, b in zip(start, end)]
        self._check_inside(lo, hi)
        if axis not in ("x", "y", "z"):
            raise ValueError("axis is x, y or z")
        size = [h - l + 1 for l, h in zip(lo, hi)]
        zz, yy, xx = np.indices(size[::-1], dtype=np.float64) + 0.5  # voxel centres within the box
        norm = {name: grid / (n / 2) - 1 for name, grid, n in zip("xyz", (xx, yy, zz), size)}  # -1..1 across it
        across = [n for n in "xyz" if n != axis]
        if shape == "ellipsoid":
            local = norm["x"] ** 2 + norm["y"] ** 2 + norm["z"] ** 2 <= 1
        elif shape == "cylinder":
            local = norm[across[0]] ** 2 + norm[across[1]] ** 2 <= 1
        elif shape == "cone":  # full width at the low end of the axis, a point at the high end
            width = (1 - norm[axis]) / 2
            local = norm[across[0]] ** 2 + norm[across[1]] ** 2 <= width ** 2 + 1e-9
        else:
            raise ValueError("shape is ellipsoid, cylinder or cone (a box is paint_box)")
        if hollow:
            from scipy import ndimage
            local &= ~ndimage.binary_erosion(local, border_value=0)
        mask = np.zeros(self.model.colour.shape, dtype=bool)
        mask[self.model._box(lo, hi)] = local
        return mask

    @synchronized
    def fill_shape(self, shape, start, end, colour, material=0, hollow=False, axis="z"):
        """An ellipsoid, cylinder or cone filling the inclusive box start..end (cylinder and cone along
        `axis`; the cone's point at the box's high end); hollow keeps a one-voxel shell; colour 0 carves."""
        return self._write(self._shape_mask(shape, start, end, hollow, axis), colour, material)

    @synchronized
    def draw_line(self, start, end, colour, material=0, radius=0):
        """A line of voxels from start to end, thickened to a ball of `radius` voxels around it (0: one voxel)."""
        self._check_box(start, end)
        self._check_inside([min(a, b) for a, b in zip(start, end)], [max(a, b) for a, b in zip(start, end)])
        if type(radius) is not int or not 0 <= radius <= 32:
            raise ValueError("radius is a whole number of voxels, 0-32")
        steps = max(abs(b - a) for a, b in zip(start, end)) + 1
        points = np.rint(np.linspace(start, end, steps)).astype(int)
        mask = np.zeros(self.model.colour.shape, dtype=bool)
        mask[points[:, 2], points[:, 1], points[:, 0]] = True
        if radius:
            from scipy import ndimage
            r = np.arange(-radius, radius + 1)
            ball = (r[:, None, None] ** 2 + r[None, :, None] ** 2 + r[None, None, :] ** 2) <= radius * radius + radius
            mask = ndimage.binary_dilation(mask, structure=ball)
        return self._write(mask, colour, material)

    @synchronized
    def set_voxels(self, voxels, colour=None, material=0):
        """Voxels as [x, y, z] (taking `colour` and `material`), [x, y, z, colour] or [x, y, z, colour, material];
        colour 0 erases. One undo step."""
        rows = [list(v) for v in voxels]
        if not rows or any(len(r) not in (3, 4, 5) or any(type(n) is not int for n in r) for r in rows):
            raise ValueError("Give voxels as [x, y, z], [x, y, z, colour] or [x, y, z, colour, material] integers.")
        if any(len(r) == 3 for r in rows) and colour is None:
            raise ValueError("Voxels given as [x, y, z] need a colour.")
        full = np.array([r + [colour, material][len(r) - 3:] if len(r) < 5 else r for r in rows], dtype=int)
        x, y, z, c, m = full.T
        sz, sy, sx = self.model.colour.shape
        if (x < 0).any() or (y < 0).any() or (z < 0).any() or (x >= sx).any() or (y >= sy).any() or (z >= sz).any():
            raise ValueError(f"A voxel lies outside the model ({sx} x {sy} x {sz}).")
        for slot in np.unique(c):
            self.model._check_colour(int(slot), allow_empty=True)
        for mid in np.unique(m[c > 0]):
            self.model._check_material(int(mid))
        m = np.where(c > 0, m, 0)
        return self._finish(self.model._edit(lambda cc, mm: (cc.__setitem__((z, y, x), c), mm.__setitem__((z, y, x), m))))

    @synchronized
    def mirror(self, axis="x", keep="low"):
        """Copy one half of the model onto the other across its centre (a symmetric figure: draw one side).
        keep: the half that stays, "low" (x below the centre) or "high"."""
        if axis not in ("x", "y", "z") or keep not in ("low", "high"):
            raise ValueError("axis is x, y or z; keep is low or high")
        dim = {"x": 2, "y": 1, "z": 0}[axis]
        n = self.model.colour.shape[dim]
        index = np.arange(n)
        other = n - 1 - index
        target = index > other if keep == "low" else index < other

        def apply(c, m):
            for plane in (c, m):
                moved = np.moveaxis(plane, dim, 0)
                moved[target] = moved[other[target]]
        return self._finish(self.model._edit(apply))

    # --- the whole model: its box and everything in it (each one undo step) --------------------------
    def _transform(self, op):
        """Apply a whole-model op unless it would lose protected voxels; the protected boxes move with it."""
        keep = self._protected
        locked = self._locked()
        if locked is not None:
            keep = keep | locked
        keep = keep & (self.model.colour > 0)
        if op is not None and keep.any():
            lost = int(keep.sum()) - int(transform_plane(keep, op).sum())
            if lost:
                raise ValueError(f"That would lose {lost} protected voxels (outside the box): move or shrink "
                                 "it another way, or lift the protection first.")
        lost = self.model.transform(op)
        self._follow()
        return {"changed": op is not None, "lost_voxels": lost, **self.info()}

    @staticmethod
    def _check_axis(axis):
        if axis not in ("x", "y", "z"):
            raise ValueError("axis is x, y or z")
        return "xyz".index(axis)

    @synchronized
    def resize_model(self, size, anchor=None, offset=None):
        """A new box [x, y, z] (1-256 a side). The voxels are placed by anchor, per axis "low", "centre" or
        "high" (one for all, or [x, y, z]; default x and y centred, z low: on the floor), or at offset [x, y, z]
        (where the old voxel [0, 0, 0] lands). Voxels left outside are lost."""
        if len(size) != 3 or any(type(v) is not int for v in size):
            raise ValueError("size is [x, y, z] integers")
        if offset is not None and (len(offset) != 3 or any(type(v) is not int for v in offset)):
            raise ValueError("offset is [x, y, z] integers")
        anchor = anchor or ["centre", "centre", "low"]
        if any(a not in ANCHORS for a in ([anchor] if isinstance(anchor, str) else anchor)):
            raise ValueError(f"anchor is {', '.join(ANCHORS)}, one or per axis")
        return self._transform(self.model.resize_op(size, offset, anchor))

    @synchronized
    def fit_model(self):
        """Shrink the box to its solid voxels."""
        return self._transform(self.model.fit_op())

    @synchronized
    def shift_model(self, offset, wrap=True):
        """Move every voxel by [dx, dy, dz] inside the box; wrap brings what leaves one side in at the other,
        else it is lost."""
        if len(offset) != 3 or any(type(v) is not int for v in offset):
            raise ValueError("offset is [dx, dy, dz] integers")
        return self._transform(self.model.shift_op(offset, bool(wrap)))

    @synchronized
    def rotate_model(self, axis="z", turns=1):
        """Turn the whole model by quarter turns about an axis, counter-clockwise looking down it; the box
        turns with it."""
        if type(turns) is not int:
            raise ValueError("turns is a whole number of quarter turns")
        return self._transform(self.model.rotate_op(self._check_axis(axis), turns))

    @synchronized
    def flip_model(self, axis="x"):
        """Mirror the whole model along an axis."""
        return self._transform(self.model.flip_op(self._check_axis(axis)))

    @synchronized
    def copy_box(self, start, end, offset, move=False):
        """Copy the solid voxels of an inclusive box by `offset` [dx, dy, dz] (those landing outside are dropped);
        move also empties the source first. Empty voxels never overwrite."""
        self._check_box(start, end)
        self._check_inside([min(a, b) for a, b in zip(start, end)], [max(a, b) for a, b in zip(start, end)])
        if len(offset) != 3 or any(type(v) is not int for v in offset):
            raise ValueError("offset is [dx, dy, dz] integers")
        z, y, x = self.model._box(start, end)
        colour, material = self.model.colour[z, y, x].copy(), self.model.material[z, y, x].copy()
        pz, py, px = np.nonzero(colour)
        values = colour[pz, py, px], material[pz, py, px]
        tx, ty, tz = px + x.start + offset[0], py + y.start + offset[1], pz + z.start + offset[2]
        sz, sy, sx = self.model.colour.shape
        keep = (tx >= 0) & (ty >= 0) & (tz >= 0) & (tx < sx) & (ty < sy) & (tz < sz)

        def apply(c, m):
            if move:
                c[z, y, x][colour > 0] = 0
            c[tz[keep], ty[keep], tx[keep]] = values[0][keep]
            m[tz[keep], ty[keep], tx[keep]] = values[1][keep]
        return self._finish(self.model._edit(apply))

    # --- other models: copies of their voxels ------------------------------------------------------
    @synchronized
    def place_model(self, path, position, orient=None, turn=0, mirror=None, empty_only=False):
        """Copy a saved model's voxels into this one, its box's low corner at position [x, y, z], turned:
        orient as in a project ("+y-x+z"), or turn (quarter turns about z) and mirror ("x", "y" or "z").
        Its solid voxels overwrite what is there (empty_only: fill only empty cells); what falls outside
        is dropped. A copy: later edits to that file do not follow (a project's instances do)."""
        from core.scene import place_plane
        from project_ops import ProjectOps, resolve, stamp
        if len(position) != 3 or any(type(v) is not int for v in position):
            raise ValueError("position is [x, y, z] integers")
        source = Model()
        source.open(resolve(path))
        source.remap_to(self.model.table)  # saved with other colours: the nearest of this model's
        o = ProjectOps._orient(orient, turn, mirror)
        colour, material = place_plane(source.colour, o), place_plane(source.material, o)
        if (material >= 128).any():
            raise ValueError(f"{Path(path).name} has materials of its own; place it as a project instance instead.")
        return self._finish(self.model._edit(lambda c, m: stamp(c, m, colour, material, position, empty_only)))

    @synchronized
    def load_volume(self, colour, material, local=(), table=None):
        """Replace the model with these (z, y, x) planes (a merged scene, on its project's colour table), unsaved."""
        if table is not None:
            self.model.table = table
        self.model._replace(np.ascontiguousarray(colour, dtype=np.uint8), np.ascontiguousarray(material, dtype=np.uint8))
        self.model.path = None
        self.model.local = {m["id"]: m for m in local}
        self.model.saved_local = {}
        self.model.undo_stack.clear()
        self.model.redo_stack.clear()
        self._unprotect_all()
        return self.info()

    # --- noise: variation that would take thousands of single voxels ----------------------------------
    def _noise_box(self, start, end):
        """The (z, y, x) slices of a box given by two corners in any order, checked."""
        self._check_box(start, end)
        lo = [min(a, b) for a, b in zip(start, end)]
        hi = [max(a, b) for a, b in zip(start, end)]
        self._check_inside(lo, hi)
        return self.model._box(lo, hi), lo, hi

    def _entries(self, entries, name):
        """A palette as an int, or [[colour, weight], ...] / [[colour, weight, material], ...]:
        (colours, weights, materials), a material None where none was given."""
        if type(entries) is int:
            entries = [[entries, 1]]
        if not isinstance(entries, (list, tuple)) or not entries or any(
                not isinstance(e, (list, tuple)) or len(e) not in (2, 3) for e in entries):
            raise ValueError(f"{name} is a colour slot or a list of [colour, weight] or [colour, weight, material]")
        colours, weights, materials = [], [], []
        for e in entries:
            colour, weight = int(e[0]), float(e[1])
            self.model._check_colour(colour, allow_empty=False)
            material = int(e[2]) if len(e) == 3 else None
            if material is not None:
                self.model._check_material(material)
            colours.append(colour), weights.append(weight), materials.append(material)
        return colours, weights, materials

    @staticmethod
    def _check_seed(seed, scale=0, share=None):
        if type(seed) is not int or seed < 0:
            raise ValueError("seed is a whole number, 0 or more")
        if not 0 <= float(scale) <= 256:
            raise ValueError("scale is 0 (scattered) to 256 voxels")
        if share is not None and not 0 <= float(share) <= 1:
            raise ValueError("shares are 0-1")

    @synchronized
    def speckle(self, start, end, colours, surface_only=True, only_colour=None, scale=0.0, seed=0):
        """Recolour the solid voxels of a box from a weighted palette, each colour taking its share exactly.
        scale 0 scatters single voxels; a scale gathers each colour into patches about that many voxels
        across. surface_only: only voxels with an empty neighbour; only_colour: only voxels of that colour.
        A palette entry's material replaces the voxel's; without one the material stays."""
        box, lo, hi = self._noise_box(start, end)
        self._check_seed(seed, scale)
        slots, weights, materials = self._entries(colours, "colours")
        solid = self.model.colour > 0
        mask = solid & noise.surface(solid) if surface_only else solid.copy()
        if only_colour is not None:
            mask &= self.model.colour == int(only_colour)
        inside = np.zeros_like(mask)
        inside[box] = True
        mask &= inside
        values = noise.value_noise(self.model.colour[box].shape, scale, seed)[mask[box]]
        pick = noise.weighted_choice(values, weights)
        cells = np.nonzero(mask)

        def apply(c, m):
            c[cells] = np.array(slots, np.uint8)[pick]
            for i, material in enumerate(materials):
                if material is not None:
                    chosen = pick == i
                    m[tuple(axis[chosen] for axis in cells)] = material
        return self._finish(self.model._edit(apply))

    @synchronized
    def noise_terrain(self, start, end, top, under=None, soil=None, under_depth=1, scale=12.0, octaves=3,
                      seed=0):
        """Ground filling a box from its floor up to a smooth noise height that spans the box's z range:
        the top layer from the `top` palette, `under_depth` layers below from `under`, the rest from `soil`
        (each a colour or a weighted palette as in speckle; a missing one repeats the one above). Fills
        only: what is above the ground stays."""
        box, lo, hi = self._noise_box(start, end)
        self._check_seed(seed, scale)
        if type(under_depth) is not int or under_depth < 0 or type(octaves) is not int or not 1 <= octaves <= 8:
            raise ValueError("under_depth is 0 or more, octaves 1-8")
        layers = [self._entries(top, "top")]
        layers.append(self._entries(under, "under") if under is not None else layers[0])
        layers.append(self._entries(soil, "soil") if soil is not None else layers[1])
        nz, ny, nx = [h - l + 1 for l, h in zip(lo[::-1], hi[::-1])]
        field = noise.value_noise((ny, nx), max(scale, 1.0), seed, octaves)
        span = field.max() - field.min()
        field = (field - field.min()) / span if span > 0 else np.zeros_like(field)
        height = np.rint(field * (nz - 1)).astype(int)  # the top layer's z within the box
        depth = height[None] - np.arange(nz)[:, None, None]  # 0 at the top, then down
        kind = np.where(depth == 0, 0, np.where(depth <= under_depth, 1, 2))
        ground = depth >= 0
        rng = np.random.default_rng(seed + 1)
        colour_box = np.zeros(ground.shape, np.uint8)
        material_box = np.zeros(ground.shape, np.uint8)
        for k, (slots, weights, materials) in enumerate(layers):
            cells = ground & (kind == k)
            pick = noise.weighted_choice(rng.random(int(cells.sum())), weights)
            colour_box[cells] = np.array(slots, np.uint8)[pick]
            material_box[cells] = np.array([m or 0 for m in materials], np.uint8)[pick]

        def apply(c, m):
            c[box][ground] = colour_box[ground]
            m[box][ground] = material_box[ground]
        return self._finish(self.model._edit(apply))

    @synchronized
    def erode_surface(self, start, end, pits=0.15, bumps=0.0, scale=0.0, keep_bottom=True, seed=0):
        """Roughen the surface in a box: empty a `pits` share of its surface voxels (scale gathers the pits
        into patches), then grow a `bumps` share of what is left by one voxel into an empty cell beside or
        above it, in its colour and material. keep_bottom leaves the box's lowest layer whole."""
        box, lo, hi = self._noise_box(start, end)
        self._check_seed(seed, scale, pits)
        self._check_seed(seed, 0, bumps)
        rng = np.random.default_rng(seed + 1)

        def apply(c, m):
            solid = c > 0
            inside = np.zeros_like(solid)
            inside[box] = True
            surf = noise.surface(solid) & inside
            if keep_bottom:
                surf[lo[2]] = False
            if pits > 0 and surf.any():
                values = noise.value_noise(c[box].shape, scale, seed)[surf[box]]
                gone = noise.weighted_choice(values, [pits, 1 - pits]) == 0
                cells = tuple(axis[gone] for axis in np.nonzero(surf))
                c[cells] = 0
            if bumps > 0:
                solid = c > 0
                rest = noise.surface(solid) & inside
                zs, ys, xs = np.nonzero(rest)
                chosen = rng.random(len(zs)) < bumps
                sz, sy, sx = c.shape
                for z, y, x in zip(zs[chosen], ys[chosen], xs[chosen]):
                    ways = [(z + dz, y + dy, x + dx) for dz, dy, dx in noise.NEIGHBOURS if dz >= 0]
                    ways = [(a, b, d) for a, b, d in ways if 0 <= a < sz and 0 <= b < sy and 0 <= d < sx and not c[a, b, d]]
                    if ways:
                        a, b, d = ways[rng.integers(len(ways))]
                        c[a, b, d], m[a, b, d] = c[z, y, x], m[z, y, x]
        return self._finish(self.model._edit(apply))

    @synchronized
    def scatter(self, start, end, options, density=0.05, on_colours=None, seed=0):
        """Small columns on the top surface in a box (solid voxels open above; on_colours: only on those):
        each such voxel takes one with chance `density`. options: [{"weight": w, "stack": [colour, ...],
        "material": id, "random_height": bool}, ...], a stack listed from the bottom (an entry may be
        [colour, material]); random_height keeps the last entry as the tip and drops some below it."""
        box, lo, hi = self._noise_box(start, end)
        self._check_seed(seed, 0, density)
        if not isinstance(options, (list, tuple)) or not options:
            raise ValueError("options is a list of {weight, stack, material, random_height}")
        stacks, weights = [], []
        for option in options:
            if not isinstance(option, dict) or not option.get("stack"):
                raise ValueError("each option needs a stack: [colour, ...] from the bottom")
            default = int(option.get("material", 0))
            self.model._check_material(default)
            stack = []
            for entry in option["stack"]:
                colour, material = (int(entry), default) if type(entry) is int else (int(entry[0]), int(entry[1]))
                self.model._check_colour(colour, allow_empty=False)
                self.model._check_material(material)
                stack.append((colour, material))
            stacks.append((stack, bool(option.get("random_height", False))))
            weights.append(float(option.get("weight", 1)))
        rng = np.random.default_rng(seed)

        def apply(c, m):
            solid = c > 0
            ground = noise.surface(solid, top_only=True)
            inside = np.zeros_like(solid)
            inside[box] = True
            ground &= inside
            if on_colours:
                ground &= np.isin(c, [int(v) for v in on_colours])
            zs, ys, xs = np.nonzero(ground)
            chosen = rng.random(len(zs)) < density
            picks = noise.weighted_choice(rng.random(int(chosen.sum())), weights)
            for (z, y, x), k in zip(zip(zs[chosen], ys[chosen], xs[chosen]), picks):
                stack, random_height = stacks[k]
                if random_height and len(stack) > 1:
                    stack = stack[:int(rng.integers(0, len(stack)))] + stack[-1:]
                for dz, (colour, material) in enumerate(stack, start=1):
                    if z + dz >= c.shape[0] or c[z + dz, y, x]:
                        break
                    c[z + dz, y, x], m[z + dz, y, x] = colour, material
        return self._finish(self.model._edit(apply))

    # --- reading what is there -----------------------------------------------------------------
    @synchronized
    def read_slice(self, axis, depth, what="colour"):
        """One layer as rows of numbers ("." empty), cropped to what is solid in it: colour slots or materials.
        axis z: rows run y from back (high) to front, columns x; axis x or y: rows run z from top down."""
        if axis not in ("x", "y", "z") or what not in ("colour", "material"):
            raise ValueError("axis is x, y or z; what is colour or material")
        sz, sy, sx = self.model.colour.shape
        limit = {"x": sx, "y": sy, "z": sz}[axis]
        if type(depth) is not int or not 0 <= depth < limit:
            raise ValueError(f"depth is 0-{limit - 1} along {axis}")
        layer = {"x": np.s_[:, :, depth], "y": np.s_[:, depth, :], "z": np.s_[depth]}[axis]
        colour = self.model.colour[layer]
        values = colour if what == "colour" else self.model.material[layer]
        u_name, v_name = {"x": ("y", "z"), "y": ("x", "z"), "z": ("x", "y")}[axis]
        solid = np.argwhere(colour > 0)
        if not len(solid):
            return {"axis": axis, "depth": depth, "empty": True}
        (v0, u0), (v1, u1) = solid.min(axis=0), solid.max(axis=0)
        width = len(str(int(values.max())))
        rows = []
        for v in range(v1, v0 - 1, -1):  # top (or back) row first
            rows.append(" ".join(f"{int(values[v, u]):>{width}}" if colour[v, u] else "." * width
                                 for u in range(u0, u1 + 1)))
        return {"axis": axis, "depth": depth, "what": what, "columns": f"{u_name} {u0}..{u1}",
                "rows": f"{v_name} {v1} down to {v0}", "grid": rows}

    @synchronized
    def voxels_in_box(self, start, end, limit=2000):
        """The solid voxels in an inclusive box as [x, y, z, colour, material], at most `limit`."""
        self._check_box(start, end)
        self._check_inside([min(a, b) for a, b in zip(start, end)], [max(a, b) for a, b in zip(start, end)])
        z, y, x = self.model._box(start, end)
        colour, material = self.model.colour[z, y, x], self.model.material[z, y, x]
        pz, py, px = np.nonzero(colour)
        rows = [[int(a + x.start), int(b + y.start), int(c + z.start), int(colour[c, b, a]), int(material[c, b, a])]
                for c, b, a in zip(pz, py, px)]
        return {"count": len(rows), "voxels": rows[:limit], "truncated": len(rows) > limit}

    @synchronized
    def protect_box(self, start, end):
        self._check_box(start, end)
        self._check_inside(start, end)
        z, y, x = self.model._box(start, end)
        self._protected[z, y, x] = True
        return self.info()

    @synchronized
    def clear_protection(self):
        self._protected[:] = False
        return self.info()

    @synchronized
    def undo(self):
        changed = self.model.undo()
        self._follow()
        return {"changed": changed, **self.info()}

    @synchronized
    def redo(self):
        changed = self.model.redo()
        self._follow()
        return {"changed": changed, **self.info()}

    # --- pictures ------------------------------------------------------------------------
    @synchronized
    def preview_png(self, model: Model | None = None):
        """Flat editing views (front, back, right, isometric) of the voxel colours; fast, no lighting.
        model: another model to show (the open editor's copy), else this one."""
        model = model or self.model
        image = render_preview(model.colour.transpose(2, 1, 0), self.palette(model))
        out = io.BytesIO()
        image.save(out, format="PNG")
        return out.getvalue()

    @synchronized
    def render_png(self, yaw=-25.0, pitch=10.0, width=640, height=640, samples=64, light="Golden hour",
                   model: Model | None = None, view: dict | None = None, look="none"):
        """The model in the path tracer, on the wooden table under one of the Light dock's presets
        (Golden hour, Day, Noon, Overcast, Night). model: another model to draw, else this one. view: the
        editor's Render dock camera and light ({"eye", "forward", "right", "up", "light"}) instead of yaw,
        pitch and the preset. look: a finish from postprocess.LOOKS ("none", "film", "night")."""
        return self._render(yaw, pitch, width, height, samples, light, model, view, look, PICTURE_LIMITS)

    def _render(self, yaw, pitch, width, height, samples, light, model, view, look, limits):
        model = model or self.model
        max_width, max_height, max_samples = limits
        if not (16 <= width <= max_width and 16 <= height <= max_height and 1 <= samples <= max_samples):
            raise ValueError(f"width 16-{max_width}, height 16-{max_height}, samples 1-{max_samples}")
        preset_name(light)  # an unknown name fails before the engine starts
        if look not in LOOKS:
            raise ValueError(f"Unknown look {look!r}: one of {', '.join(LOOKS)}.")
        if not (model.colour > 0).any():
            raise ValueError("The model is empty.")
        if self._engine is None:
            sys.path.insert(0, str(PIPELINE / "engine"))
            from voxel_renderer import VoxelRenderer
            self._engine = VoxelRenderer()
        shown, version = self._engine_shown
        if shown is not model or version != model.version:
            self._engine.show(model.colour, model.material, model.all_materials(), model.colors)
            self._engine_shown = (model, model.version)
        from PIL import Image
        if view is None:
            apply_preset(self._engine, light)
            rgba = self._engine.render(width, height, yaw_deg=yaw, pitch_deg=pitch, samples=samples)
        else:
            apply_state(self._engine, view["light"])
            rgba = self._engine.render_camera(width, height, view["eye"], view["forward"], view["right"], view["up"],
                                              samples)
        out = io.BytesIO()
        Image.fromarray(finish(rgba[..., :3].copy(), look)).save(out, format="PNG")
        return out.getvalue()

    @staticmethod
    def output_path(name):
        target = (OUTPUTS / name).resolve()
        if not target.is_relative_to(OUTPUTS.resolve()) or target.suffix.lower() != ".png":
            raise ValueError("Pictures are saved as .png inside the editor's outputs folder.")
        target.parent.mkdir(parents=True, exist_ok=True)
        return target

    def save_preview(self, name="preview.png"):
        target = self.output_path(name)
        target.write_bytes(self.preview_png())
        return str(target)

    def save_render(self, name="render.png", yaw=-25.0, pitch=10.0, width=640, height=640, samples=64,
                    light="Golden hour", model: Model | None = None, view: dict | None = None, look="none"):
        """render_png's picture saved in the outputs folder, up to FILE_LIMITS (print sizes) instead of the
        size a picture handed back may have."""
        target = self.output_path(name)
        target.write_bytes(self._render(yaw, pitch, width, height, samples, light, model, view, look, FILE_LIMITS))
        return str(target)

    def close(self):
        if self._engine is not None:
            self._engine.close()
            self._engine = None


def _coord(cfg, u, v, depth):
    c = [0, 0, 0]
    c[cfg["u"]], c[cfg["v"]], c[cfg["d"]] = u, v, depth
    return tuple(c)
