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
# Fuzz (group "fuzz") is a soft pile of fibres: opaque in its body, its edge soft and broken. A ray that
# enters meets a fibre after a free flight; the fibres thin near the face it came in by and reach their
# density (voxels travelled before a fibre, as for gas) sss voxels below it (its reach), broken into tufts
# as far as roughness says (its clump: 0 an even pile, 1 tufts with gaps). The pile is solid within a voxel
# of the face (the renderer caps the reach to fit), so it thins the same way below a face and beside one. Paint a layer or two over a
# hard core for a soft surface (the core shows through where it is thin); a lone fuzz voxel is a tuft.
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
    # Graded fog: the mist's look at more densities, from a faint haze over a whole diorama to a fog
    # that hides what is a few voxels in.
    (39, "faint haze", "gas", 1.0, 0, 0, 1.0, 0, 64, 0, 0, 0, 0.6, "yes",
     "the faintest fog: distance and depth over a whole diorama; light scatters once per 64 voxels"),
    (40, "haze", "gas", 1.0, 0, 0, 1.0, 0, 32, 0, 0, 0, 0.6, "yes",
     "a light haze: morning air, a valley's depth"),
    (41, "light mist", "gas", 1.0, 0, 0, 1.0, 0, 24, 0, 0, 0, 0.6, "yes",
     "between haze and mist: a veil over water, low clouds far off"),
    (42, "fog", "gas", 1.0, 0, 0, 1.0, 0, 8, 0, 0, 0, 0.6, "yes",
     "a fog the scene fades into within a few dozen voxels: moors, graveyards"),
    (43, "thick fog", "gas", 1.0, 0, 0, 1.0, 0, 4, 0, 0, 0, 0.5, "yes",
     "fog that hides what is more than a dozen voxels in: a wall of cloud, a fogbank"),
    # Fuzz: soft piles of fibres in the voxel colour (density, sss as the reach, roughness as the clump).
    (44, "moss", "fuzz", 0.8, 0, 0, 1.5, 0, 0.5, 0.75, 0, 0.3, 0, "yes",
     "a soft, clumpy cushion: moss on stones and roofs, lichen, grass seen from afar"),
    (45, "felt", "fuzz", 0.15, 0, 0, 1.5, 0, 0.3, 0.8, 0, 1, 0, "yes",
     "a short, even nap: felt hats, wool cloth, velvet, a soft toy"),
    (46, "fur", "fuzz", 0.7, 0, 0, 1.5, 0, 0.4, 0.75, 0, 0.25, 0, "yes",
     "a deep pile with tufts: animal fur, a fur collar, a beard; paint it over a dark core for dark roots"),
    (47, "wool", "fuzz", 0.5, 0, 0, 1.5, 0, 0.35, 0.8, 0, 0.2, 0, "yes",
     "thick, matte and springy: sheep, yarn, a woolly hat, clouds as a toy"),
    (48, "dust", "fuzz", 0.4, 0, 0, 1.5, 0, 0.3, 0.4, 0, 0.3, 0, "yes",
     "a thin, soft film: dust on old things, ash, pollen; one layer over a hard surface"),
    # In between and beyond (30 October 2026): a ladder per family, so a surface can be one step glossier,
    # a glow one step brighter, a fog one step thinner, a pile one step shorter.
    # Cloth and glaze.
    (49, "cloth", "rough", 0.9, 0, 0, 1.5, 0, 4, 0, 0, 0.5, 0, "yes",
     "woven cloth, canvas, a cloak: matte with a soft brightening at grazing angles"),
    (50, "velvet", "rough", 1.0, 0, 0, 1.5, 0, 4, 0, 0, 1, 0, "yes",
     "velvet, peach skin, suede: dark head-on, bright where light grazes"),
    (51, "silk", "glossy", 0.4, 0, 0, 1.5, 0, 4, 0, 0, 0.6, 0, "yes", "silk, satin ribbons, a sheen on fine cloth"),
    (52, "eggshell", "glossy", 0.7, 0, 0, 1.5, 0, 4, 0, 0, 0, 0, "yes",
     "between matte and satin: painted walls, bone, unglazed clay"),
    (53, "ceramic", "glossy", 0.12, 0, 0, 1.5, 0, 4, 0, 0, 0, 0, "yes", "glazed pottery, tiles, enamel"),
    # Metals in between, and metals in part.
    (54, "satin metal", "metal", 0.12, 1, 0, 1.5, 0, 4, 0, 0, 0, 0, "yes",
     "between mirror and polished: silverware, a blade's flat"),
    (55, "brushed metal", "metal", 0.3, 1, 0, 1.5, 0, 4, 0, 0, 0, 0, "yes", "brushed steel, pewter, a helmet"),
    (56, "dull metal", "metal", 0.8, 1, 0, 1.5, 0, 4, 0, 0, 0, 0, "yes",
     "cast iron, lead, old bronze: a metal that hardly shines"),
    (57, "metallic paint", "metal", 0.3, 0.5, 0, 1.5, 0, 4, 0, 0, 0, 0, "yes",
     "half metal: car paint, a beetle's shell, painted armour"),
    (58, "pearl", "metal", 0.25, 0.3, 0, 1.5, 0, 4, 0, 0, 0.4, 0, "yes",
     "mother-of-pearl, a pearl, nacre: a little metal with a soft sheen"),
    # Glows from very faint to blinding, and more moving ones.
    (59, "very faint glow", "emissive", 1.0, 0, 0.15, 1.5, 0, 4, 0, 0, 0, 0, "yes",
     "just visible in the dark: phosphorescence, a cat's eyes, distant windows"),
    (60, "dim glow", "emissive", 1.0, 0, 0.7, 1.5, 0, 4, 0, 0, 0, 0, "yes", "between faint glow and glow: coals, lit paper"),
    (61, "bright glow", "emissive", 1.0, 0, 2.5, 1.5, 0, 4, 0, 0, 0, 0, "yes",
     "between glow and light: a lantern's glass, a crystal lighting its corner"),
    (62, "strong light", "emissive", 1.0, 0, 10, 1.5, 0, 4, 0, 0, 0, 0, "yes",
     "a light that fills a room: a lamp, a window at night seen from inside"),
    (63, "blinding light", "emissive", 1.0, 0, 24, 1.5, 0, 4, 0, 0, 0, 0, "yes",
     "a sun on the table: lights a whole diorama, burns out to white"),
    (64, "embers", "emissive", 1.0, 0, 0.6, 1.5, 0, 4, 0, 0, 0, 0, "yes",
     "a slow, low flicker: dying coals, a cigarette, glowing ash"),
    (65, "candle", "emissive", 1.0, 0, 1.2, 1.5, 0, 4, 0, 0, 0, 0, "yes", "a small, warm flicker: candle flames, oil lamps"),
    (66, "torch", "emissive", 1.0, 0, 4, 1.5, 0, 4, 0, 0, 0, 0, "yes",
     "a strong flicker that lights its surroundings: torches, a campfire's heart"),
    (67, "slow pulse", "emissive", 1.0, 0, 0.6, 1.5, 0, 4, 0, 0, 0, 0, "yes", "a faint, slow breathing: sleeping runes"),
    (68, "bright pulse", "emissive", 1.0, 0, 4, 1.5, 0, 4, 0, 0, 0, 0, "yes", "a strong beat: a beacon, a warning light"),
    # Glass at more densities and indices, and cloudy ones.
    (69, "pale glass", "transparent", 0.0, 0, 0, 1.5, 0.96, 16, 0, 0, 0, 0, "yes",
     "glass that barely takes its colour: window panes, clear bottles"),
    (70, "tinted glass", "transparent", 0.0, 0, 0, 1.5, 0.96, 2.5, 0, 0, 0, 0, "yes",
     "glass deep in its colour within a few voxels: stained glass, wine, potions"),
    (71, "deep glass", "transparent", 0.0, 0, 0, 1.5, 0.96, 0.25, 0, 0, 0, 0, "yes",
     "nearly opaque glass that glows where it is thin: obsidian, dark gems, ink"),
    (72, "crystal", "transparent", 0.0, 0, 0, 2.0, 0.96, 4, 0, 0, 0, 0, "yes",
     "lead crystal, quartz points: bends and sparkles more than glass"),
    (73, "diamond", "transparent", 0.0, 0, 0, 2.42, 0.97, 8, 0, 0, 0, 0, "yes",
     "the strongest sparkle: diamonds, cut gems"),
    (74, "smoked glass", "transparent", 0.15, 0, 0, 1.5, 0.7, 6, 0, 0, 0, 0, "yes",
     "glass that lets less through and reflects more: sunglasses, a dark visor"),
    (75, "milky glass", "transparent", 0.2, 0, 0, 1.5, 0.6, 4, 1, 0.6, 0, 0, "yes",
     "cloudy glass that scatters inside: opal, milk glass, a frosted lampshade"),
    (76, "murky water", "transparent", 0.05, 0, 0, 1.33, 0.6, 1.5, 1.5, 0.5, 0, 0, "yes",
     "pond and swamp water: clear at the surface, cloudy deeper in"),
    # More things light scatters under.
    (77, "wax", "subsurface", 0.35, 0, 0, 1.45, 0, 4, 1.5, 1, 0, 0, "yes", "candles, soap, cheese: soft light deep inside"),
    (78, "marble", "subsurface", 0.15, 0, 0, 1.5, 0, 4, 1, 0.8, 0, 0, "yes",
     "polished marble, alabaster: glossy over a soft glow"),
    (79, "porcelain", "subsurface", 0.1, 0, 0, 1.5, 0, 4, 0.3, 0.7, 0, 0, "yes", "porcelain, teeth, eggshell china"),
    (80, "gummy", "subsurface", 0.1, 0, 0, 1.45, 0.3, 2, 2.5, 1, 0, 0, "yes",
     "jelly, slime, gummy sweets: glossy, see-through at the edges, glowing inside"),
    (81, "flesh", "subsurface", 0.5, 0, 0, 1.4, 0, 4, 1.5, 1, 0, 0, "yes",
     "deeper than skin: meat, fruit flesh, petals lit from behind"),
    # Fog in between and beyond.
    (82, "dense fog", "gas", 1.0, 0, 0, 1.0, 0, 2, 0, 0, 0, 0.5, "yes",
     "a fog that swallows what is a few voxels in: a cloud you stand in"),
    (83, "heavy mist", "gas", 1.0, 0, 0, 1.0, 0, 12, 0, 0, 0, 0.6, "yes", "between fog and mist"),
    (84, "thin haze", "gas", 1.0, 0, 0, 1.0, 0, 48, 0, 0, 0, 0.6, "yes", "between haze and faint haze"),
    (85, "faintest haze", "gas", 1.0, 0, 0, 1.0, 0, 128, 0, 0, 0, 0.6, "yes",
     "air you only notice over a large scene: depth for a whole landscape"),
    # Smoke, steam and clouds at more densities.
    (86, "thin smoke", "gas", 1.0, 0, 0, 1.0, 0, 10, 0, 0, 0, 0.3, "yes", "wisps from a chimney, incense"),
    (87, "thick smoke", "gas", 1.0, 0, 0, 1.0, 0, 2, 0, 0, 0, 0.3, "yes", "black smoke from a fire, a smoke bomb"),
    (88, "dense smoke", "gas", 1.0, 0, 0, 1.0, 0, 1, 0, 0, 0, 0.3, "yes",
     "smoke you cannot see into: a burning building, a volcano's plume"),
    (89, "light steam", "gas", 1.0, 0, 0, 1.0, 0, 6, 0, 0, 0, 0.7, "yes", "breath on a cold day, a kettle, hot springs"),
    (90, "cloud", "gas", 1.0, 0, 0, 1.0, 0, 1.5, 0, 0, 0, 0.75, "yes",
     "white cumulus: bright on the sunny side, soft grey under it"),
    (91, "dust cloud", "gas", 1.0, 0, 0, 1.0, 0, 6, 0, 0, 0, 0.2, "yes", "dust kicked up, a sandstorm, flour in the air"),
    (92, "faint glowing gas", "gas", 1.0, 0, 0.4, 1.0, 0, 16, 0, 0, 0, 0, "yes",
     "a faint glow hanging in the air: will-o'-the-wisps, a haunted fog"),
    (93, "bright glowing gas", "gas", 1.0, 0, 2.5, 1.0, 0, 4, 0, 0, 0, 0, "yes",
     "a strong glowing cloud that lights the scene: a spell's blast, plasma"),
    (94, "magic mist", "gas", 1.0, 0, 0.6, 1.0, 0, 16, 0, 0, 0, 0.4, "yes",
     "a mist with bands of light rising through it: enchanted ground, a portal's haze"),
    # Fuzz: more piles, from a velvet nap to shaggy fur, and airy ones.
    (95, "velvet nap", "fuzz", 0.0, 0, 0, 1.5, 0, 0.2, 0.25, 0, 1, 0, "yes",
     "the shortest pile: velvet, a peach, moleskin; a soft edge on a hard shape"),
    (96, "short fur", "fuzz", 0.5, 0, 0, 1.5, 0, 0.3, 0.4, 0, 0.3, 0, "yes", "a short coat: a horse, a mouse, a deer"),
    (97, "shaggy fur", "fuzz", 1.0, 0, 0, 1.5, 0, 0.5, 0.75, 0, 0.2, 0, "yes",
     "long tufts with gaps: a bear, a yak, a shaggy dog"),
    (98, "plush", "fuzz", 0.3, 0, 0, 1.5, 0, 0.25, 0.6, 0, 0.5, 0, "yes", "a dense, soft pile: a teddy bear, a plush cushion"),
    (99, "carpet", "fuzz", 0.2, 0, 0, 1.5, 0, 0.3, 0.5, 0, 0.1, 0, "yes", "a rug, a carpet, a doormat"),
    (100, "cotton", "fuzz", 0.4, 0, 0, 1.5, 0, 0.6, 0.8, 0, 0.1, 0, "yes",
     "a soft, airy pile: cotton wool, a cotton plant, dandelion clocks"),
    (101, "fluff", "fuzz", 0.6, 0, 0, 1.5, 0, 1.2, 0.8, 0, 0.2, 0, "yes",
     "see-through fluff: down feathers, thistledown, spider silk, a fuzzy halo"),
    (102, "lichen", "fuzz", 1.0, 0, 0, 1.5, 0, 0.8, 0.4, 0, 0.1, 0, "yes",
     "sparse, crusty patches: lichen on stone, mould, a shadow of moss"),
    (103, "grass", "fuzz", 1.0, 0, 0, 1.5, 0, 0.6, 0.75, 0, 0.1, 0, "yes",
     "a lawn or meadow seen from afar: blades in tufts, the ground showing between"),
    (104, "hay", "fuzz", 0.9, 0, 0, 1.5, 0, 0.6, 0.75, 0, 0.4, 0, "yes", "straw, hay bales, a thatched roof, a broom"),
    (105, "thin dust", "fuzz", 0.3, 0, 0, 1.5, 0, 0.8, 0.3, 0, 0.3, 0, "yes",
     "a faint film: the first dust on a shelf, frost, flour on a table"),
]
LIGHTS = {28: "fire", 29: "pulse", 30: "flash", 31: "sickly", 32: "unnatural", 33: "arcane", 38: "fire", 64: "fire",
          65: "fire", 66: "fire", 67: "pulse", 68: "pulse", 94: "arcane"}
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
