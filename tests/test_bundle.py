"""Bundle bytes and geometry against docs/VIEWER_CONTRACT.md.

This is the backend half of the acceptance tests; viewer/scripts/contract-test.mjs is the other.
"""

import json
import math

import cv2
import numpy as np

from depthwizard.export.bundle import write_bundle
from depthwizard.export.synthetic import build


def load(path):
    meta = json.loads((path / "meta.json").read_text())
    dsm = np.fromfile(path / "dsm.bin", dtype="<f4").reshape(meta["height"], meta["width"])
    ortho = cv2.cvtColor(cv2.imread(str(path / "ortho.png")), cv2.COLOR_BGR2RGB)
    return meta, dsm, ortho


def world(meta, row, col):
    """Contract projection: x east, z south, pixel centres."""
    px = meta["pixel_size_m"]
    return (col + 0.5 - meta["width"] / 2) * px, (row + 0.5 - meta["height"] / 2) * px


def test_cone_bundle_matches_the_contract(tmp_path):
    meta = build("cone", tmp_path)
    meta, dsm, ortho = load(tmp_path)
    assert meta["contract_version"] == 4 and (meta["width"], meta["height"]) == (1025, 1025)
    assert (tmp_path / "dsm.bin").stat().st_size == 1025 * 1025 * 4
    assert np.isfinite(dsm).all()
    peak = np.unravel_index(np.argmax(dsm), dsm.shape)
    assert peak == (512, 512) and abs(dsm[peak] - 100.0) < 0.5
    assert world(meta, *peak) == (0.0, 0.0)
    assert tuple(ortho[512, 512]) == (220, 30, 30)  # red dot on the peak
    assert tuple(ortho[8, 512]) == (30, 60, 230)  # blue dot at the north edge ...
    assert world(meta, 8, 512)[1] < 0  # ... which is toward −z
    # slope on the flank: atan(100 / 400) = 14.04°
    gx = (dsm[512, 712] - dsm[512, 710]) / (2 * meta["pixel_size_m"])
    assert abs(math.degrees(math.atan(abs(gx))) - 14.04) < 0.1


def test_orientation_bundle_raises_only_the_north_west_corner(tmp_path):
    build("orientation", tmp_path)
    meta, dsm, _ = load(tmp_path)
    raised = np.argwhere(dsm > 0)
    x, z = world(meta, *raised.mean(axis=0))
    assert x < 0 and z < 0  # viewer's −x, −z corner


def test_relative_bundle_flags_assumed_scale(tmp_path):
    build("relative", tmp_path)
    meta, dsm, _ = load(tmp_path)
    assert meta["units"] == "relative" and meta["pixel_size_assumed"] is True
    assert 0.0 <= dsm.min() and dsm.max() <= 1.0
    assert meta["dem_file"] is None and not (tmp_path / "dem.bin").exists()  # no DEM, no flip


def test_big_input_is_capped_and_gaps_are_filled_and_masked(tmp_path):
    h, w = 3000, 4500
    heights = np.full((h, w), 10.0, np.float32)
    heights[:300, :300] = np.nan  # a hole
    rgb = np.zeros((h, w, 3), np.uint8)
    meta = write_bundle(
        tmp_path,
        heights,
        rgb,
        units="m",
        pixel_size_m=0.5,
        pixel_size_assumed=False,
        bounds=[0, 0, 2250, 1500],
        crs="EPSG:32644",
        calibration={},
        source_name="big",
        max_dsm_side=2048,
        max_ortho_side=4096,
    )
    assert max(meta["width"], meta["height"]) == 2048
    assert abs(meta["pixel_size_m"] - 0.5 * 4500 / 2048) < 1e-3
    _, dsm, ortho = load(tmp_path)
    assert np.isfinite(dsm).all() and meta["has_mask"]
    assert max(ortho.shape[:2]) == 4096
    mask = cv2.imread(str(tmp_path / "mask.png"), cv2.IMREAD_UNCHANGED)
    assert mask[0, 0] == 255 and mask[-1, -1] == 0


def test_dem_is_written_on_the_dsm_grid_with_the_same_gaps_filled(tmp_path):
    h, w = 3000, 4500
    terrain = np.linspace(100.0, 200.0, w, dtype=np.float32)[None, :].repeat(h, axis=0)
    heights = terrain + 5.0
    heights[:300, :300] = np.nan  # a hole in the DSM ...
    terrain[-50:, -50:] = np.nan  # ... and one in the DEM alone, under valid DSM cells
    heights[-50:, -50:] = np.nan  # (the pipeline masks the DSM wherever the DEM is missing)
    meta = write_bundle(
        tmp_path,
        heights,
        np.zeros((h, w, 3), np.uint8),
        units="m",
        pixel_size_m=0.5,
        pixel_size_assumed=False,
        bounds=[0, 0, 2250, 1500],
        crs="EPSG:32644",
        calibration={},
        source_name="dem",
        max_dsm_side=2048,
        max_ortho_side=4096,
        terrain=terrain,
    )
    assert meta["contract_version"] == 4 and meta["dem_file"] == "dem.bin"
    _, dsm, _ = load(tmp_path)
    dem = np.fromfile(tmp_path / "dem.bin", dtype="<f4").reshape(dsm.shape)
    assert np.isfinite(dem).all()
    assert np.allclose(dsm - dem, 5.0, atol=1e-3)  # same cells, same averaging, same fill
