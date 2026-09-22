"""Compare a finished job's DSM with an uploaded reference DSM (POST /api/jobs/{id}/validate).

Metrics use the full-resolution DSM GeoTIFF. The viewer also gets, on its own bundle grid:
  error.bin      prediction − reference (NaN where there's no reference)
  reference.bin  the reference itself, in the DSM's units, for the viewer's comparison tools
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_bounds

from evals.metrics import dsm_metrics, reference_on_grid, relative_metrics


def validate_job(out_dir: Path, reference_path: Path) -> dict:
    bundle = out_dir / "bundle"
    meta = json.loads((bundle / "meta.json").read_text(encoding="utf-8"))
    tif = out_dir / ("dsm.tif" if (out_dir / "dsm.tif").exists() else "rdsm.tif")
    with rasterio.open(tif) as src:
        pred = src.read(1, masked=True).filled(np.nan).astype(np.float32)
        crs, transform = src.crs, src.transform
    georeferenced = meta["crs"] is not None and meta["bounds"] is not None

    if georeferenced:
        ref = reference_on_grid(reference_path, crs, transform, pred.shape)
    else:  # no georeference: only a pixel-aligned reference of the same size can be compared
        ref = _read_same_size(reference_path, pred.shape)
    if not np.isfinite(ref).any():
        raise ValueError("The reference DSM does not overlap this result.")

    relative = meta["units"] == "relative"
    metrics = relative_metrics(pred, ref) if relative else dsm_metrics(pred, ref)
    if metrics["n_pixels"] < 2:
        raise ValueError("Too few pixels are valid in both the result and the reference.")

    w, h = meta["width"], meta["height"]
    if georeferenced:
        ref_v = reference_on_grid(
            reference_path, meta["crs"], from_bounds(*meta["bounds"], w, h), (h, w)
        )
    else:
        ref_v = _downsample_nan(ref, (h, w))
    if relative:  # express the reference in the DSM's relative units
        ref_v = (ref_v - metrics["align_b"]) / metrics["align_a"]
    dsm_v = np.fromfile(bundle / "dsm.bin", dtype="<f4").reshape(h, w)
    mask_path = bundle / "mask.png"
    if mask_path.exists():  # filled cells are not predictions; keep them out of comparisons
        import cv2

        ref_v[cv2.imread(str(mask_path), cv2.IMREAD_UNCHANGED) > 0] = np.nan
    (dsm_v - ref_v).astype("<f4").tofile(bundle / "error.bin")
    ref_v.astype("<f4").tofile(bundle / "reference.bin")

    return {
        "rmse": metrics["rmse"],
        "mae": metrics["mae"],
        "bias": metrics["bias"],
        "nmad": metrics["nmad"],
        "pearson_r": metrics["pearson_r"],
        "n_pixels": metrics["n_pixels"],
        "units": "relative" if relative else "m",
        "scale_aligned": relative,
        "error_file": "error.bin",
        "reference_file": "reference.bin",
    }


def _read_same_size(path: Path, shape: tuple[int, int]) -> np.ndarray:
    with rasterio.open(path) as src:
        if (src.height, src.width) != shape:
            raise ValueError(
                f"This result has no georeference, so the reference must be exactly "
                f"{shape[1]}x{shape[0]} pixels (got {src.width}x{src.height})."
            )
        return src.read(1, masked=True).filled(np.nan).astype(np.float32)


def _downsample_nan(grid: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    from depthwizard.export.bundle import area_downsample

    ok = np.isfinite(grid)
    out, _ = area_downsample(grid, ok, max(shape))
    return out if out.shape == shape else np.full(shape, np.nan, np.float32)
