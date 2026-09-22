"""GeoTIFF output: float32, LZW, nodata sentinel, DW_* tags."""

from __future__ import annotations

import warnings
from pathlib import Path

import numpy as np
import rasterio
from affine import Affine
from rasterio.crs import CRS
from rasterio.errors import NotGeoreferencedWarning


def write_geotiff(
    path: str | Path,
    grid: np.ndarray,
    crs: CRS | None,
    transform: Affine,
    nodata: float,
    tags: dict[str, str] | None = None,
) -> None:
    data = np.where(np.isfinite(grid), grid, nodata).astype(np.float32)
    profile = {
        "driver": "GTiff",
        "height": data.shape[0],
        "width": data.shape[1],
        "count": 1,
        "dtype": "float32",
        "crs": crs,
        "transform": transform,
        "nodata": nodata,
        "compress": "lzw",
        "predictor": 3,  # floating-point predictor; makes LZW effective on heights
        "tiled": True,
        "blockxsize": 256,
        "blockysize": 256,
        "BIGTIFF": "IF_SAFER",
    }
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", NotGeoreferencedWarning)
        with rasterio.open(path, "w", **profile) as dst:
            dst.write(data, 1)
            if tags:
                dst.update_tags(**tags)
