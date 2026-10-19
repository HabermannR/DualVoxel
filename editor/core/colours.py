"""Colour tables: what each colour slot 1-255 means (0 is empty). A voxel stores only its slot.

Colours belong to a project: each keeps its own table, <project>.colors.json
beside its .project.json, one line per slot, which starts as a copy of the
default table and is changed in the Colours dock. The default table,
palette/colors.json (built by palette/build_colors.py), is never changed in
the editor. A .vx2 file's colour fingerprint (pipeline/vx2.py) names the table
its slots mean; a model brought from another table is remapped to the nearest
colours (`mapping_to`).
"""
from __future__ import annotations

import copy
import json
import os
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]  # VoxelPipeline
for folder in ("pipeline", "palette"):
    if str(ROOT / folder) not in sys.path:
        sys.path.insert(0, str(ROOT / folder))
import vx2  # noqa: E402
from colour_math import de2000, srgb_to_lab  # noqa: E402

FORMAT = "voxelpipeline-colours"
SUFFIX = vx2.COLOURS_SUFFIX
NEAR = 3.0  # CIEDE2000 below which two slots are hard to tell apart (2.3 is just noticeable)


def _hex(rgb) -> str:
    return "#" + "".join(f"{int(v):02x}" for v in rgb)


class ColourTable:
    """The slots of one table, shared (the same object) by every model that uses it, so a change
    shows in all of them. `version` bumps on each change; `saved` is each slot's hex as last saved."""

    def __init__(self, colors: list[dict], path: Path | None = None, owner: str | None = None,
                 read_only: bool = False):
        self.colors = colors
        self.path = Path(path) if path else None
        self.owner = owner  # the project's name, None for the default table
        self.read_only = read_only
        self.version = 0
        self.by_id = {c["id"]: c for c in colors}
        for c in colors:
            if "lab" not in c or "hex" not in c:
                self._derive(c)
        self.labs = np.array([c["lab"] for c in colors])
        self.saved = {c["id"]: c["hex"] for c in colors}
        self.saved_fingerprint = self.fingerprint
        self._rgb = None
        self._tree = None

    @staticmethod
    def _derive(c: dict) -> None:
        """hex, Lab and LCh from the slot's rgb."""
        c["rgb"] = [int(v) for v in c["rgb"]]
        c["hex"] = _hex(c["rgb"])
        lab = srgb_to_lab(np.array(c["rgb"], dtype=np.float64))
        c["lab"] = [round(float(v), 2) for v in lab]
        c["lch"] = [round(float(lab[0]), 1), round(float(np.hypot(lab[1], lab[2])), 1),
                    round(float(np.degrees(np.arctan2(lab[2], lab[1])) % 360), 1)]

    # --- what it is ----------------------------------------------------------------------------
    @property
    def is_default(self) -> bool:
        return self.path is not None and self.path.resolve() == vx2.DEFAULT_COLOURS.resolve()

    @property
    def title(self) -> str:
        if self.owner:
            return f"{self.owner} colours"
        if self.is_default:
            return "Default colours"
        return "New project's colours" if self.path is None else f"{self.path.name.removesuffix(SUFFIX)} colours"

    @property
    def fingerprint(self) -> bytes:
        return vx2.colour_fingerprint(self.colors)

    @property
    def modified(self) -> bool:
        """Slots changed since the table was opened or saved."""
        return self.fingerprint != self.saved_fingerprint

    def changed_slots(self) -> list[int]:
        return [c["id"] for c in self.colors if c["hex"] != self.saved[c["id"]]]

    @property
    def rgb(self) -> np.ndarray:
        """Slot -> sRGB, (256, 3) uint8, row 0 black (empty)."""
        if self._rgb is None:
            self._rgb = np.zeros((256, 3), dtype=np.uint8)
            for c in self.colors:
                self._rgb[c["id"]] = c["rgb"]
        return self._rgb

    # --- changing a slot ----------------------------------------------------------------------
    def set_rgb(self, slot: int, rgb) -> bool:
        """Give a slot a new colour; False if it already is that colour."""
        if self.read_only:
            raise ValueError(f"{self.title} cannot be changed here")
        c = self.by_id[int(slot)]
        rgb = [max(0, min(255, int(v))) for v in rgb]
        if rgb == c["rgb"]:
            return False
        c["rgb"] = rgb
        self._derive(c)
        self.labs[int(slot) - 1] = c["lab"]
        self._rgb = self._tree = None
        self.version += 1
        return True

    def set_hex(self, slot: int, hex_value: str) -> bool:
        text = hex_value.strip().lstrip("#")
        if len(text) == 3:
            text = "".join(ch * 2 for ch in text)
        if len(text) != 6 or any(ch not in "0123456789abcdefABCDEF" for ch in text):
            raise ValueError(f"not a colour: {hex_value!r} (give #rrggbb)")
        return self.set_rgb(slot, [int(text[i:i + 2], 16) for i in (0, 2, 4)])

    def revert(self, slot: int | None = None) -> bool:
        """A slot (or every slot) back to how it was last saved."""
        changed = False
        for s in [slot] if slot is not None else list(self.saved):
            changed |= self.set_hex(s, self.saved[s])
        return changed

    # --- looking up ---------------------------------------------------------------------------
    def nearest_slot(self, rgb) -> int:
        """Fast nearest slot (CIE76 in Lab), for many lookups (painting from a picture)."""
        if self._tree is None:
            from scipy.spatial import cKDTree
            self._tree = cKDTree(self.labs)
        return self.colors[int(self._tree.query(srgb_to_lab(np.asarray(rgb, dtype=np.float64)))[1])]["id"]

    def nearest(self, rgb, count: int = 5, skip: int | None = None) -> list[tuple[int, float]]:
        """(slot, CIEDE2000) of the closest slots to a colour, closest first (`skip` leaves one out)."""
        d = de2000(srgb_to_lab(np.array(rgb, dtype=np.float64))[None, :], self.labs)
        if skip is not None:
            d[int(skip) - 1] = np.inf
        order = np.argsort(d)[:count]
        return [(self.colors[i]["id"], round(float(d[i]), 2)) for i in order]

    def closest_other(self, slot: int) -> tuple[int, float]:
        """The slot most like this one, and how far (CIEDE2000)."""
        return self.nearest(self.by_id[int(slot)]["rgb"], 1, skip=slot)[0]

    def mapping_to(self, other: "ColourTable") -> np.ndarray:
        """A (256,) lookup taking this table's slots to the other's: the same slot where it is the same
        colour, else the nearest colour there (CIEDE2000). 0 stays 0."""
        lut = np.zeros(256, dtype=np.uint8)
        for c in self.colors:
            same = other.by_id.get(c["id"])
            if same is not None and same["rgb"] == c["rgb"]:
                lut[c["id"]] = c["id"]
            else:
                d = de2000(np.array(c["lab"])[None, :], other.labs)
                lut[c["id"]] = other.colors[int(np.argmin(d))]["id"]
        return lut

    # --- files ----------------------------------------------------------------------------------
    def copy(self, owner: str | None = None, path: Path | None = None) -> "ColourTable":
        """A table of one's own to change (a project's), starting as this one."""
        rows = [{k: c[k] for k in ("id", "rgb", "band", "name") if k in c} for c in self.colors]
        return ColourTable(copy.deepcopy(rows), path, owner)

    def save(self, path: Path | None = None) -> Path:
        """Write the table, one line per slot: id, hex, band, name (rgb and Lab follow from hex)."""
        if self.read_only:
            raise ValueError(f"{self.title} cannot be changed here")
        target = Path(path or self.path)
        lines = [json.dumps({"id": c["id"], "hex": c["hex"], "band": c.get("band", ""), "name": c.get("name", "")},
                            ensure_ascii=False) for c in self.colors]
        based = os.path.relpath(vx2.DEFAULT_COLOURS, target.parent).replace("\\", "/")
        text = ("{\n" f'  "format": "{FORMAT}", "version": 1,\n'
                f'  "note": "colour slots 1-{len(self.colors)} of this project; started as a copy of {based}",\n'
                '  "colors": [\n    ' + ",\n    ".join(lines) + "\n  ]\n}\n")
        target.write_text(text, encoding="utf-8")
        self.path = target
        self.saved = {c["id"]: c["hex"] for c in self.colors}
        self.saved_fingerprint = self.fingerprint
        return target


