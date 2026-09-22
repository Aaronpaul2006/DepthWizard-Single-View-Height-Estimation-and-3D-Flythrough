"""Polarity check: on a top-down image, taller surfaces must get larger predicted values.

Run it on every new data source (CLAUDE.md, known gotchas). Reference heights are only used
here and in evals; calibration never sees them.
"""

from __future__ import annotations

import numpy as np


def polarity_r(pred: np.ndarray, ref: np.ndarray) -> float:
    """Pearson r between prediction and reference over pixels finite in both.
    Positive means rooftops come out above roads; negative means the sign is flipped."""
    ok = np.isfinite(pred) & np.isfinite(ref)
    if ok.sum() < 2:
        raise ValueError("Need at least two valid pixels to check polarity.")
    return float(np.corrcoef(pred[ok].astype(np.float64), ref[ok].astype(np.float64))[0, 1])
