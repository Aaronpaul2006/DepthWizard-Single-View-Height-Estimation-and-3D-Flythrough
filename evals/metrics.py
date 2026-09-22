"""DSM accuracy metrics (EVALUATION.md).

Error e = prediction − reference, over pixels valid in both.

Reference data is read here and in the eval runner only, never by depthwizard/calibrate.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import rasterio
from affine import Affine
from rasterio.crs import CRS
from rasterio.warp import Resampling, reproject

NMAD_K = 1.4826  # makes NMAD equal the standard deviation for normally distributed errors


def reference_on_grid(
    path: str | Path, crs: CRS, transform: Affine, shape: tuple[int, int]
) -> np.ndarray:
    """Reproject a reference raster onto the prediction grid (bilinear), NaN where missing."""
    out = np.full(shape, np.nan, np.float32)
    with rasterio.open(path) as src:
        reproject(
            source=rasterio.band(src, 1),
            destination=out,
            src_nodata=src.nodata,
            dst_transform=transform,
            dst_crs=crs,
            dst_nodata=np.nan,
            resampling=Resampling.bilinear,
        )
    return out


def valid_pairs(pred: np.ndarray, ref: np.ndarray, mask: np.ndarray | None = None) -> np.ndarray:
    ok = np.isfinite(pred) & np.isfinite(ref)
    return ok & mask if mask is not None else ok


def dsm_metrics(pred: np.ndarray, ref: np.ndarray, mask: np.ndarray | None = None) -> dict:
    ok = valid_pairs(pred, ref, mask)
    n = int(ok.sum())
    if n < 2:
        return {"n_pixels": n}
    p, r = pred[ok].astype(np.float64), ref[ok].astype(np.float64)
    e = p - r
    med = float(np.median(e))
    return {
        "rmse": float(np.sqrt(np.mean(e**2))),
        "mae": float(np.mean(np.abs(e))),
        "pearson_r": float(np.corrcoef(p, r)[0, 1]) if np.ptp(p) > 0 and np.ptp(r) > 0 else 0.0,
        "bias": float(np.mean(e)),
        "nmad": float(NMAD_K * np.median(np.abs(e - med))),
        "offset_free_rmse": float(np.sqrt(np.mean((e - med) ** 2))),
        "n_pixels": n,
    }


def scale_aligned(
    pred: np.ndarray, ref: np.ndarray, mask: np.ndarray | None = None
) -> tuple[np.ndarray, float, float]:
    """Least-squares a, b so that a·pred + b best matches ref. For relative-mode evaluation only;
    results must be labelled 'scale-aligned' wherever they appear."""
    ok = valid_pairs(pred, ref, mask)
    a, b = np.polyfit(pred[ok].astype(np.float64), ref[ok].astype(np.float64), 1)
    return (a * pred + b).astype(np.float32), float(a), float(b)


def relative_metrics(pred: np.ndarray, ref: np.ndarray, mask: np.ndarray | None = None) -> dict:
    aligned, a, b = scale_aligned(pred, ref, mask)
    out = dsm_metrics(aligned, ref, mask)
    out.update(scale_aligned=True, align_a=a, align_b=b)
    return out


def object_mask(ref_dsm: np.ndarray, ref_dtm: np.ndarray, min_height_m: float) -> np.ndarray:
    """Pixels whose reference height above ground exceeds min_height_m (buildings, trees)."""
    with np.errstate(invalid="ignore"):
        return (ref_dsm - ref_dtm) > min_height_m
