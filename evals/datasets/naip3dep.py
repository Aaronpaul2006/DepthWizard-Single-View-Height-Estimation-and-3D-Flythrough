"""NAIP imagery + USGS 3DEP LiDAR truth from Microsoft Planetary Computer (no sign-up).

Collections (confirmed 2026-09-11): `naip` (RGBN, 0.3-0.6 m), `3dep-lidar-dsm` and
`3dep-lidar-dtm` (2 m, NAD83 UTM, NAVD88 heights). For each site in sites.yaml, the latest NAIP
year is mosaicked onto a `size_px` square grid centred on the site at native GSD; LiDAR DSM and
DTM tiles are mosaicked and resampled (bilinear) onto that grid, NaN where LiDAR is missing.

    data/datasets/naip3dep/<site>/scene.tif              whole crop (RGB, native UTM CRS)
    data/datasets/naip3dep/<site>/site.json              provenance: item ids, years, datum
    data/datasets/naip3dep/<site>/<r>_<c>/image.tif      eval tile
                                         /dsm.tif, dtm.tif  LiDAR truth on the tile grid

    python -m evals.datasets.naip3dep build [--site NAME]
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import numpy as np
import planetary_computer
import pystac_client
import rasterio
import yaml
from affine import Affine
from pyproj import Transformer
from rasterio.crs import CRS
from rasterio.warp import Resampling, reproject
from shapely.geometry import Point, box, shape

from depthwizard.config import REPO_ROOT
from depthwizard.io.write import write_geotiff

log = logging.getLogger(__name__)

STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"
SITES_FILE = Path(__file__).with_name("sites.yaml")
ROOT = REPO_ROOT / "data" / "datasets" / "naip3dep"
NODATA = -9999.0
MIN_NAIP_COVERAGE = 0.999  # a site crop must be (almost) fully covered by one NAIP year
# Remote COG reads: fetch only the byte ranges needed, never list directories.
GDAL_ENV = {
    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
    "GDAL_HTTP_MERGE_CONSECUTIVE_RANGES": "YES",
    "VSI_CACHE": "TRUE",
}


def load_sites() -> dict:
    return yaml.safe_load(SITES_FILE.read_text(encoding="utf-8"))


def build_site(site: dict, tile_px: int, min_valid_frac: float) -> list[Path]:
    catalog = pystac_client.Client.open(STAC_URL, modifier=planetary_computer.sign_inplace)
    out = ROOT / site["name"]
    out.mkdir(parents=True, exist_ok=True)
    with rasterio.Env(**GDAL_ENV):
        rgb, crs, transform, naip = _read_naip(catalog, site)
        write_geotiff_rgb(out / "scene.tif", rgb, crs, transform)
        truth, sources = {}, {}
        for kind in ("dsm", "dtm"):
            truth[kind], sources[kind] = _mosaic_lidar(
                catalog, f"3dep-lidar-{kind}", site, rgb.shape[1:], crs, transform
            )
    provenance = {
        "site": site,
        "naip": naip,
        "lidar": sources,
        "crs": crs.to_string(),
        "vertical_datum": "NAVD88 (3DEP LiDAR)",
        "truth_resolution_m": 2.0,
    }
    (out / "site.json").write_text(json.dumps(provenance, indent=2), encoding="utf-8")

    tiles = []
    h, w = rgb.shape[1:]
    for r in range(0, h - tile_px + 1, tile_px):
        for c in range(0, w - tile_px + 1, tile_px):
            dsm = truth["dsm"][r : r + tile_px, c : c + tile_px]
            valid = float(np.isfinite(dsm).mean())
            if valid < min_valid_frac:
                log.info("%s tile %d_%d skipped: %.0f%% LiDAR", site["name"], r, c, 100 * valid)
                continue
            tdir = out / f"{r // tile_px}_{c // tile_px}"
            tdir.mkdir(exist_ok=True)
            t = transform @ Affine.translation(c, r)
            write_geotiff_rgb(tdir / "image.tif", rgb[:, r : r + tile_px, c : c + tile_px], crs, t)
            for kind, grid in truth.items():
                tile = grid[r : r + tile_px, c : c + tile_px]
                write_geotiff(tdir / f"{kind}.tif", tile, crs, t, NODATA)
            tiles.append(tdir)
    log.info("%s: %d tiles", site["name"], len(tiles))
    return tiles


def _read_naip(catalog, site: dict):
    """Latest-year NAIP mosaic on a size_px square centred on the site, at native GSD.

    NAIP images are quarter-quads (3.75' tiles) and city centres often sit on a corner, so the
    crop is assembled from every same-year image that touches it."""
    lon, lat, n = site["lon"], site["lat"], site["size_px"]
    items = list(catalog.search(collections=["naip"], intersects=Point(lon, lat)).items())
    if not items:
        raise RuntimeError(f"No NAIP imagery at site {site['name']!r}.")
    year = max(i.datetime.year for i in items)
    first = next(i for i in items if i.datetime.year == year)
    with rasterio.open(first.assets["image"].href) as src:
        crs, res, (ox, oy) = src.crs, src.res[0], (src.transform.c, src.transform.f)
    x, y = Transformer.from_crs("EPSG:4326", crs, always_xy=True).transform(lon, lat)
    # Snap the crop to the source pixel grid so nearest-neighbour copies pixels unchanged.
    left = ox + round((x - n / 2 * res - ox) / res) * res
    top = oy + round((y + n / 2 * res - oy) / res) * res
    transform = Affine(res, 0.0, left, 0.0, -res, top)
    footprint = _lonlat_footprint(crs, transform, n, n)
    same_year = [
        i
        for i in catalog.search(collections=["naip"], intersects=footprint).items()
        if i.datetime.year == year
    ]
    rgb = np.zeros((3, n, n), np.uint8)
    filled = np.zeros((n, n), bool)
    used = []
    for item in same_year:
        tmp = np.zeros((3, n, n), np.uint8)
        with rasterio.open(item.assets["image"].href) as src:
            reproject(
                source=rasterio.band(src, [1, 2, 3]),
                destination=tmp,
                dst_transform=transform,
                dst_crs=crs,
                resampling=Resampling.nearest,
            )
        new = tmp.any(axis=0) & ~filled
        if new.any():
            rgb[:, new] = tmp[:, new]
            filled |= new
            used.append(item.id)
        if filled.all():
            break
    coverage = float(filled.mean())
    if coverage < MIN_NAIP_COVERAGE:
        raise RuntimeError(f"NAIP {year} covers only {coverage:.1%} of site {site['name']!r}.")
    return rgb, crs, transform, {"year": year, "gsd_m": res, "items": used}


def _lonlat_footprint(crs: CRS, transform: Affine, h: int, w: int):
    left, top = transform @ (0, 0)
    right, bottom = transform @ (w, h)
    to_lonlat = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    lons, lats = to_lonlat.transform([left, right, right, left], [top, top, bottom, bottom])
    return box(min(lons), min(lats), max(lons), max(lats))


def _mosaic_lidar(catalog, collection, site, shape_hw, crs, transform):
    h, w = shape_hw
    footprint = _lonlat_footprint(crs, transform, h, w)
    items = list(catalog.search(collections=[collection], intersects=footprint).items())
    items = [i for i in items if shape(i.geometry).intersects(footprint)]
    items.sort(key=lambda i: i.properties.get("end_datetime") or "", reverse=True)
    mosaic = np.full((h, w), np.nan, np.float32)
    used = []
    for item in items:
        tmp = np.full((h, w), np.nan, np.float32)
        with rasterio.open(item.assets["data"].href) as src:
            reproject(
                source=rasterio.band(src, 1),
                destination=tmp,
                src_nodata=src.nodata if src.nodata is not None else np.nan,
                dst_transform=transform,
                dst_crs=crs,
                dst_nodata=np.nan,
                resampling=Resampling.bilinear,
            )
        fill = np.isnan(mosaic) & np.isfinite(tmp)
        if fill.any():
            mosaic[fill] = tmp[fill]
            used.append(
                {
                    "id": item.id,
                    "usgs_id": item.properties.get("3dep:usgs_id"),
                    "end": item.properties.get("end_datetime"),
                }
            )
        if np.isfinite(mosaic).all():
            break
    log.info(
        "%s %s: %.1f%% covered by %d items",
        site["name"],
        collection,
        100 * np.isfinite(mosaic).mean(),
        len(used),
    )
    return mosaic, used


def write_geotiff_rgb(path: Path, rgb: np.ndarray, crs, transform) -> None:
    profile = {
        "driver": "GTiff",
        "height": rgb.shape[1],
        "width": rgb.shape[2],
        "count": 3,
        "dtype": "uint8",
        "crs": crs,
        "transform": transform,
        "compress": "lzw",
        "tiled": True,
        "blockxsize": 256,
        "blockysize": 256,
        "photometric": "RGB",
    }
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(rgb)


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m evals.datasets.naip3dep")
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build")
    b.add_argument("--site", help="build only this site (default: all)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = load_sites()
    for site in cfg["sites"]:
        if args.site and site["name"] != args.site:
            continue
        try:
            build_site(site, cfg["tile_px"], cfg["min_valid_frac"])
        except RuntimeError as e:  # one bad site shouldn't stop the others
            log.error("%s: %s", site["name"], e)


if __name__ == "__main__":
    main()
