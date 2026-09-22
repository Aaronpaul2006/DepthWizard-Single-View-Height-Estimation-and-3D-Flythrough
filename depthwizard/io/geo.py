"""Georeferencing helpers: UTM zone choice, ground pixel size, reprojection of degree grids."""

from __future__ import annotations

import dataclasses
import logging
import math

import numpy as np
from affine import Affine
from pyproj import Transformer
from rasterio.crs import CRS
from rasterio.transform import array_bounds
from rasterio.warp import Resampling, calculate_default_transform, reproject

from depthwizard.io.read import Raster

log = logging.getLogger(__name__)


def utm_crs(lon: float, lat: float) -> CRS:
    """WGS 84 / UTM zone containing (lon, lat)."""
    zone = min(max(int((lon + 180.0) // 6.0) + 1, 1), 60)
    return CRS.from_epsg((32600 if lat >= 0 else 32700) + zone)


def center_lonlat(crs: CRS, transform: Affine, height: int, width: int) -> tuple[float, float]:
    x, y = transform @ (width / 2, height / 2)
    if crs.is_geographic:
        return x, y
    lon, lat = Transformer.from_crs(crs, "EPSG:4326", always_xy=True).transform(x, y)
    return lon, lat


def ground_pixel_size_m(crs: CRS, transform: Affine, height: int, width: int) -> float:
    """Finer side of the centre pixel, in metres on the ground (works for degree grids too)."""
    return min(ground_pixel_sides_m(crs, transform, height, width))


def ground_pixel_sides_m(
    crs: CRS, transform: Affine, height: int, width: int
) -> tuple[float, float]:
    """(east-west, north-south) ground size of the centre pixel in metres. On degree grids the
    two differ away from the equator (1″ of longitude shrinks with cos(latitude))."""
    if not crs.is_geographic:
        return float(abs(transform.a)), float(abs(transform.e))
    lon, lat = center_lonlat(crs, transform, height, width)
    to_utm = Transformer.from_crs(crs, utm_crs(lon, lat), always_xy=True)
    cx, cy = width / 2, height / 2
    corners = [transform @ p for p in ((cx, cy), (cx + 1, cy), (cx, cy + 1))]
    xs, ys = to_utm.transform([p[0] for p in corners], [p[1] for p in corners])
    dx = math.hypot(xs[1] - xs[0], ys[1] - ys[0])
    dy = math.hypot(xs[2] - xs[0], ys[2] - ys[0])
    return dx, dy


def reproject_to_utm(raster: Raster) -> Raster:
    """Degree grids (EPSG:4326 and similar) -> UTM zone of the scene centre, square metre pixels
    at the native ground resolution, bilinear. Projected or non-georeferenced input is returned
    unchanged. Pixels outside the source footprint are marked invalid."""
    if not raster.georeferenced or not raster.crs.is_geographic:
        return raster
    h, w = raster.shape
    lon, lat = center_lonlat(raster.crs, raster.transform, h, w)
    dst_crs = utm_crs(lon, lat)
    res = ground_pixel_size_m(raster.crs, raster.transform, h, w)
    left, bottom, right, top = array_bounds(h, w, raster.transform)
    transform, dw, dh = calculate_default_transform(
        raster.crs, dst_crs, w, h, left, bottom, right, top, resolution=res
    )
    common = dict(
        src_transform=raster.transform,
        src_crs=raster.crs,
        dst_transform=transform,
        dst_crs=dst_crs,
        dst_nodata=0,
    )
    rgb = np.zeros((3, dh, dw), np.uint8)
    reproject(np.moveaxis(raster.rgb, -1, 0), rgb, resampling=Resampling.bilinear, **common)
    src_valid = raster.valid if raster.valid is not None else np.ones((h, w), bool)
    valid = np.zeros((dh, dw), np.uint8)
    reproject(src_valid.astype(np.uint8), valid, resampling=Resampling.nearest, **common)
    log.info(
        "Reprojected %s from %s to %s at %.3f m/px (%dx%d -> %dx%d).",
        raster.name,
        raster.crs,
        dst_crs,
        res,
        w,
        h,
        dw,
        dh,
    )
    return dataclasses.replace(
        raster,
        rgb=np.ascontiguousarray(np.moveaxis(rgb, 0, -1)),
        crs=dst_crs,
        transform=transform,
        valid=valid.astype(bool),
    )
