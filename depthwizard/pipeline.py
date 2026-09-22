"""End-to-end pipeline: run(input, options) -> Result."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import rasterio
import requests
import torch
from rasterio.transform import array_bounds

from depthwizard import __version__
from depthwizard.calibrate.dem import (
    Dem,
    dem_files,
    fetch_copernicus,
    image_bounds_lonlat,
    infer_source,
    load_dem,
    to_geoid_heights,
)
from depthwizard.calibrate.fit import method_b
from depthwizard.calibrate.gcp import read_gcps
from depthwizard.calibrate.relative import normalize_relative
from depthwizard.config import Config, resolve_path
from depthwizard.depth.model import DepthModel
from depthwizard.depth.stitch import predict_tiled
from depthwizard.export.bundle import write_bundle
from depthwizard.export.preview import write_png16
from depthwizard.io.geo import ground_pixel_size_m, reproject_to_utm
from depthwizard.io.read import Raster, read_image
from depthwizard.io.write import write_geotiff

log = logging.getLogger(__name__)

ProgressFn = Callable[[str, float], None]  # (stage, fraction of that stage done)


@dataclass
class Result:
    out_dir: Path
    mode: str = "relative"  # relative | absolute
    files: dict[str, Path] = field(default_factory=dict)
    timings_s: dict[str, float] = field(default_factory=dict)
    info: dict[str, object] = field(default_factory=dict)
    calibration: dict[str, object] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


@contextmanager
def timed(result: Result, stage: str) -> Iterator[None]:
    start = time.perf_counter()
    yield
    result.timings_s[stage] = time.perf_counter() - start
    log.info("stage %-10s %.2f s", stage, result.timings_s[stage])


def run(
    input_path: str | Path,
    out_dir: str | Path,
    cfg: Config,
    model: DepthModel | None = None,
    progress: ProgressFn | None = None,
    dem_path: str | Path | None = None,
    gcps_path: str | Path | None = None,
    gsd_m: float | None = None,
    allow_fetch: bool = True,
) -> Result:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    result = Result(out_dir=out)
    report = progress or (lambda stage, frac: None)
    if model is None:
        with timed(result, "load_model"):
            model = DepthModel(cfg.model)

    with timed(result, "read"):
        raster = reproject_to_utm(read_image(input_path, cfg.input))
    h, w = raster.shape
    valid = raster.valid if raster.valid is not None else np.ones((h, w), bool)
    result.info.update(
        source_name=raster.name,
        width=w,
        height=h,
        georeferenced=raster.georeferenced,
        crs=raster.crs.to_string() if raster.georeferenced else None,
        pixel_size_m=(
            ground_pixel_size_m(raster.crs, raster.transform, h, w)
            if raster.georeferenced
            else gsd_m
        ),
        device=model.describe_device(),
    )
    log.info("Read %s: %dx%d, georeferenced=%s", raster.name, w, h, raster.georeferenced)

    with timed(result, "depth"):
        d = _depth(model, raster.rgb, cfg, lambda frac: report("depth", frac))

    dsm = None
    if raster.georeferenced:
        report("calibrate", 0.0)
        with timed(result, "calibrate"):
            dem = _load_dem(raster, cfg, dem_path, allow_fetch, result)
            if dem is not None:
                gcps = (
                    read_gcps(gcps_path, raster.crs, raster.transform, (h, w))
                    if gcps_path
                    else None
                )
                cal = method_b(
                    d, dem.heights, dem.res_m, result.info["pixel_size_m"], cfg.calibration, gcps
                )
                dsm = np.where(valid & np.isfinite(dem.heights), cal.dsm, np.nan)
                result.mode = "absolute"
                result.calibration = {
                    "method": cal.method,
                    "confidence": cal.confidence,
                    "dem_source": dem.source,
                    "dem_datum": dem.datum,
                    "dem_res_m": round(dem.res_m, 2),
                    "scale": cal.scale,
                    **cal.details,
                }
        report("calibrate", 1.0)

    report("export", 0.0)
    with timed(result, "export"):
        if dsm is None:
            grid = normalize_relative(np.where(valid, d, np.nan), cfg.relative.norm_percentiles)
            _export(result, "rdsm", grid, raster, cfg, {"DW_MODE": "relative"}, (0.0, 100.0))
            units = "relative"
            viewer_cal = {"method": "none", "confidence": "n/a", "dem_source": None}
        else:
            grid = dsm
            tags = {
                "DW_MODE": "absolute",
                "DW_CAL_METHOD": result.calibration["method"],
                "DW_CAL_CONFIDENCE": result.calibration["confidence"],
                "DW_DEM_SOURCE": result.calibration["dem_source"],
                "DW_DEM_DATUM": result.calibration["dem_datum"],
            }
            _export(result, "dsm", dsm, raster, cfg, tags, tuple(cfg.relative.norm_percentiles))
            units = "m"
            viewer_cal = {k: result.calibration[k] for k in ("method", "confidence", "dem_source")}
        _export_bundle(result, grid, raster, cfg, units, viewer_cal, valid, gsd_m)

    result.files["run_json"] = out / "run.json"
    _write_run_json(result, cfg)
    report("export", 1.0)
    return result


def _depth(model: DepthModel, rgb: np.ndarray, cfg: Config, progress) -> np.ndarray:
    try:
        return predict_tiled(model, rgb, cfg.depth, progress)
    except torch.cuda.OutOfMemoryError:
        log.warning("CUDA out of memory even at batch size 1; continuing on the CPU (slow).")
        model.to_cpu()
        return predict_tiled(model, rgb, cfg.depth, progress)


def _load_dem(
    raster: Raster, cfg: Config, dem_path, allow_fetch: bool, result: Result
) -> Dem | None:
    """User DEM if given, else Copernicus GLO-30 (cached after the first fetch). Any failure
    degrades to a relative DSM with a warning rather than failing the job."""
    h, w = raster.shape
    try:
        if dem_path:
            files = dem_files(dem_path)
            source = infer_source(files[0])
        elif allow_fetch:
            bounds = image_bounds_lonlat(raster.crs, raster.transform, h, w)
            cache = resolve_path(cfg.paths.cache) / cfg.dem.cache_subdir
            files = fetch_copernicus(bounds, cache, cfg.dem.copernicus_url, cfg.dem.fetch_timeout_s)
            source = "copernicus_glo30"
        else:
            raise FileNotFoundError("no DEM given and fetching is disabled")
        dem = load_dem(files, source, raster.crs, raster.transform, (h, w), cfg.dem.resampling)
        geoid = resolve_path(cfg.dem.geoid_grid)
        return to_geoid_heights(dem, geoid, raster.crs, raster.transform)
    except (OSError, ValueError, requests.RequestException, rasterio.errors.RasterioError) as e:
        message = f"No usable DEM ({e}); output is a relative DSM."
        log.warning(message)
        result.warnings.append(message)
        return None


def _export(result, stem, grid, raster, cfg, tags, preview_percentiles) -> None:
    tif, png = result.out_dir / f"{stem}.tif", result.out_dir / f"{stem}_preview.png"
    tags = {**tags, "DW_VERSION": __version__}
    write_geotiff(tif, grid, raster.crs, raster.transform, cfg.export.nodata, tags)
    write_png16(png, grid, preview_percentiles)
    result.files[f"{stem}_tif"], result.files[f"{stem}_preview_png"] = tif, png


def _export_bundle(result, grid, raster, cfg, units, calibration, valid, gsd_m) -> None:
    """Viewer bundle (VIEWER_CONTRACT.md) in <out>/bundle/."""
    h, w = raster.shape
    if raster.georeferenced:
        pixel_size_m, assumed = result.info["pixel_size_m"], False
        bounds, crs = list(array_bounds(h, w, raster.transform)), raster.crs.to_string()
        bounds = [bounds[0], bounds[1], bounds[2], bounds[3]]  # minx, miny, maxx, maxy
    else:
        pixel_size_m, assumed = (gsd_m, False) if gsd_m else (1.0, True)
        bounds = crs = None
    bundle = result.out_dir / "bundle"
    meta = write_bundle(
        bundle,
        grid,
        raster.rgb,
        units=units,
        pixel_size_m=pixel_size_m,
        pixel_size_assumed=assumed,
        bounds=bounds,
        crs=crs,
        calibration=calibration,
        source_name=raster.name,
        max_dsm_side=cfg.export.viewer_max_dsm_side,
        max_ortho_side=cfg.export.viewer_max_ortho_side,
        valid=valid,
    )
    result.files["bundle"] = bundle
    result.info["bundle"] = {k: meta[k] for k in ("width", "height", "pixel_size_m", "units")}


def _write_run_json(result: Result, cfg: Config) -> None:
    record = {
        "version": __version__,
        "mode": result.mode,
        "info": result.info,
        "calibration": result.calibration,
        "warnings": result.warnings,
        "timings_s": {k: round(v, 3) for k, v in result.timings_s.items()},
        "files": {k: v.name for k, v in result.files.items()},
        "config": cfg.to_dict(),
    }
    result.files["run_json"].write_text(json.dumps(record, indent=2), encoding="utf-8")
