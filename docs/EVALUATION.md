# Evaluation

Half the score is DSM accuracy: RMSE, MAE, and correlation against LiDAR or reference data, checked across urban, sparse, hilly, and forested landscapes. This doc covers how we produce those numbers without fooling ourselves.

## Metrics

The reference is reprojected onto the prediction grid (bilinear). Metrics use only pixels valid in both. Error is e = prediction − reference.

| Metric | Definition | Why we report it |
|---|---|---|
| RMSE | sqrt(mean(e²)) | ISRO asks for it |
| MAE | mean(\|e\|) | ISRO asks for it |
| Pearson r | correlation between prediction and reference | ISRO asks for it; the only fair metric in relative mode |
| Bias | mean(e) | exposes datum and scale offsets |
| NMAD | 1.4826 × median(\|e − median(e)\|) | standard outlier-resistant measure in DEM accuracy work |
| Offset-free RMSE | RMSE after subtracting median(e) | separates datum mismatch from shape error |
| nDSM RMSE | RMSE of height above ground, where a reference DTM exists | measures buildings and trees, not terrain |

**Relative mode.** Fit the prediction to the reference with a least-squares scale and shift, then report the aligned RMSE and r. Label these "scale-aligned" everywhere they appear, including slides.

## Datasets

| Landscape | Source | Imagery | Truth | Notes |
|---|---|---|---|---|
| Urban | DFC2019 (Jacksonville, Omaha) | satellite, about 1.3 m | airborne LiDAR | The true satellite test. Needs sign-up; request on Day 1. |
| Urban (second set, optional) | ISPRS Vaihingen / Potsdam | aerial | nDSM | Needs a request form |
| Sparse | NAIP + USGS 3DEP (rural or suburban areas), or suburban DFC2019 tiles | aerial, 0.6 to 1 m | 3DEP LiDAR DSM | |
| Hilly | NAIP + USGS 3DEP (hilly area) | aerial, 0.6 to 1 m | 3DEP LiDAR DSM | |
| Forested | NAIP + USGS 3DEP (forested area) | aerial, 0.6 to 1 m | 3DEP LiDAR DSM | |
| Urban, relative (GAMUS) | Hugging Face `earthflow/GAMUS` (DC, NYC, PHL) | aerial RGB, 1024×1024 tiles | height above ground (nDSM) | Recommended by the official brief. CC-BY-4.0, no sign-up. No georeference, so no DEM calibration: report scale-aligned r / RMSE and nDSM RMSE with prior-only scale, in a separate table. |
| India (qualitative only) | our demo GeoTIFF | varies | none public | Visuals only, calibrated with CartoDEM. No accuracy claims. Final judging uses ISRO RGB satellite imagery. |

NAIP and the 3DEP LiDAR products are on Microsoft Planetary Computer (look for collections like `naip`, `3dep-lidar-dsm`, `3dep-lidar-dtm`; confirm the exact names before coding). Copernicus GLO-30 is on the public AWS bucket `copernicus-dem-30m` (confirm tile naming). CartoDEM covers India only, so the US test sites are calibrated with Copernicus or SRTM.

NAIP urban sites are picked outside DC, New York and Philadelphia, so a model fine-tuned on GAMUS is never tested on the cities it was trained on.

Be upfront in the pitch: DFC2019 is the satellite result. NAIP is aerial and is there because it has matching public LiDAR for hilly and forested ground.

## Splits

Tiles are about 1024×1024 px. Lists live in evals/splits/ and are committed.

| Split | Size | Used for |
|---|---|---|
| quick | 5 tiles (2 urban, 1 each of the rest) | after every model or calibration change |
| val | about 5 tiles per landscape | tuning config values (σ factor k, scene prior, thresholds) |
| test_urban, test_sparse, test_hilly, test_forested | as many as available, target 20 each | the reported numbers |
| gamus_val / gamus_test | balanced subsets of GAMUS val / test | scene-prior tuning and polarity (val only) / the relative-mode table (test) |

Tile assignment (fixed on 2026-09-11, before any metric was computed): every NAIP + 3DEP site (evals/datasets/sites.yaml) is a 4×4 grid of 1024 px tiles. Row 0, the northern strip, goes to val; rows 1–3 go to the landscape's test split. quick is 5 val tiles. Sites per landscape: urban = Denver, Austin; sparse = Palouse; hilly = Boulder foothills; forested = Great Smokies, Vermont. Val and test tiles from the same site are neighbours, so add more sites before claiming generalisation to new places.

Scene mode (from 2026-09-11): each site's whole 4096 px scene is processed once, the way a user upload is (depth, DEM, calibration), and the listed tiles are scored inside it. Calibration still never reads reference data; it simply sees a realistic scene size. A single 300–600 m tile holds only about 10×10 DEM cells, too few to learn a scene scale from.

Rules:

1. Once a test split has been evaluated, don't change its tile list.
2. Tune only on val. Test results never feed back into config.
3. Calibration code never reads reference data. `depthwizard/calibrate` must not import anything from `evals/`; add a test that checks this.
4. Every run saves: git commit, config, dataset versions, per-tile CSV, metrics.json, and error-map PNGs, all in evals/results/<run_id>/.

## Methods compared

Each method is one row group in the report:

1. **DEM only:** the calibration DEM resampled to the image grid. This answers "what did the model add?"
2. **Method A:** global affine fit.
3. **Method B:** terrain + detail (our default).
4. **Method B + fine-tuned model:** stretch goal, only if there's time.
5. **Method B with a different DEM:** SRTM versus Copernicus, on one landscape only.

## REPORT.md format

evals/run.py generates evals/REPORT.md. Nobody edits it by hand.

- Table 1: landscape × method, with RMSE, MAE, r, bias, NMAD, and offset-free RMSE (metres)
- Table 2: runtime per pipeline stage
- Failure gallery: the 5 worst tiles, each showing image, prediction, reference, error map, and a one-line cause written by a teammate
- Footer: run id, commit hash, config path

## What goes on the slide

- Table 1, cut down to DEM-only vs Method B per landscape. This is the main result.
- One error map from a good tile and one from a failure, side by side.
- One sentence on what we couldn't test: no public LiDAR for Indian cities.

## Reporting rules

- Failures get the same prominence as wins.
- The table uses the full test split, never hand-picked tiles.
- If a number depends on datum handling, say so next to it.
