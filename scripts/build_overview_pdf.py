"""Build the project overview PDF: docs/overview/overview.html -> out/overview/*.pdf.

Accuracy numbers are filled in from eval runs in evals/results/ (the newest full run and the newest
tuning run, unless named), never typed into the template. The template's prose was written for the
run named in its footer: after a new full run, reread the Results section before sending the PDF.
Figures come from out/pitch_assets/ and the run's failure gallery. Printing uses Microsoft Edge or
Google Chrome in headless mode.

    python scripts/build_overview_pdf.py [--run full-...] [--tune tune-...] [--html-only]
"""

from __future__ import annotations

import argparse
import csv
import datetime
import html
import json
import math
import shutil
import subprocess
import tempfile
from pathlib import Path
from string import Template

import cv2
import yaml

from depthwizard.config import REPO_ROOT

TEMPLATE = REPO_ROOT / "docs" / "overview" / "overview.html"
RESULTS = REPO_ROOT / "evals" / "results"
OUT_DIR = REPO_ROOT / "out" / "overview"
PDF_NAME = "DepthWizard-Overview.pdf"
LANDSCAPES = ("urban", "sparse", "hilly", "forested")
METHODS = {"dem_only": "dem", "method_a": "a", "method_b": "b"}
METHOD_LABELS = {
    "dem_only": "DEM only",
    "method_a": "Method A",
    "method_b": "DepthWizard (Method B)",
}
METRICS = {
    "rmse": "rmse",
    "mae": "mae",
    "pearson_r": "r",
    "bias": "bias",
    "nmad": "nmad",
    "offset_free_rmse": "ofrmse",
    "ndsm_rmse": "ndsm",
}
SITE_NAMES = {
    "denver": "Denver, CO",
    "austin": "Austin, TX",
    "palouse": "Palouse farmland, WA",
    "boulder_foothills": "Boulder foothills, CO",
    "smokies": "Great Smoky Mts, TN",
    "vermont": "Green Mountains, VT",
}
FIGURES = {
    "fig_icon": "docs/assets/icon.png",
    "fig_hero": "out/pitch_assets/viewer_namchi_3d.png",
    "fig_app": "out/pitch_assets/viewer_namchi_app.png",
    "fig_terrains": "out/pitch_assets/viewer_terrains.png",
    "fig_namchi_rgb": "out/pitch_assets/namchi_input_rgb_zoom1km.jpg",
    "fig_namchi_zoom": "out/pitch_assets/namchi_dem_vs_dsm_zoom1km.png",
    "fig_namchi_rgb_full": "out/pitch_assets/namchi_input_rgb.jpg",
    "fig_namchi_full": "out/pitch_assets/namchi_dem_vs_dsm_full.png",
}
BROWSERS = (
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
)
DEM_COLOR, B_COLOR = "#a7adb5", "#1f5b45"
# Figures go into the PDF as JPEG copies this size: sharp in print, and a PDF small enough to send.
FIG_MAX_SIDE_PX, FIG_JPEG_QUALITY = 2000, 85


def run_dir(prefix: str, name: str | None) -> Path:
    if name:
        path = RESULTS / name
        if not path.is_dir():
            raise SystemExit(f"No eval run at {path}")
        return path
    runs = sorted(p for p in RESULTS.glob(f"{prefix}-*") if p.is_dir())
    if not runs:
        raise SystemExit(
            f"No {prefix} run in {RESULTS}. Run `python -m evals.run --split full` first."
        )
    return runs[-1]


def fmt(short: str, value: float) -> str:
    return f"{value:.3f}" if short == "r" else f"{value:.2f}"


def accuracy_numbers(summary: dict) -> dict[str, str]:
    """$urban_b_rmse, $all_dem_r, ...; $urban_gain_rmse is Method B's gain over DEM only, in %."""
    out = {}
    for landscape in (*LANDSCAPES, "all"):
        for method, m in METHODS.items():
            row = summary[landscape][method]
            out[f"{landscape}_{m}_tiles"] = str(row["tiles"])
            for metric, short in METRICS.items():
                out[f"{landscape}_{m}_{short}"] = fmt(short, row[metric])
        dem, b = summary[landscape]["dem_only"], summary[landscape]["method_b"]
        for metric, short in (("rmse", "rmse"), ("ndsm_rmse", "ndsm")):
            gain = 100 * (dem[metric] - b[metric]) / dem[metric]
            out[f"{landscape}_gain_{short}"] = f"{gain:.1f}"
    return out


