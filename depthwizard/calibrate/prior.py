"""Scene prior: last-resort scale for the model detail when nothing better is available.

Assumes the `percentile`-th value of d_high corresponds to `height_m` metres above the local
terrain. The pair is tuned on validation splits only; confidence is always low.
"""

from __future__ import annotations

import numpy as np


def prior_scale(d_high: np.ndarray, percentile: float, height_m: float) -> float:
    ref = float(np.nanpercentile(d_high, percentile))
    if ref <= np.finfo(np.float32).eps:  # featureless scene: add no detail
        return 0.0
    return height_m / ref
