"""Voxel editing previews; no desktop context or native renderer required."""
import numpy as np
from PIL import Image, ImageDraw

BACKGROUND = (28, 35, 43, 255)
CELL_W, CELL_H = 300, 430

def orthographic(grid, palette, u, v, d, reverse_depth=False, reverse_u=False):
    volume = np.transpose(grid, (u, v, d))
    if reverse_depth:
        volume = volume[:, :, ::-1]
    nearest = np.argmax(volume != 0, axis=2)
    ids = np.take_along_axis(volume, nearest[:, :, None], axis=2)[:, :, 0]
    pixels = palette[ids].transpose(1, 0, 2)[::-1].copy()
    if reverse_u:
        pixels = pixels[:, ::-1]
    return Image.fromarray(pixels)

def isometric(grid, palette):
    faces = []
    sx, sy, sz = grid.shape
    for x, y, z in np.argwhere(grid != 0):
        color = palette[grid[x, y, z]]
        if x == sx - 1 or grid[x + 1, y, z] == 0:
            faces.append((x-y+z+0.5, [(x+1,y,z),(x+1,y+1,z),(x+1,y+1,z+1),(x+1,y,z+1)], color, 0.70))
        if y == 0 or grid[x, y-1, z] == 0:
            faces.append((x-y+z+0.5, [(x,y,z),(x+1,y,z),(x+1,y,z+1),(x,y,z+1)], color, 0.85))
        if z == sz - 1 or grid[x, y, z+1] == 0:
            faces.append((x-y+z+0.5, [(x,y,z+1),(x+1,y,z+1),(x+1,y+1,z+1),(x,y+1,z+1)], color, 1.0))
    image = Image.new("RGBA", (CELL_W, CELL_H - 52), BACKGROUND)
    if not faces:
        return image
    project = lambda p: ((p[0]+p[1])*0.8660254, (p[0]-p[1])*0.5-p[2])
    points = [project(p) for _, vertices, _, _ in faces for p in vertices]
    lo = np.min(points, axis=0); hi = np.max(points, axis=0)
    scale = min((CELL_W-24)/max(hi[0]-lo[0],1), (CELL_H-76)/max(hi[1]-lo[1],1))
    draw = ImageDraw.Draw(image)
    for _, vertices, color, light in sorted(faces, key=lambda f: f[0]):
        xy = [(12+(project(p)[0]-lo[0])*scale, 12+(project(p)[1]-lo[1])*scale) for p in vertices]
        rgb = tuple(int(float(c)*light) for c in color[:3]) + (255,)
        draw.polygon(xy, fill=rgb)
    return image

def render_preview(grid, palette):
    sheet = Image.new("RGBA", (CELL_W*4, CELL_H), BACKGROUND)
    views = [
        ("FRONT (-Y)", orthographic(grid,palette,0,2,1)),
        ("BACK (+Y)", orthographic(grid,palette,0,2,1,True,True)),
        ("RIGHT (+X)", orthographic(grid,palette,1,2,0,True)),
        ("ISOMETRIC", isometric(grid,palette)),
    ]
    draw = ImageDraw.Draw(sheet)
    for index, (name, image) in enumerate(views):
        draw.text((index*CELL_W+12,10), name, fill=(225,225,215,255))
        if index < 3:
            scale = min((CELL_W-24)/image.width, (CELL_H-70)/image.height)
            image = image.resize((max(1,int(image.width*scale)),max(1,int(image.height*scale))),Image.Resampling.NEAREST)
        x = index*CELL_W+(CELL_W-image.width)//2
        y = 35+(CELL_H-70-image.height)//2
        sheet.alpha_composite(image,(x,y))
    draw.text((12,CELL_H-20), f"Voxel dimensions: {grid.shape[0]} x {grid.shape[1]} x {grid.shape[2]}   Occupied: {np.count_nonzero(grid)}",fill=(160,185,193,255))
    return sheet.convert("RGB")
