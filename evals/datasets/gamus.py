"""GAMUS (Hugging Face `earthflow/GAMUS`, CC-BY-4.0), the dataset recommended by the SIH26175 brief.

1024x1024 RGB tiles with float32 height above ground (AGL, i.e. an nDSM) from Washington DC,
New York and Philadelphia; splits train 5004 / val 859 / test 2861. There is no georeference,
so GAMUS serves relative-mode evaluation, polarity checks, scene-prior tuning (val only) and
decoder fine-tuning. Absolute-DSM numbers come from NAIP + 3DEP instead.

    python -m evals.datasets.gamus download --split val --limit 60
    python -m evals.datasets.gamus png --split val --stem DC_03_26 --out data/samples/sample.png
"""

from __future__ import annotations

import argparse
import math
from collections import defaultdict
from pathlib import Path

import cv2
import h5py
import numpy as np
from huggingface_hub import HfApi, snapshot_download

from depthwizard.config import REPO_ROOT

REPO_ID = "earthflow/GAMUS"
ROOT = REPO_ROOT / "data" / "datasets" / "gamus"


def list_stems(split: str) -> list[str]:
    files = HfApi().list_repo_files(REPO_ID, repo_type="dataset")
    prefix, suffix = f"images/{split}/", "_RGB.h5"
    return sorted(
        Path(f).name[: -len(suffix)] for f in files if f.startswith(prefix) and f.endswith(suffix)
    )


def local_stems(split: str) -> list[str]:
    return sorted(p.name[: -len("_RGB.h5")] for p in (ROOT / "images" / split).glob("*_RGB.h5"))


def select_balanced(stems: list[str], limit: int) -> list[str]:
    """Deterministic subset spread evenly over each city's tiles, cities equally represented."""
    by_city: dict[str, list[str]] = defaultdict(list)
    for s in stems:
        by_city[s.split("_")[0]].append(s)
    per_city = math.ceil(limit / len(by_city))
    chosen = []
    for city in sorted(by_city):
        tiles = by_city[city]
        idx = np.unique(
            np.linspace(0, len(tiles) - 1, min(per_city, len(tiles))).round().astype(int)
        )
        chosen += [tiles[i] for i in idx]
    return sorted(chosen)[:limit] if len(chosen) > limit else sorted(chosen)


def download(split: str, limit: int | None = None) -> list[str]:
    stems = list_stems(split)
    if limit:
        stems = select_balanced(stems, limit)
    patterns = [f"images/{split}/{s}_RGB.h5" for s in stems] + [
        f"heights/{split}/{s}_AGL.h5" for s in stems
    ]
    snapshot_download(REPO_ID, repo_type="dataset", local_dir=ROOT, allow_patterns=patterns)
    return stems


def load_pair(split: str, stem: str) -> tuple[np.ndarray, np.ndarray]:
    """(H, W, 3) uint8 RGB and (H, W) float32 height above ground in metres."""
    with h5py.File(ROOT / "images" / split / f"{stem}_RGB.h5", "r") as f:
        rgb = f["image"][()]
    with h5py.File(ROOT / "heights" / split / f"{stem}_AGL.h5", "r") as f:
        agl = f["image"][()]
    return np.asarray(rgb, dtype=np.uint8), np.asarray(agl, dtype=np.float32)


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m evals.datasets.gamus")
    sub = parser.add_subparsers(dest="command", required=True)
    dl = sub.add_parser("download")
    dl.add_argument("--split", required=True, choices=["train", "val", "test"])
    dl.add_argument("--limit", type=int, help="balanced subset size (default: whole split)")
    png = sub.add_parser("png", help="export one tile's RGB as a PNG sample")
    png.add_argument("--split", required=True)
    png.add_argument("--stem", required=True)
    png.add_argument("--out", required=True)
    args = parser.parse_args()
    if args.command == "download":
        stems = download(args.split, args.limit)
        print(f"{len(stems)} tiles in {ROOT}")
    else:
        rgb, _ = load_pair(args.split, args.stem)
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(args.out, cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
        print(args.out)


if __name__ == "__main__":
    main()
