"""Is CartoDEM V3R1 ellipsoidal? Compare every local CartoDEM tile with Copernicus GLO-30.

Copernicus heights are orthometric (EGM2008). If CartoDEM heights are ellipsoidal (WGS84),
CartoDEM − Copernicus equals the EGM2008 geoid undulation N, because ellipsoidal height =
orthometric height + N. The check runs on each tile's own 1 arc-second grid and reports the
median difference, its NMAD, the correlation, the median N, and the median difference left
after the pipeline's geoid correction (CartoDEM − N − Copernicus).

    python -m evals.datum_check        -> evals/results/datum-<time>/metrics.json

Reads every tile under data/dem/cartodem/ (a single-user NRSC licence: never commit them).
Downloads the matching Copernicus tiles once into the DEM cache.
"""

from __future__ import annotations

import json
import time

import numpy as np
import rasterio
from rasterio.warp import Resampling, reproject

from depthwizard.calibrate.dem import dem_files, fetch_copernicus
from depthwizard.config import REPO_ROOT, load_config, resolve_path

CARTODEM_DIR = REPO_ROOT / "data" / "dem" / "cartodem"
RESULTS = REPO_ROOT / "evals" / "results"
# Pull the tile bounds in slightly so only the matching 1° Copernicus tile is fetched.
EDGE_DEG = 0.01


def _on_grid(path, shape, transform, crs, scaled: bool = False) -> np.ndarray:
    out = np.full(shape, np.nan, np.float32)
    with rasterio.open(path) as src:
        reproject(
            rasterio.band(src, 1),
            out,
            src_nodata=src.nodata,
            dst_transform=transform,
            dst_crs=crs,
            dst_nodata=np.nan,
            resampling=Resampling.bilinear,
        )
        if scaled:  # PROJ geoid grids may store scaled integers
            out = out * src.scales[0] + src.offsets[0]
    return out


def check_tile(path, cfg) -> dict:
    with rasterio.open(path) as src:
        carto = src.read(1).astype(np.float32)
        if src.nodata is not None:
            carto[carto == src.nodata] = np.nan
        shape, transform, crs, b = carto.shape, src.transform, src.crs, src.bounds
    cache = resolve_path(cfg.paths.cache) / cfg.dem.cache_subdir
    bounds = (b.left + EDGE_DEG, b.bottom + EDGE_DEG, b.right - EDGE_DEG, b.top - EDGE_DEG)
    cop = np.full(shape, np.nan, np.float32)
    for f in fetch_copernicus(bounds, cache, cfg.dem.copernicus_url, cfg.dem.fetch_timeout_s):
        part = _on_grid(f, shape, transform, crs)
        cop = np.where(np.isnan(cop), part, cop)
    geoid = _on_grid(resolve_path(cfg.dem.geoid_grid), shape, transform, crs, scaled=True)
    ok = np.isfinite(carto) & np.isfinite(cop) & np.isfinite(geoid)
    diff = (carto - cop)[ok]
    median = float(np.median(diff))
    left = (carto - geoid - cop)[ok]
    return {
        "tile": path.stem,
        "bounds_lonlat": [round(v, 4) for v in b],
        "cells": int(ok.sum()),
        "cartodem_minus_copernicus_median_m": median,
        "cartodem_minus_copernicus_nmad_m": 1.4826 * float(np.median(np.abs(diff - median))),
        "pearson_r": float(np.corrcoef(carto[ok], cop[ok])[0, 1]),
        "egm2008_geoid_median_m": float(np.median(geoid[ok])),
        "egm2008_geoid_range_m": [float(geoid[ok].min()), float(geoid[ok].max())],
        "after_geoid_correction_median_m": float(np.median(left)),
    }


def main() -> None:
    cfg = load_config()
    tiles = [p for p in dem_files(CARTODEM_DIR) if p.stem.startswith("cdn")]
    rows = [check_tile(p, cfg) for p in tiles]
    run = RESULTS / time.strftime("datum-%Y%m%d-%H%M%S")
    run.mkdir(parents=True)
    note = (
        "CartoDEM V3R1 vs Copernicus GLO-30 (EGM2008) on each CartoDEM tile's grid. If CartoDEM "
        "is ellipsoidal, CartoDEM - Copernicus = EGM2008 geoid undulation N."
    )
    (run / "metrics.json").write_text(
        json.dumps({"run_id": run.name, "note": note, "tiles": rows}, indent=2), encoding="utf-8"
    )
    for r in rows:
        print(
            f"{r['tile']}: CartoDEM - Copernicus {r['cartodem_minus_copernicus_median_m']:+.1f} m "
            f"(NMAD {r['cartodem_minus_copernicus_nmad_m']:.1f} m, r {r['pearson_r']:.3f}); "
            f"geoid N {r['egm2008_geoid_median_m']:+.1f} m; after correction "
            f"{r['after_geoid_correction_median_m']:+.1f} m"
        )
    print(f"results: {run.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
