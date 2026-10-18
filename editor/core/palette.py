import numpy as np


def hex_to_rgb(hex_str):
    hex_str = hex_str.lstrip('#')
    return [int(hex_str[i:i + 2], 16) for i in (0, 2, 4)]


def lerp_color(c1, c2, t):
    return [int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3)]


def create_poly_ramp(keyframes_hex, total_steps):
    if total_steps <= 1: return [hex_to_rgb(keyframes_hex[0])]
    keyframes = [hex_to_rgb(k) for k in keyframes_hex]
    output = []
    num_segments = len(keyframes) - 1
    for i in range(total_steps):
        t_global = i / (total_steps - 1)
        pos = t_global * num_segments
        idx = int(pos)
        t_local = pos - idx
        if idx >= num_segments: idx = num_segments - 1; t_local = 1.0
        col = lerp_color(keyframes[idx], keyframes[idx + 1], t_local)
        col.append(255)
        output.append(col)
    return output


def generate_game_palette():
    full_palette = np.zeros((256, 4), dtype=np.uint8)
    full_palette[0] = [0, 0, 0, 0]
    base_108 = []
    base_108 += create_poly_ramp(["#18141d", "#4b5261", "#828d9c", "#c3cdd9"], 8)
    base_108 += create_poly_ramp(["#26211f", "#6e665f", "#d1ccc7"], 6)
    base_108 += create_poly_ramp(["#120d0b", "#2b2918", "#4f4b30", "#756c45"], 8)
    base_108 += create_poly_ramp(["#210e08", "#5c2a18", "#8f4426", "#c78665"], 6)
    base_108 += create_poly_ramp(["#3d2d22", "#8f6746", "#dcbfaa", "#fff0d4"], 6)
    base_108 += create_poly_ramp(["#210611", "#7a091c", "#d12424", "#ff8c8c"], 8)
    base_108 += create_poly_ramp(["#1f0906", "#5e1d0f", "#b55224"], 6)
    base_108 += create_poly_ramp(["#06170e", "#134022", "#2d8544", "#6bd484"], 8)
    base_108 += create_poly_ramp(["#1a2106", "#566e0b", "#9ec71a", "#eaff5e"], 6)
    base_108 += create_poly_ramp(["#050817", "#112a52", "#266fc4", "#59bfff"], 8)
    base_108 += create_poly_ramp(["#062124", "#155e63", "#3ebdb8", "#a6fffa"], 6)
    base_108 += create_poly_ramp(["#4a0e04", "#cf4904", "#ffae00", "#fffa94"], 10)
    base_108 += create_poly_ramp(["#0e0a14", "#2a223d", "#514373", "#8976b5"], 8)
    base_108 += create_poly_ramp(["#260519", "#7d105b", "#d645ad", "#ffbdf0"], 6)
    breath = ["#e6ebf2", "#f2ebd4", "#ffe0e0", "#e3ffd6", "#d6faff", "#ffffe0", "#fbe0ff", "#ffffff"]
    for hex_c in breath: base_108.append(hex_to_rgb(hex_c) + [255])
    while len(base_108) < 108: base_108.append([255, 0, 255, 255])

    metals = []
    metals += create_poly_ramp(["#1a1c21", "#545e6e", "#8da1ba", "#dcebf7"], 6)
    metals += create_poly_ramp(["#2b1a0e", "#b88a32", "#ffe085"], 5)
    metals += create_poly_ramp(["#30120b", "#b05735", "#e8a682"], 5)

    for i, c in enumerate(metals): full_palette[i + 1] = c
    emis_hex = ["#ffffff", "#ff2b2b", "#ff8800", "#ffdd00", "#99ff00", "#00ff66", "#00ffff", "#0088ff",
                "#0000ff", "#9900ff", "#ff00ff", "#ff0066", "#444444", "#220000", "#002200", "#000022"]
    for i, h in enumerate(emis_hex): full_palette[16 + i] = hex_to_rgb(h) + [255]
    for i in range(108): full_palette[32 + i] = base_108[i]
    for i in range(108): full_palette[140 + i] = base_108[i]
    specials = ["#8ccaff", "#ff3333", "#33ff33", "#3388ff", "#21639c", "#4da6e0", "#ff6600", "#000000"]
    for i, h in enumerate(specials): full_palette[248 + i] = hex_to_rgb(h) + [255]
    return full_palette