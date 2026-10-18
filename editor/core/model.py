"""The editor's data model: two bytes per voxel (colour slot and material planes), undo, and the edits.

Coordinates in this API are (x, y, z) integers, z up, box ends inclusive; the
planes are stored (z, y, x) as in .vx2 and the renderer. Colour 0 is empty; a
colour slot is 1-255 in palette/colors.json, a material an id in
palette/materials.json. Every edit is one undo step.
"""
from __future__ import annotations

import sys
from pathlib import Path

import copy

import numpy as np

ROOT = Path(__file__).resolve().parents[2]  # VoxelPipeline
sys.path.insert(0, str(ROOT / "pipeline"))
sys.path.insert(0, str(ROOT / "palette"))
sys.path.insert(0, str(ROOT / "engine"))
import vx2  # noqa: E402
from colour_math import de2000, srgb_to_lab  # noqa: E402
from to_two_bytes import material_from_matl, read_vox, read_vox_scene  # noqa: E402,F401

SAVE_ROOT = ROOT / "assets"
HISTORY_LIMIT = 200


class Model:
    def __init__(self):
        self.colors, self.materials = vx2.load_tables()
        self.table_labs = np.array([c["lab"] for c in self.colors])
        self.by_id = {c["id"]: c for c in self.colors}
        self.colour = np.zeros((32, 32, 32), dtype=np.uint8)
        self.material = np.zeros_like(self.colour)
        self.path: Path | None = None
        # The model's own materials, ids 128-255 (vx2.LOCAL_FIRST up), saved in its .vx2; and
        # as they were last opened or saved, to tell what is unsaved.
        self.local: dict[int, dict] = {}
        self.saved_local: dict[int, dict] = {}
        self.undo_stack: list[tuple[np.ndarray, np.ndarray]] = []
        self.redo_stack: list[tuple[np.ndarray, np.ndarray]] = []
        self.version = 0  # bumps on every change, so views know when to reload

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
        """A .vx2, or a .vox imported on the fly (colours snap to the table, MATL types become materials)."""
        path = Path(path)
        local = []
        if path.suffix == ".vx2":
            colour, material, local = vx2.read_model(path)
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
        vx2.write(target, self.colour, self.material, local)
        if export_vox:
            in_assets = target.resolve().parent == SAVE_ROOT.resolve()
            vox = ROOT / "export" / f"{target.stem}.vox" if in_assets else target.with_suffix(".vox")
            vx2.to_vox(self.colour, self.material, vox, local=local)
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

    def checkpoint(self) -> None:
        """Snapshot before edits made directly on the planes (the desktop editor's tools)."""
        self.undo_stack.append((self.colour.copy(), self.material.copy()))
        del self.undo_stack[:-HISTORY_LIMIT]
        self.redo_stack.clear()

    def touched(self) -> None:
        """After direct edits: empty voxels carry no material, and views reload."""
        self.material[self.colour == 0] = 0
        self.version += 1

    def nearest_slot(self, rgb) -> int:
        """Fast nearest table colour for many lookups (CIE76 in Lab), e.g. painting from a reference image."""
        if not hasattr(self, "_tree"):
            from scipy.spatial import cKDTree
            self._tree = cKDTree(self.table_labs)
        return self.colors[int(self._tree.query(srgb_to_lab(np.asarray(rgb, dtype=np.float64)))[1])]["id"]

    def undo(self) -> bool:
        if not self.undo_stack:
            return False
        self.redo_stack.append((self.colour.copy(), self.material.copy()))
        self._replace(*self.undo_stack.pop())
        return True

    def redo(self) -> bool:
        if not self.redo_stack:
            return False
        self.undo_stack.append((self.colour.copy(), self.material.copy()))
        self._replace(*self.redo_stack.pop())
        return True

    # --- questions ---------------------------------------------------------------
    def info(self) -> dict:
        solid = self.colour > 0
        z, y, x = self.colour.shape
        colours, counts = np.unique(self.colour[solid], return_counts=True)
        pairs, pair_counts = np.unique(np.stack([self.colour[solid], self.material[solid]], axis=1), axis=0,
                                       return_counts=True) if solid.any() else (np.zeros((0, 2), int), [])
        return {"path": str(self.path) if self.path else None, "size": [x, y, z], "voxels": int(solid.sum()),
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
        changed = int(((self.colour != before_c) | (self.material != before_m)).sum())
        if changed:
            self.undo_stack.append((before_c, before_m))
            del self.undo_stack[:-HISTORY_LIMIT]
            self.redo_stack.clear()
            self.version += 1
        return changed

    def _replace(self, colour: np.ndarray, material: np.ndarray) -> None:
        self.colour, self.material = colour, material
        self.version += 1
