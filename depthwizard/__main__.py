"""CLI: python -m depthwizard run --input img.tif --out out/"""

from __future__ import annotations

import argparse
import json
import logging

from depthwizard.config import load_config
from depthwizard.pipeline import run


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m depthwizard")
    sub = parser.add_subparsers(dest="command", required=True)
    run_p = sub.add_parser("run", help="Estimate a DSM from one image")
    run_p.add_argument("--input", required=True, help="PNG, JPG or GeoTIFF")
    run_p.add_argument("--out", required=True, help="output directory")
    run_p.add_argument("--dem", help="DEM GeoTIFF, or a folder of DEM tiles (e.g. CartoDEM)")
    run_p.add_argument("--gcps", help="CSV: x,y,height_m (image CRS) or lon,lat,height_m")
    run_p.add_argument(
        "--offline",
        action="store_true",
        help="don't use Copernicus GLO-30 at all; without --dem the output is a relative DSM",
    )
    run_p.add_argument(
        "--config", action="append", default=[], help="YAML merged over configs/default.yaml"
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    cfg = load_config(*args.config)
    result = run(
        args.input,
        args.out,
        cfg,
        dem_path=args.dem,
        gcps_path=args.gcps,
        allow_fetch=not args.offline,
    )
    print(json.dumps({k: str(v) for k, v in result.files.items()}, indent=2))


if __name__ == "__main__":
    main()
