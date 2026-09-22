"""Demo scene: Namchi, South Sikkim. WorldView-3, 14 March 2022, 0.37 m, true colour.

Imagery: Maxar Open Data Program (event "India-Floods-Oct-2023"), licence CC BY-NC 4.0.
Credit "Maxar Open Data Program" wherever the imagery is shown. Non-commercial use only.

The town centre sits where four "visual" COG tiles meet. This script downloads them once into
data/demo/namchi/raw/, mosaics them, and crops a square around the town:

    python scripts/fetch_demo_namchi.py        -> data/demo/namchi/namchi.tif

Calibration DEM for this scene: CartoDEM V3R1 tile 88E27N (Bhuvan), or Copernicus by default.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import rasterio
import requests
from pyproj import Transformer
from rasterio.merge import merge

from depthwizard.config import REPO_ROOT
from evals.datasets.naip3dep import write_geotiff_rgb

BASE_URL = (
    "https://maxar-opendata.s3.amazonaws.com/events/India-Floods-Oct-2023/ard/45/"
    "{quadkey}/2022-03-14/1040010073381800-visual.tif"
)
QUADKEYS = ["120220211230", "120220211231", "120220211232", "120220211233"]
CENTRE_LONLAT = (88.363, 27.165)  # Namchi town centre
SIZE_PX = 8192  # about 3 km at 0.37 m; the pipeline handles this in well under a minute
OUT_DIR = REPO_ROOT / "data" / "demo" / "namchi"
ATTRIBUTION = "Maxar Open Data Program, WorldView-3 2022-03-14, CC BY-NC 4.0"
TIMEOUT_S = 120


def download(url: str, dest: Path) -> Path:
    if dest.exists():
        return dest
    print(f"downloading {url}")
    with requests.get(url, stream=True, timeout=TIMEOUT_S) as resp:
        resp.raise_for_status()
        part = dest.with_suffix(".part")
        with part.open("wb") as f:
            for chunk in resp.iter_content(chunk_size=1 << 20):
                f.write(chunk)
    part.replace(dest)
    return dest


def main() -> None:
    raw = OUT_DIR / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    paths = [download(BASE_URL.format(quadkey=q), raw / f"{q}.tif") for q in QUADKEYS]

    sources = [rasterio.open(p) for p in paths]
    try:
        crs, res = sources[0].crs, sources[0].res[0]
        x, y = Transformer.from_crs("EPSG:4326", crs, always_xy=True).transform(*CENTRE_LONLAT)
        half = SIZE_PX / 2 * res
        rgb, transform = merge(
            sources,
            bounds=(x - half, y - half, x + half, y + half),
            res=res,
            indexes=[1, 2, 3],
            nodata=0,
        )
    finally:
        for src in sources:
            src.close()

    coverage = float(rgb.any(axis=0).mean())
    out = OUT_DIR / "namchi.tif"
    write_geotiff_rgb(out, rgb.astype(np.uint8), crs, transform)
    with rasterio.open(out, "r+") as dst:
        dst.update_tags(SOURCE=ATTRIBUTION, CENTRE_LONLAT=str(CENTRE_LONLAT))
    print(f"{out}: {rgb.shape[2]}x{rgb.shape[1]} px at {res:.3f} m, {crs}, coverage {coverage:.1%}")
    print(f"Credit: {ATTRIBUTION}")


if __name__ == "__main__":
    main()
