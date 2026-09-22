"""Stage 2 tiling and blending, checked with a fake model (no GPU or weights needed)."""

import numpy as np

from depthwizard.config import load_config
from depthwizard.depth.model import DepthModel
from depthwizard.depth.stitch import align_to_global, predict_tiled, seam_ratio
from depthwizard.depth.tiling import tile_origins, window2d


class FakeModel(DepthModel):
    """Each forward pass returns a *different* random affine of channel 0, mimicking the
    per-tile scale/shift ambiguity of a relative depth model."""

    def __init__(self, seed: int = 0):
        self.rng = np.random.default_rng(seed)

    def predict_batch(self, batch):
        out = []
        for img in batch:
            a, b = self.rng.uniform(0.3, 3.0), self.rng.uniform(-100, 100)
            out.append(a * img[..., 0].astype(np.float32) + b)
        return np.stack(out)


def synthetic_scene(h=1500, w=1300):
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    surface = 60 + 40 * np.sin(xx / 210) * np.cos(yy / 170)
    for y0, x0, size, height in [(200, 300, 90, 80), (900, 700, 140, 60), (1200, 150, 70, 100)]:
        surface[y0 : y0 + size, x0 : x0 + size] += height
    img = np.clip(surface, 0, 255).astype(np.uint8)
    return np.dstack([img, img, img]), surface


def test_tiles_cover_the_image_and_weights_stay_positive():
    for n in (518, 519, 777, 1036, 1500):
        starts = tile_origins(n, 518, 259)
        assert starts[0] == 0 and starts[-1] + 518 == max(n, 518)
    h, w = 1100, 800
    wsum = np.zeros((h, w), np.float32)
    for y in tile_origins(h, 518, 259):
        for x in tile_origins(w, 518, 259):
            wsum[y : y + 518, x : x + 518] += window2d(y, x, 518, h, w)
    assert wsum.min() > 0.05


def test_alignment_recovers_scale_and_shift_despite_outliers():
    rng = np.random.default_rng(1)
    g = rng.normal(size=(64, 64)).astype(np.float32)
    t = (g - 7.0) / 2.5
    t.ravel()[:100] += 50.0  # 2.4% outliers
    a, b = align_to_global(t, g, trim_frac=0.05)
    assert abs(a - 2.5) < 1e-3 and abs(b - 7.0) < 1e-2


def test_stitched_depth_matches_truth_without_seams():
    cfg = load_config().depth
    rgb, truth = synthetic_scene()
    d = predict_tiled(FakeModel(), rgb, cfg)
    assert d.shape == truth.shape
    r = np.corrcoef(d.ravel(), rgb[..., 0].ravel().astype(np.float64))[0, 1]
    assert r > 0.999
    assert seam_ratio(d, cfg) < 1.1


def test_small_images_use_the_global_pass_only():
    cfg = load_config().depth
    rgb, _ = synthetic_scene(400, 600)
    assert predict_tiled(FakeModel(), rgb, cfg).shape == (400, 600)
