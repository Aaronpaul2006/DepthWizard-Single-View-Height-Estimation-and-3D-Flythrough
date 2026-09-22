"""Tune calibration settings on the val split only (EVALUATION.md, rule 2: never on test).

    python -m evals.tune       -> evals/results/tune-<time>/grid.csv, summary.json, config.yaml

Scene mode, like evals.run: each site's whole scene is predicted and calibrated once per setting,
and its val tiles are scored inside it. Sites are handled one at a time (depth, DEM per
resampling mode, detail band per band-split factor and DEM-band scale all cached for that site
only), so memory stays at one scene's worth. The objective is the mean over landscapes of the mean
per-tile RMSE, so every landscape weighs the same. The winner is reported, not applied: copy it
into configs/default.yaml by hand and log it.
"""

from __future__ import annotations

import csv
import dataclasses
import itertools
import json
import time
from collections import defaultdict

import numpy as np
import yaml

from depthwizard.calibrate.dem import fetch_copernicus, image_bounds_lonlat, load_dem
from depthwizard.calibrate.fit import band_scale, band_split, method_b
from depthwizard.config import REPO_ROOT, load_config, resolve_path
from depthwizard.depth.model import DepthModel
from depthwizard.depth.stitch import predict_tiled
from depthwizard.io.geo import ground_pixel_size_m, reproject_to_utm
from depthwizard.io.read import read_image
from evals.metrics import object_mask, reference_on_grid
from evals.run import git_state, group_by_site, load_eval_config, read_split, tile_window

GRID = {
    "resampling": ["bilinear", "cubic_spline"],
    "band_sigma_k": [0.3, 0.5, 1.0],
    "band_coarse_cells": [2.0, 4.0, 8.0],
    "band_min_r": [0.1, 0.3, 0.5, 2.0],  # 2.0 can never be reached: the DEM-band scale is off
    "dem_relief_std_m": [15.0, 1.0e9],  # 1e9 is never exceeded: the DEM-relief scale is off
    "prior_height_m": [0.0, 6.0, 12.0],  # 0 adds no detail when no other source applies
}
KEYS = ["band_sigma_k", "band_coarse_cells", "band_min_r", "dem_relief_std_m", "prior_height_m"]


def rmse(pred: np.ndarray, ref: np.ndarray, mask: np.ndarray | None = None) -> float:
    ok = np.isfinite(pred) & np.isfinite(ref)
    if mask is not None:
        ok &= mask
    return float(np.sqrt(np.mean((pred[ok] - ref[ok]) ** 2))) if ok.any() else float("nan")


def score(per_tile: list[tuple[str, float]]) -> tuple[float, dict[str, float]]:
    by_landscape: dict[str, list[float]] = defaultdict(list)
    for landscape, value in per_tile:
        by_landscape[landscape].append(value)
    means = {
        k: float(np.nanmean(v)) if np.isfinite(v).any() else float("nan")
        for k, v in sorted(by_landscape.items())
    }
    finite = [v for v in means.values() if np.isfinite(v)]
    return (float(np.mean(finite)) if finite else float("nan")), means


