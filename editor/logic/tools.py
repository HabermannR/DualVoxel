"""Slice-tool geometry on the editor's window: every write sets a colour and a material together."""
GRID_SIZE = 32  # shapes and fills work in a layer of 32 x 32 cells


def get_voxel_coord(view_config, u, v, depth):
    cfg = view_config
    if cfg['inv_u']:
        u = (GRID_SIZE - 1) - u
    if cfg['inv_v']:
        v = (GRID_SIZE - 1) - v
    c = [0, 0, 0]
    c[cfg['u']] = u
    c[cfg['v']] = v
    c[cfg['d']] = depth
    return tuple(c)


def bresenham_line(x0, y0, x1, y1):
    points = []
    dx, dy = abs(x1 - x0), abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx - dy
    while True:
        points.append((x0, y0))
        if x0 == x1 and y0 == y1:
            break
        e2 = 2 * err
        if e2 > -dy:
            err -= dy
            x0 += sx
        if e2 < dx:
            err += dx
            y0 += sy
    return points


def write(grid, mat_grid, coord, val, mat_val):
    """Set one voxel; erasing (val 0) clears its material too. True when anything changed."""
    mat_val = mat_val if val else 0
    if grid[coord] == val and (mat_grid is None or mat_grid[coord] == mat_val):
        return False
    grid[coord] = val
    if mat_grid is not None:
        mat_grid[coord] = mat_val
    return True


def flood_fill_2d(grid, view_config, start_u, start_v, depth, new_val, coord_func=get_voxel_coord,
                  mat_grid=None, new_mat=0):
    """Fill the connected region of the same colour and material in one slice."""
    start = coord_func(view_config, start_u, start_v, depth)
    target = (grid[start], mat_grid[start] if mat_grid is not None else 0)
    if target == (new_val, (new_mat if new_val else 0) if mat_grid is not None else 0):
        return False
    stack, visited, count = [(start_u, start_v)], set(), 0
    while stack:
        u, v = stack.pop()
        if (u, v) in visited or not (0 <= u < GRID_SIZE and 0 <= v < GRID_SIZE):
            continue
        visited.add((u, v))
        coord = coord_func(view_config, u, v, depth)
        if (grid[coord], mat_grid[coord] if mat_grid is not None else 0) == target:
            write(grid, mat_grid, coord, new_val, new_mat)
            count += 1
            stack.extend(((u + 1, v), (u - 1, v), (u, v + 1), (u, v - 1)))
    return count > 0


def commit_shape(grid, view_config, start_u, start_v, end_u, end_v, depth, shape_type, val,
                 coord_func=get_voxel_coord, mat_grid=None, mat_val=0):
    u_min, u_max = min(start_u, end_u), max(start_u, end_u)
    v_min, v_max = min(start_v, end_v), max(start_v, end_v)
    changed = False
    if shape_type == "Rect":
        for u in range(u_min, u_max + 1):
            for v in range(v_min, v_max + 1):
                changed |= write(grid, mat_grid, coord_func(view_config, u, v, depth), val, mat_val)
    elif shape_type == "Circle":
        cu, cv = (u_min + u_max) / 2, (v_min + v_max) / 2
        ru, rv = max(0.5, (u_max - u_min) / 2), max(0.5, (v_max - v_min) / 2)
        for u in range(u_min, u_max + 1):
            for v in range(v_min, v_max + 1):
                if ((u - cu) / ru) ** 2 + ((v - cv) / rv) ** 2 <= 1.05:
                    changed |= write(grid, mat_grid, coord_func(view_config, u, v, depth), val, mat_val)
    return changed
