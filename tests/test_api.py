"""Jobs API end to end with the real model. Skipped when the model or eval data isn't present."""

import time

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from depthwizard.config import REPO_ROOT

MODEL = REPO_ROOT / "data" / "models" / "Depth-Anything-V2-Small-hf" / "config.json"
TILE = REPO_ROOT / "data" / "datasets" / "naip3dep" / "denver" / "0_1"
DEM_CACHE = REPO_ROOT / "data" / "cache" / "copernicus"

pytestmark = pytest.mark.skipif(not MODEL.exists(), reason="needs the model in data/models/")


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    import api.main as main

    # Test jobs go to a temporary folder, never into data/jobs (the user's terrain list).
    main.cfg.paths.jobs = str(tmp_path_factory.mktemp("jobs"))
    with TestClient(main.app) as c:
        yield c


def wait(client, job_id, timeout_s=300):
    start = time.time()
    while time.time() - start < timeout_s:
        status = client.get(f"/api/jobs/{job_id}").json()
        assert set(status) == {"status", "stage", "progress", "message"}
        if status["status"] in ("done", "error"):
            return status
        time.sleep(0.25)
    raise TimeoutError(job_id)


def bundle(client, job_id):
    meta = client.get(f"/api/jobs/{job_id}/bundle/meta.json").json()
    dsm = client.get(f"/api/jobs/{job_id}/bundle/dsm.bin").content
    assert len(dsm) == meta["width"] * meta["height"] * 4
    assert client.get(f"/api/jobs/{job_id}/bundle/ortho.png").status_code == 200
    return meta, np.frombuffer(dsm, "<f4")


def test_health_and_errors(client):
    health = client.get("/api/health").json()
    assert health["ok"] and health["model_loaded"]
    assert client.get("/api/jobs/doesnotexist").status_code == 404
    bad = client.post("/api/jobs", files={"image": ("notes.txt", b"hello", "text/plain")})
    assert bad.status_code == 400


def test_viewer_page_is_always_rechecked(client):
    from api.main import VIEWER_DIST

    if not (VIEWER_DIST / "index.html").exists():
        pytest.skip("viewer not built")
    page = client.get("/")
    assert page.status_code == 200 and page.headers["cache-control"] == "no-cache"


def test_corrupt_image_fails_cleanly_and_the_worker_survives(client):
    broken = client.post("/api/jobs", files={"image": ("broken.tif", b"not a tiff", "image/tiff")})
    status = wait(client, broken.json()["job_id"])
    assert status["status"] == "error" and status["message"]
    assert client.get("/api/health").json()["ok"]


def test_png_gives_a_relative_bundle(client, tmp_path):
    img = np.random.default_rng(0).integers(0, 255, (300, 400, 3), dtype=np.uint8)
    cv2.imwrite(str(tmp_path / "a.png"), img)
    with open(tmp_path / "a.png", "rb") as f:
        job_id = client.post("/api/jobs", files={"image": ("a.png", f, "image/png")}).json()[
            "job_id"
        ]
    assert wait(client, job_id)["status"] == "done"
    meta, dsm = bundle(client, job_id)
    assert meta["units"] == "relative" and meta["pixel_size_assumed"] is True
    assert meta["crs"] is None and meta["bounds"] is None
    assert np.isfinite(dsm).all() and dsm.min() >= 0 and dsm.max() <= 1
    assert client.get(f"/api/jobs/{job_id}/dsm.tif").status_code == 200
    listed = client.get("/api/jobs").json()  # the viewer's terrain switcher
    entry = next(r for r in listed if r["job_id"] == job_id)
    assert entry["name"] == "a.png" and entry["units"] == "relative"


@pytest.mark.skipif(
    not TILE.exists() or not any(DEM_CACHE.glob("*.tif")), reason="needs NAIP tiles and DEM cache"
)
def test_geotiff_is_metric_and_validates(client, tmp_path):
    with open(TILE / "image.tif", "rb") as f:
        job_id = client.post("/api/jobs", files={"image": ("scene.tif", f, "image/tiff")}).json()[
            "job_id"
        ]
    assert wait(client, job_id)["status"] == "done"
    meta, dsm = bundle(client, job_id)
    assert meta["units"] == "m" and meta["crs"] and len(meta["bounds"]) == 4
    assert meta["calibration"]["dem_source"] == "copernicus_glo30"
    assert np.isfinite(dsm).all()

    with open(TILE / "dsm.tif", "rb") as f:
        lidar = client.post(f"/api/jobs/{job_id}/validate", files={"reference": ("dsm.tif", f)})
    report = lidar.json()
    assert lidar.status_code == 200, report
    assert {"rmse", "mae", "bias", "nmad", "pearson_r", "n_pixels", "units"} <= set(report)
    err = client.get(f"/api/jobs/{job_id}/bundle/error.bin").content
    assert len(err) == meta["width"] * meta["height"] * 4

    # Acceptance test 4, backend side: a result validated against itself has zero error.
    own = client.get(f"/api/jobs/{job_id}/dsm.tif").content
    (tmp_path / "own.tif").write_bytes(own)
    with open(tmp_path / "own.tif", "rb") as f:
        same = client.post(f"/api/jobs/{job_id}/validate", files={"reference": ("own.tif", f)})
    assert same.json()["rmse"] < 1e-3