def sweep_site(name: str, tiles: list[str], model, cfg, ecfg, dem_only, results, sources) -> None:
    """Score every setting on one site's val tiles; only per-tile scores are kept."""
    root = resolve_path(ecfg["datasets_root"])
    landscape = json.loads((root / name / "site.json").read_text(encoding="utf-8"))["site"][
        "landscape"
    ]
    scene = reproject_to_utm(read_image(root / name / "scene.tif", cfg.input))
    h, w = scene.shape
    d = predict_tiled(model, scene.rgb, cfg.depth)
    pixel_m = ground_pixel_size_m(scene.crs, scene.transform, h, w)
    truth = []
    for tile in tiles:  # reference read after the prediction, for scoring only
        win, transform, shape = tile_window(root / tile / "image.tif", scene)
        ref = reference_on_grid(root / tile / "dsm.tif", scene.crs, transform, shape)
        dtm = reference_on_grid(root / tile / "dtm.tif", scene.crs, transform, shape)
        truth.append((win, ref, object_mask(ref, dtm, ecfg["object_min_height_m"])))
    bounds = image_bounds_lonlat(scene.crs, scene.transform, h, w)
    cache = resolve_path(cfg.paths.cache) / cfg.dem.cache_subdir
    files = fetch_copernicus(bounds, cache, cfg.dem.copernicus_url, cfg.dem.fetch_timeout_s)

    band_r = {}
    for mode in GRID["resampling"]:
        dem = load_dem(files, "copernicus_glo30", scene.crs, scene.transform, (h, w), mode)
        dem_only[mode] += [(landscape, rmse(dem.heights[win], ref)) for win, ref, _ in truth]
        d_high = {k: band_split(d, dem.res_m, pixel_m, k)[1] for k in GRID["band_sigma_k"]}
        bands = {
            c: band_scale(
                d,
                dem.heights,
                dem.res_m,
                pixel_m,
                dataclasses.replace(cfg.calibration, band_coarse_cells=c),
            )
            for c in GRID["band_coarse_cells"]
        }
        band_r.update({f"{mode}/{c}": round(b[1], 2) for c, b in bands.items()})
        for values in itertools.product(*(GRID[k] for k in KEYS)):
            params = dict(zip(KEYS, values, strict=True))
            cal = method_b(
                d,
                dem.heights,
                dem.res_m,
                pixel_m,
                dataclasses.replace(cfg.calibration, **params),
                d_high=d_high[params["band_sigma_k"]],
                band=bands[params["band_coarse_cells"]],
            )
            key = (mode, *values)
            sources[key][cal.method] += 1
            for win, ref, obj in truth:
                results[key].append(
                    (landscape, rmse(cal.dsm[win], ref), rmse(cal.dsm[win], ref, obj))
                )
    print(f"  swept {name} ({landscape}, {len(tiles)} val tiles), band r {band_r}")


def main() -> None:
    cfg, ecfg = load_config(), load_eval_config()
    out = resolve_path(ecfg["results_dir"]) / f"tune-{time.strftime('%Y%m%d-%H%M%S')}"
    out.mkdir(parents=True)
    model = DepthModel(cfg.model)
    dem_only: dict[str, list] = defaultdict(list)
    results: dict[tuple, list] = defaultdict(list)
    sources: dict[tuple, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    sites = group_by_site(read_split(ecfg, "val"))
    for name, tiles in sites.items():
        sweep_site(name, tiles, model, cfg, ecfg, dem_only, results, sources)

    rows = []
    for mode, per_tile in dem_only.items():
        objective, by_l = score(per_tile)
        rows.append({"method": "dem_only", "resampling": mode, "objective": objective, **by_l})
    for key, per_tile in results.items():
        mode, *values = key
        objective, by_l = score([(land, v) for land, v, _ in per_tile])
        rows.append(
            {
                "method": "method_b",
                "resampling": mode,
                **dict(zip(KEYS, values, strict=True)),
                "objective": objective,
                "ndsm_objective": score([(land, o) for land, _, o in per_tile])[0],
                "sources": ";".join(f"{k}:{v}" for k, v in sorted(sources[key].items())),
                **by_l,
            }
        )

    lead = ("method", "resampling", *KEYS, "objective", "ndsm_objective", "sources")
    fields = [*lead, *sorted({k for r in rows for k in r} - set(lead))]
    with (out / "grid.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    method_rows = [r for r in rows if r["method"] == "method_b"]
    ranked = sorted(method_rows, key=lambda r: r["objective"])

    def is_current(r):
        return r["resampling"] == cfg.dem.resampling and all(
            r[k] == getattr(cfg.calibration, k) for k in KEYS
        )

    summary = {
        "split": "val",
        "mode": "scene",
        "sites": list(sites),
        "objective": "mean over landscapes of mean per-tile RMSE (m)",
        "dem_only": [r for r in rows if r["method"] == "dem_only"],
        "current_default": next((r for r in method_rows if is_current(r)), None),
        "best": ranked[0],
        "top10": ranked[:10],
        "git": git_state(),
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (out / "config.yaml").write_text(
        yaml.safe_dump(cfg.to_dict(), sort_keys=False), encoding="utf-8"
    )
    for r in [*summary["dem_only"], summary["current_default"], *summary["top10"]]:
        if r:
            print(
                json.dumps({k: (round(v, 3) if isinstance(v, float) else v) for k, v in r.items()})
            )
    print(f"results: {out.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
