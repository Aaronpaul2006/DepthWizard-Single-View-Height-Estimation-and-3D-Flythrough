"""Calibration on synthetic scenes where the true surface is known."""

import ast
from pathlib import Path

import cv2
import numpy as np

from depthwizard.calibrate.fit import band_split, lowpass, method_a, method_b
from depthwizard.calibrate.gcp import Gcps
from depthwizard.config import load_config

PIXEL_M, DEM_RES_M = 1.0, 30.0


def scene(h=600, w=600, relief=80.0):
    """Rolling terrain plus box buildings; the 'DEM' is the surface blurred to 30 m."""
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    terrain = 200 + relief * np.sin(xx / 150) * np.cos(yy / 190)
    buildings = np.zeros_like(terrain)
    rng = np.random.default_rng(3)
    for _ in range(25):
        y0, x0 = rng.integers(0, h - 30, 2)
        size = rng.integers(10, 30)
        buildings[y0 : y0 + size, x0 : x0 + size] = rng.uniform(6, 30)
    truth = terrain + buildings
    # How a real DEM reaches the image grid: area average at 30 m, then bilinear resampling.
    block = int(DEM_RES_M / PIXEL_M)
    coarse = cv2.resize(truth, (w // block, h // block), interpolation=cv2.INTER_AREA)
    dem = cv2.resize(coarse, (w, h), interpolation=cv2.INTER_LINEAR)
    return truth, dem


def rmse(a, b):
    return float(np.sqrt(np.nanmean((a - b) ** 2)))


def test_lowpass_downsampled_path_matches_direct_blur():
    import cv2

    x = np.random.default_rng(0).normal(size=(400, 400)).astype(np.float32)
    x = cv2.GaussianBlur(x, (0, 0), 3)
    direct = cv2.GaussianBlur(x, (0, 0), 20, borderType=cv2.BORDER_REFLECT)
    fast = lowpass(x, 20)
    assert rmse(direct[50:-50, 50:-50], fast[50:-50, 50:-50]) < 0.1 * direct.std()


def test_method_b_with_gcps_recovers_building_heights():
    cfg = load_config().calibration
    cfg.band_sigma_k = 0.5  # this synthetic DEM's blur is exactly what k = 0.5 matches
    truth, dem = scene()
    d = 0.02 * truth + 3.0  # model: unknown scale and shift, correct polarity
    _, d_high, _ = band_split(d, DEM_RES_M, PIXEL_M, cfg.band_sigma_k)
    rows = np.array([100.5, 300.5, 450.5, 50.5, 520.5])
    cols = np.array([80.5, 210.5, 400.5, 500.5, 90.5])
    gcps = Gcps(rows=rows, cols=cols, heights=truth[rows.astype(int), cols.astype(int)])
    cal = method_b(d, dem, DEM_RES_M, PIXEL_M, cfg, gcps)
    assert cal.method == "gcp" and cal.confidence == "high"
    assert abs(cal.scale - 50.0) / 50.0 < 0.2
    assert rmse(cal.dsm, truth) < rmse(dem, truth)


def test_method_b_falls_back_to_dem_relief_then_prior():
    cfg = load_config().calibration
    cfg.band_min_r = 2.0  # switch the DEM-band source off to test the later fallbacks alone
    cfg.dem_relief_std_m, cfg.prior_height_m = 15.0, 12.0  # both are off in the tuned defaults
    truth, dem = scene(relief=80.0)
    d = 0.02 * truth + 3.0
    hilly = method_b(d, dem, DEM_RES_M, PIXEL_M, cfg)
    assert hilly.method == "dem_relief" and hilly.confidence == "medium"
    assert rmse(hilly.dsm, truth) < rmse(dem, truth)
    flat_truth, flat_dem = scene(relief=1.0)
    flat = method_b(0.02 * flat_truth, flat_dem, DEM_RES_M, PIXEL_M, cfg)
    assert flat.method == "scene_prior" and flat.confidence == "low"


def test_tuned_defaults_fall_back_to_the_dem_when_no_source_applies():
    cfg = load_config().calibration
    cfg.band_min_r = 2.0  # force every source to fail
    flat_truth, flat_dem = scene(relief=1.0)
    cal = method_b(0.02 * flat_truth, flat_dem, DEM_RES_M, PIXEL_M, cfg)
    assert cal.method == "dem_only" and cal.scale == 0.0
    assert np.allclose(cal.dsm, flat_dem)


def test_method_a_is_exact_when_the_model_is_affine_in_height():
    cfg = load_config().calibration
    truth, dem = scene()
    cal = method_a(0.02 * truth + 3.0, dem, DEM_RES_M, PIXEL_M, cfg)
    assert abs(cal.scale - 50.0) < 5.0


def test_calibration_never_imports_evals():
    root = Path(__file__).resolve().parent.parent / "depthwizard" / "calibrate"
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            assert not any(n.split(".")[0] == "evals" for n in names), f"{path.name} imports evals"
