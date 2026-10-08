"""DepthWizard backend: the jobs API plus the built viewer (ARCHITECTURE.md, VIEWER_CONTRACT.md).

    uvicorn api.main:app --port 8000        then open http://localhost:8000

Local app: no auth. The model loads once at startup; jobs run one at a time on the GPU.
"""

from __future__ import annotations

import json
import logging
import shutil
from contextlib import asynccontextmanager
from pathlib import Path

import torch
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from api.jobs import Job, JobQueue
from api.validate import validate_job
from depthwizard.config import REPO_ROOT, load_config, resolve_path
from depthwizard.depth.model import DepthModel
from depthwizard.io.read import SUPPORTED_SUFFIXES

log = logging.getLogger("depthwizard.api")

VIEWER_DIST = REPO_ROOT / "viewer" / "dist"
BUNDLE_FILES = {
    "meta.json": "application/json",
    "dsm.bin": "application/octet-stream",
    "ortho.png": "image/png",
    "mask.png": "image/png",
    "error.bin": "application/octet-stream",
    "reference.bin": "application/octet-stream",
    "dem.bin": "application/octet-stream",
}
RASTER_SUFFIXES = {".tif", ".tiff"}

cfg = load_config()
state: dict = {}


@asynccontextmanager
async def lifespan(_app: FastAPI):
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    try:
        model = DepthModel(cfg.model)
    except FileNotFoundError as e:  # keep serving the viewer; jobs report the problem
        log.error("%s", e)
        model = None
    state["model"] = model
    state["jobs"] = JobQueue(cfg, model, resolve_path(cfg.paths.jobs))
    yield


app = FastAPI(title="DepthWizard", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=cfg.api.cors_origins, allow_methods=["*"], allow_headers=["*"]
)


def _suffix(upload: UploadFile, allowed: set[str], field: str) -> str:
    suffix = Path(upload.filename or "").suffix.lower()
    if suffix not in allowed:
        raise HTTPException(400, f"{field}: expected one of {', '.join(sorted(allowed))}")
    return suffix


def _save(upload: UploadFile, dest: Path) -> Path:
    with dest.open("wb") as f:
        shutil.copyfileobj(upload.file, f, length=1 << 20)
    if dest.stat().st_size > cfg.api.max_upload_mb * 2**20:
        dest.unlink()
        raise HTTPException(413, f"{upload.filename} is larger than {cfg.api.max_upload_mb} MB.")
    return dest


def _job(job_id: str) -> Job:
    job = state["jobs"].get(job_id)
    if job is None:
        raise HTTPException(404, "Unknown job.")
    return job


@app.post("/api/jobs")
def create_job(
    image: UploadFile = File(...),
    dem: UploadFile | None = File(None),
    gcps: UploadFile | None = File(None),
    gsd_m: float | None = Form(None),
):
    if gsd_m is not None and not gsd_m > 0:
        raise HTTPException(400, "gsd_m must be a positive number of metres per pixel.")
    image_suffix = _suffix(image, SUPPORTED_SUFFIXES, "image")
    has_dem, has_gcps = bool(dem and dem.filename), bool(gcps and gcps.filename)
    dem_suffix = _suffix(dem, RASTER_SUFFIXES, "dem") if has_dem else None
    jobs: JobQueue = state["jobs"]
    job_id, job_dir = jobs.new_job_dir()
    inputs = job_dir / "input"

    # Keep original file names, made filesystem-safe: the image name labels the result in the
    # viewer, and the DEM name tells the pipeline which DEM it is, and so which vertical datum.
    def safe(upload: UploadFile) -> str:
        stem = "".join(c if c.isalnum() or c in "-_" else "_" for c in Path(upload.filename).stem)
        return stem[:64] or "upload"

    (inputs / "image").mkdir()
    image_path = _save(image, inputs / "image" / f"{safe(image)}{image_suffix}")
    dem_path = None
    if has_dem:
        (inputs / "dem").mkdir()
        dem_path = _save(dem, inputs / "dem" / f"{safe(dem)}{dem_suffix}")
    job = Job(
        id=job_id,
        dir=job_dir,
        image=image_path,
        dem=dem_path,
        gcps=_save(gcps, inputs / "gcps.csv") if has_gcps else None,
        gsd_m=gsd_m,
    )
    request = {
        "image": image.filename,
        "dem": dem.filename if has_dem else None,
        "gcps": gcps.filename if has_gcps else None,
        "gsd_m": gsd_m,
    }
    (job_dir / "request.json").write_text(json.dumps(request, indent=2), encoding="utf-8")
    jobs.submit(job)
    return {"job_id": job_id}


@app.get("/api/jobs")
def list_jobs():
    """Finished results, newest first, for the viewer's terrain switcher."""
    return state["jobs"].list_results()


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    return _job(job_id).public()


@app.get("/api/jobs/{job_id}/bundle/{name}")
def bundle_file(job_id: str, name: str):
    if name not in BUNDLE_FILES:
        raise HTTPException(404, "Not a bundle file.")
    path = _job(job_id).out / "bundle" / name
    if not path.exists():
        raise HTTPException(404, f"{name} is not available for this job.")
    return FileResponse(path, media_type=BUNDLE_FILES[name])


@app.get("/api/jobs/{job_id}/dsm.tif")
def dsm_geotiff(job_id: str):
    out = _job(job_id).out
    for stem in ("dsm", "rdsm"):
        path = out / f"{stem}.tif"
        if path.exists():
            return FileResponse(path, media_type="image/tiff", filename=f"{job_id}_{stem}.tif")
    raise HTTPException(404, "The DSM is not ready yet.")


@app.post("/api/jobs/{job_id}/validate")
def validate(job_id: str, reference: UploadFile = File(...)):
    job = _job(job_id)
    if job.status != "done":
        raise HTTPException(409, "The job has not finished yet.")
    ref = _save(reference, job.dir / f"reference{_suffix(reference, RASTER_SUFFIXES, 'reference')}")
    try:
        return validate_job(job.out, ref)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.get("/api/health")
def health():
    model: DepthModel | None = state.get("model")
    return {
        "ok": True,
        "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        "model_loaded": model is not None,
        "device": model.describe_device() if model else None,
    }


class ViewerFiles(StaticFiles):
    """The built viewer. Its HTML must be rechecked on every load: without this, the desktop
    app's WebView2 keeps serving a cached index.html (and so the old viewer) after an update.
    The JS/CSS it links have content hashes in their names, so they may still be cached."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        if response.media_type == "text/html":
            response.headers["Cache-Control"] = "no-cache"
        return response


if VIEWER_DIST.exists():
    app.mount("/", ViewerFiles(directory=VIEWER_DIST, html=True), name="viewer")
else:

    @app.get("/", response_class=PlainTextResponse)
    def viewer_missing():
        return "Viewer not built. Run: cd viewer && npm ci && npm run build"