# --- display orders: how the Colours dock lays the slots out; slot numbers never change -------------------
ORDERS = ("Table", "Hue", "Lightness", "Chroma", "Similar")
GREY = 8.0  # LCh chroma below which a colour counts as grey (first in the hue order)
HUE_BAND = 30.0  # degrees of hue per band in the hue order, each band dark to light
LIGHTNESS_STEP = 10.0  # L* per step in the lightness order
CHROMA_STEP = 15.0  # C* per step in the chroma order


def display_order(table: ColourTable, order: str = "Table") -> list[int]:
    """The table's slots in a display order: Table (slot order: the table's own ramps), Hue (greys, then
    bands of hue, each dark to light), Lightness (L*), Chroma (C*, greys first) or Similar (a chain from
    black, each next slot the nearest of those left, so neighbours look alike). Lightness and Chroma go
    in steps (of L* or C*), each step round the hues, so a row reads as one lightness or vividness."""
    slots = [c["id"] for c in table.colors]
    lch = {c["id"]: c["lch"] for c in table.colors}
    if order == "Table":
        return slots
    if order == "Hue":
        def key(s):
            L, C, h = lch[s]
            return (0, 0, L) if C < GREY else (1, int(h // HUE_BAND), L)
        return sorted(slots, key=key)
    if order == "Lightness":  # steps of L*, each grey first, then round the hues
        return sorted(slots, key=lambda s: (int(lch[s][0] // LIGHTNESS_STEP), lch[s][1] >= GREY,
                                            lch[s][2] if lch[s][1] >= GREY else lch[s][0]))
    if order == "Chroma":  # greys, then steps from muted to vivid, each round the hues
        return sorted(slots, key=lambda s: (0, 0, lch[s][0]) if lch[s][1] < GREY
                      else (1, int(lch[s][1] // CHROMA_STEP), lch[s][2]))
    if order == "Similar":
        labs = table.labs
        left = list(range(len(slots)))
        chain = [min(left, key=lambda i: labs[i][0])]  # the darkest first
        left.remove(chain[0])
        while left:
            d = de2000(labs[chain[-1]][None, :], labs[left])
            chain.append(left.pop(int(np.argmin(d))))
        return [slots[i] for i in chain]
    raise ValueError(f"order is one of {', '.join(ORDERS)}")


_DEFAULT: ColourTable | None = None


def default_table() -> ColourTable:
    """palette/colors.json, read-only (one object for the session)."""
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = ColourTable(vx2.load_colours(vx2.DEFAULT_COLOURS), vx2.DEFAULT_COLOURS, read_only=True)
    return _DEFAULT


def load_table(path: Path, owner: str | None = None, read_only: bool = False) -> ColourTable:
    path = Path(path)
    if path.resolve() == vx2.DEFAULT_COLOURS.resolve():
        return default_table()
    owner = owner or path.name.removesuffix(SUFFIX)
    return ColourTable(vx2.load_colours(path), path, owner, read_only)


def table_for(fingerprint: bytes, folders=()) -> ColourTable | None:
    """The table a file was made with, found by its fingerprint (read-only: only its project changes it)."""
    path = vx2.find_colours(fingerprint, folders)
    return None if path is None else load_table(path, read_only=True)
