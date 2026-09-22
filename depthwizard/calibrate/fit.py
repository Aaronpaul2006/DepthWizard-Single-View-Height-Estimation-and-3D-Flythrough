"""Stage 3b: metric calibration (ARCHITECTURE.md).

Method A (baseline): D ≈ a·d + b, Huber fit on the DEM grid; DSM_A = a·d + b.
Method B (default):  DSM_B = D + s·d_high, where d_high = d − gaussian(d, σ) is the detail a
30 m DEM can't see. s comes from the first available source: GCPs; the DEM band (the detail the
DEM itself resolves, regressed on the model's, used only where they correlate); DEM relief
(Method A's a); then the scene prior, where a zero prior means "add no detail".

Calibration reads the DEM, GCPs and the image only. It must never import from evals/.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import cv2
import numpy as np
from scipy.optimize import least_squares

from depthwizard.calibrate.gcp import Gcps
from depthwizard.calibrate.prior import prior_scale
from depthwizard.config import CalibrationConfig

log = logging.getLogger(__name__)

# Blur at reduced resolution once σ exceeds this many pixels; a Gaussian that wide is smooth
# enough that area-downsampling first loses nothing and saves a very long kernel.
DIRECT_BLUR_MAX_SIGMA_PX = 4.0


@dataclass
class Calibration:
    dsm: np.ndarray  # float32 metres, NaN where invalid
    method: str  # dem_affine | gcp | dem_relief | scene_prior
    confidence: str  # high | medium | low
    scale: float
    offset: float | None = None
    details: dict = field(default_factory=dict)


def lowpass(d: np.ndarray, sigma_px: float) -> np.ndarray:
    if sigma_px <= DIRECT_BLUR_MAX_SIGMA_PX:
        return cv2.GaussianBlur(d, (0, 0), sigma_px, borderType=cv2.BORDER_REFLECT)
    h, w = d.shape
    f = int(sigma_px // DIRECT_BLUR_MAX_SIGMA_PX)
    small = cv2.resize(d, (max(1, w // f), max(1, h // f)), interpolation=cv2.INTER_AREA)
    # the area average already acts as a box filter of width f (variance f²/12)
    sigma_small = np.sqrt(max(sigma_px**2 - f**2 / 12.0, 0.0)) / f
    small = cv2.GaussianBlur(small, (0, 0), sigma_small, borderType=cv2.BORDER_REFLECT)
    return cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR)


def band_split(
    d: np.ndarray, dem_res_m: float, pixel_m: float, k: float
) -> tuple[np.ndarray, np.ndarray, float]:
    sigma_px = k * dem_res_m / pixel_m
    d_low = lowpass(d.astype(np.float32), sigma_px)
    return d_low, d - d_low, sigma_px


def block_mean(x: np.ndarray, block: int) -> np.ndarray:
    """Area average over block×block cells (NaN if any cell is NaN); edge remainder dropped."""
    h, w = x.shape
    hh, ww = h // block * block, w // block * block
    return x[:hh, :ww].reshape(hh // block, block, ww // block, block).mean(axis=(1, 3))


def fit_dem_affine(
    d: np.ndarray, dem: np.ndarray, block: int, huber_delta_m: float
) -> tuple[float, float]:
    """Huber fit of D ≈ a·d + b with both grids area-averaged to the DEM's resolution."""
    x, y = block_mean(d, block).ravel(), block_mean(dem, block).ravel()
    ok = np.isfinite(x) & np.isfinite(y)
    x, y = x[ok].astype(np.float64), y[ok].astype(np.float64)
    if len(x) < 2 or np.ptp(x) == 0:
        return 0.0, float(np.nanmedian(dem))
    a0, b0 = np.polyfit(x, y, 1)
    res = least_squares(
        lambda p: p[0] * x + p[1] - y, x0=[a0, b0], loss="huber", f_scale=huber_delta_m
    )
    return float(res.x[0]), float(res.x[1])


def method_a(
    d: np.ndarray, dem: np.ndarray, dem_res_m: float, pixel_m: float, cfg: CalibrationConfig
) -> Calibration:
    block = max(1, round(dem_res_m / pixel_m))
    a, b = fit_dem_affine(d, dem, block, cfg.huber_delta_m)
    dsm = (a * d + b).astype(np.float32)
    return Calibration(dsm, "dem_affine", "medium", a, b, {"block_px": block})


