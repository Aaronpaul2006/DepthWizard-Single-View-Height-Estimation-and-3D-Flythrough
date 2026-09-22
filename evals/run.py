"""Eval runner (EVALUATION.md).

    python -m evals.run --split quick    # 5 val tiles, after every model or calibration change
    python -m evals.run --split val      # tuning split
    python -m evals.run --split full     # the four landscape test splits + GAMUS test -> REPORT.md

Each line of evals/splits/<split>.txt names a tile under data/datasets/:
- `naip3dep/<site>/<r>_<c>`: metric. Each site's whole scene is processed once, exactly like a
  user upload (depth, then DEM only, Method A and Method B), and the listed 1024 px tiles are
  scored against the LiDAR DSM on all pixels and on objects only (nDSM metric). The calibration
  DEM is Copernicus GLO-30, fetched through the app's own provider.
- `gamus/<split>/<stem>`: relative. The relative DSM is scale-aligned to the height above ground.
Everything lands in evals/results/<run_id>/: config, split list, per-tile CSV, metrics.json,
error maps, previews, provenance.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import subprocess
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import rasterio
import yaml

from depthwizard.calibrate.dem import fetch_copernicus, image_bounds_lonlat, load_dem
from depthwizard.calibrate.fit import method_a, method_b
from depthwizard.calibrate.relative import normalize_relative
from depthwizard.config import REPO_ROOT, Config, load_config, resolve_path
from depthwizard.depth.model import DepthModel
from depthwizard.depth.stitch import predict_tiled
from depthwizard.io.geo import ground_pixel_size_m, reproject_to_utm
from depthwizard.io.read import Raster, read_image
from evals.metrics import dsm_metrics, object_mask, reference_on_grid, relative_metrics
from evals.visuals import save_error_map, save_hillshade, save_rgb

log = logging.getLogger(__name__)

EVAL_CONFIG = REPO_ROOT / "configs" / "eval.yaml"
FULL_SPLITS = ["test_urban", "test_sparse", "test_hilly", "test_forested", "gamus_test"]
METHODS = ("dem_only", "method_a", "method_b")
METRIC_KEYS = ("rmse", "mae", "pearson_r", "bias", "nmad", "offset_free_rmse")
PREVIEW_PX = 320  # failure-gallery panels


def load_eval_config() -> dict:
    return yaml.safe_load(EVAL_CONFIG.read_text(encoding="utf-8"))


def read_split(ecfg: dict, split: str) -> list[str]:
    path = resolve_path(ecfg["splits_dir"]) / f"{split}.txt"
    lines = path.read_text(encoding="utf-8").splitlines()
    return [ln.split("#")[0].strip() for ln in lines if ln.split("#")[0].strip()]


def group_by_site(tiles: list[str]) -> dict[str, list[str]]:
    """naip3dep/<site>/<r>_<c> -> {naip3dep/<site>: [tiles...]}, keeping split order."""
    sites: dict[str, list[str]] = {}
    for tile in tiles:
        sites.setdefault(tile.rsplit("/", 1)[0], []).append(tile)
    return sites


def tile_window(tile_image: Path, scene: Raster) -> tuple[tuple[slice, slice], object, tuple]:
    """Where a tile sits inside its site scene (both share one pixel grid)."""
    with rasterio.open(tile_image) as src:
        transform, shape = src.transform, (src.height, src.width)
    col = round((transform.c - scene.transform.c) / scene.transform.a)
    row = round((transform.f - scene.transform.f) / scene.transform.e)
    return (slice(row, row + shape[0]), slice(col, col + shape[1])), transform, shape


def eval_site(
    site: str, tiles: list[str], model: DepthModel, cfg: Config, ecfg: dict, out: Path
) -> list[dict]:
    root = resolve_path(ecfg["datasets_root"])
    info = json.loads((root / site / "site.json").read_text(encoding="utf-8"))
    t0 = time.perf_counter()
    scene = reproject_to_utm(read_image(root / site / "scene.tif", cfg.input))
    h, w = scene.shape
    d = predict_tiled(model, scene.rgb, cfg.depth)
    depth_s = time.perf_counter() - t0

    t0 = time.perf_counter()
    pixel_m = ground_pixel_size_m(scene.crs, scene.transform, h, w)
    bounds = image_bounds_lonlat(scene.crs, scene.transform, h, w)
    cache = resolve_path(cfg.paths.cache) / cfg.dem.cache_subdir
    files = fetch_copernicus(bounds, cache, cfg.dem.copernicus_url, cfg.dem.fetch_timeout_s)
    dem = load_dem(
        files, "copernicus_glo30", scene.crs, scene.transform, (h, w), cfg.dem.resampling
    )
    cal_a = method_a(d, dem.heights, dem.res_m, pixel_m, cfg.calibration)
    cal_b = method_b(d, dem.heights, dem.res_m, pixel_m, cfg.calibration)
    calibrate_s = time.perf_counter() - t0

    rows = []
    for tile in tiles:
        # Reference data is read only now, after every prediction for the scene is final.
        win, transform, shape = tile_window(root / tile / "image.tif", scene)
        ref = reference_on_grid(root / tile / "dsm.tif", scene.crs, transform, shape)
        dtm = reference_on_grid(root / tile / "dtm.tif", scene.crs, transform, shape)
        objects = object_mask(ref, dtm, ecfg["object_min_height_m"])
        preds = {
            "dem_only": dem.heights[win],
            "method_a": cal_a.dsm[win],
            "method_b": cal_b.dsm[win],
        }

        stem = tile.replace("/", "_")
        save_rgb(scene.rgb[win], out / "previews" / f"{stem}_image.png", PREVIEW_PX)
        save_hillshade(
            preds["method_b"], pixel_m, out / "previews" / f"{stem}_pred.png", PREVIEW_PX
        )
        save_hillshade(ref, pixel_m, out / "previews" / f"{stem}_ref.png", PREVIEW_PX)
        for name, pred in preds.items():
            m, mo = dsm_metrics(pred, ref), dsm_metrics(pred, ref, objects)
            rows.append(
                {
                    "tile": tile,
                    "landscape": info["site"]["landscape"],
                    "method": name,
                    **{k: m.get(k) for k in (*METRIC_KEYS, "n_pixels")},
                    "ndsm_rmse": mo.get("rmse"),
                    "ndsm_pixels": mo["n_pixels"],
                    "cal_source": {"method_a": "dem_affine", "method_b": cal_b.method}.get(
                        name, ""
                    ),
                    "scale": {"method_a": cal_a.scale, "method_b": cal_b.scale}.get(name),
                    "scene": site,
                    "scene_px": f"{w}x{h}",
                    "scene_depth_s": round(depth_s, 3),
                    "scene_calibrate_s": round(calibrate_s, 3),
                }
            )
            if name in ("dem_only", "method_b"):
                clamp = ecfg["error_map_nmad_clamp"] * (m.get("nmad") or 1.0)
                path = out / "error_maps" / f"{stem}_{name}.png"
                save_error_map(pred - ref, clamp, path, ecfg["error_map_max_side"])
    return rows


def eval_gamus(tile: str, model: DepthModel, cfg: Config, ecfg: dict, out: Path) -> list[dict]:
    """Relative mode: no georeference, so the rDSM is scale-aligned to height above ground."""
    from evals.datasets.gamus import load_pair

    _, split, stem = tile.split("/")
    rgb, agl = load_pair(split, stem)
    rdsm = normalize_relative(predict_tiled(model, rgb, cfg.depth), cfg.relative.norm_percentiles)
    m = relative_metrics(rdsm, agl)
    return [
        {
            "tile": tile,
            "landscape": "urban (GAMUS)",
            "method": "relative",
            **{k: m.get(k) for k in (*METRIC_KEYS, "n_pixels")},
            "cal_source": "scale-aligned",
            "scale": m.get("align_a"),
        }
    ]


def summarize(rows: list[dict]) -> dict:
    """Mean of per-tile values for each landscape × metric method (and 'all')."""
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in rows:
        if r["method"] in METHODS:
            groups[(r["landscape"], r["method"])].append(r)
            groups[("all", r["method"])].append(r)
    summary = {}
    for (landscape, method), rs in sorted(groups.items()):
        entry = {"tiles": len(rs)}
        for k in (*METRIC_KEYS, "ndsm_rmse"):
            vals = [r[k] for r in rs if r.get(k) is not None]
            entry[k] = float(np.mean(vals)) if vals else None
        summary.setdefault(landscape, {})[method] = entry
    return summary


def summarize_relative(rows: list[dict]) -> dict | None:
    rel = [r for r in rows if r["method"] == "relative"]
    if not rel:
        return None
    return {
        "tiles": len(rel),
        **{k: float(np.mean([r[k] for r in rel if r[k] is not None])) for k in METRIC_KEYS},
        "scale_aligned": True,
    }


def print_table(summary: dict, relative: dict | None) -> None:
    keys = (*METRIC_KEYS, "ndsm_rmse")
    print(
        f"{'landscape':10s} {'method':9s} {'tiles':>5s} " + " ".join(f"{k[:9]:>9s}" for k in keys)
    )
    for landscape, methods in summary.items():
        for method in METHODS:
            if method in methods:
                e = methods[method]
                vals = " ".join(f"{e[k]:9.3f}" if e[k] is not None else f"{'-':>9s}" for k in keys)
                print(f"{landscape:10s} {method:9s} {e['tiles']:5d} {vals}")
    if relative:
        print(
            f"GAMUS relative (scale-aligned), {relative['tiles']} tiles: RMSE "
            f"{relative['rmse']:.3f} m, MAE {relative['mae']:.3f} m, r {relative['pearson_r']:.3f}"
        )


def git_state() -> dict:
    def git(*args):
        res = subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True)
        return res.stdout.strip() if res.returncode == 0 else None

    return {
        "commit": git("rev-parse", "HEAD") or "uncommitted",
        "dirty": bool(git("status", "--porcelain")),
    }


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m evals.run")
    parser.add_argument("--split", required=True, help="a file in evals/splits/, or 'full'")
    parser.add_argument("--config", action="append", default=[], help="YAML over default.yaml")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    cfg, ecfg = load_config(*args.config), load_eval_config()
    splits = FULL_SPLITS if args.split == "full" else [args.split]
    tiles = [t for s in splits for t in read_split(ecfg, s)]
    run_id = f"{args.split}-{time.strftime('%Y%m%d-%H%M%S')}"
    out = resolve_path(ecfg["results_dir"]) / run_id
    out.mkdir(parents=True)
    model = DepthModel(cfg.model)

    rows = []
    for site, site_tiles in group_by_site([t for t in tiles if t.startswith("naip3dep/")]).items():
        print(f"  {site}: {len(site_tiles)} tiles")
        rows += eval_site(site, site_tiles, model, cfg, ecfg, out)
    gamus = [t for t in tiles if t.startswith("gamus/")]
    if gamus:
        print(f"  GAMUS: {len(gamus)} tiles")
    for tile in gamus:
        rows += eval_gamus(tile, model, cfg, ecfg, out)

    fields = list(dict.fromkeys(k for r in rows for k in r))
    with (out / "per_tile.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    summary, relative = summarize(rows), summarize_relative(rows)
    sites = sorted({t.rsplit("/", 1)[0] for t in tiles if t.startswith("naip3dep/")})
    provenance = {
        s: json.loads(
            (resolve_path(ecfg["datasets_root"]) / s / "site.json").read_text(encoding="utf-8")
        )
        for s in sites
    }
    record = {
        "run_id": run_id,
        "split": args.split,
        "splits": splits,
        "tiles": tiles,
        "git": git_state(),
        "device": model.describe_device(),
        "object_min_height_m": ecfg["object_min_height_m"],
        "summary": summary,
        "relative_summary": relative,
        "datasets": provenance,
        "note": (
            "Each site scene is processed once like a user upload; landscape values are means of "
            "per-tile metrics. Truth: 3DEP LiDAR (NAVD88); DEM: Copernicus GLO-30 (EGM2008), so "
            "raw RMSE includes a datum offset; see offset_free_rmse. "
            "GAMUS values are scale-aligned."
        ),
    }
    (out / "metrics.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    (out / "config.yaml").write_text(
        yaml.safe_dump(cfg.to_dict(), sort_keys=False), encoding="utf-8"
    )
    (out / "split.txt").write_text("\n".join(tiles) + "\n", encoding="utf-8")
    print_table(summary, relative)
    print(f"results: {out.relative_to(REPO_ROOT)}")
    if args.split == "full":
        from evals.report import build_report

        print(f"report: {build_report(out).relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
