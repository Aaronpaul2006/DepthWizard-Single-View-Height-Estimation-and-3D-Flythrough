"""Calibration DEM: a local file (CartoDEM, SRTM, ...) or Copernicus GLO-30 fetched once and cached.

The DEM is resampled onto the image grid in metres. The Copernicus fetch is one of the two
network calls the app may make (CLAUDE.md rule 6); with a local file it runs fully offline.
Record the vertical datum of every source: a mismatch shows up as a constant offset.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import rasterio
import requests
from affine import Affine
from rasterio.crs import CRS
from rasterio.warp import Resampling, reproject, transform_bounds

from depthwizard.io.geo import ground_pixel_sides_m

log = logging.getLogger(__name__)

# Vertical datum per known source; anything else is reported as unknown.
DATUMS = {
    "copernicus_glo30": "EGM2008",
    # Measured on V3R1 tile 88E27N: 46 m below Copernicus, matching the EGM2008 geoid (-43.8 m).
    "cartodem": "WGS84 ellipsoid (measured, V3R1)",
    "srtm": "EGM96",
    "nasadem": "EGM96",
}


@dataclass
class Dem:
    heights: np.ndarray  # (H, W) float32 metres on the image grid, NaN where the DEM has no data
    source: str  # "copernicus_glo30", "cartodem", "srtm", or the file stem
    res_m: float  # native DEM ground resolution
    datum: str
    files: list[Path] = field(default_factory=list)


def copernicus_tile_names(west: float, south: float, east: float, north: float) -> list[str]:
    """1°x1° GLO-30 COG names on the AWS bucket; each is named after its south-west corner."""
    names = []
    for lat in range(math.floor(south), math.ceil(north)):
        for lon in range(math.floor(west), math.ceil(east)):
            ns = f"N{lat:02d}" if lat >= 0 else f"S{-lat:02d}"
            ew = f"E{lon:03d}" if lon >= 0 else f"W{-lon:03d}"
            names.append(f"Copernicus_DSM_COG_10_{ns}_00_{ew}_00_DEM")
    return names


def fetch_copernicus(
    bounds_lonlat: tuple[float, float, float, float],
    cache_dir: Path,
    url_template: str,
    timeout_s: float,
) -> list[Path]:
    """Download the GLO-30 tiles covering the bounds into cache_dir (once). Ocean tiles don't
    exist on the bucket (404) and are skipped."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for name in copernicus_tile_names(*bounds_lonlat):
        path = cache_dir / f"{name}.tif"
        if not path.exists():
            url = url_template.format(name=name)
            log.info("Fetching %s", url)
            resp = requests.get(url, timeout=timeout_s, stream=True)
            if resp.status_code == 404:
                log.info("No Copernicus tile %s (open water).", name)
                continue
            resp.raise_for_status()
            part = path.with_suffix(".part")
            with part.open("wb") as f:
                for chunk in resp.iter_content(chunk_size=1 << 20):
                    f.write(chunk)
            part.replace(path)
        paths.append(path)
    if not paths:
        raise FileNotFoundError("No Copernicus DEM tiles cover this scene.")
    return paths


def dem_files(path: str | Path) -> list[Path]:
    """A single DEM file, or every GeoTIFF under a folder, searched recursively (an unzipped
    CartoDEM tile sits in its own subfolder, e.g. cartodem/cdng45e_v3r1/cdng45e.tif)."""
    path = Path(path)
    if path.is_file():
        return [path]
    files = sorted(p for p in path.rglob("*") if p.suffix.lower() in {".tif", ".tiff"})
    if not files:
        raise FileNotFoundError(f"No GeoTIFF DEM files in {path}.")
    return files


def infer_source(path: Path) -> str:
    """Name the DEM source from its path (folder names count), e.g. data/dem/cartodem/x.tif."""
    text = str(path).lower()
    for key, name in (
        ("carto", "cartodem"),
        ("copernicus", "copernicus_glo30"),
        ("nasadem", "nasadem"),
        ("srtm", "srtm"),
    ):
        if key in text:
            return name
    stem = path.stem.lower()
    if len(stem) == 7 and stem.startswith("cdn") and stem[4:6].isdigit():
        return "cartodem"  # Bhuvan tile names, e.g. cdng45e
    return path.stem