def band_scale(
    d: np.ndarray, dem: np.ndarray, dem_res_m: float, pixel_m: float, cfg: CalibrationConfig
) -> tuple[float, float, int]:
    """Scale learnt from the band the DEM itself resolves (its cell size up to band_coarse_cells
    cells). Both grids are area-averaged to DEM cells and high-passed with the same Gaussian; the
    DEM's detail is regressed on the model's. Returns (scale, correlation, cells used). A low
    correlation means the model's detail disagrees with the terrain here and should not be used."""
    block = max(1, round(dem_res_m / pixel_m))
    model_cells, dem_cells = block_mean(d, block), block_mean(dem, block)
    ok = np.isfinite(model_cells) & np.isfinite(dem_cells)
    cells = int(ok.sum())
    if cells < cfg.band_min_cells:
        return 0.0, 0.0, cells

    def detail(grid: np.ndarray) -> np.ndarray:
        filled = np.where(ok, grid, grid[ok].mean()).astype(np.float32)
        smooth = cv2.GaussianBlur(
            filled, (0, 0), cfg.band_coarse_cells, borderType=cv2.BORDER_REFLECT
        )
        return (filled - smooth)[ok].astype(np.float64)

    x, y = detail(model_cells), detail(dem_cells)
    if x.std() <= 0 or y.std() <= 0:
        return 0.0, 0.0, cells
    return float(np.dot(x, y) / np.dot(x, x)), float(np.corrcoef(x, y)[0, 1]), cells


def method_b(
    d: np.ndarray,
    dem: np.ndarray,
    dem_res_m: float,
    pixel_m: float,
    cfg: CalibrationConfig,
    gcps: Gcps | None = None,
    d_high: np.ndarray | None = None,  # precomputed detail band (evals/tune.py caches it)
    band: tuple[float, float, int] | None = None,  # precomputed band_scale() result
) -> Calibration:
    sigma_px = cfg.band_sigma_k * dem_res_m / pixel_m
    if d_high is None:
        _, d_high, sigma_px = band_split(d, dem_res_m, pixel_m, cfg.band_sigma_k)
    details: dict = {"sigma_px": round(sigma_px, 2)}
    method = confidence = None
    scale = None

    if gcps is not None and len(gcps) >= cfg.gcp_min_points:
        target = gcps.heights - gcps.sample(dem)  # height above the DEM at each GCP
        feat = gcps.sample(d_high)
        ok = np.isfinite(target) & np.isfinite(feat)
        denom = float(np.sum(feat[ok] ** 2))
        if ok.sum() >= cfg.gcp_min_points and denom > 0:
            scale, method, confidence = float(np.sum(feat[ok] * target[ok]) / denom), "gcp", "high"
            details["gcps_used"] = int(ok.sum())

    if scale is None:
        s_band, r_band, cells = band or band_scale(d, dem, dem_res_m, pixel_m, cfg)
        details.update(band_r=round(r_band, 3), band_cells=cells)
        if r_band >= cfg.band_min_r and s_band > 0:
            scale, method, confidence = s_band, "dem_band", "medium"

    relief = float(np.nanstd(dem))
    details["dem_std_m"] = round(relief, 2)
    if scale is None and relief > cfg.dem_relief_std_m:
        a = method_a(d, dem, dem_res_m, pixel_m, cfg).scale
        if a > 0:
            scale, method, confidence = a, "dem_relief", "medium"
        else:
            log.warning("Method A slope %.4g is not positive; skipping the DEM-relief scale.", a)

    if scale is None:
        scale = prior_scale(d_high, cfg.prior_percentile, cfg.prior_height_m)
        # a zero prior means "add no detail": the DSM is then the DEM itself
        method, confidence = ("scene_prior" if scale > 0 else "dem_only"), "low"

    log.info("Method B: s = %.5g from %s (confidence %s).", scale, method, confidence)
    dsm = (dem + scale * d_high).astype(np.float32)
    return Calibration(dsm, method, confidence, scale, None, details)
