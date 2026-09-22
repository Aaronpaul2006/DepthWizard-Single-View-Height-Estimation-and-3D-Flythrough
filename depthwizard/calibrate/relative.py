"""Stage 3a: relative DSM for images without georeference (no units, 0 = low, 1 = high)."""

from __future__ import annotations

import numpy as np


def normalize_relative(d: np.ndarray, percentiles: list[float]) -> np.ndarray:
    """rDSM = (d − p_lo) / (p_hi − p_lo), clipped to [0, 1]."""
    lo, hi = np.nanpercentile(d, percentiles)
    scaled = (d - lo) / max(float(hi - lo), float(np.finfo(np.float32).eps))
    return np.clip(scaled, 0.0, 1.0).astype(np.float32)