def landscape_table(summary: dict, methods: tuple[str, ...]) -> str:
    cols = (
        ("rmse", "RMSE"),
        ("mae", "MAE"),
        ("pearson_r", "r"),
        ("bias", "Bias"),
        ("nmad", "NMAD"),
        ("offset_free_rmse", "Offset-free RMSE"),
        ("ndsm_rmse", "nDSM RMSE"),
    )
    head = "".join(f'<th class="num">{label}</th>' for _, label in cols)
    rows = []
    for landscape in (*LANDSCAPES, "all"):
        name = "All test tiles" if landscape == "all" else landscape.capitalize()
        for i, method in enumerate(methods):
            r = summary[landscape][method]
            classes = ["grp"] if i == 0 else []
            if method == "method_b":
                classes.append("hl")
            first = (
                f'<td rowspan="{len(methods)}" class="ls">{name}<br>'
                f"<span>{r['tiles']} tiles</span></td>"
                if i == 0
                else ""
            )
            cells = "".join(f'<td class="num">{fmt(METRICS[key], r[key])}</td>' for key, _ in cols)
            rows.append(
                f'<tr class="{" ".join(classes)}">{first}'
                f"<td>{METHOD_LABELS[method]}</td>{cells}</tr>"
            )
    return (
        f'<table class="results"><thead><tr><th>Landscape</th><th>Method</th>{head}</tr></thead>'
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def bar_chart(title: str, metric: str, summary: dict) -> str:
    """Grouped bars, DEM only vs Method B, per landscape; inline SVG so the PDF stays vector."""
    cats = [*LANDSCAPES, "all"]
    series = (("DEM only", DEM_COLOR, "dem_only"), ("DepthWizard", B_COLOR, "method_b"))
    values = {key: [summary[c][key][metric] for c in cats] for _, _, key in series}
    top = max(max(v) for v in values.values())
    step = next(s for s in (0.5, 1, 2, 2.5, 5, 10, 20, 25, 50, 100, 200) if top / s <= 5)
    ymax = step * math.ceil(top / step)
    w, h, left, right, top_pad, bottom = 330, 210, 30, 4, 44, 24
    plot_w, plot_h = w - left - right, h - top_pad - bottom

    def y(v: float) -> float:
        return top_pad + plot_h * (1 - v / ymax)

    parts = [
        f'<svg viewBox="0 0 {w} {h}" class="chart" role="img" aria-label="{html.escape(title)}">',
        f'<text x="0" y="13" class="ct">{html.escape(title)}</text>',
    ]
    lx = 0
    for label, color, _ in series:
        parts.append(f'<rect x="{lx}" y="22" width="9" height="9" rx="2" fill="{color}"/>')
        parts.append(f'<text x="{lx + 13}" y="30" class="lg">{label}</text>')
        lx += 13 + 7 * len(label) + 14
    for i in range(round(ymax / step) + 1):
        v = i * step
        parts.append(
            f'<line x1="{left}" x2="{w - right}" y1="{y(v):.1f}" y2="{y(v):.1f}" class="grid"/>'
            f'<text x="{left - 5}" y="{y(v) + 3:.1f}" class="tick" text-anchor="end">{v:g}</text>'
        )
    group = plot_w / len(cats)
    bw = min(group * 0.34, 22)
    for i, cat in enumerate(cats):
        cx = left + group * (i + 0.5)
        for j, (_, color, key) in enumerate(series):
            v = values[key][i]
            x = cx - bw - 1 if j == 0 else cx + 1
            parts.append(
                f'<rect x="{x:.1f}" y="{y(v):.1f}" width="{bw:.1f}" height="{y(0) - y(v):.1f}" '
                f'rx="1.5" fill="{color}"/>'
                f'<text x="{x + bw / 2:.1f}" y="{y(v) - 3:.1f}" class="val" text-anchor="middle">'
                f"{v:.1f}</text>"
            )
        label = "All" if cat == "all" else cat.capitalize()
        parts.append(
            f'<text x="{cx:.1f}" y="{h - 8}" class="cat" text-anchor="middle">{label}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


def runtime(per_tile: list[dict]) -> dict[str, str]:
    scenes = {r["scene"]: r for r in per_tile if r.get("scene") and r.get("scene_depth_s")}
    if not scenes:
        raise SystemExit("The run has no per-scene timings (scene_depth_s) in per_tile.csv.")
    depth = [float(r["scene_depth_s"]) for r in scenes.values()]
    cal = [float(r["scene_calibrate_s"]) for r in scenes.values()]
    return {
        "rt_scenes": str(len(scenes)),
        "rt_scene_px": next(iter(scenes.values()))["scene_px"].replace("x", "×"),
        "rt_depth": f"{sum(depth) / len(depth):.2f}",
        "rt_cal": f"{sum(cal) / len(cal):.2f}",
    }


def load_causes() -> dict[str, str]:
    path = REPO_ROOT / "evals" / "failure_causes.yaml"
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}


def worst_tiles(per_tile: list[dict], run: Path, n: int = 5) -> dict[str, str]:
    rows = [r for r in per_tile if r["method"] == "method_b" and r.get("rmse")]
    rows.sort(key=lambda r: float(r["rmse"]), reverse=True)
    rows = rows[:n]
    causes = load_causes()
    body = "".join(
        f"<tr><td>{html.escape(r['tile'])}</td><td>{r['landscape']}</td>"
        f'<td class="num">{float(r["rmse"]):.2f}</td><td class="num">{float(r["nmad"]):.2f}</td>'
        f"<td>{html.escape(r.get('cal_source') or '')}</td>"
        f"<td>{html.escape(causes.get(r['tile'], 'to be confirmed by the team'))}</td></tr>"
        for r in rows
    )
    table = (
        '<table class="compact"><thead><tr><th>Tile</th><th>Landscape</th>'
        '<th class="num">RMSE (m)</th><th class="num">NMAD (m)</th><th>Scale source</th>'
        "<th>Cause</th></tr></thead>"
        f"<tbody>{body}</tbody></table>"
    )
    figures = []
    shown = [rows[0]] + [r for r in rows[1:] if r["landscape"] != rows[0]["landscape"]][:1]
    for r in shown:
        image = run / "gallery" / f"{r['tile'].replace('/', '_')}.png"
        if not image.exists():
            continue
        figures.append(
            f'<figure><img src="{compact(image)}" alt="{html.escape(r["tile"])}"><figcaption>'
            f"<b>{html.escape(r['tile'])}</b> ({r['landscape']}): RMSE {float(r['rmse']):.2f} m, "
            f"NMAD {float(r['nmad']):.2f} m. Panels: the image, DepthWizard's DSM, the LiDAR "
            "reference, and the error (red: too high, blue: too low).</figcaption></figure>"
        )
    return {"worst_table": table, "gallery_figures": "".join(figures)}


def sites_table(datasets: dict) -> str:
    rows = []
    for key, d in datasets.items():
        if not key.startswith("naip3dep/"):
            continue
        site = d["site"]
        lidar = d["lidar"]["dsm"][0]["usgs_id"] if d["lidar"]["dsm"] else ""
        rows.append(
            f"<tr><td>{SITE_NAMES.get(site['name'], site['name'])}</td><td>{site['landscape']}</td>"
            f'<td class="num">{site["lat"]:.2f}°, {site["lon"]:.2f}°</td>'
            f'<td class="num">{d["naip"]["year"]}</td><td class="num">{d["naip"]["gsd_m"]:g} m</td>'
            f'<td class="small">{html.escape(lidar)}</td></tr>'
        )
    return (
        '<table class="compact"><thead><tr><th>Site</th><th>Landscape</th>'
        '<th class="num">Lat, lon</th><th class="num">NAIP year</th><th class="num">Pixel</th>'
        "<th>LiDAR project (USGS 3DEP)</th>"
        f"</tr></thead><tbody>{''.join(rows)}</tbody></table>"
    )


def tuning_numbers(tune: Path) -> dict[str, str]:
    summary = json.loads((tune / "summary.json").read_text(encoding="utf-8"))
    dem = next(r for r in summary["dem_only"] if r["resampling"] == "bilinear")
    return {
        "tune_run": tune.name,
        "tune_dem": f"{dem['objective']:.2f}",
        "tune_old": f"{summary['current_default']['objective']:.2f}",
        "tune_best": f"{summary['best']['objective']:.2f}",
    }


def compact(path: Path) -> str:
    """URI of a JPEG copy of the figure, at most FIG_MAX_SIDE_PX on its long side."""
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        raise SystemExit(f"Can't read figure {path}")
    scale = FIG_MAX_SIDE_PX / max(image.shape[:2])
    if scale < 1:
        image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    out = OUT_DIR / "figures" / f"{path.stem}.jpg"
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), image, [cv2.IMWRITE_JPEG_QUALITY, FIG_JPEG_QUALITY])
    return out.as_uri()


