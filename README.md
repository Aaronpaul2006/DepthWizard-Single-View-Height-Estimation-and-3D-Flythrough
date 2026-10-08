# DepthWizard

Height maps and 3D flythroughs from a single satellite image.

Smart India Hackathon 2026 · Problem statement **SIH26175** · Indian Space Research Organisation (ISRO) · Software · Miscellaneous

## The problem

Elevation data usually comes from stereo image pairs, LiDAR, or radar interferometry (InSAR). Each one needs a particular sensor, costs money, or takes heavy processing. A single optical image is much easier to get. The catch is that depth models are trained mostly on ground-level photos. They predict depth with no units, and top-down views confuse them.

ISRO's brief asks for a pipeline that:

1. Accepts one RGB image (PNG, JPG, or GeoTIFF) and outputs a Digital Surface Model (DSM) in a standard geospatial format.
2. For images without location data, outputs a relative DSM.
3. For georeferenced images, outputs an absolute DSM in metres. A lower-resolution DEM such as SRTM, or a few ground control points, sets the scale.
4. Drapes the original image over a 3D terrain mesh in a rendering engine, with first-person navigation and tools to check structure heights and slopes.
5. Lets users upload imagery and compare estimated heights against reference data.
6. Ships as a standalone application with full source and documentation.

**Scoring:**
- **50% DSM accuracy:** RMSE, MAE, and correlation against LiDAR or reference data, including stability across urban, sparse, hilly, and forested landscapes.
- **50% visualization:** projection accuracy, visual quality, navigation, interface, stability, and standalone deployment.

## How DepthWizard works

1. **Relative height.** Depth Anything V2 (Small) runs on overlapping tiles. Each tile is aligned to a low-resolution pass over the whole image, then blended, so large scenes come out without tile seams.
2. **Terrain from the DEM, detail from the model.** A 30 m DEM already knows the hills and valleys, but it can't see a single building. The model sees buildings and trees but has no idea of scale. We keep the DEM's terrain and add the model's fine detail on top. The detail is scaled by ground control points, OpenStreetMap building heights, or a fit against the DEM, whichever is available.
3. **Export.** A Float32 GeoTIFF DSM, plus a compact bundle for the viewer.
4. **Viewer.** A Three.js flythrough with:
   - height readout on click
   - a slope map
   - elevation profiles along a drawn line
   - an error heatmap against an uploaded reference DSM
5. **Packaging.** A Tauri desktop app with the Python backend as a sidecar. It also runs as a local web app.

For Indian scenes we calibrate with ISRO's own CartoDEM from Bhuvan. Copernicus GLO-30 and SRTM are supported too.

## Results

These come from `evals/REPORT.md`. Don't type numbers here by hand.

| Landscape | DEM-only RMSE (m) | DepthWizard RMSE (m) | DepthWizard MAE (m) | Correlation |
|---|---|---|---|---|
| Urban | TBD | TBD | TBD | TBD |
| Sparse | TBD | TBD | TBD | TBD |
| Hilly | TBD | TBD | TBD | TBD |
| Forested | TBD | TBD | TBD | TBD |

## Quickstart

Needs Python 3.12 (3.11 works) and Node.js 22+. RTX 50-series (Blackwell) GPUs need the CUDA 12.8 PyTorch wheels; the app also runs, slowly, on CPU.

```bash
py -3.12 -m venv .venv
.venv/Scripts/python -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
.venv/Scripts/python -m pip install -e ".[dev,eval]"
.venv/Scripts/python scripts/fetch_model.py    # once: downloads the depth model to data/models/
.venv/Scripts/python scripts/fetch_geoid.py    # once: EGM2008 geoid grid (converts CartoDEM to sea-level heights)

# build the viewer (stratum) once
cd viewer && npm ci && npm run build && cd ..

# run the pipeline on one image. --dem is optional: without it, Copernicus GLO-30 is fetched once and cached
python -m depthwizard run --input path/to/scene.tif --out out/ --dem data/dem/cartodem/

# start the app (backend + viewer); the browser opens by itself at http://127.0.0.1:8000
run_local.bat          # Windows (or ./run_local.sh elsewhere)
```

In the app, **Process image** uploads a new image, and **Terrains** switches between everything processed so far. A result's link (`?job=<id>`) reopens it. On a metric result, **DEM only** (key B, also while flying) swaps the terrain between the calibration DEM alone and DepthWizard's DSM under the same camera; it shows best on the Slope surface at Quality "Detail · 1024". **Water level** floods the terrain and shows the share of the area under water.

```bash
# optional: the demo scene (Namchi, Sikkim; Maxar Open Data, CC BY-NC 4.0)
python scripts/fetch_demo_namchi.py
```

## Desktop app

`dist\DepthWizard\depthwizard.exe` is the standalone build: a Tauri window plus the bundled backend. The target machine needs no Python. It is about 4.7 GB, almost all of it PyTorch with CUDA; without a GPU it runs on the CPU. Jobs and caches go to `%LOCALAPPDATA%\in.sih2026.depthwizard`. Build it with the steps in [desktop/README.md](desktop/README.md). `run_local.bat` is the web-mode fallback.

## Repository layout

```
depthwizard/   pipeline package (io, depth, calibrate, export)
api/           FastAPI backend
evals/         datasets, test splits, metrics, REPORT.md
viewer/        Three.js flythrough
desktop/       Tauri app shell
configs/       all tunable settings
docs/          plan, architecture, viewer contract, evaluation, pitch
```

## Docs

- [Plan and phases](docs/PLAN.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Viewer contract](docs/VIEWER_CONTRACT.md)
- [Evaluation](docs/EVALUATION.md)
- [Pitch and demo](docs/PITCH.md)
- Project overview PDF: `python scripts/build_overview_pdf.py` writes `out/overview/DepthWizard-Overview.pdf`. The template is [docs/overview/overview.html](docs/overview/overview.html); its numbers come from `evals/results/`.

## Team

[Team name] · [Team ID] · [Institute]
