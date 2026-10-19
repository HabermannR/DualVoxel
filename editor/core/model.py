"""The editor's data model: two bytes per voxel (colour slot and material planes), undo, and the edits.

Coordinates in this API are (x, y, z) integers, z up, box ends inclusive; the
planes are stored (z, y, x) as in .vx2 and the renderer. Colour 0 is empty; a
colour slot is 1-255 in the model's colour table (`table`: its project's
<name>.colors.json, or the default palette/colors.json; core/colours.py), a
material an id in palette/materials.json. Every edit is one undo step.

An undo step keeps only the box of voxels it changed (both planes), zlib-packed;
the history holds at most HISTORY_LIMIT steps and HISTORY_BYTES of them.

Whole-model transforms (as MagicaVoxel's edit mode has them) change the box or
move everything in it: resize (to a new size, the voxels placed at an offset),
fit (the box shrunk to its voxels), shift (with or without wrapping round),
turn by quarter turns and flip. Each is one undo step keeping both planes as
they were. Every transform, and every undo or redo of one, is logged
(`transforms_since`) as (count, op, old size, new size), so what is laid over
the voxels (a protection mask, where a scene places the model) can follow it
with `transform_plane`.
"""
from __future__ import annotations

import sys
from pathlib import Path

import copy
import zlib

import numpy as np

ROOT = Path(__file__).resolve().parents[2]  # VoxelPipeline
sys.path.insert(0, str(ROOT / "pipeline"))
sys.path.insert(0, str(ROOT / "palette"))
sys.path.insert(0, str(ROOT / "engine"))
import vx2  # noqa: E402
from colour_math import de2000, srgb_to_lab  # noqa: E402
from core.colours import ColourTable, default_table, table_for  # noqa: E402
from to_two_bytes import material_from_matl, read_vox, read_vox_scene  # noqa: E402,F401

SAVE_ROOT = ROOT / "assets"
HISTORY_LIMIT = 200
HISTORY_BYTES = 256 * 2**20  # the undo steps' packed voxels, all together; the newest step is always kept
PACK_FROM = 256  # boxes of fewer voxels are kept unpacked


class Step:
    """One undo step: the box of voxels it changed and their values on the far side of it (before the
    step while it waits on the undo stack, after it on the redo stack). Undo and redo swap them with
    the model's, so a step stays the same object as it moves between the stacks."""
    __slots__ = ("shape", "box", "_data", "_packed")

    def __init__(self, shape, box, colour: np.ndarray, material: np.ndarray):
        self.shape, self.box = shape, box
        self._keep(colour, material)

    def _keep(self, colour, material) -> None:
        raw = np.stack([colour, material]).tobytes()
        self._packed = colour.size >= PACK_FROM
        self._data = zlib.compress(raw, 1) if self._packed else raw

    @property
    def nbytes(self) -> int:
        return len(self._data)

    def values(self) -> tuple[np.ndarray, np.ndarray]:
        """The (colour, material) values it keeps, shaped as its box."""
        raw = zlib.decompress(self._data) if self._packed else self._data
        both = np.frombuffer(raw, dtype=np.uint8).reshape(2, *(s.stop - s.start for s in self.box))
        return both[0].copy(), both[1].copy()

    def swap(self, model: Model) -> None:
        colour, material = self.values()
        now = model.colour[self.box].copy(), model.material[self.box].copy()
        model.colour[self.box], model.material[self.box] = colour, material
        self._keep(*now)


# --- whole-model transforms ------------------------------------------------------------------------
# An op is a tuple: ("resize", new size (x, y, z), offset (x, y, z): where the old voxel (0, 0, 0) lands),
# ("shift", (dx, dy, dz), wrap), ("rotate", scene axis 0-2, quarter turns counter-clockwise looking down
# the axis, as core.scene.rotated), ("flip", axis).
ANCHORS = ("low", "centre", "high")
TRANSFORM_LOG = 64


