"""Viewer bundle, exactly as docs/VIEWER_CONTRACT.md specifies.

meta.json   metadata
dsm.bin     float32 little-endian, row-major, width × height, row 0 = north, never NaN
ortho.png   RGB over exactly the same ground extent
mask.png    optional, 255 where heights were filled or are unreliable
"""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
from scipy.ndimage import distance_transform_edt

CONTRACT_VERSION = 3
# A downsampled DSM cell is trusted if at least half of the source pixels under it were valid.
MIN_VALID_FRACTION = 0.5


def area_downsample(
    values: np.ndarray, ok: np.ndarray, max_side: int
) -> tuple[np.ndarray, np.ndarray]:
    """Area average of the valid pixels onto a grid whose long side is at most max_side.
    Returns (grid with NaN where no source pixel was valid, fraction of valid source pixels)."""
    h, w = values.shape
    scale = min(1.0, max_side / max(h, w))
    if scale == 1.0:
        return np.where(ok, values, np.nan).astype(np.float32), ok.astype(np.float32)
    size = (max(2, round(w * scale)), max(2, round(h * scale)))
    total = cv2.resize(
        np.where(ok, values, 0).astype(np.float32), size, interpolation=cv2.INTER_AREA
    )
    frac = cv2.resize(ok.astype(np.float32), size, interpolation=cv2.INTER_AREA)
    with np.errstate(invalid="ignore", divide="ignore"):
        grid = np.where(frac > 0, total / frac, np.nan)
    return grid.astype(np.float32), frac


def write_bundle(
    out_dir: str | Path,
    heights: np.ndarray,
    rgb: np.ndarray,
    *,
    units: str,
    pixel_size_m: float,
    pixel_size_assumed: bool,
    bounds: list[float] | None,
    crs: str | None,
    calibration: dict,
    source_name: str,
    max_dsm_side: int,
    max_ortho_side: int,
    valid: np.ndarray | None = None,
) -> dict:
    if units not in ("m", "relative"):
        raise ValueError(f"units must be 'm' or 'relative', not {units!r}")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    src_h, src_w = heights.shape
    ok = np.isfinite(heights) if valid is None else np.isfinite(heights) & valid
    if not ok.any():
        raise ValueError("No valid heights to export.")

    grid, frac = area_downsample(heights, ok, max_dsm_side)
    h, w = grid.shape
    missing = ~np.isfinite(grid)
    unreliable = missing | (frac < MIN_VALID_FRACTION)
    if missing.any():  # the contract forbids NaN: take the nearest valid value, flag it
        idx = distance_transform_edt(missing, return_distances=False, return_indices=True)
        grid = grid[tuple(idx)]
    mask = np.where(unreliable, 255, 0).astype(np.uint8)
    has_mask = bool(mask.any())
    trusted = grid[~unreliable] if (~unreliable).any() else grid.ravel()

    grid.astype("<f4").tofile(out / "dsm.bin")
    ortho_scale = min(1.0, max_ortho_side / max(rgb.shape[:2]))
    if ortho_scale < 1.0:
        rgb = cv2.resize(rgb, None, fx=ortho_scale, fy=ortho_scale, interpolation=cv2.INTER_AREA)
    cv2.imwrite(str(out / "ortho.png"), cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
    if has_mask:
        cv2.imwrite(str(out / "mask.png"), mask)
    elif (out / "mask.png").exists():
        (out / "mask.png").unlink()

    # Downsampling changes spacing; x and y factors agree to within one pixel of rounding.
    spacing = pixel_size_m * 0.5 * (src_w / w + src_h / h)
    meta = {
        "contract_version": CONTRACT_VERSION,
        "width": w,
        "height": h,
        "pixel_size_m": spacing,
        "pixel_size_assumed": pixel_size_assumed,
        "min_h": float(trusted.min()),
        "max_h": float(trusted.max()),
        "units": units,
        "bounds": bounds,
        "crs": crs,
        "has_mask": has_mask,
        "calibration": calibration,
        "source_name": source_name,
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta
