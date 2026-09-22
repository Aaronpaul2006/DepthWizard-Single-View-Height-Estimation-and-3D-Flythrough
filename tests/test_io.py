import cv2
import numpy as np
import rasterio
from affine import Affine

from depthwizard.config import load_config
from depthwizard.io.read import read_image
from depthwizard.io.write import write_geotiff

UTM = rasterio.crs.CRS.from_epsg(32644)
TRANSFORM = Affine(0.5, 0, 331200.0, 0, -0.5, 1442868.0)


def test_png_is_not_georeferenced_and_comes_back_as_rgb(tmp_path):
    img = np.zeros((20, 30, 3), np.uint8)
    img[0, 0] = (0, 0, 255)  # cv2 writes BGR: this is pure red
    cv2.imwrite(str(tmp_path / "a.png"), img)
    raster = read_image(tmp_path / "a.png", load_config().input)
    assert raster.shape == (20, 30)
    assert not raster.georeferenced
    assert tuple(raster.rgb[0, 0]) == (255, 0, 0)


def test_oversized_images_are_downsampled_with_a_warning(tmp_path, caplog):
    cv2.imwrite(str(tmp_path / "big.png"), np.full((300, 600, 3), 80, np.uint8))
    cfg = load_config().input
    cfg.max_long_side = 150
    with caplog.at_level("WARNING"):
        raster = read_image(tmp_path / "big.png", cfg)
    assert raster.shape == (75, 150)
    assert "downsampling" in caplog.text


def test_16bit_multiband_geotiff_is_stretched_and_georeferenced(tmp_path):
    data = np.random.default_rng(0).integers(0, 4000, (4, 32, 48), dtype=np.uint16)
    profile = dict(
        driver="GTiff", height=32, width=48, count=4, dtype="uint16", crs=UTM, transform=TRANSFORM
    )
    with rasterio.open(tmp_path / "ms.tif", "w", **profile) as dst:
        dst.write(data)
    raster = read_image(tmp_path / "ms.tif", load_config().input)
    assert raster.rgb.dtype == np.uint8 and raster.rgb.shape == (32, 48, 3)
    assert raster.georeferenced and raster.crs == UTM
    assert raster.rgb.min() == 0 and raster.rgb.max() == 255


def test_geotiff_writer_round_trip(tmp_path):
    grid = np.arange(12, dtype=np.float32).reshape(3, 4)
    grid[1, 2] = np.nan
    write_geotiff(tmp_path / "d.tif", grid, UTM, TRANSFORM, -9999.0, {"DW_MODE": "absolute"})
    with rasterio.open(tmp_path / "d.tif") as src:
        back = src.read(1)
        assert src.nodata == -9999.0 and src.crs == UTM and src.transform == TRANSFORM
        assert src.tags()["DW_MODE"] == "absolute"
        assert src.profile["compress"] == "lzw"
    assert back[1, 2] == -9999.0
    assert back[0, 3] == 3.0
