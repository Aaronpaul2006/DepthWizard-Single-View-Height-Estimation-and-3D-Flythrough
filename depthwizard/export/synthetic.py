"""Synthetic bundles for the viewer acceptance tests in docs/VIEWER_CONTRACT.md.

python -m depthwizard.export.synthetic cone --out data/samples/cone
python -m depthwizard.export.synthetic orientation --out data/samples/orientation
python -m depthwizard.export.synthetic relative --out data/samples/relative
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

from depthwizard.export.bundle import write_bundle

# Test geometry fixed by the contract.
CONE_SIZE, CONE_PIXEL_M, CONE_PEAK_M, CONE_RADIUS_M = 1025, 1.0, 100.0, 400.0
ORIENT_SIZE, ORIENT_RAISE_M = 513, 50.0
CHECKER_PX = 64
DOT_RADIUS_PX = 8
RED, BLUE = (220, 30, 30), (30, 60, 230)
LIGHT, DARK = (205, 205, 200), (120, 125, 120)


def _world_xz(n: int, pixel_m: float) -> tuple[np.ndarray, np.ndarray]:
    """Pixel-centre world coordinates per the contract: x east, z south, origin at the centre."""
    idx = (np.arange(n) + 0.5 - n / 2) * pixel_m
    return np.meshgrid(idx, idx)  # (x by column, z by row)


def _checkerboard(n: int) -> np.ndarray:
    r, c = np.mgrid[0:n, 0:n]
    dark = ((r // CHECKER_PX) + (c // CHECKER_PX)) % 2 == 1
    return np.where(dark[..., None], np.array(DARK), np.array(LIGHT)).astype(np.uint8)


def _dot(rgb: np.ndarray, row: int, col: int, color) -> None:
    r, c = np.mgrid[0 : rgb.shape[0], 0 : rgb.shape[1]]
    rgb[(r - row) ** 2 + (c - col) ** 2 <= DOT_RADIUS_PX**2] = color


def cone_heights() -> np.ndarray:
    x, z = _world_xz(CONE_SIZE, CONE_PIXEL_M)
    return np.maximum(0.0, CONE_PEAK_M * (1.0 - np.hypot(x, z) / CONE_RADIUS_M)).astype(np.float32)


def cone_ortho() -> np.ndarray:
    rgb = _checkerboard(CONE_SIZE)
    centre = CONE_SIZE // 2  # pixel 512 sits exactly at world (0, 0), the peak
    _dot(rgb, centre, centre, RED)
    _dot(rgb, DOT_RADIUS_PX, centre, BLUE)  # middle of the north edge
    return rgb


def build(name: str, out: Path) -> dict:
    common = dict(bounds=None, crs=None, max_dsm_side=2048, max_ortho_side=4096)
    if name == "cone":
        return write_bundle(
            out,
            cone_heights(),
            cone_ortho(),
            units="m",
            pixel_size_m=CONE_PIXEL_M,
            pixel_size_assumed=False,
            calibration={"method": "synthetic", "confidence": "exact"},
            source_name="synthetic cone",
            **common,
        )
    if name == "relative":
        return write_bundle(
            out,
            cone_heights() / CONE_PEAK_M,
            cone_ortho(),
            units="relative",
            pixel_size_m=1.0,
            pixel_size_assumed=True,
            calibration={"method": "none", "confidence": "n/a"},
            source_name="synthetic relative cone",
            **common,
        )
    if name == "orientation":
        n, q = ORIENT_SIZE, ORIENT_SIZE // 4
        heights = np.zeros((n, n), np.float32)
        heights[:q, :q] = ORIENT_RAISE_M  # north-west corner only
        rgb = _checkerboard(n)
        rgb[:q, :q] = RED
        return write_bundle(
            out,
            heights,
            rgb,
            units="m",
            pixel_size_m=1.0,
            pixel_size_assumed=False,
            calibration={"method": "synthetic", "confidence": "exact"},
            source_name="synthetic orientation (NW corner raised)",
            **common,
        )
    raise ValueError(f"Unknown synthetic bundle {name!r}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m depthwizard.export.synthetic")
    parser.add_argument("name", choices=["cone", "orientation", "relative"])
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    meta = build(args.name, Path(args.out))
    size = f"{meta['width']}x{meta['height']}"
    print(f"{args.out}: {size}, {meta['min_h']:.1f}..{meta['max_h']:.1f} {meta['units']}")


if __name__ == "__main__":
    main()
