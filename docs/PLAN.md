# Plan

**Current phase:** 4 done except the two human steps (faculty review, failure causes); 5 in progress: fixes, packaging, GAMUS fine-tune (update this line when a phase closes)

We have six build days before the internal presentation. The idea deadline on the SIH portal is 20 September 2026 (confirm on sih.gov.in). If the dates move, keep the phase order and drop items from the cut list below.

## Strategy

Half the marks are accuracy numbers. Most teams will render raw Depth Anything output in 3D and stop there. That output has no metres, so it scores nothing on the accuracy half. We win on three things:

1. Metric calibration that holds up on hilly terrain: terrain from the DEM, detail from the model.
2. A per-landscape accuracy table (urban, sparse, hilly, forested) against a DEM-only baseline, with failures shown.
3. A demo where a judge clicks a building and reads its height in metres, then sees the error map against LiDAR.

The viewer is stratum (github.com/Ahd4wnn/stratum), vendored into viewer/ at a pinned commit (viewer/UPSTREAM.md). We only add a thin integration layer against docs/VIEWER_CONTRACT.md, so the team's time goes into accuracy.

Data: the official brief (github.com/IMG-PROCESS-SAC/SIH-DepthWizard-2026) recommends GAMUS (Hugging Face `earthflow/GAMUS`, CC-BY-4.0) and allows SRTM-class DEMs. Final judging uses ISRO RGB optical satellite imagery. GAMUS has no georeference, so it covers relative-mode evaluation and fine-tuning; NAIP + 3DEP covers the absolute numbers.

## Team roles

| Role | Owns |
|---|---|
| A: Model lead | Depth backbone, tiling and stitching, fine-tune (stretch) |
| B: Geo lead | GeoTIFF IO, reprojection, DEM providers, calibration |
| C: Viewer integration | Wiring stratum to our API, keeping patches minimal and logged |
| D: Backend and packaging | FastAPI jobs API, bundle export, Tauri + PyInstaller |
| E: Evaluation | Datasets, test splits, eval runner, REPORT.md, failure gallery |
| F: Pitch | PPT in the official SIH template, demo script, backup video, Q&A prep |

A and B review each other's code. E signs off on every number before it goes on a slide.

## Phases

### Phase 0: Setup and data (Day 1 morning)

Goal: everyone can run the model on a sample image by lunch.