def figures() -> dict[str, str]:
    missing = [p for p in FIGURES.values() if not (REPO_ROOT / p).exists()]
    if missing:
        raise SystemExit("Missing figures (see docs/PITCH.md and scripts/): " + ", ".join(missing))
    # The icon keeps its PNG transparency; everything else is a photo or a render.
    return {
        k: (REPO_ROOT / p).as_uri() if k == "fig_icon" else compact(REPO_ROOT / p)
        for k, p in FIGURES.items()
    }


def find_browser() -> str:
    for path in BROWSERS:
        if Path(path).exists():
            return path
    for name in ("msedge", "chrome", "chromium"):
        if found := shutil.which(name):
            return found
    raise SystemExit("Printing the PDF needs Microsoft Edge or Google Chrome.")


def print_pdf(page: Path, pdf: Path) -> None:
    pdf.unlink(missing_ok=True)
    profile = Path(tempfile.mkdtemp(prefix="dw-print-"))  # never touch the user's browser profile
    try:
        subprocess.run(
            [
                find_browser(),
                "--headless=new",
                "--disable-gpu",
                "--no-first-run",
                "--no-pdf-header-footer",
                f"--user-data-dir={profile}",
                "--virtual-time-budget=15000",
                f"--print-to-pdf={pdf}",
                page.as_uri(),
            ],
            check=True,
            capture_output=True,
            timeout=300,
        )
    finally:
        shutil.rmtree(profile, ignore_errors=True)
    if not pdf.exists():
        raise SystemExit("The browser exited without writing the PDF.")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python scripts/build_overview_pdf.py")
    parser.add_argument("--run", help="full eval run id (default: the newest full-* run)")
    parser.add_argument("--tune", help="tuning run id (default: the newest tune-* run)")
    parser.add_argument("--html-only", action="store_true", help="write the HTML, skip the PDF")
    args = parser.parse_args()

    run, tune = run_dir("full", args.run), run_dir("tune", args.tune)
    metrics = json.loads((run / "metrics.json").read_text(encoding="utf-8"))
    with open(run / "per_tile.csv", newline="", encoding="utf-8") as f:
        per_tile = list(csv.DictReader(f))
    summary, relative = metrics["summary"], metrics["relative_summary"]

    values = {
        "run_id": run.name,
        "build_date": datetime.date.today().strftime("%d %B %Y").lstrip("0"),
        "device": metrics["device"].removeprefix("cuda:"),
        "gamus_tiles": str(relative["tiles"]),
        "gamus_rmse": f"{relative['rmse']:.2f}",
        "gamus_mae": f"{relative['mae']:.2f}",
        "gamus_r": f"{relative['pearson_r']:.3f}",
        "table_main": landscape_table(summary, ("dem_only", "method_b")),
        "table_all_methods": landscape_table(summary, ("dem_only", "method_a", "method_b")),
        "chart_rmse": bar_chart("RMSE against LiDAR (m, lower is better)", "rmse", summary),
        "chart_ndsm": bar_chart("Buildings and trees only: nDSM RMSE (m)", "ndsm_rmse", summary),
        "sites_table": sites_table(metrics["datasets"]),
        **accuracy_numbers(summary),
        **runtime(per_tile),
        **tuning_numbers(tune),
        **worst_tiles(per_tile, run),
        **figures(),
    }
    page = Template(TEMPLATE.read_text(encoding="utf-8")).substitute(values)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    page_path = OUT_DIR / "DepthWizard-Overview.html"
    page_path.write_text(page, encoding="utf-8")
    if args.html_only:
        print(page_path)
        return
    print_pdf(page_path, OUT_DIR / PDF_NAME)
    print(f"{OUT_DIR / PDF_NAME} (numbers from {run.name} and {tune.name})")


if __name__ == "__main__":
    main()
