"""Tile layout and blending windows for Stage 2."""

from __future__ import annotations

import numpy as np


def tile_origins(length: int, tile: int, stride: int) -> list[int]:
    """Start offsets of tiles covering [0, length); the last tile sits flush with the end."""
    if length <= tile:
        return [0]
    starts = list(range(0, length - tile + 1, stride))
    if starts[-1] != length - tile:
        starts.append(length - tile)
    return starts


def taper(n: int, flat_start: bool, flat_end: bool) -> np.ndarray:
    """1D sin² (Hann) window; at 50% overlap neighbouring windows sum to 1.

    A side lying on the image boundary is held at full weight, otherwise the outermost pixels
    would get (near) zero total weight."""
    w = np.sin(np.pi * (np.arange(n) + 0.5) / n) ** 2
    half = n // 2
    if flat_start:
        w[:half] = 1.0
    if flat_end:
        w[half:] = 1.0
    return w.astype(np.float32)


def window2d(y: int, x: int, tile: int, height: int, width: int) -> np.ndarray:
    rows = taper(tile, y == 0, y + tile >= height)
    cols = taper(tile, x == 0, x + tile >= width)
    return np.outer(rows, cols)
