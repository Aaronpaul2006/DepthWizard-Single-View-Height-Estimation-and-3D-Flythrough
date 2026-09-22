"""Quick-look previews of height grids."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np


def write_png16(path: str | Path, grid: np.ndarray, percentiles: tuple[float, float]) -> None:
    """Stretch `grid` between the given percentiles of its finite values into a 16-bit PNG."""
    finite = grid[np.isfinite(grid)]
    lo, hi = np.percentile(finite, percentiles) if finite.size else (0.0, 1.0)
    scaled = np.clip((grid - lo) / max(hi - lo, 1e-12), 0.0, 1.0)
    img = (np.nan_to_num(scaled) * 65535.0 + 0.5).astype(np.uint16)
    if not cv2.imwrite(str(path), img):
        raise OSError(f"Could not write {path}")
