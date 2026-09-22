"""DEM-band scale: learn metres-per-model-unit from detail the DEM itself resolves."""

import cv2
import numpy as np

from depthwizard.calibrate.fit import band_scale, method_b
from depthwizard.config import load_config

PIXEL_M, DEM_RES_M, N = 1.0, 30.0, 1200  # a 1.2 km scene: 40 x 40 DEM cells


def surface(seed: int = 1) -> np.ndarray:
    """Hills, 30-150 m features a 30 m DEM can see, and buildings it can't."""
    rng = np.random.default_rng(seed)
    hills = cv2.resize(
        rng.normal(size=(6, 6)).astype(np.float32), (N, N), interpolation=cv2.INTER_CUBIC
    )
    mid = cv2.resize(
        rng.normal(size=(40, 40)).astype(np.float32), (N, N), interpolation=cv2.INTER_CUBIC
    )
    buildings = np.zeros((N, N), np.float32)
    for _ in range(40):
        y, x = rng.integers(0, N - 30, 2)
        buildings[y : y + rng.integers(10, 30), x : x + rng.integers(10, 30)] = rng.uniform(5, 25)
    return 500 + 60 * hills + 8 * mid + buildings


def dem_from(truth: np.ndarray) -> np.ndarray:
    block = int(DEM_RES_M / PIXEL_M)
    coarse = cv2.resize(truth, (N // block, N // block), interpolation=cv2.INTER_AREA)
    return cv2.resize(coarse, (N, N), interpolation=cv2.INTER_LINEAR)


def test_band_scale_recovers_the_metres_per_model_unit():
    truth = surface()
    scale, r, cells = band_scale(
        0.02 * truth + 3.0, dem_from(truth), DEM_RES_M, PIXEL_M, load_config().calibration
    )
    assert cells >= 64 and r > 0.8
    assert abs(scale - 50.0) / 50.0 < 0.25


def test_model_detail_that_disagrees_with_the_dem_is_not_trusted():
    cfg = load_config().calibration
    truth = surface()
    rng = np.random.default_rng(9)
    unrelated = cv2.GaussianBlur(rng.normal(size=truth.shape).astype(np.float32), (0, 0), 20)
    cal = method_b(unrelated, dem_from(truth), DEM_RES_M, PIXEL_M, cfg)
    assert cal.method != "dem_band"
    assert cal.details["band_r"] < cfg.band_min_r


def test_method_b_prefers_the_band_scale_when_it_agrees():
    cfg = load_config().calibration
    truth = surface()
    cal = method_b(0.02 * truth + 3.0, dem_from(truth), DEM_RES_M, PIXEL_M, cfg)
    assert cal.method == "dem_band" and cal.confidence == "medium"
