"""Noise for the editor's procedural tools: smooth value noise, weighted picks that keep their shares, and
the model's surface.

Arrays are (z, y, x) as in the model. Everything takes a seed, so the same call gives the same voxels.
"""
from __future__ import annotations

import numpy as np


def value_noise(shape, scale: float, seed: int, octaves: int = 1, persistence: float = 0.5) -> np.ndarray:
    """Smooth noise in 0..1 over an array of `shape` (2 or 3 axes): features about `scale` cells across,
    each further octave half the size and `persistence` as strong. scale 0 gives white noise."""
    rng = np.random.default_rng(seed)
    if scale <= 0:
        return rng.random(shape)
    total = np.zeros(shape)
    amplitude, weight, size = 1.0, 0.0, float(scale)
    for _ in range(max(1, int(octaves))):
        total += amplitude * _lattice(shape, max(size, 1.0), rng)
        weight += amplitude
        amplitude *= persistence
        size /= 2
    return total / weight


def _lattice(shape, size: float, rng) -> np.ndarray:
    """Random values on a grid `size` cells apart, smoothstep-interpolated between."""
    points = [int(np.ceil(n / size)) + 2 for n in shape]
    grid = rng.random(points)
    offset = rng.random(len(shape))  # so octaves and seeds do not line up on cell corners
    coords = [np.arange(n) / size + o for n, o in zip(shape, offset)]
    mesh = np.meshgrid(*coords, indexing="ij")
    base = [np.floor(c).astype(int) for c in mesh]
    frac = [c - b for c, b in zip(mesh, base)]
    smooth = [f * f * (3 - 2 * f) for f in frac]
    out = np.zeros(shape)
    for corner in range(1 << len(shape)):
        bits = [(corner >> axis) & 1 for axis in range(len(shape))]
        w = np.ones(shape)
        for axis, bit in enumerate(bits):
            w *= smooth[axis] if bit else 1 - smooth[axis]
        out += w * grid[tuple(b + bit for b, bit in zip(base, bits))]
    return out


def weighted_choice(values: np.ndarray, weights) -> np.ndarray:
    """For each value (noise over the cells to choose for), the index of a weight, so each index takes
    its share of the cells exactly: the lowest values take the first weight, and so on. With white noise
    the picks are scattered; with smooth noise they gather into patches."""
    values = np.asarray(values, dtype=np.float64).ravel()
    weights = np.asarray(weights, dtype=np.float64)
    if (weights < 0).any() or weights.sum() <= 0:
        raise ValueError("weights must be zero or more, and not all zero")
    rank = np.empty(len(values))
    rank[np.argsort(values, kind="stable")] = (np.arange(len(values)) + 0.5) / max(1, len(values))
    edges = np.cumsum(weights) / weights.sum()
    return np.minimum(np.searchsorted(edges, rank, side="right"), len(weights) - 1)


NEIGHBOURS = ((0, 0, 1), (0, 0, -1), (0, 1, 0), (0, -1, 0), (1, 0, 0), (-1, 0, 0))  # (dz, dy, dx)


def shifted(solid: np.ndarray, dz: int, dy: int, dx: int) -> np.ndarray:
    """solid moved by (dz, dy, dx): out[z, y, x] = solid[z + dz, y + dy, x + dx], empty outside."""
    out = np.zeros_like(solid)
    src = tuple(slice(max(0, d), n + min(0, d)) for d, n in zip((dz, dy, dx), solid.shape))
    dst = tuple(slice(max(0, -d), n + min(0, -d)) for d, n in zip((dz, dy, dx), solid.shape))
    out[dst] = solid[src]
    return out


def surface(solid: np.ndarray, top_only: bool = False) -> np.ndarray:
    """Solid voxels with an empty neighbour (top_only: with an empty voxel, or the model's edge, above).
    Outside the model counts as empty, except below the bottom layer, which counts as the table."""
    if top_only:
        return solid & ~shifted(solid, 1, 0, 0)
    covered = np.ones_like(solid)
    for dz, dy, dx in NEIGHBOURS:
        side = shifted(solid, dz, dy, dx)
        if dz == -1:
            side[0] = True  # the table under the model
        covered &= side
    return solid & ~covered
