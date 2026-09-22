"""The app must still run, slowly, on a machine without a GPU (CLAUDE.md, Hardware)."""

import cv2
import numpy as np
import pytest
import rasterio

from depthwizard.config import REPO_ROOT, load_config
from depthwizard.pipeline import run

MODEL = REPO_ROOT / "data" / "models" / "Depth-Anything-V2-Small-hf" / "config.json"


@pytest.mark.skipif(not MODEL.exists(), reason="needs the model in data/models/")
def test_pipeline_runs_on_cpu(tmp_path):
    cfg = load_config()
    cfg.model.device = "cpu"
    image = np.random.default_rng(0).integers(0, 255, (200, 260, 3), dtype=np.uint8)
    cv2.imwrite(str(tmp_path / "small.png"), image)
    result = run(tmp_path / "small.png", tmp_path / "out", cfg)
    assert result.info["device"] == "cpu" and result.mode == "relative"
    with rasterio.open(result.files["rdsm_tif"]) as src:
        assert src.read(1).shape == (200, 260)
    assert (tmp_path / "out" / "bundle" / "meta.json").exists()