def image_bounds_lonlat(crs: CRS, transform: Affine, height: int, width: int):
    left, top = transform @ (0, 0)
    right, bottom = transform @ (width, height)
    return transform_bounds(crs, "EPSG:4326", left, bottom, right, top, densify_pts=21)


def load_dem(
    files: list[Path],
    source: str,
    dst_crs: CRS,
    dst_transform: Affine,
    shape: tuple[int, int],
    resampling: str,
) -> Dem:
    """Mosaic the DEM file(s) onto the image grid. First file wins where they overlap."""
    heights = np.full(shape, np.nan, np.float32)
    res_m = math.nan
    for path in files:
        tmp = np.full(shape, np.nan, np.float32)
        with rasterio.open(path) as src:
            reproject(
                source=rasterio.band(src, 1),
                destination=tmp,
                src_nodata=src.nodata,
                dst_transform=dst_transform,
                dst_crs=dst_crs,
                dst_nodata=np.nan,
                resampling=Resampling[resampling],
            )
            if math.isnan(res_m):
                # geometric mean: the isotropic scale a Gaussian band split can match
                dx, dy = ground_pixel_sides_m(src.crs, src.transform, src.height, src.width)
                res_m = math.sqrt(dx * dy)
        fill = np.isnan(heights) & np.isfinite(tmp)
        heights[fill] = tmp[fill]
    coverage = float(np.isfinite(heights).mean())
    if coverage == 0.0:
        raise ValueError(f"The DEM ({source}) does not overlap the image.")
    if coverage < 1.0:
        log.warning("DEM %s covers %.1f%% of the image.", source, 100 * coverage)
    datum = DATUMS.get(source, "unknown")
    log.info("DEM %s: %.1f m resolution, datum %s, %d file(s).", source, res_m, datum, len(files))
    return Dem(heights=heights, source=source, res_m=res_m, datum=datum, files=list(files))


# Sources whose heights are above the WGS84 ellipsoid, not the geoid (see CLAUDE.md gotchas).
ELLIPSOIDAL_SOURCES = {"cartodem"}
GEOID_DATUM = "EGM2008"


def to_geoid_heights(dem: Dem, geoid_grid: Path, dst_crs: CRS, dst_transform: Affine) -> Dem:
    """Ellipsoidal DEM -> EGM2008 heights (H = h − N), the datum of Copernicus and of sea-level
    references. Other sources pass through unchanged. Without the geoid grid the DEM stays
    ellipsoidal and its datum label says so."""
    if dem.source not in ELLIPSOIDAL_SOURCES:
        return dem
    if not geoid_grid.exists():
        log.warning(
            "Geoid grid %s is missing (run scripts/fetch_geoid.py); %s stays ellipsoidal.",
            geoid_grid,
            dem.source,
        )
        return dem
    undulation = np.full(dem.heights.shape, np.nan, np.float32)
    with rasterio.open(geoid_grid) as src:
        reproject(
            source=rasterio.band(src, 1),
            destination=undulation,
            src_nodata=src.nodata,
            dst_transform=dst_transform,
            dst_crs=dst_crs,
            dst_nodata=np.nan,
            resampling=Resampling.bilinear,
        )
        scale, offset = src.scales[0], src.offsets[0]  # PROJ grids may store scaled integers
    undulation = undulation * scale + offset
    if not np.isfinite(undulation).all():
        log.warning(
            "Geoid grid %s does not cover this scene; %s stays ellipsoidal.", geoid_grid, dem.source
        )
        return dem
    log.info(
        "Geoid correction for %s: N = %.2f to %.2f m.",
        dem.source,
        np.nanmin(undulation),
        np.nanmax(undulation),
    )
    return Dem(
        heights=(dem.heights - undulation).astype(np.float32),
        source=dem.source,
        res_m=dem.res_m,
        datum=f"{GEOID_DATUM} (converted from the WGS84 ellipsoid)",
        files=dem.files,
    )
