"""Geoid conversion of ellipsoidal DEMs, and input nodata / alpha masks."""

import cv2
import numpy as np
import rasterio
from affine import Affine
from rasterio.crs import CRS

from depthwizard.calibrate.dem import Dem, to_geoid_heights
from depthwizard.config import load_config
from depthwizard.io.read import read_image
from depthwizard.io.write import write_geotiff

UTM45 = CRS.from_epsg(32645)
GRID = Affine(30.0, 0, 634000.0, 0, -30.0, 3006000.0)  # UTM 45N near Namchi, 27.16 N 88.36 E


def geoid_file(tmp_path, undulation_m: float):
    """A small EPSG:4326 geoid grid with a constant undulation, stored as scaled integers."""
    raw = np.full((40, 40), undulation_m / 0.01, np.int16)  # value = raw * 0.01
    path = tmp_path / "geoid.tif"
    profile = dict(
        driver="GTiff",
        height=40,
        width=40,
        count=1,
        dtype="int16",
        crs="EPSG:4326",
        transform=Affine(0.05, 0, 87.5, 0, -0.05, 28.0),
    )
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(raw, 1)
        dst.scales, dst.offsets = (0.01,), (0.0,)
    return path


def dem(source: str) -> Dem:
    return Dem(np.full((20, 20), 1000.0, np.float32), source, 30.0, "whatever", [])


def test_ellipsoidal_cartodem_is_converted_to_geoid_heights(tmp_path):
    out = to_geoid_heights(dem("cartodem"), geoid_file(tmp_path, -43.8), UTM45, GRID)
    assert np.allclose(out.heights, 1043.8, atol=0.01)  # H = h − N
    assert out.datum.startswith("EGM2008")


def test_other_dems_and_a_missing_grid_pass_through(tmp_path):
    grid = geoid_file(tmp_path, -43.8)
    assert to_geoid_heights(dem("copernicus_glo30"), grid, UTM45, GRID).heights[0, 0] == 1000.0
    kept = to_geoid_heights(dem("cartodem"), tmp_path / "missing.tif", UTM45, GRID)
    assert kept.heights[0, 0] == 1000.0 and kept.datum == "whatever"


def test_geotiff_nodata_becomes_invalid(tmp_path):
    rgb = np.full((3, 20, 30), 120, np.uint8)
    rgb[:, :, :5] = 0  # black collar marked as nodata
    profile = dict(
        driver="GTiff",
        height=20,
        width=30,
        count=3,
        dtype="uint8",
        crs=UTM45,
        transform=GRID,
        nodata=0,
    )
    with rasterio.open(tmp_path / "collar.tif", "w", **profile) as dst:
        dst.write(rgb)
    raster = read_image(tmp_path / "collar.tif", load_config().input)
    assert raster.valid is not None
    assert not raster.valid[:, :5].any() and raster.valid[:, 5:].all()


def test_png_alpha_becomes_invalid_and_opaque_images_have_no_mask(tmp_path):
    bgra = np.full((10, 12, 4), 200, np.uint8)
    bgra[:4, :, 3] = 0  # transparent top rows
    cv2.imwrite(str(tmp_path / "a.png"), bgra)
    raster = read_image(tmp_path / "a.png", load_config().input)
    assert raster.valid is not None and not raster.valid[:4].any() and raster.valid[4:].all()
    write_geotiff(tmp_path / "plain.tif", np.ones((5, 5), np.float32), UTM45, GRID, -9999.0)
    cv2.imwrite(str(tmp_path / "opaque.png"), np.full((6, 6, 3), 90, np.uint8))
    assert read_image(tmp_path / "opaque.png", load_config().input).valid is None
