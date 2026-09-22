"""Polarity check on GAMUS val: prediction vs height above ground must correlate positively.

python -m evals.polarity --n 12
"""

from __future__ import annotations

import argparse
import logging

import numpy as np

from depthwizard.config import load_config
from depthwizard.depth.model import DepthModel
from depthwizard.depth.polarity import polarity_r
from depthwizard.depth.stitch import predict_tiled
from evals.datasets.gamus import load_pair, local_stems, select_balanced


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m evals.polarity")
    parser.add_argument("--split", default="val", choices=["val"])  # never tune or check on test
    parser.add_argument("--n", type=int, default=12)
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)

    cfg = load_config()
    model = DepthModel(cfg.model)
    stems = select_balanced(local_stems(args.split), args.n)
    rs = []
    for stem in stems:
        rgb, agl = load_pair(args.split, stem)
        r = polarity_r(predict_tiled(model, rgb, cfg.depth), agl)
        rs.append(r)
        print(f"{stem:12s} r = {r:+.3f}")
    rs = np.array(rs)
    negative = int((rs < 0).sum())
    print(f"GAMUS {args.split}: {len(rs)} tiles, mean r = {rs.mean():+.3f}, negative: {negative}")
    # A flipped sign shows up on most tiles; one weak or negative tile is a model failure
    # (failure gallery material), not a polarity problem.
    if rs.mean() <= 0 or negative > len(rs) / 2:
        raise SystemExit("Polarity looks flipped: most tiles put rooftops below roads.")
    if negative:
        print(f"Warning: {negative} tile(s) correlate negatively; inspect them as failure cases.")


if __name__ == "__main__":
    main()
