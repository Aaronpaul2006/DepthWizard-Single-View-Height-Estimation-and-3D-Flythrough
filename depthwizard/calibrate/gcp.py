"""Ground control points: CSV with `x,y,height_m` (image CRS) or `lon,lat,height_m`.

Heights must use the same vertical datum as the calibration DEM.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from affine import Affine
from pyproj import Transformer
from rasterio.crs import CRS
from scipy.ndimage import map_coordinates


@dataclass
class Gcps:
    rows: np.ndarray  # fractional pixel coordinates (pixel centres at .5)
    cols: np.ndarray
    heights: np.ndarray  # metres

    def __len__(self) -> int:
        return len(self.heights)

    def sample(self, grid: np.ndarray) -> np.ndarray:
        """Bilinear sample of `grid` at the GCPs (NaN outside)."""
        coords = np.vstack([self.rows - 0.5, self.cols - 0.5])
        return map_coordinates(grid, coords, order=1, mode="constant", cval=np.nan)


def read_gcps(path: str | Path, crs: CRS, transform: Affine, shape: tuple[int, int]) -> Gcps:
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise ValueError(f"{path}: no GCP rows.")
    keys = {k.strip().lower() for k in rows[0]}
    heights = np.array([float(r["height_m"]) for r in rows])
    if {"x", "y"} <= keys:
        xs = np.array([float(r["x"]) for r in rows])
        ys = np.array([float(r["y"]) for r in rows])
    elif {"lon", "lat"} <= keys:
        to_img = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
        xs, ys = to_img.transform(
            np.array([float(r["lon"]) for r in rows]), np.array([float(r["lat"]) for r in rows])
        )
    else:
        raise ValueError(f"{path}: expected columns x,y,height_m or lon,lat,height_m.")
    cols, rows_px = (~transform) * (np.asarray(xs), np.asarray(ys))
    cols, rows_px = np.asarray(cols), np.asarray(rows_px)
    h, w = shape
    inside = (cols >= 0) & (cols < w) & (rows_px >= 0) & (rows_px < h)
    return Gcps(rows=rows_px[inside], cols=cols[inside], heights=heights[inside])
