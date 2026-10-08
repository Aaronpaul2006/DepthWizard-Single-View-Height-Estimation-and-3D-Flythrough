# CLAUDE.md

Read this at the start of every session. It's short on purpose; the details live in docs/.

## What this repo is

DepthWizard is our entry for Smart India Hackathon 2026, problem statement SIH26175 from ISRO. It takes one optical RGB image, produces a height map (DSM), and lets users fly through it in 3D.

- PNG/JPG with no georeference: output a relative DSM (no units).
- GeoTIFF: output an absolute DSM in metres. Scale comes from a coarse DEM, ground control points (GCPs), or OpenStreetMap building heights.

Judging is 50% DSM accuracy and 50% visualization. Accuracy means RMSE, MAE, and correlation against LiDAR, checked separately on urban, sparse, hilly, and forested scenes. The Three.js viewer is stratum (vendored in viewer/, see viewer/UPSTREAM.md) and talks to the backend through a fixed contract. **This repo's main job is the accuracy half, plus the backend that feeds the viewer.**

## Docs: read the one you need

| File | Read it when |
|---|---|
| docs/PLAN.md | Every session. It says which phase we're in and what's unticked. |
| docs/ARCHITECTURE.md | Before writing pipeline, calibration, or API code. |
| docs/VIEWER_CONTRACT.md | Before touching export code, the API, or anything in viewer/. |
| docs/EVALUATION.md | Before changing the model or calibration, and before any eval run. |
| docs/PITCH.md | Only when asked to help with slides or the demo. |

## Rules

1. Work phase by phase from docs/PLAN.md. When a task passes its "done when" check, tick it and add a line to the log at the bottom of PLAN.md.
2. `viewer/` is vendored from stratum. Don't rewrite or restyle it. If it breaks the contract, make the smallest fix that works and record it under "Open issues" in docs/VIEWER_CONTRACT.md.
3. Contract changes are never silent. Bump `contract_version`, update the doc, and add a changelog line.
4. LiDAR ground truth is for metrics only. Calibration may read the DEM, GCPs, OSM, and the image itself. It must never read reference data. Nothing gets tuned on test tiles.
5. After any change to depth, stitching, or calibration, run `python -m evals.run --split quick` and put before/after RMSE in the log. A change isn't done until that's there.
6. The app runs offline. The only allowed network calls are the optional DEM and OSM fetches. Both cache to data/cache/, and the app still works without them.
7. Don't write accuracy numbers anywhere (README, slides, comments) unless they come from evals/results/.
8. All tunables go in configs/default.yaml. No unexplained constants in code.

## Stack

- Python 3.12 in `.venv` (3.11 also works; not 3.13+), PyTorch with CUDA 12.8 wheels, Hugging Face transformers (Depth Anything V2)
- rasterio, pyproj, numpy, scipy, opencv-python-headless, shapely; h5py and pystac-client for eval data
- FastAPI + uvicorn, which runs the jobs API and serves the built viewer (viewer/dist) as static files
- viewer/: stratum, i.e. Vite + TypeScript + Three.js, with all assets bundled locally (no CDN links)
- desktop/: Tauri shell with the backend bundled as a PyInstaller sidecar

## Hardware

The development laptop has an RTX 5060 Laptop GPU (Blackwell, sm_120) with 8 GB VRAM. Blackwell needs PyTorch ≥ 2.7 built for CUDA 12.8+ (`--index-url https://download.pytorch.org/whl/cu128`); older wheels fail with "no kernel image". The default model is `depth-anything/Depth-Anything-V2-Small-hf` in fp16. Base is fine for inference if it fits. Nothing in the plan needs Large or Giant. The app must still run (slowly) on CPU.

## Commands

Create these as you build and keep this list accurate.

