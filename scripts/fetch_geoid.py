"""Download the EGM2008 geoid grid once (2.5 arc-minute, PROJ CDN, public domain, ~81 MB).

With it, ellipsoidal DEMs such as CartoDEM V3R1 are converted to EGM2008 heights offline, the
same datum Copernicus GLO-30 uses. Without it they stay ellipsoidal and say so.

    python scripts/fetch_geoid.py          -> data/geoid/us_nga_egm08_25.tif
"""

import rasterio
import requests

from depthwizard.config import load_config, resolve_path

URL = "https://cdn.proj.org/us_nga_egm08_25.tif"
TIMEOUT_S = 120


def main() -> None:
    dest = resolve_path(load_config().dem.geoid_grid)
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        print(f"downloading {URL}")
        with requests.get(URL, stream=True, timeout=TIMEOUT_S) as resp:
            resp.raise_for_status()
            part = dest.with_suffix(".part")
            with part.open("wb") as f:
                for chunk in resp.iter_content(chunk_size=1 << 20):
                    f.write(chunk)
        part.replace(dest)
    with rasterio.open(dest) as src:
        print(
            f"{dest}: {src.width}x{src.height} {src.dtypes[0]}, {src.crs}, "
            f"scale {src.scales[0]}, offset {src.offsets[0]}"
        )


if __name__ == "__main__":
    main()
