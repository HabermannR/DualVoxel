"""The headless shape_slice tool's geometry: a rectangle or an ellipse in one layer, every write setting a
colour and a material together."""


def write(grid, mat_grid, coord, val, mat_val):
    """Set one voxel; erasing (val 0) clears its material too. True when anything changed."""
    mat_val = mat_val if val else 0
    if grid[coord] == val and (mat_grid is None or mat_grid[coord] == mat_val):
        return False
    grid[coord] = val
    if mat_grid is not None:
        mat_grid[coord] = mat_val
    return True


def commit_shape(grid, view_config, start_u, start_v, end_u, end_v, depth, shape_type, val, coord_func,
                 mat_grid=None, mat_val=0):
    """A Rect or Circle from (start_u, start_v) to (end_u, end_v) in a layer; coord_func(view_config, u, v, depth)
    gives each cell's index into grid. True when anything changed."""
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