```bash
# one-time setup (Windows paths; keep HF_HOME and the pip cache on D:)
py -3.12 -m venv .venv
.venv/Scripts/python -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
.venv/Scripts/python -m pip install -e ".[dev,eval]"
python scripts/fetch_model.py                                   # depth model -> data/models/
python scripts/fetch_geoid.py                                   # EGM2008 geoid grid -> data/geoid/ (CartoDEM datum fix)
python -m evals.datasets.gamus download --split val --limit 60  # GAMUS subset -> data/datasets/gamus/
cd viewer && npm ci && npm test && npm run build                # viewer/dist

python -m evals.datasets.naip3dep build                        # NAIP + 3DEP eval tiles -> data/datasets/naip3dep/

python -m depthwizard run --input img.tif --out out/ [--dem dem.tif|dem_dir/] [--gcps gcps.csv] [--offline]
python -m depthwizard.export.synthetic cone --out data/samples/cone   # also: orientation, relative
python -m evals.run --split quick     # 5 tiles, run after every model/calibration change
python -m evals.run --split val       # tuning split; test_urban/test_sparse/test_hilly/test_forested for reporting
python -m evals.polarity              # GAMUS val: prediction must correlate positively with height
python -m evals.tune                  # sweep calibration settings on val only; apply the winner by hand
python -m evals.datum_check           # CartoDEM tiles vs Copernicus: confirms the ellipsoidal offset per tile
python -m evals.run --split full      # the four test splits + GAMUS test, regenerates evals/REPORT.md
run_local.bat                         # backend + viewer on http://127.0.0.1:8000, opens the browser (= python scripts/serve.py)
uvicorn api.main:app --port 8000      # same, without opening the browser (?job=<id> reopens a job)
pytest tests
node viewer/scripts/contract-test.mjs # viewer acceptance tests against the running backend
python scripts/finetune_gamus.py      # decoder fine-tune on GAMUS train (val picks the epoch) -> data/models/*-gamus
python -m evals.run --split quick --config configs/model_gamus.yaml   # compare the fine-tuned model
# desktop build (PyInstaller backend + Tauri shell -> dist/DepthWizard/): see desktop/README.md
python scripts/build_overview_pdf.py  # project overview PDF from docs/overview/overview.html + evals/results -> out/overview/
```

## Known gotchas

- Depth Anything V2 outputs relative inverse depth. On a top-down image, bigger values should mean taller. Check polarity on every new data source: rooftops must come out above roads.
- Every tile's prediction has its own scale and offset. Align tiles to the low-res global pass before blending, or the seams show. See ARCHITECTURE.md, Stage 2.
- GeoTIFFs in EPSG:4326 have pixel sizes in degrees. Reproject to the scene's UTM zone before anything else.
- Height sources use different vertical datums (EGM96, EGM2008, ellipsoid). A mismatch shows up as a constant offset of metres to tens of metres. Always report offset-free RMSE next to raw RMSE.
- CartoDEM V3R1 heights are ellipsoidal (WGS84), not sea level. On tile 88E27N (Namchi) CartoDEM sits 46 m below Copernicus GLO-30 (median over the scene, NMAD 5.8 m, r = 0.999), which matches the EGM2008 geoid undulation there (−43.8 m). The pipeline converts CartoDEM to EGM2008 heights with the geoid grid from `scripts/fetch_geoid.py`. Without that grid the DSM stays ellipsoidal (absolute heights about 35–80 m low in India, depending on the local geoid), and its datum tag says so. Confirmed tile-wide on three tiles (`python -m evals.datum_check`, `evals/results/datum-20260924-103041`): Sikkim G45E -38.5 m vs N -35.0 m, -1.0 m after correction; Ahmedabad F43A -52.6 m vs N -53.3 m, +0.6 m after correction; Hyderabad E44M -74.5 m vs N -76.4 m, +2.1 m after correction.
- Method B assumes the DEM is a blurred version of the true surface. Copernicus GLO-30, SRTM, and CartoDEM roughly are. A bare-earth DEM will under-predict dense city blocks. Log which DEM each run used.
- Water, shadows, and leaning tall buildings (in off-nadir images) are known failures. Measure them and keep them in the failure gallery.
