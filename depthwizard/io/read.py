"""Stage 1: read PNG / JPG / GeoTIFF into 8-bit RGB plus its georeferencing."""

from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import rasterio
from affine import Affine
from rasterio.crs import CRS
from rasterio.enums import ColorInterp, Resampling
from rasterio.errors import NotGeoreferencedWarning

from depthwizard.config import InputConfig

log = logging.getLogger(__name__)

SUPPORTED_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff"}


@dataclass
class Raster:
    rgb: np.ndarray  # (H, W, 3) uint8
    crs: CRS | None
    transform: Affine
    name: str
    valid: np.ndarray | None = None  # (H, W) bool; None means every pixel is valid

    @property
    def georeferenced(self) -> bool:
        """A CRS plus a non-identity transform; plain PNG/JPG get neither from GDAL."""
        return self.crs is not None and not self.transform.is_identity

    @property
    def shape(self) -> tuple[int, int]:
        return self.rgb.shape[0], self.rgb.shape[1]


def read_image(path: str | Path, cfg: InputConfig) -> Raster:
    path = Path(path)
    if path.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise ValueError(f"Unsupported file type {path.suffix!r}; expected PNG, JPG or GeoTIFF.")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", NotGeoreferencedWarning)
        with rasterio.open(path) as src:
            scale = min(1.0, cfg.max_long_side / max(src.width, src.height))
            out_h, out_w = round(src.height * scale), round(src.width * scale)
            if scale < 1.0:
                log.warning(
                    "Input %dx%d exceeds max_long_side=%d; downsampling to %dx%d.",
                    src.width,
                    src.height,
                    cfg.max_long_side,
                    out_w,
                    out_h,
                )
            resampling = Resampling.average if scale < 1.0 else Resampling.nearest
            palette = src.count == 1 and src.colorinterp[0] == ColorInterp.palette
            bands = [1] if palette else _select_bands(src.count, cfg.rgb_bands)
            data = src.read(bands, out_shape=(len(bands), out_h, out_w), resampling=resampling)
            colormap = src.colormap(1) if palette else None
            transform = src.transform @ Affine.scale(src.width / out_w, src.height / out_h)
            crs = src.crs
    if colormap is not None:
        lut = np.array([colormap.get(i, (0, 0, 0, 255))[:3] for i in range(256)], dtype=np.uint8)
        rgb = lut[data[0]]
    else:
        rgb = _to_uint8(np.moveaxis(data, 0, -1), cfg.stretch_percentiles)
        if rgb.shape[2] == 1:
            rgb = np.repeat(rgb, 3, axis=2)
    valid = _valid_mask(path, rgb.shape[0], rgb.shape[1])
    return Raster(
        rgb=np.ascontiguousarray(rgb), crs=crs, transform=transform, name=path.name, valid=valid
    )


def _valid_mask(path: Path, height: int, width: int) -> np.ndarray | None:
    """GDAL's dataset mask (nodata values, an alpha band or an internal mask) at the output size.
    None when every pixel is valid."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", NotGeoreferencedWarning)
        with rasterio.open(path) as src:
            mask = src.dataset_mask(out_shape=(height, width)) > 0
    return None if mask.all() else mask


def _select_bands(count: int, rgb_bands: list[int]) -> list[int]:
    if count >= max(rgb_bands):
        return list(rgb_bands)
    if count in (1, 2):  # grayscale, or grayscale + alpha
        return [1]
    raise ValueError(f"Image has {count} bands; configured RGB bands {rgb_bands} don't fit.")


def _to_uint8(data: np.ndarray, percentiles: list[float]) -> np.ndarray:
    if data.dtype == np.uint8:
        return data
    log.info(
        "Input dtype %s: stretching each band to 8-bit on percentiles %s.", data.dtype, percentiles
    )
    out = np.empty(data.shape, dtype=np.uint8)
    for b in range(data.shape[2]):
        band = data[..., b].astype(np.float32)
        finite = band[np.isfinite(band)]
        lo, hi = np.percentile(finite, percentiles) if finite.size else (0.0, 1.0)
        scaled = (band - lo) / max(hi - lo, 1e-6)
        out[..., b] = (np.nan_to_num(np.clip(scaled, 0.0, 1.0)) * 255.0 + 0.5).astype(np.uint8)
    return out
