"""Stage 2: global low-res pass, per-tile scale/shift alignment, Hann-window blending.

Every tile prediction has its own arbitrary scale and offset. Aligning each tile to the
whole-image pass G before blending is what removes the seams (ARCHITECTURE.md, Stage 2).
"""

from __future__ import annotations

import logging
from collections.abc import Callable

import cv2
import numpy as np
import torch

from depthwizard.config import DepthConfig
from depthwizard.depth.model import DepthModel
from depthwizard.depth.tiling import tile_origins, window2d

log = logging.getLogger(__name__)

ProgressFn = Callable[[float], None]


def align_to_global(t: np.ndarray, g: np.ndarray, trim_frac: float) -> tuple[float, float]:
    """α, β minimising ‖α·t + β − g‖² over all but the `trim_frac` largest residuals.

    The first estimate is robust (median / MAD): a plain least-squares start lets a few extreme
    pixels in t (water noise, say) drag the slope to ~0, after which their residuals look small
    and trimming can't find them. Two trimmed refits follow; the second uses cleaner residuals."""
    x = t.ravel().astype(np.float64)
    y = g.ravel().astype(np.float64)
    mx, my = np.median(x), np.median(y)
    sx, sy = np.median(np.abs(x - mx)), np.median(np.abs(y - my))
    if sx <= np.finfo(np.float32).eps:  # featureless tile: carry G's level only
        return 0.0, float(my)
    a, b = sy / sx, my - sy / sx * mx
    for _ in range(2):
        resid = np.abs(a * x + b - y)
        keep = resid <= np.quantile(resid, 1.0 - trim_frac)
        a, b = _fit_affine(x[keep], y[keep])
    return a, b


def _fit_affine(x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    xm, ym = x.mean(), y.mean()
    var = np.mean((x - xm) ** 2)
    if var <= np.finfo(np.float32).eps:  # featureless tile: carry G's level only
        return 0.0, float(ym)
    a = np.mean((x - xm) * (y - ym)) / var
    return float(a), float(ym - a * xm)


def predict_tiled(
    model: DepthModel, rgb: np.ndarray, cfg: DepthConfig, progress: ProgressFn | None = None
) -> np.ndarray:
    """Full-resolution relative depth d (float32, larger = higher) for an (H, W, 3) uint8 image."""
    h, w = rgb.shape[:2]
    g = model.predict_resized(rgb, cfg.global_long_side)
    if max(h, w) <= cfg.global_long_side:
        log.info("Image %dx%d fits the global pass; tiles would add no resolution.", w, h)
        if progress:
            progress(1.0)
        return g.astype(np.float32)

    ts = cfg.tile_size
    ph, pw = max(h, ts), max(w, ts)
    if (ph, pw) != (h, w):  # thin strips: mirror-pad so at least one full tile fits
        rgb = cv2.copyMakeBorder(rgb, 0, ph - h, 0, pw - w, cv2.BORDER_REFLECT_101)
        g = cv2.copyMakeBorder(g, 0, ph - h, 0, pw - w, cv2.BORDER_REFLECT_101)

    origins = [
        (y, x)
        for y in tile_origins(ph, ts, cfg.tile_stride)
        for x in tile_origins(pw, ts, cfg.tile_stride)
    ]
    acc = np.zeros((ph, pw), np.float32)
    wsum = np.zeros((ph, pw), np.float32)
    batch_size, i = cfg.batch_size, 0
    while i < len(origins):
        chunk = origins[i : i + batch_size]
        try:
            preds = model.predict_batch(np.stack([rgb[y : y + ts, x : x + ts] for y, x in chunk]))
        except torch.cuda.OutOfMemoryError:
            if batch_size == 1:
                raise
            batch_size = max(1, batch_size // 2)
            torch.cuda.empty_cache()
            log.warning("CUDA out of memory; retrying with batch size %d.", batch_size)
            continue
        for (y, x), t in zip(chunk, preds, strict=True):
            a, b = align_to_global(t, g[y : y + ts, x : x + ts], cfg.align_trim_frac)
            weight = window2d(y, x, ts, ph, pw)
            acc[y : y + ts, x : x + ts] += weight * (a * t + b)
            wsum[y : y + ts, x : x + ts] += weight
        i += len(chunk)
        if progress:
            progress(i / len(origins))
    log.info("Blended %d tiles of %d px (batch size %d).", len(origins), ts, batch_size)
    return (acc / np.maximum(wsum, np.finfo(np.float32).tiny))[:h, :w]


def seam_ratio(d: np.ndarray, cfg: DepthConfig) -> float:
    """Mean |gradient| across tile borders divided by the mean across all other pixel pairs.
    About 1.0 means borders are invisible; clearly above 1.0 means seams."""
    h, w = d.shape
    gx = np.abs(np.diff(d, axis=1))  # gx[:, j] spans columns j and j+1
    gy = np.abs(np.diff(d, axis=0))
    on_x = np.zeros(w - 1, bool)
    on_y = np.zeros(h - 1, bool)
    on_x[[e - 1 for e in _borders(w, cfg)]] = True
    on_y[[e - 1 for e in _borders(h, cfg)]] = True
    border = np.concatenate([gx[:, on_x].ravel(), gy[on_y, :].ravel()])
    inner = np.concatenate([gx[:, ~on_x].ravel(), gy[~on_y, :].ravel()])
    return float(border.mean() / max(inner.mean(), np.finfo(np.float64).tiny))


def _borders(n: int, cfg: DepthConfig) -> list[int]:
    edges = set()
    for start in tile_origins(n, cfg.tile_size, cfg.tile_stride):
        for edge in (start, start + cfg.tile_size):
            if 0 < edge < n:
                edges.add(edge)
    return sorted(edges)