def anchor_offset(old: int, new: int, anchor: str) -> int:
    """Where the old voxels start along an axis resized from `old` to `new`: kept at the low end, centred, or
    at the high end."""
    if anchor not in ANCHORS:
        raise ValueError(f"anchor is one of {', '.join(ANCHORS)}")
    return {"low": 0, "centre": (new - old) // 2, "high": new - old}[anchor]


def transform_plane(plane: np.ndarray, op) -> np.ndarray:
    """A (z, y, x) plane (colour, material, a bool mask) as the op leaves it; cells it empties are 0."""
    kind = op[0]
    if kind == "resize":
        size, offset = op[1], op[2]
        out = np.zeros(tuple(size[::-1]), dtype=plane.dtype)
        source, target = [], []
        for old, new, o in zip(plane.shape, size[::-1], offset[::-1]):
            lo, hi = max(0, -o), min(old, new - o)
            if lo >= hi:
                return out
            source.append(slice(lo, hi))
            target.append(slice(lo + o, hi + o))
        out[tuple(target)] = plane[tuple(source)]
        return out
    if kind == "shift":
        delta, wrap = op[1][::-1], op[2]
        out = np.roll(plane, delta, axis=(0, 1, 2))
        if not wrap:  # what went out past one side is gone, not back in at the other
            for axis, d in enumerate(delta):
                view = np.moveaxis(out, axis, 0)
                if d > 0:
                    view[:d] = 0
                elif d < 0:
                    view[d:] = 0
        return out
    if kind == "rotate":
        b, c = (op[1] + 1) % 3, (op[1] + 2) % 3  # axis b turns towards axis c
        return np.ascontiguousarray(np.rot90(plane, op[2], axes=(2 - b, 2 - c)))
    if kind == "flip":
        return np.ascontiguousarray(np.flip(plane, 2 - op[1]))
    raise ValueError(f"not a transform: {op!r}")


def inverse_op(op, old_size):
    """The op that undoes `op` on a model that was `old_size` (x, y, z) before it."""
    kind = op[0]
    if kind == "resize":
        return ("resize", tuple(old_size), tuple(-v for v in op[2]))
    if kind == "shift":
        return ("shift", tuple(-v for v in op[1]), op[2])
    if kind == "rotate":
        return ("rotate", op[1], -op[2])
    return op


class Reshape:
    """The undo step of a whole-model transform: both planes in full as they are on its far side, and the
    op that leads there (logged when undo or redo swaps them, so masks and scenes follow)."""
    __slots__ = ("shape", "_data", "_far", "ahead", "behind")

    def __init__(self, ahead, behind, colour: np.ndarray, material: np.ndarray, shape):
        self.ahead, self.behind = ahead, behind  # swapping applies `ahead`; `behind` brings it back
        self.shape = shape  # the model's, while this step can apply
        self._keep(colour, material)

    def _keep(self, colour, material) -> None:
        self._far = colour.shape
        self._data = zlib.compress(np.stack([colour, material]).tobytes(), 1)

    @property
    def nbytes(self) -> int:
        return len(self._data)

    @property
    def box(self):
        return tuple(slice(0, n) for n in self.shape)

    def values(self) -> tuple[np.ndarray, np.ndarray]:
        both = np.frombuffer(zlib.decompress(self._data), dtype=np.uint8).reshape(2, *self._far)
        return both[0].copy(), both[1].copy()

    def swap(self, model: Model):
        colour, material = self.values()
        now = model.colour, model.material
        old_size = model.size
        model.colour, model.material = colour, material
        self._keep(*now)
        self.shape = colour.shape
        applied = self.ahead
        self.ahead, self.behind = self.behind, self.ahead
        model._log_transform(applied, old_size)
        return applied


class Model:
    def __init__(self):
        self.materials = vx2.load_tables()[1]
        self.table: ColourTable = default_table()  # what the colour slots mean; shared with its project
        self.colour = np.zeros((32, 32, 32), dtype=np.uint8)
        self.material = np.zeros_like(self.colour)
        self.path: Path | None = None
        # The model's own materials, ids 128-255 (vx2.LOCAL_FIRST up), saved in its .vx2; and
        # as they were last opened or saved, to tell what is unsaved.
        self.local: dict[int, dict] = {}
        self.saved_local: dict[int, dict] = {}
        self.undo_stack: list[Step] = []
        self.redo_stack: list[Step] = []
        self.history_limit, self.history_bytes = HISTORY_LIMIT, HISTORY_BYTES
        self.version = 0  # bumps on every change, so views know when to reload
        self.transform_count = 0  # whole-model transforms so far, undo and redo included
        self._transforms: list[tuple] = []  # the last TRANSFORM_LOG of them: (count, op, old size, new size)

    @property
    def size(self) -> tuple[int, int, int]:
        """(x, y, z) voxels."""
        sz, sy, sx = self.colour.shape
        return sx, sy, sz

    # --- the colour table -------------------------------------------------------------
    @property
    def colors(self) -> list[dict]:
        return self.table.colors

    @property
    def by_id(self) -> dict[int, dict]:
        return self.table.by_id

    @property
    def table_labs(self) -> np.ndarray:
        return self.table.labs

    def remap_to(self, table: ColourTable) -> int:
        """Move the model onto another colour table: each slot to the same colour there, else the nearest
        (an edit, not undone: the undo history is cleared). Returns how many slots moved."""
        if table is self.table:
            return 0
        lut = self.table.mapping_to(table) if table.fingerprint != self.table.fingerprint else np.arange(256)
        used = np.unique(self.colour[self.colour > 0])
        moved = int((lut[used] != used).sum())
        self.table = table
        if moved:
            self._replace(lut.astype(np.uint8)[self.colour], self.material)
            self.undo_stack.clear()
            self.redo_stack.clear()
        return moved

    # --- files -------------------------------------------------------------------
    def new(self, x: int, y: int, z: int) -> None:
        if not all(1 <= v <= 256 for v in (x, y, z)):
            raise ValueError("each side must be 1-256 voxels")
        self._replace(np.zeros((z, y, x), dtype=np.uint8), np.zeros((z, y, x), dtype=np.uint8))
        self.path = None
        self.local, self.saved_local = {}, {}
        self.undo_stack.clear()
        self.redo_stack.clear()

    def open(self, path: str | Path, material_overrides: dict[int, int] | None = None) -> None:
        """A .vx2, or a .vox imported on the fly (colours snap to the table, MATL types become materials).
        A .vx2 keeps the colour table it was saved with: the model's own if it is the same colours, else
        the one its fingerprint names (palette/colors.json, or a *.colors.json beside it or in assets/)."""
        path = Path(path)
        local = []
        if path.suffix == ".vx2":
            fingerprint = vx2.read_fingerprints(path)[0]
            table = self.table if fingerprint == self.table.fingerprint else table_for(fingerprint, [path.parent, SAVE_ROOT])
            if table is None:
                raise ValueError(f"{path.name} was saved with colours that are not here: not palette/colors.json, "
                                 f"nor a *{vx2.COLOURS_SUFFIX} beside it or in assets/ (its project's colours file?)")
            colour, material, local = vx2.read_model(path, colors=table.colors)
            self.table = table
        elif path.suffix == ".vox":
            colour, material = self._import_vox(path, material_overrides or {})
        else:
            raise ValueError("open a .vx2 or .vox file")
        self._replace(colour, material)
        self.local = {m["id"]: m for m in local}
        self.saved_local = copy.deepcopy(self.local)
        self.path = path
        self.undo_stack.clear()
        self.redo_stack.clear()

    def _import_vox(self, path: Path, overrides: dict[int, int]):
        size, voxels, palette, matl = read_vox(path)
        return self.import_vox_model(size, voxels, palette, matl, overrides)

    def import_vox_model(self, size, voxels, palette, matl, overrides=None):
        """One MagicaVoxel model's (colour, material) planes: colours snap to the table, MATL types become
        materials (or `overrides`, source palette index -> material id)."""
        overrides = overrides or {}
        used = np.unique(voxels[:, 3]).tolist()
        labs = srgb_to_lab(np.array([palette[i] for i in used]))
        slots = de2000(labs[:, None, :], self.table_labs[None, :, :]).argmin(axis=1)
        pair = {i: (self.colors[int(s)]["id"], overrides.get(i, material_from_matl(matl.get(i))))
                for i, s in zip(used, slots)}
        colour = np.zeros(size[::-1], dtype=np.uint8)
        material = np.zeros(size[::-1], dtype=np.uint8)
        x, y, z, index = (voxels[:, k].astype(int) for k in range(4))
        colour[z, y, x] = [pair[i][0] for i in index]
        material[z, y, x] = [pair[i][1] for i in index]
        return colour, material

    def save(self, name: str, export_vox: bool = True) -> Path:
        """Save as assets/<name>.vx2 (and a lossless export/<name>.vox)."""
        if not name or any(ch in name for ch in "/\\:") or name.startswith("."):
            raise ValueError("give a plain file name, saved into assets/")
        return self.save_path(SAVE_ROOT / f"{Path(name).stem}.vx2", export_vox)

    def save_path(self, path: str | Path, export_vox: bool = True) -> Path:
        """Save as a .vx2 anywhere, with a lossless .vox: export/<name>.vox for a model in assets/,
        else beside the .vx2."""
        target = Path(path).with_suffix(".vx2")
        local = [self.local[i] for i in sorted(self.local)]
        vx2.write(target, self.colour, self.material, local, self.table.colors)
        if export_vox:
            in_assets = target.resolve().parent == SAVE_ROOT.resolve()
            vox = ROOT / "export" / f"{target.stem}.vox" if in_assets else target.with_suffix(".vox")
            vx2.to_vox(self.colour, self.material, vox, local=local, colors=self.table.colors)
        self.saved_local = copy.deepcopy(self.local)
        self.path = target
        return target

    # --- materials: the shared table (ids 0..n-1) and the model's own (128-255) ----------
    def material_info(self, material: int) -> dict:
        """A material by id: one of the model's own, or from the shared table."""
        material = int(material)
        if material in self.local:
            return self.local[material]
        if 0 <= material < len(self.materials):
            return self.materials[material]
        raise KeyError(f"no material {material}")

    def has_material(self, material: int) -> bool:
        return int(material) in self.local or 0 <= int(material) < len(self.materials)

    def all_materials(self) -> list[dict]:
        """The shared table, then the model's own materials, in id order."""
        return [*self.materials, *(self.local[i] for i in sorted(self.local))]

    def add_local(self, material: dict) -> int:
        """Keep a material as one of the model's own under the first free id from 128; returns it."""
        free = next((i for i in range(vx2.LOCAL_FIRST, 256) if i not in self.local), None)
        if free is None:
            raise ValueError("a model holds at most 128 materials of its own")
        self.local[free] = dict(copy.deepcopy(material), id=free)
        return free

    # --- edits (each one undo step) ---------------------------------------------
    def paint_box(self, start, end, colour: int, material: int = 0) -> int:
        self._check_colour(colour, allow_empty=False)
        self._check_material(material)
        z, y, x = self._box(start, end)
        return self._edit(lambda c, m: (c.__setitem__((z, y, x), colour), m.__setitem__((z, y, x), material)))

    def erase_box(self, start, end) -> int:
        z, y, x = self._box(start, end)
        return self._edit(lambda c, m: (c.__setitem__((z, y, x), 0), m.__setitem__((z, y, x), 0)))

    def set_material_box(self, start, end, material: int) -> int:
        """Change the material of the solid voxels in a box, keeping their colours."""
        self._check_material(material)
        z, y, x = self._box(start, end)

        def apply(c, m):
            region = m[z, y, x]
            region[c[z, y, x] > 0] = material
            m[z, y, x] = region
        return self._edit(apply)

    def set_material_for_colour(self, colour: int, material: int) -> int:
        """Every voxel of one colour gets this material (e.g. the skin colours become subsurface)."""
        self._check_colour(colour, allow_empty=False)
        self._check_material(material)
        return self._edit(lambda c, m: m.__setitem__(c == colour, material))

    def replace_colour(self, old: int, new: int, material: int | None = None) -> int:
        """Every voxel of colour `old` becomes `new` (and, if given, that material)."""
        self._check_colour(old, allow_empty=False)
        self._check_colour(new, allow_empty=False)
        if material is not None:
            self._check_material(material)

        def apply(c, m):
            where = c == old
            c[where] = new
            if material is not None:
                m[where] = material
        return self._edit(apply)

    def record(self, colour: np.ndarray, material: np.ndarray, box=None) -> int:
        """After edits made directly on the planes (the desktop editor's tools): one undo step back to these
        planes as they were before, or to these values of a box (z, y, x slices) when it is given (the
        voxels outside it unchanged). Keeps only the box of voxels that changed; no step when none did.
        Returns how many changed."""
        box = box or tuple(slice(0, n) for n in self.colour.shape)
        changed = (self.colour[box] != colour) | (self.material[box] != material)
        count = int(changed.sum())
        if not count:
            return 0
        rows = np.flatnonzero(changed.any(axis=(1, 2)))
        inner = changed[rows[0]:rows[-1] + 1]
        cols, cells = np.flatnonzero(inner.any(axis=(0, 2))), np.flatnonzero(inner.any(axis=(0, 1)))
        tight = tuple(slice(int(r[0]), int(r[-1]) + 1) for r in (rows, cols, cells))
        whole = tuple(slice(b.start + t.start, b.start + t.stop) for b, t in zip(box, tight))
        self._push(Step(self.colour.shape, whole, colour[tight], material[tight]))
        return count

    def _push(self, step) -> None:
        self.undo_stack.append(step)
        self.redo_stack.clear()
        del self.undo_stack[:-self.history_limit]
        while len(self.undo_stack) > 1 and self.history_size() > self.history_bytes:
            del self.undo_stack[0]

    # --- whole-model transforms (each one undo step) -------------------------------------
    # Each has an *_op twin giving the op it would apply (None for no change), to check it first.
    def resize(self, size, offset=None, anchor=("centre", "centre", "low")) -> int:
        """A new box of `size` (x, y, z), 1-256 a side: the voxels at `offset` in it (where the old (0, 0, 0)
        lands), by default placed by `anchor` per axis (low, centre or high: x and y centred, on the floor).
        Voxels left outside are gone. Returns how many solid voxels were lost."""
        return self.transform(self.resize_op(size, offset, anchor))

    def resize_op(self, size, offset=None, anchor=("centre", "centre", "low")):
        size = tuple(int(v) for v in size)
        if len(size) != 3 or not all(1 <= v <= 256 for v in size):
            raise ValueError("each side must be 1-256 voxels")
        if offset is None:
            anchor = (anchor,) * 3 if isinstance(anchor, str) else tuple(anchor)
            if len(anchor) != 3:
                raise ValueError("give an anchor per axis, or one for all three")
            offset = tuple(anchor_offset(o, n, a) for o, n, a in zip(self.size, size, anchor))
        offset = tuple(int(v) for v in offset)
        if len(offset) != 3:
            raise ValueError("the offset is [x, y, z]")
        return None if size == self.size and not any(offset) else ("resize", size, offset)

    def fit(self):
        """Shrink the box to its solid voxels. Returns the offset they moved by (x, y, z), or None when there
        are none or the box already fits."""
        op = self.fit_op()
        self.transform(op)
        return op[2] if op else None

    def fit_op(self):
        solid = self.colour > 0
        if not solid.any():
            return None
        ends = [np.flatnonzero(solid.any(axis=tuple(a for a in range(3) if a != k))) for k in range(3)]
        lo, hi = [int(e[0]) for e in ends][::-1], [int(e[-1]) for e in ends][::-1]  # (x, y, z)
        size = tuple(h - l + 1 for l, h in zip(lo, hi))
        return None if size == self.size else ("resize", size, tuple(-l for l in lo))

    def shift(self, delta, wrap: bool = True) -> int:
        """Move every voxel by (dx, dy, dz) inside the box; with wrap what leaves one side comes back in at the
        other (MagicaVoxel's Move), else it is gone. Returns how many solid voxels were lost."""
        return self.transform(self.shift_op(delta, wrap))

    def shift_op(self, delta, wrap: bool = True):
        delta = tuple(int(v) for v in delta)
        if len(delta) != 3:
            raise ValueError("shift by [dx, dy, dz]")
        if wrap:
            delta = tuple(d % n for d, n in zip(delta, self.size))
        return ("shift", delta, bool(wrap)) if any(delta) else None

    def rotate(self, axis: int, quarter_turns: int = 1) -> None:
        """Turn the whole model about an axis (0 x, 1 y, 2 z), counter-clockwise looking down it; the box
        turns with it."""
        self.transform(self.rotate_op(axis, quarter_turns))

    def rotate_op(self, axis: int, quarter_turns: int = 1):
        if axis not in (0, 1, 2):
            raise ValueError("axis is 0 (x), 1 (y) or 2 (z)")
        return ("rotate", axis, int(quarter_turns) % 4) if int(quarter_turns) % 4 else None

    def flip(self, axis: int) -> None:
        """Mirror the whole model along an axis (0 x, 1 y, 2 z)."""
        self.transform(self.flip_op(axis))

    def flip_op(self, axis: int):
        if axis not in (0, 1, 2):
            raise ValueError("axis is 0 (x), 1 (y) or 2 (z)")
        return ("flip", axis)

    def transform(self, op) -> int:
        """Apply a whole-model op (see transform_plane) as one undo step; None does nothing. Returns how many
        solid voxels it lost (left outside the box)."""
        if op is None:
            return 0
        solid = int(np.count_nonzero(self.colour))
        old_size = self.size
        colour, material = transform_plane(self.colour, op), transform_plane(self.material, op)
        self._push(Reshape(inverse_op(op, old_size), op, self.colour, self.material, colour.shape))
        self.colour, self.material = colour, material
        self.version += 1
        self._log_transform(op, old_size)
        return solid - int(np.count_nonzero(self.colour))

    def _log_transform(self, op, old_size) -> None:
        self.transform_count += 1
        self._transforms.append((self.transform_count, op, tuple(old_size), self.size))
        del self._transforms[:-TRANSFORM_LOG]

    def transforms_since(self, count: int) -> list[tuple] | None:
        """The transforms (count, op, old size, new size) after `count`, oldest first; None when the log no
        longer reaches back that far."""
        if count >= self.transform_count:
            return []
        entries = [t for t in self._transforms if t[0] > count]
        return entries if entries and entries[0][0] == count + 1 else None

    def history_size(self) -> int:
        """Bytes the undo and redo steps keep."""
        return sum(step.nbytes for step in (*self.undo_stack, *self.redo_stack))

    def touched(self) -> None:
        """After direct edits: empty voxels carry no material, and views reload."""
        self.material[self.colour == 0] = 0
        self.version += 1

    def nearest_slot(self, rgb) -> int:
        """Fast nearest table colour for many lookups (CIE76 in Lab), e.g. painting from a reference image."""
        return self.table.nearest_slot(rgb)

    def undo(self) -> bool:
        return self._step(self.undo_stack, self.redo_stack)

    def redo(self) -> bool:
        return self._step(self.redo_stack, self.undo_stack)

    def _step(self, source: list[Step], target: list[Step]) -> bool:
        if not source:
            return False
        if source[-1].shape != self.colour.shape:  # the planes were replaced under the history
            self.undo_stack.clear()
            self.redo_stack.clear()
            return False
        step = source.pop()
        step.swap(self)  # a Reshape logs the transform it applies
        target.append(step)
        self.version += 1
        return True

    # --- questions ---------------------------------------------------------------
    def info(self) -> dict:
        solid = self.colour > 0
        z, y, x = self.colour.shape
        colours, counts = np.unique(self.colour[solid], return_counts=True)
        pairs, pair_counts = np.unique(np.stack([self.colour[solid], self.material[solid]], axis=1), axis=0,
                                       return_counts=True) if solid.any() else (np.zeros((0, 2), int), [])
        return {"path": str(self.path) if self.path else None, "size": [x, y, z], "voxels": int(solid.sum()),
                "colour_table": self.table.title,
                "colours": [{"slot": int(c), "hex": self.by_id[int(c)]["hex"], "family": self.by_id[int(c)]["band"],
                             "voxels": int(n)} for c, n in zip(colours, counts)],
                "pairs": [{"slot": int(c), "material": int(mat), "material_name": self.material_info(mat)["name"],
                           "voxels": int(n)} for (c, mat), n in zip(pairs, pair_counts)],
                "undo": len(self.undo_stack), "redo": len(self.redo_stack)}

    def nearest_colours(self, hex_value: str, count: int = 5) -> list[dict]:
        rgb = [int(hex_value.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
        d = de2000(srgb_to_lab(np.array(rgb))[None, :], self.table_labs)
        order = np.argsort(d)[:count]
        return [{"slot": self.colors[i]["id"], "hex": self.colors[i]["hex"], "family": self.colors[i]["band"],
                 "delta_e2000": round(float(d[i]), 2)} for i in order]

    # --- internals ---------------------------------------------------------------
    def _box(self, start, end):
        sz, sy, sx = self.colour.shape
        lo = [max(0, min(int(a), int(b))) for a, b in zip(start, end)]
        hi = [min(limit - 1, max(int(a), int(b))) for a, b, limit in zip(start, end, (sx, sy, sz))]
        if any(l > h for l, h in zip(lo, hi)):
            raise ValueError(f"the box lies outside the model ({sx} x {sy} x {sz})")
        return slice(lo[2], hi[2] + 1), slice(lo[1], hi[1] + 1), slice(lo[0], hi[0] + 1)

    def _check_colour(self, colour: int, allow_empty: bool) -> None:
        if not (0 if allow_empty else 1) <= colour <= len(self.colors):
            raise ValueError(f"colour slot must be 1-{len(self.colors)}")

    def _check_material(self, material: int) -> None:
        if not self.has_material(material):
            raise ValueError(f"material must be 0-{len(self.materials) - 1} or one of the model's own (128 up)")

    def _edit(self, apply) -> int:
        before_c, before_m = self.colour.copy(), self.material.copy()
        apply(self.colour, self.material)
        self.material[self.colour == 0] = 0
        changed = self.record(before_c, before_m)
        if changed:
            self.version += 1
        return changed

    def _replace(self, colour: np.ndarray, material: np.ndarray) -> None:
        if colour.shape != self.colour.shape:  # steps of another size cannot come back
            self.undo_stack.clear()
            self.redo_stack.clear()
        self.colour, self.material = colour, material
        self.version += 1
