r"""The material byte: a first, deliberately small table (byte 2 of each voxel; 0 = default matte).

    .venv\Scripts\python.exe palette\build_materials.py

Writes palette/materials.json and palette/materials.html (an offline table; no
shading here: previews come from the path tracer). A
material says how a surface behaves, never which colour it has: emissive glows
in the voxel's colour, water and glass are tinted by it, subsurface scatters it.
The "engine" field says what the path tracer draws: "yes", "partly" (an approximation) or "new".
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent

# Every field blends with the others, as in Blender's Principled BSDF (the renderer reads
# them in one shading path): roughness 0..1, metal 0..1 (a metal over the rest), emission (relative
# radiance, added to anything), ior (reflectance and refraction), transmission 0..1 (the share of the
# non-metal light that enters, as through glass), density (voxels light travels inside before it has
# taken the voxel colour once), sss (the subsurface depth: a mean free path in voxels), subsurface
# 0..1 (the share of the remaining diffuse light that scatters under the surface), sheen 0..1 (a soft,
# fuzzy brightening at grazing angles: cloth, moss, dust) and anisotropy -0.95..0.95 (gas only).
# Gas (group "gas") is a volume, not a surface: light crosses its boundary unbent and scatters
# inside, once per density voxels on average, a thick body of it looking the voxel colour; anisotropy above 0 sends that
# light on forward (mist and steam glow toward the sun), below 0 back. Emission glows all through it,
# with a magic light's pattern when it has one (flames).
MATERIALS = [
    # id, name, group, roughness, metal, emission, ior, transmission, density, sss, subsurface, sheen,
    # anisotropy, engine, note
    # Ids never change meaning; new materials go at the end. Patterns (rust patches, scratches,
    # worn spots) are painted voxel by voxel with these materials, never textured in the shader.
    (0, "matte", "rough", 1.0, 0, 0, 1.5, 0, 4, 0, 0, 0, 0, "yes", "the default (kind 0)"),
    (1, "rough stone", "rough", 0.9, 0, 0, 1.5, 0, 4, 0, 0, 0, 0, "yes", "draws as matte (above roughness 0.85)"),
    (2, "dusty", "rough", 1.0, 0, 0, 1.5, 0, 4, 0, 0, 0, 0, "yes", "draws as matte"),
    (3, "satin", "glossy", 0.55, 0, 0, 1.5, 0, 4, 0, 0, 0, 0, "yes", "soft sheen: cloth, dry wood (kind 7)"),
    (4, "glossy", "glossy", 0.25, 0, 0, 1.5, 0, 4, 0, 0, 0, 0, "yes", "varnish, wet stone, glazed pottery (kind 7)"),
    (5, "polished", "glossy", 0.08, 0, 0, 1.5, 0, 4, 0, 0, 0, 0, "yes", "lacquer, polished stone (kind 7)"),
    (6, "rough metal", "metal", 0.5, 1, 0, 1.5, 0, 4, 0, 0, 0, 0, "yes", "iron, armour (kind 8)"),
    (7, "polished metal", "metal", 0.2, 1, 0, 1.5, 0, 4, 0, 0, 0, 0, "yes", "goblin axe, gold trim (kind 8)"),
    (8, "mirror metal", "metal", 0.02, 1, 0, 1.5, 0, 4, 0, 0, 0, 0, "yes",
     "chrome: a perfect mirror tinted by the colour (kind 1)"),
    (9, "faint glow", "emissive", 1.0, 0, 0.35, 1.5, 0, 4, 0, 0, 0, 0, "yes", "embers, runes, mushrooms (kind 9)"),
    (10, "glow", "emissive", 1.0, 0, 1.2, 1.5, 0, 4, 0, 0, 0, 0, "yes", "eyes, gems (kind 9)"),
    (11, "light", "emissive", 1.0, 0, 5, 1.5, 0, 4, 0, 0, 0, 0, "yes",
     "a light source that lights its surroundings (kind 9)"),
    (12, "water", "transparent", 0.04, 0, 0, 1.33, 0.92, 4, 0, 0, 0, 0, "partly",
     "the river's glossy opaque water (kind 3)"),
    (13, "glass", "transparent", 0.0, 0, 0, 1.5, 0.96, 4, 0, 0, 0, 0, "yes",
     "coloured by its voxel colour: bottle glass, ruby, amber (kind 10)"),
    (14, "ice", "transparent", 0.3, 0, 0, 1.31, 0.75, 4, 1.5, 1, 0, 0, "partly",
     "translucent, scattering light inside (kind 6); no gloss"),
    (15, "skin", "subsurface", 0.45, 0, 0, 1.4, 0, 4, 0.8, 1, 0, 0, "yes", "skin, wax, flesh (kind 6)"),
    (16, "leaf", "subsurface", 0.6, 0, 0, 1.4, 0, 4, 0.4, 1, 0, 0, "partly",
     "subsurface (kind 6); thin sheets not modelled"),
    (17, "jade", "subsurface", 0.2, 0, 0, 1.6, 0, 4, 2.5, 1, 0, 0, "partly",
     "subsurface (kind 6): light travels 2.5 voxels deep; no gloss"),
    (18, "staff field", "special", 1.0, 0, 6, 1.5, 0, 4, 0, 0, 0, 0, "yes",
     "the alchemist's gem, wandering emission lobes (kind 4, energy_light.glsl)"),
    (19, "leather", "glossy", 0.6, 0, 0, 1.5, 0, 4, 0, 0, 0, 0, "yes", "cured leather: a soft, low sheen (kind 7)"),
    (20, "worn leather", "glossy", 0.8, 0, 0, 1.5, 0, 4, 0, 0, 0, 0, "yes",
     "scuffed leather; paint it on edges and creases (kind 7)"),
    (21, "rust", "rough", 0.95, 0, 0, 1.5, 0, 4, 0, 0, 0, 0, "yes",
     "corrosion, not metal: rust colours on these voxels, scattered into worn metal (matte)"),
    (22, "worn metal", "metal", 0.65, 1, 0, 1.5, 0, 4, 0, 0, 0, 0, "yes",
     "scuffed iron, old tools, dull gold (kind 8)"),
    (23, "scratched metal", "metal", 0.4, 1, 0, 1.5, 0, 4, 0, 0, 0, 0, "yes",
     "a blurred metal; paint lines of polished metal into it for scratches (kind 8)"),
    (24, "oiled wood", "glossy", 0.5, 0, 0, 1.5, 0, 4, 0, 0, 0, 0, "yes", "handles, tabletops, staffs (kind 7)"),
    (25, "wet", "glossy", 0.15, 0, 0, 1.33, 0, 4, 0, 0, 0, 0, "yes", "puddles, wet stone, slime (kind 7)"),
    (26, "plastic", "glossy", 0.35, 0, 0, 1.5, 0, 4, 0, 0, 0, 0, "yes", "plastic, enamel, painted toys (kind 7)"),
    (27, "frosted glass", "transparent", 0.35, 0, 0, 1.5, 0.9, 4, 0, 0, 0, 0, "yes",
     "milky coloured glass, sea glass, quartz (kind 10)"),
    # Magic lights: emissive in the voxel colour, moving with the renderer's clock (presentation
    # only; native/gpu/voxel_material.glsl voxel_light). "light" names the movement.
    (28, "fire glow", "emissive", 1.0, 0, 2, 1.5, 0, 4, 0, 0, 0, 0, "yes",
     "flickering flames, rising voxel by voxel, yellower when brighter: torches, braziers"),
    (29, "pulse glow", "emissive", 1.0, 0, 1.5, 1.5, 0, 4, 0, 0, 0, 0, "yes",
     "slow, even breathing: runes at rest, sleeping crystals"),
    (30, "flash", "emissive", 1.0, 0, 3, 1.5, 0, 4, 0, 0, 0, 0, "yes",
     "dim, then white-hot flashes at uneven beats: lightning, a spell going off"),
    (31, "sickly glow", "emissive", 1.0, 0, 1, 1.5, 0, 4, 0, 0, 0, 0, "yes",
     "a weak, uneven throb with gasping dips, pulled to bile green: rot, poison, plague"),
    (32, "unnatural glow", "emissive", 1.0, 0, 1.5, 1.5, 0, 4, 0, 0, 0, 0, "yes",
     "the hue drifts through every colour, voxel by voxel: wrong, otherworldly magic"),
    (33, "arcane glow", "emissive", 1.0, 0, 2, 1.5, 0, 4, 0, 0, 0, 0, "yes",
     "bands of light rising through the voxels: charged runes, spell circles"),
    (34, "smoke", "gas", 1.0, 0, 0, 1.0, 0, 4, 0, 0, 0, 0.3, "yes",
     "a volume, not a surface: grey or black smoke, dust clouds; light scatters once per 4 voxels"),
    (35, "steam", "gas", 1.0, 0, 0, 1.0, 0, 2, 0, 0, 0, 0.7, "yes",
     "white steam and clouds, brightest toward the sun"),
    (36, "mist", "gas", 1.0, 0, 0, 1.0, 0, 16, 0, 0, 0, 0.6, "yes",
     "thin haze and ground fog: a wide, low layer the scene shows through"),
    (37, "glowing gas", "gas", 1.0, 0, 1, 1.0, 0, 6, 0, 0, 0, 0, "yes",
     "poison clouds, magic vapour: glows in its colour all through and lights what is near"),
    (38, "flame", "gas", 1.0, 0, 3, 1.0, 0, 3, 0, 0, 0, 0.2, "yes",
     "flames as a glowing gas, flickering and rising: torches, braziers; smoke above them"),
]
LIGHTS = {28: "fire", 29: "pulse", 30: "flash", 31: "sickly", 32: "unnatural", 33: "arcane", 38: "fire"}
FIELDS = ["id", "name", "group", "roughness", "metal", "emission", "ior", "transmission", "density", "sss", "subsurface", "sheen",
          "anisotropy", "engine", "note"]


def main() -> None:
    table = [dict(zip(FIELDS, row)) | {"light": LIGHTS.get(row[0], "")} for row in MATERIALS]
    ids = [m["id"] for m in table]
    assert ids == list(range(len(ids))), "material ids must be 0..n-1 without gaps"
    (HERE / "materials.json").write_text(json.dumps({"materials": table}, indent=1), encoding="utf-8")
    page = HTML.replace("__DATA__", json.dumps({"materials": table}))
    (HERE / "materials.html").write_text(page, encoding="utf-8")
    counts = {e: sum(m["engine"] == e for m in table) for e in ("yes", "partly", "new")}
    print(f"{len(table)} materials: {counts}")


HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Voxel Materials</title>
<style>
:root{--bg:#f4f2ee;--panel:#fff;--ink:#1d1d1f;--muted:#6b6b70;--line:#d8d5cf;--yes:#2f7d4f;--partly:#a0711c;--new:#8a3d6b}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#17171a;--panel:#212125;--ink:#ececef;--muted:#9a9aa2;--line:#34343a;--yes:#6fcf97;--partly:#e2b45a;--new:#d98cbc}}
:root[data-theme="dark"]{--bg:#17171a;--panel:#212125;--ink:#ececef;--muted:#9a9aa2;--line:#34343a;--yes:#6fcf97;--partly:#e2b45a;--new:#d98cbc}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 system-ui,sans-serif}
main{max-width:1100px;margin:0 auto;padding:20px 16px 60px}h1{font-size:22px;margin:0 0 4px}
.muted{color:var(--muted)}button{font:inherit;border:1px solid var(--line);background:var(--panel);color:var(--ink);border-radius:6px;padding:4px 10px;cursor:pointer}
.scroll{overflow-x:auto;margin-top:14px;background:var(--panel);border:1px solid var(--line);border-radius:8px}
table{border-collapse:collapse;width:100%;font-size:13px}th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);white-space:nowrap}
td.note{white-space:normal;color:var(--muted);min-width:220px}tr.group td{background:transparent;font-weight:600;text-transform:capitalize;padding-top:14px}
.num{text-align:right;font-variant-numeric:tabular-nums}.tag{font-size:11px;border-radius:999px;padding:1px 8px;border:1px solid currentColor}
.yes{color:var(--yes)}.partly{color:var(--partly)}.new{color:var(--new)}
</style></head><body><main>
<h1>Voxel materials</h1>
<div class="muted">Byte 2 of each voxel: how a surface behaves, never its colour (emissive glows in the voxel's colour, water and glass are tinted by it, subsurface scatters it). A first small set; material 0 is the default matte. Previews come from the path tracer; this page is only the table. Engine: <span class="tag yes">yes</span> an existing kind, <span class="tag partly">partly</span>, <span class="tag new">new</span>.</div>
<p><button id="theme">theme</button></p>
<div class="scroll"><table id="t"></table></div>
</main><script>
const D=__DATA__;
const rows=['<tr><th class="num">id</th><th>name</th><th class="num">roughness</th><th class="num">metal</th><th class="num">emission</th><th class="num">IOR</th><th class="num">transmission</th><th class="num">scattering</th><th>engine</th><th>note</th></tr>'];
let group=null;
for(const m of D.materials){
  if(m.group!==group){group=m.group;rows.push('<tr class="group"><td colspan="10">'+group+'</td></tr>')}
  const show=(v,f)=>v?f(v):'';
  rows.push('<tr><td class="num">'+m.id+'</td><td>'+m.name+'</td><td class="num">'+m.roughness+'</td><td class="num">'+show(m.metal,v=>v)+'</td><td class="num">'+show(m.emission,v=>v)+
    '</td><td class="num">'+(m.transmission?m.ior:'')+'</td><td class="num">'+show(m.transmission,v=>v)+'</td><td class="num">'+show(m.sss,v=>v+' vox')+
    '</td><td><span class="tag '+m.engine+'">'+m.engine+'</span></td><td class="note">'+m.note+'</td></tr>');
}
document.getElementById('t').innerHTML=rows.join('');
document.getElementById('theme').onclick=()=>{const r=document.documentElement;r.dataset.theme=r.dataset.theme==='dark'?'light':'dark'};
</script></body></html>
"""


if __name__ == "__main__":
    main()