- [x] Repo scaffold matching the layout in ARCHITECTURE.md; pyproject.toml, ruff, .gitignore covering data/
- [x] Environment: PyTorch with CUDA, transformers, rasterio. Confirm the GPU is visible from Python. (torch 2.11+cu128 on the RTX 5060, Python 3.12 venv)
- [x] Download Depth-Anything-V2-Small-hf to data/models/ so it loads offline. Check the license on the model card. (Apache-2.0)
- [x] GAMUS (brief's recommended dataset, no sign-up): 60-tile balanced val subset in data/datasets/gamus/. DFC2019 / ISPRS optional, only if access turns up.
- [x] In parallel, pull NAIP imagery + USGS 3DEP LiDAR tiles, which need no sign-up. These cover the hilly and forested splits. (6 sites × 16 tiles: `python -m evals.datasets.naip3dep build`)
- [x] Calibration DEMs: CartoDEM (Bhuvan, needs login), SRTM, Copernicus GLO-30. (Copernicus: auto-fetched and cached. CartoDEM V3R1 tile 88E27N in data/dem/cartodem/: single-user NRSC licence, so never commit, host or bundle it. SRTM: optional, not fetched.)
- [x] Pick one Indian GeoTIFF scene we are allowed to use for the demo: Namchi, South Sikkim. WorldView-3, 14 March 2022, 0.3 m, from the Maxar Open Data Program (CC BY-NC 4.0; credit Maxar). Recreate it with `python scripts/fetch_demo_namchi.py`. No open high-resolution imagery of Ahmedabad was found (OpenAerialMap, Maxar ODP).

**Done when:** `python -m depthwizard run --input sample.png --out out/` writes a raw depth PNG using the GPU.

### Phase 1: Height extraction (Day 1)

Goal: a relative DSM with no seams, even on large images.

- [x] Model wrapper: fp16, batched tiles, 518 px input (OOM: halve batch, then CPU fallback)
- [x] Global low-res pass, per-tile scale/shift alignment, Hann-window blending (ARCHITECTURE.md, Stage 2). Alignment starts from a median/MAD fit so outlier pixels can't collapse the slope.
- [x] Polarity check utility (`python -m evals.polarity`, GAMUS val): sign correct on aggregate, weak on some DC tiles
- [x] Relative mode output: normalized rDSM as GeoTIFF (no CRS) plus a 16-bit PNG preview
- [x] Seam test: on a real image, mean gradient magnitude along tile borders is no higher than inside tiles (Denver 4096² NAIP)

**Done when:** a 4000×4000 image processes on the 4060 with no visible seams, and per-stage runtime is logged (target under 2 minutes total).

### Phase 2: Scale calibration (Day 2)

Goal: an absolute DSM in metres for GeoTIFF inputs, and the first real numbers.

- [x] GeoTIFF reader: CRS and transform; reproject EPSG:4326 inputs to UTM
- [x] DEM providers: a local file (CartoDEM/SRTM), plus Copernicus auto-fetch with a cache (a folder of tiles also works)
- [x] Method A: global affine fit of depth to the DEM (Huber loss)
- [x] Method B: terrain + detail, with scale from GCPs, then OSM heights, then DEM fit, then scene prior (OSM step not built: cut-list #2)
- [x] Write calibration method, confidence, and DEM source into GeoTIFF tags and meta.json
- [x] Build the quick split: 5 tiles with LiDAR truth (EVALUATION.md)

**Done when:** `python -m evals.run --split quick` reports RMSE, MAE, and correlation for DEM only, Method A, and Method B, and Method B beats DEM only on the urban tiles. If it doesn't, fixing that is Day 3 morning, before any viewer work.

### Phase 3: Backend and viewer integration (Day 3)

Goal: upload in the viewer, get a flythrough back.

- [x] Bundle exporter per VIEWER_CONTRACT.md (meta.json, dsm.bin, ortho.png, mask.png)
- [x] FastAPI jobs API: create, status, bundle files, GeoTIFF download
- [x] Serve viewer/ as static files from FastAPI (viewer/dist)
- [x] Synthetic bundles (cone, orientation, relative) and the five acceptance tests in VIEWER_CONTRACT.md (`node viewer/scripts/contract-test.mjs`)
- [x] Validate endpoint: reference DSM upload returns metrics and writes error.bin (+ reference.bin, contract v2)

**Done when:** starting from a fresh clone, a teammate uploads a GeoTIFF in the browser, flies over it, clicks a building, and sees a height in metres.

### Phase 4: Full evaluation (Day 4)

Goal: the table that goes on the slide.

- [x] Build all four landscape test splits plus the validation split (EVALUATION.md). 72 LiDAR test tiles from 6 sites, 24 val tiles, 60 GAMUS test tiles.
- [x] Full run, producing evals/REPORT.md, a per-tile CSV, and error maps (`python -m evals.run --split full`, scene mode)
- [ ] Failure gallery: the 5 worst tiles, each with a one-line cause written by a human (gallery generated; causes go in evals/failure_causes.yaml)
- [ ] Afternoon: show everything to a faculty member and copy their critique into the log word for word

**Done when:** REPORT.md has all four landscape rows filled in for every method, and the faculty feedback is logged.

### Phase 5: Fixes and packaging (Day 5)

Goal: a stable app that runs on a machine that isn't ours.

- [ ] Fix the top issues from the faculty review
- [x] PyInstaller sidecar + Tauri build. Fallback: `run_local.bat` / `run_local.sh` to start web mode. Portable `dist\DepthWizard\`; see desktop/README.md.
- [x] Stability: corrupt files, huge images (downsample with a warning), missing CRS, CPU-only machines (tests/test_api.py, test_io.py, test_cpu.py)
- [ ] Stretch, only if Phase 4 is done: fine-tune the DA V2-Small decoder on GAMUS (the brief's dataset; DFC2019 was never needed) with a scale-and-shift-invariant loss, then rerun the full eval. `scripts/finetune_gamus.py`; in progress.

**Done when:** the packaged app runs on a second laptop that has no Python installed.

### Phase 6: Pitch (Day 6)

Goal: a rehearsed pitch with a demo that can't fail. Tasks are in PITCH.md.

**Done when:** two timed rehearsals are done, the backup video is recorded, and every number on the slides traces to a run in evals/results/.

## Cut list

If behind, drop in this order:

1. Fine-tuning
2. OSM building-height calibration
3. Tauri packaging (fall back to local web mode plus the backup video)
4. Validate endpoint (show error maps from the eval run instead)

Never cut: calibration, the per-landscape table, the backup video.

## Risks

| Risk | Early sign | What we do |
|---|---|---|
| DFC2019 access is slow | No approval by end of Day 2 | Use NAIP + 3DEP for all four landscapes, ISPRS for urban |
| Method B doesn't beat DEM only | Day 2 quick eval | Day 3 morning on it: tune σ and scale source on the val split, try the Base model |
| Viewer doesn't match the contract | Cone test fails | Smallest fix, log under Open issues, resend the contract to ChatGPT |
| Packaging eats a day | Tauri not building by Day 5 noon | Local web mode + backup video |
| CUDA out of memory | OOM errors | Batch size 1, then smaller global pass, then CPU fallback |
| Live demo fails | n/a | Backup video; bundles preloaded for the viewer's local-file mode |

## Log

One line per completed task or eval run. Newest at the bottom.

| Date | Phase | What changed | Quick eval RMSE (before → after) |
|---|---|---|---|
| 2026-09-11 | 0 | Repo restructured (docs/, stratum vendored at 46abc2279903, baseline `npm test` 8/8 + build OK). Python 3.12 venv, torch 2.11+cu128 on RTX 5060. DA V2-Small in data/models/ (Apache-2.0). GAMUS val subset (60 tiles). Done-when passed: `python -m depthwizard run --input data/samples/sample.png --out out/sample` wrote depth_raw.png on the GPU (fp16). | n/a (no eval yet) |
| 2026-09-11 | 1 | Tiled depth (global 1036 px pass + 518 px tiles, robust per-tile α/β, Hann blending), relative DSM export, GAMUS polarity check. Done-when passed: Denver NAIP 4096² (0.3 m) depth + stitch 6.5 s, whole run ~12 s on the RTX 5060; seam ratio 0.83 (border/interior gradient), no visible seams in the gradient map. | n/a (quick split not built yet) |
| 2026-09-11 | 2 | Calibration: UTM reprojection, DEM providers (local file or folder + cached Copernicus GLO-30), Method A (Huber), Method B (GCP → DEM relief → scene prior; OSM not built, cut-list #2). Band-split k 1.5 → 0.5 (double-counting fix, see ARCHITECTURE.md). 6 NAIP + 3DEP sites, splits fixed before any metric. First quick eval, `evals/results/quick-20260911-130602`: Method B beats DEM-only on urban (done-when met) but is worse on sparse (1.25 → 5.89) and hilly (2.74 → 4.35), where the untuned scene prior invents relief. Tune on val in Phase 4. | urban: DEM-only 16.24 → Method B 15.68; all 5 tiles: 8.77 → 9.75 |
| 2026-09-11 | 3 | Bundle exporter (area average to ≤ 2048, ortho ≤ 4096, nearest-fill + mask.png), FastAPI jobs API (one GPU worker, finished jobs restored from disk), /validate (full-resolution metrics + error.bin + reference.bin, contract v2), viewer/dist served at /. stratum patched minimally: src/backend.ts plus marked patches, listed under Open issues in VIEWER_CONTRACT.md. Done-when passed: `node viewer/scripts/contract-test.mjs` 13/13, including a GeoTIFF uploaded in the browser and a click reading 1592.14 m, cone 100 m / 14°, orientation, relative %, validate, 4096² input. Fly mode (pointer lock) can't be automated and still needs a hand check. Quick eval rerun `quick-20260911-132359` reproduces the Phase 2 numbers exactly (no calibration change since). | urban: DEM-only 16.24 → Method B 15.68 (unchanged) |
| 2026-09-11 | 3 (demo) | Demo scene: Namchi, South Sikkim (Maxar ODP WorldView-3, 0.3 m, CC BY-NC 4.0; `scripts/fetch_demo_namchi.py`) calibrated with CartoDEM V3R1 88E27N; 8192² in ~38 s. Found that CartoDEM is ellipsoidal: it sits 46 m below Copernicus, matching the EGM2008 geoid (−43.8 m); recorded in CLAUDE.md gotchas and dem.py. Fixes: DEM folders searched recursively, uploads keep their names (DEM source and datum are now detected), `pip install -e .` re-run so `evals`/`api` import anywhere. Rust 1.98.1 (stable-msvc) installed for Phase 5. Contract suite 13/13 after the changes. | n/a (no calibration change) |
| 2026-09-11 | 3→4 | Viewer: Terrains switcher (`GET /api/jobs`, contract v3), open result kept in `?job=`, mask.png cells shown as holes; contract suite 17/17. Backend: GeoTIFF nodata/alpha masks honoured; CartoDEM converted to EGM2008 with the NGA geoid grid (`scripts/fetch_geoid.py`); API tests use a temporary jobs folder. Phase 4 tuning v1, per tile on val (`evals/results/tune-20260911-143413`): no Method B setting beat DEM only on the landscape-balanced objective. Only urban improved. Cause: a single 300–600 m tile holds about 10×10 DEM cells, so calibration falls back to the blind scene prior. Response: scene-mode eval (calibrate each whole site scene, as for a user upload) and a new DEM-band scale source gated by correlation; re-tuning. | val objective: DEM only 5.655 → Method B default 7.539 (urban 11.75 → 11.35) |
| 2026-09-11 | 4 | Tuning v2, scene mode on val (`evals/results/tune-20260911-144322`): new DEM-band scale source (the DEM's own resolvable detail regressed on the model's, gated by correlation). Applied to default.yaml: k 0.5 → 1.0, band_min_r 0.1, DEM-relief scale off, scene prior 0 (DEM only when no source applies); bilinear DEM resampling kept (cubic spline was worse). Val objective: DEM only 5.657, old default 6.800, tuned 5.578. Found and fixed: YAML read `1.0e9` as text; the config loader now type-checks every value. Namchi keeps its detail (band r 0.157, s 66). | quick, all 5 tiles: 9.515 → 8.689 (DEM only 8.776); urban 15.857 → 16.096, forested 7.389 → 7.255 |
| 2026-09-11 | 4 | Full evaluation with the tuned config (`evals/results/full-20260911-145944`, REPORT.md regenerated): 72 LiDAR test tiles in scene mode plus 60 GAMUS test tiles. Method B beats DEM only overall and in urban and forested; hilly and sparse are level (DEM-only fallback where the model disagrees). GAMUS relative, scale-aligned: RMSE 5.30 m, r 0.420. Runtime per 4096² scene: depth 6.5 s, calibrate 0.8 s. Failure gallery: Smokies 3_0 (RMSE 123.7 m, NMAD 7.2 m: a few extreme outliers) and four downtown Denver tiles. Causes still to be written by a teammate in evals/failure_causes.yaml. | test, all 72 tiles: DEM only 10.78 → Method B 10.67; urban 17.83 → 17.62; forested 12.28 → 12.14 |
| 2026-09-11 | 5 | Packaging: PyInstaller one-folder backend (4.7 GB, of which PyTorch/CUDA 4.0 GB) plus a Tauri 2 shell (7.7 MB), assembled as a portable `dist\DepthWizard\` (`desktop/README.md`, `desktop/package_portable.ps1`). `DEPTHWIZARD_HOME` keeps jobs and caches in %LOCALAPPDATA%. Verified: the frozen backend serves the viewer and runs PNG and GeoTIFF jobs; the desktop app starts the backend (healthy after 7 s) and stops it when the window closes. Web-mode fallback: `run_local.bat` (`scripts/serve.py`). Stability tests: a corrupt upload gives a clean job error, an oversized image is downsampled with a warning, the pipeline runs CPU-only. Still to do: run on a second laptop without Python. | n/a |
| 2026-09-11 | 5 | The desktop app showed only the sample terrain. Cause: it keeps results in `%LOCALAPPDATA%\in.sih2026.depthwizard`, separate from the repo's `data/jobs` that web mode uses. Copied the tuned Namchi result (`out/` only, no CartoDEM) and the Copernicus cache into it, and re-ran Denver inside the app. Project overview PDF: `scripts/build_overview_pdf.py` fills `docs/overview/overview.html` from evals/results and prints it with headless Edge, giving `out/overview/DepthWizard-Overview.pdf` (24 pages). | n/a |
| 2026-09-11 | 6 | Demo kit on the desktop (`DepthWizard Demo Kit`, 824 MB). Contents: inputs for a live run (plain Denver JPG, Namchi + CartoDEM, Austin scene + mosaicked 3DEP LiDAR DSM for Validate, one scene per landscape); finished DSM GeoTIFFs with hillshades; figures, the overview PDF and a two-page print handout; `START HERE - Demo guide.txt` (checklist, 3-minute script, numbers filled in from `full-20260911-145944`). All seven results were processed in the desktop app and appear under Terrains. The Austin Validate call works end to end. PITCH.md step 3 now uses the Austin pair (DFC2019 never arrived). | n/a |
