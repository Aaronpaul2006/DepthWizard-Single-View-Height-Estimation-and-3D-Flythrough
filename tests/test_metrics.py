import numpy as np
import rasterio
from affine import Affine

from depthwizard.io.write import write_geotiff
from evals.metrics import dsm_metrics, object_mask, reference_on_grid, relative_metrics

UTM = rasterio.crs.CRS.from_epsg(32613)


def test_metrics_separate_datum_offset_from_shape_error():
    rng = np.random.default_rng(0)
    ref = rng.normal(100, 10, (200, 200)).astype(np.float32)
    noise = rng.normal(0, 1, ref.shape).astype(np.float32)
    pred = ref + 5.0 + noise  # 5 m datum offset plus 1 m noise
    pred[0, 0] = np.nan
    m = dsm_metrics(pred, ref)
    assert m["n_pixels"] == ref.size - 1
    assert abs(m["bias"] - 5.0) < 0.05
    assert abs(m["rmse"] - np.sqrt(26)) < 0.05
    assert abs(m["offset_free_rmse"] - 1.0) < 0.05
    assert abs(m["nmad"] - 1.0) < 0.05
    assert m["pearson_r"] > 0.99


def test_relative_metrics_are_scale_aligned():
    ref = np.linspace(0, 30, 400, dtype=np.float32).reshape(20, 20)
    m = relative_metrics(0.01 * ref - 4.0, ref)
    assert m["scale_aligned"] and m["rmse"] < 1e-4 and abs(m["align_a"] - 100) < 1e-3


def test_object_mask_uses_height_above_ground():
    dsm = np.array([[10.0, 14.0], [np.nan, 11.0]])
    dtm = np.array([[10.0, 10.0], [10.0, 10.0]])
    assert object_mask(dsm, dtm, 2.5).tolist() == [[False, True], [False, False]]


def test_reference_is_reprojected_onto_the_prediction_grid(tmp_path):
    grid = np.arange(16, dtype=np.float32).reshape(4, 4)
    t = Affine(2.0, 0, 500000.0, 0, -2.0, 4400000.0)
    write_geotiff(tmp_path / "ref.tif", grid, UTM, t, -9999.0)
    same = reference_on_grid(tmp_path / "ref.tif", UTM, t, (4, 4))
    assert np.allclose(same, grid)
    fine = reference_on_grid(
        tmp_path / "ref.tif", UTM, Affine(1.0, 0, 500000.0, 0, -1.0, 4400000.0), (8, 8)
    )
    assert fine.shape == (8, 8) and np.nanmin(fine) >= 0 and np.nanmax(fine) <= 15
