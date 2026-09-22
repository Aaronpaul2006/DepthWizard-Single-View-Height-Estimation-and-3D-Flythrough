"""Background jobs: one worker thread for the one GPU, jobs run in submission order.

Job files live in data/jobs/<id>/ (input/, out/, request.json). Finished jobs survive a
restart: an id with a bundle on disk is served as done, and list_results() finds them all.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path

from depthwizard.config import Config
from depthwizard.depth.model import DepthModel
from depthwizard.pipeline import run

log = logging.getLogger(__name__)

# Share of the progress bar per contract stage; depth dominates the runtime.
STAGE_SPAN = {"depth": (0.0, 0.8), "calibrate": (0.8, 0.95), "export": (0.95, 1.0)}
STAGE_MESSAGE = {
    "depth": "Estimating relative height",
    "calibrate": "Calibrating to metres",
    "export": "Writing the DSM and viewer bundle",
}


@dataclass
class Job:
    id: str
    dir: Path
    image: Path | None = None
    dem: Path | None = None
    gcps: Path | None = None
    gsd_m: float | None = None
    status: str = "queued"  # queued | running | done | error
    stage: str = "depth"  # depth | calibrate | export
    progress: float = 0.0
    message: str = "Waiting for the GPU"

    @property
    def out(self) -> Path:
        return self.dir / "out"

    def public(self) -> dict:
        return {
            "status": self.status,
            "stage": self.stage,
            "progress": round(self.progress, 3),
            "message": self.message,
        }


def valid_job_id(job_id: str) -> bool:
    return 0 < len(job_id) <= 32 and job_id.isalnum()


class JobQueue:
    def __init__(self, cfg: Config, model: DepthModel | None, root: Path):
        self.cfg, self.model, self.root = cfg, model, root
        self.root.mkdir(parents=True, exist_ok=True)
        self.jobs: dict[str, Job] = {}
        self._queue: queue.Queue[Job] = queue.Queue()
        threading.Thread(target=self._work, name="depthwizard-worker", daemon=True).start()

    def new_job_dir(self) -> tuple[str, Path]:
        job_id = uuid.uuid4().hex[:12]
        job_dir = self.root / job_id
        (job_dir / "input").mkdir(parents=True)
        return job_id, job_dir

    def submit(self, job: Job) -> None:
        self.jobs[job.id] = job
        self._queue.put(job)

    def get(self, job_id: str) -> Job | None:
        if not valid_job_id(job_id):
            return None
        return self.jobs.get(job_id) or self._restore(job_id)

    def list_results(self) -> list[dict]:
        """Every finished result on disk, newest first: what the viewer's terrain switcher shows."""
        results = []
        for meta_path in self.root.glob("*/out/bundle/meta.json"):
            job_id = meta_path.parents[2].name
            if not valid_job_id(job_id):
                continue
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue  # a bundle being written right now, or a damaged one
            results.append(
                {
                    "job_id": job_id,
                    "name": meta.get("source_name") or job_id,
                    "units": meta.get("units"),
                    "width": meta.get("width"),
                    "height": meta.get("height"),
                    "pixel_size_m": meta.get("pixel_size_m"),
                    "crs": meta.get("crs"),
                    "calibration": meta.get("calibration") or {},
                    "finished": meta_path.stat().st_mtime,
                }
            )
        return sorted(results, key=lambda r: r["finished"], reverse=True)

    def _restore(self, job_id: str) -> Job | None:
        job_dir = self.root / job_id
        if not (job_dir / "out" / "bundle" / "meta.json").exists():
            return None
        job = Job(id=job_id, dir=job_dir, status="done", stage="export", progress=1.0)
        job.message = "Finished earlier"
        self.jobs[job_id] = job
        return job

    def _work(self) -> None:
        while True:
            job = self._queue.get()
            job.status, job.message = "running", STAGE_MESSAGE["depth"]
            try:
                if self.model is None:
                    raise RuntimeError(
                        "The depth model is not loaded. Run `python scripts/fetch_model.py` once."
                    )
                result = run(
                    job.image,
                    job.out,
                    self.cfg,
                    model=self.model,
                    progress=lambda stage, frac, job=job: self._progress(job, stage, frac),
                    dem_path=job.dem,
                    gcps_path=job.gcps,
                    gsd_m=job.gsd_m,
                )
                job.status, job.stage, job.progress = "done", "export", 1.0
                job.message = " ".join(result.warnings) or f"{result.mode.capitalize()} DSM ready"
            except Exception as e:  # any failure must reach the UI, not kill the worker
                log.exception("Job %s failed", job.id)
                job.status, job.message = "error", str(e) or type(e).__name__
            finally:
                self._queue.task_done()

    @staticmethod
    def _progress(job: Job, stage: str, frac: float) -> None:
        lo, hi = STAGE_SPAN[stage]
        job.stage = stage
        job.progress = lo + (hi - lo) * min(max(frac, 0.0), 1.0)
        job.message = STAGE_MESSAGE[stage]
