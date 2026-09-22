"""Small PNG renders for eval runs and REPORT.md: hillshades, RGB thumbnails, error maps."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

SUN_AZIMUTH_DEG, SUN_ALTITUDE_DEG = 315.0, 45.0  # the cartographic convention: light from NW


def hillshade(z: np.ndarray, cell_m: float) -> np.ndarray:
    """0..1 shaded relief of a height grid with square cells of `cell_m` metres."""
    gy, gx = np.gradient(z, cell_m)
    slope = np.arctan(np.hypot(gx, gy))
    aspect = np.arctan2(-gx, gy)
    az, alt = np.radians(SUN_AZIMUTH_DEG), np.radians(SUN_ALTITUDE_DEG)
    shade = np.sin(alt) * np.cos(slope) + np.cos(alt) * np.sin(slope) * np.cos(az - aspect)
    return np.clip(shade, 0.0, 1.0)


def save_hillshade(z: np.ndarray, pixel_m: float, path: Path, size: int) -> None:
    filled = np.where(np.isfinite(z), z, np.nanmin(z))
    small = cv2.resize(filled.astype(np.float32), (size, size), interpolation=cv2.INTER_AREA)
    cell = pixel_m * z.shape[1] / size
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), (hillshade(small, cell) * 255).astype(np.uint8))


def save_rgb(rgb: np.ndarray, path: Path, size: int) -> None:
    small = cv2.resize(rgb, (size, size), interpolation=cv2.INTER_AREA)
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), cv2.cvtColor(small, cv2.COLOR_RGB2BGR))


def save_error_map(err: np.ndarray, clamp: float, path: Path, max_side: int) -> None:
    """Diverging map centred on 0 (blue = too low, red = too high), clamped at ±clamp."""
    t = np.clip(np.nan_to_num(err / max(clamp, 1e-6)), -1.0, 1.0)[..., None]
    white, blue, red = np.array([235, 235, 230]), np.array([60, 110, 190]), np.array([200, 70, 55])
    rgb = np.where(t < 0, white + (blue - white) * -t, white + (red - white) * t)
    rgb[~np.isfinite(err)] = (70, 70, 70)
    scale = max_side / max(err.shape)
    if scale < 1:
        rgb = cv2.resize(
            rgb.astype(np.float32), None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), cv2.cvtColor(rgb.astype(np.uint8), cv2.COLOR_RGB2BGR))


def labelled_strip(images: list[tuple[str, Path]], size: int, out: Path) -> None:
    """Side-by-side panels, each with a caption above it (for the failure gallery)."""
    gap, caption_h = 12, 28
    canvas = np.full((size + caption_h, len(images) * (size + gap) - gap, 3), 255, np.uint8)
    for i, (label, path) in enumerate(images):
        img = cv2.imread(str(path))
        if img is None:
            continue
        img = cv2.resize(img, (size, size), interpolation=cv2.INTER_AREA)
        x = i * (size + gap)
        canvas[caption_h:, x : x + size] = img
        cv2.putText(
            canvas, label, (x + 4, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (40, 40, 40), 1, cv2.LINE_AA
        )
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), canvas)
