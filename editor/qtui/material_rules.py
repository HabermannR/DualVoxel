"""How the renderer reads a material of the two-byte table, field by field.

A mirror of engine/voxel_renderer.py style_of() and the renderer's material
code (its voxel_material() and principled shading path). Since the principled path (as Blender's
Principled BSDF) every field is an amount that blends with the others: the
voxel colour is the base, metal goes over the rest, transmission takes its share
of the non-metal light (density sets how deep the colour builds inside),
subsurface takes its share of what remains (sss sets how deep it scatters),
sheen softens the base, emission adds light. Only a few cases do not read a
field: the fixed water, staff field and mirror; a full metal's ior; density
without transmission; sss without subsurface. A plain matte material (rough,
nothing else) is drawn by the fast matte path, the same picture. Gas (group
"gas", kind 8) is a volume instead: it reads only density, anisotropy, emission
and its light. Keep this in
step with those functions; palette/build_field_sweep.py renders every field.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "engine"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "palette"))
from voxel_renderer import style_of  # noqa: E402
import material_source  # noqa: E402

MAX_EMISSION = 32.0  # voxel_material() clamps emission to this
MATTE_LIMIT = 0.85   # from this roughness up a non-metal no longer reflects (plain matte)

USED, SWITCH, IGNORED = "used", "switch", "ignored"
FIELDS = ("roughness", "metal", "emission", "transmission", "density", "subsurface", "sss", "sheen", "ior", "anisotropy")
FIXED_STYLES = {2: "staff field (kind 4)", 3: "water (kind 3)", 6: "mirror metal (kind 1)"}
DEFAULTS = {"density": 4, "subsurface": 0, "sheen": 0, "anisotropy": 0}


def value(m: dict, field: str) -> float:
    return float(m.get(field, DEFAULTS.get(field, 0)) or 0)


def reading(m: dict) -> tuple[str, dict[str, tuple[str, str]]]:
    """(what the renderer draws, {field: (used | switch | ignored, why)})."""
    style = style_of(m)
    if style in FIXED_STYLES:
        why = {2: "the staff field is a fixed effect, chosen by the name",
               3: "water is a fixed effect, chosen by the name",
               6: "a fixed mirror, chosen by the name"}[style]
        return FIXED_STYLES[style], {f: (IGNORED, why) for f in FIELDS}
    if m.get("group") == "gas":
        fields = {f: (IGNORED, "gas is a volume, not a surface") for f in FIELDS}
        fields["density"] = (USED, "the voxels light travels on average before it scatters: low is thick smoke")
        fields["anisotropy"] = (USED, "where scattered light goes: above 0 on forward (glows toward the sun), below 0 back")
        fields["emission"] = (USED, f"light given all through the gas in its colour (up to {MAX_EMISSION:g})")
        if m.get("light"):
            fields["emission"] = (USED, f"the strength of the '{m['light']}' light's moving glow through the gas")
        return "gas (kind 8): " + ("glowing " if value(m, "emission") > 0 else "") + "scattering volume", fields
    rough, metal, transmission = value(m, "roughness"), value(m, "metal"), value(m, "transmission")
    fields = {
        "roughness": (USED, f"the blur of every reflection; from {MATTE_LIMIT} up a non-metal no longer reflects"),
        "metal": (USED, "how much is metal, tinted by the colour, over everything else"),
        "emission": (USED, f"light added in the voxel colour (up to {MAX_EMISSION:g}), whatever else it is"),
        "transmission": (USED, "the share of the non-metal light that enters, as through glass"),
        "density": (USED, "the voxels light travels inside before it has taken the colour once"),
        "subsurface": (USED, "the share of the remaining light that scatters under the surface"),
        "sss": (USED, "how deep the subsurface light travels: the mean free path in voxels"),
        "sheen": (USED, "a soft brightening where light grazes or comes from behind: cloth, moss, dust"),
        "ior": (USED, "the non-metal reflection (1.5: 4 % head-on, 1.33: 2 %) and the refraction of glass"),
        "anisotropy": (IGNORED, "read by gas only (group gas)"),
    }
    if m.get("light"):
        fields["emission"] = (USED, f"the strength of the '{m['light']}' light's moving glow (up to {MAX_EMISSION:g})")
    if metal >= 1:
        for f in ("transmission", "density", "subsurface", "sss", "sheen", "ior"):
            fields[f] = (IGNORED, "a full metal is only its metal: lower metal to let the rest show")
    if transmission <= 0:
        fields["density"] = (IGNORED, "counts once transmission is above 0")
    if value(m, "subsurface") <= 0:
        fields["sss"] = (IGNORED, "counts once subsurface is above 0")
    if rough >= MATTE_LIMIT and metal <= 0 and transmission <= 0:
        fields["ior"] = (IGNORED, f"a non-metal from roughness {MATTE_LIMIT} up does not reflect")
    extras = any(value(m, f) > 0 for f in ("metal", "emission", "transmission", "subsurface", "sheen"))
    if rough >= MATTE_LIMIT and not extras and not m.get("light"):
        return "plain matte (kind 0, the same picture as the blend)", fields
    parts = [name for name, f in (("metal", "metal"), ("glass", "transmission"), ("subsurface", "subsurface"),
                                  ("sheen", "sheen"), ("glow", "emission")) if value(m, f) > 0]
    return "principled blend (kind 7)" + (f": {', '.join(parts)}" if parts else ""), fields


def table_row(m: dict) -> str:
    """The material as a row of palette/build_materials.py's MATERIALS (light goes in its LIGHTS)."""
    return material_source.row_text(m, indent="").strip()
