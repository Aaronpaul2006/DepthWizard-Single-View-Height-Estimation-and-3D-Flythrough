"""Demo scenes for the CartoDEM tiles F43A (Ahmedabad) and E44M (Hyderabad): Sentinel-2 true colour.

Free 10 m imagery: the only open imagery we found for these cities (Maxar's Open Data has none,
see PLAN.md). At 10 m single buildings are not resolved, so these scenes show the city, rivers,
lakes and terrain calibrated with ISRO's CartoDEM, not building heights.

Reads a window of the Sentinel-2 L2A "visual" (TCI) cloud-optimised GeoTIFF straight from the
public AWS bucket (Element 84 Earth Search), no login, and writes it with its own UTM georeference:

    python scripts/fetch_demo_sentinel2.py    -> data/demo/sentinel2/<city>_sentinel2_<date>.tif

Attribution: "Contains modified Copernicus Sentinel data <year>".
Process each scene with its CartoDEM tile: cdnf43a.tif (Ahmedabad), cdne44m.tif (Hyderabad).
"""

from __future__ import annotations

import rasterio
from pyproj import Transformer
from rasterio.windows import Window

from depthwizard.config import REPO_ROOT

OUT_DIR = REPO_ROOT / "data" / "demo" / "sentinel2"
BASE = "https://sentinel-cogs.s3.us-west-2.amazonaws.com/sentinel-s2-l2a-cogs"
SIZE_M = 16000  # a 16 km square around the city centre: 1600 × 1600 px at 10 m
# city: (Sentinel-2 item, city centre lon/lat); items picked as cloud-free with full coverage
SCENES = {
    "ahmedabad": ("43/Q/BF/2026/3/S2B_43QBF_20260302_0_L2A", (72.571, 23.022)),
    "hyderabad": ("44/Q/KE/2026/4/S2A_44QKE_20260429_0_L2A", (78.474, 17.406)),
}


def fetch(city: str, item: str, lonlat: tuple[float, float]) -> None:
    url = f"/vsicurl/{BASE}/{item}/TCI.tif"
    with rasterio.open(url) as src:
        x, y = Transformer.from_crs("EPSG:4326", src.crs, always_xy=True).transform(*lonlat)
        row, col = src.index(x, y)
        half = round(SIZE_M / src.res[0] / 2)
        window = Window(col - half, row - half, 2 * half, 2 * half)
        rgb = src.read(window=window)
        profile = src.profile | {
            "driver": "GTiff",
            "width": 2 * half,
            "height": 2 * half,
            "transform": src.window_transform(window),
            "compress": "deflate",
            "tiled": True,
            "blockxsize": 256,
            "blockysize": 256,
            "nodata": None,
        }
    date = item.split("_")[2]
    out = OUT_DIR / f"{city}_sentinel2_{date[:4]}-{date[4:6]}-{date[6:]}.tif"
    with rasterio.open(out, "w", **profile) as dst:
        dst.write(rgb)
        dst.update_tags(ATTRIBUTION=f"Contains modified Copernicus Sentinel data {date[:4]}")
    print(out)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for city, (item, lonlat) in SCENES.items():
        fetch(city, item, lonlat)


if __name__ == "__main__":
    main()
