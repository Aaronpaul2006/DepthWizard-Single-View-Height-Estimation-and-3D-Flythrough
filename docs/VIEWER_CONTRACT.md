# Viewer contract (v3)

This is the agreement between our backend (built with Claude Code) and the Three.js viewer (stratum, vendored in viewer/, see viewer/UPSTREAM.md). If either side needs a change, bump `contract_version` and add a changelog line at the bottom.

## Bundle files

A bundle is a folder, or a URL prefix, containing:

| File | Required | Content |
|---|---|---|
| meta.json | yes | metadata, described below |
| dsm.bin | yes | Float32 heights, little-endian, row-major, `width × height` values |
| ortho.png | yes | RGB texture covering exactly the same ground extent as dsm.bin |
| mask.png | no | 8-bit, 255 where DSM values were filled in or are unreliable |
| error.bin | no | Float32, same grid as dsm.bin, prediction minus reference (written by /validate) |
| reference.bin | no | Float32, same grid as dsm.bin, the reference DSM resampled onto it, in the DSM's units; NaN where there is no reference (written by /validate) |
| dem.bin | no | Float32, same grid and layout as dsm.bin: the calibration DEM alone (metric results only), averaged and gap-filled exactly like dsm.bin. Named by `dem_file` in meta.json. |

### meta.json

Example values:

```json
{
  "contract_version": 4,
  "width": 2048,
  "height": 1536,
  "pixel_size_m": 0.5,
  "pixel_size_assumed": false,
  "min_h": 12.4,
  "max_h": 87.9,
  "units": "m",
  "bounds": [331200.0, 1442100.0, 332224.0, 1442868.0],
  "crs": "EPSG:32644",
  "has_mask": false,
  "dem_file": "dem.bin",
  "calibration": { "method": "osm_heights", "confidence": "medium", "dem_source": "cartodem" },
  "source_name": "scene_03.tif"
}
```

Field rules:

- `width`, `height`: the DSM grid size. dsm.bin is exactly `width × height × 4` bytes.
- `pixel_size_m`: ground distance between neighboring DSM samples, in metres. This is the viewer DSM, after downsampling.
- `pixel_size_assumed`: true for non-georeferenced input where the user gave no ground sample distance. Then `pixel_size_m` is 1.0, and the viewer shows an "approximate scale" label.
- `units`: `"m"` or `"relative"`. When relative, heights are in [0, 1]. The viewer shows them as percentages and uses world height = h × 0.1 × max(width, height) × pixel_size_m, so the relief is visible by default.
- `bounds` (`[minx, miny, maxx, maxy]`) and `crs`: null for non-georeferenced input.
- `min_h`, `max_h`: computed over valid pixels.
- `calibration`: for display only. Show it in an info panel.
- `dem_file`: `"dem.bin"` when the bundle carries the calibration DEM, else null (relative results). The viewer's "DEM only" button (key B) swaps the terrain between dsm.bin and dem.bin under the same camera, so the audience sees what the 30 m DEM knows and what the model adds.

### Grid orientation and projection

This is where projection accuracy gets lost, so follow it exactly.

- Row 0 is the north (top) edge and column 0 is the west (left) edge, in both dsm.bin and ortho.png.
- Heights are sampled at pixel centers.
- Three.js world axes: x = east, y = up, z = south.
- DSM sample (row r, col c) sits at:
  - x = (c + 0.5 − width / 2) · pixel_size_m
  - z = (r + 0.5 − height / 2) · pixel_size_m
  - y = h (times the vertical exaggeration)
- UVs: u = (c + 0.5) / width, v = 1 − (r + 0.5) / height, with the Three.js default `texture.flipY = true`. The ortho can have a different resolution from the DSM; the UVs are normalized, so it still lines up.
- dsm.bin never contains NaN. The backend fills gaps and marks them in mask.png.
- Size caps: the longest DSM side is at most 2048 and the longest ortho side at most 4096. The viewer may downsample further for level of detail.

## Endpoints the viewer calls

Base URL: the same origin as the viewer page, because FastAPI serves viewer/. Inside the Tauri app, the backend listens on 127.0.0.1:8765, and the viewer uses `window.DW_API_BASE` when it's set.

1. **Upload.** `POST /api/jobs`, multipart. Fields: `image` (required), `dem` (optional GeoTIFF), `gcps` (optional CSV), `gsd_m` (optional number). Response: `{"job_id": "..."}`.
2. **Poll.** `GET /api/jobs/{id}` about once a second. Response: `{"status": "queued|running|done|error", "stage": "depth|calibrate|export", "progress": 0.0 to 1.0, "message": "..."}`. Show stage and progress in the UI.
3. **Load.** When done, fetch `/api/jobs/{id}/bundle/meta.json`, then `dsm.bin` and `ortho.png` (and `mask.png` if `has_mask`, and `dem.bin` if `dem_file` is set; mask.png applies to both).
4. **Download.** A button linking to `/api/jobs/{id}/dsm.tif`.
5. **Validate.** `POST /api/jobs/{id}/validate` with a `reference` GeoTIFF. The backend reprojects the reference onto the full-resolution DSM for the metrics, which needs rasterio, so this can't happen in the browser. Response (example values):

```json
{ "rmse": 3.1, "mae": 2.2, "bias": 0.4, "nmad": 1.9, "pearson_r": 0.87, "n_pixels": 2451000, "units": "m", "scale_aligned": false, "error_file": "error.bin", "reference_file": "reference.bin" }
```

The backend also writes error.bin and reference.bin on the bundle grid. The viewer loads reference.bin into its own comparison tools (difference surface, profiles), shows the backend's numbers in the panel, and clamps the diverging heatmap at ±3 × nmad, centred on 0. Cells flagged in mask.png are NaN in reference.bin, so they never count. For a relative result the metrics are scale-aligned (`scale_aligned: true`) and both files are in relative units. A result without georeference can only be validated against a reference with exactly the same pixel grid.

6. **List results.** `GET /api/jobs` returns every finished result, newest first: `[{"job_id", "name", "units", "width", "height", "pixel_size_m", "crs", "calibration", "finished"}]`, with `finished` in seconds since the epoch. The viewer's Terrains switcher lists them; picking one loads it as in step 3 and keeps `?job=<id>` in the page URL, so a reload or a shared link reopens it.

**Local-file mode (backup).** The viewer can also open a bundle folder directly through a file picker (meta.json + dsm.bin + ortho.png), with no backend running. This is the demo fallback.

## Acceptance tests

Run all five before calling integration done. The backend generates the synthetic bundles with `python -m depthwizard.export.synthetic <name>`; `node viewer/scripts/contract-test.mjs` runs them in a browser against the running backend.

1. **Cone.** A 1025×1025 grid at 1.0 m pixels, with a cone in the center: peak 100 m, base radius 400 m. The ortho is a checkerboard with a red dot at the peak and a blue dot at the middle of the north edge. Pass if:
   - the height readout at the peak says 100.0 m (±0.5)
   - the red dot sits exactly on the peak
   - the blue dot is toward −z
   - the slope readout on the cone's side is about 14.0° (atan(100/400) = 14.04°)
2. **Orientation.** Only the north-west corner is raised. It must appear at the viewer's −x, −z corner.
3. **Relative.** `units: "relative"`, `pixel_size_assumed: true`. The viewer shows the approximate-scale label and percent heights.
4. **Validate.** Validate the cone against itself. RMSE is 0 and the error heatmap is flat.
5. **Big input.** A 4000×4000 source image. The viewer stays interactive, with a target of 60 fps on an integrated GPU and never below 30.

## Open issues

Record mismatches found during integration here: date, what's wrong, who fixes it. Every change to upstream stratum files is marked `DepthWizard patch` in the code.

| Date | Issue | Owner | Status |
|---|---|---|---|
| 2026-09-11 | stratum only opened local files: no upload, polling, bundle loading or GeoTIFF download. | Backend (Claude Code) | Patched: new `src/backend.ts` ("Process image" dialog, polling, bundle load via stratum's `loadDataset`, DSM download link, `?job=<id>` deep link), wired in with one `installBackend` call in `main.ts`. |
| 2026-09-11 | `units: "relative"` rendered flat (heights 0–1 over a ~km extent) and showed raw fractions. | Backend | Patched: `viewer.ts` applies the base vertical scale h × 0.1 × max(width, height) × pixel_size_m, and keeps markers round; `main.ts` / `chart.ts` show relative heights as %. |
| 2026-09-11 | `pixel_size_assumed` was ignored. | Backend | Patched: "approximate scale" appended to the resolution readout. |
| 2026-09-11 | `calibration` was not displayed. | Backend | Patched: calibration method, confidence and DEM source rows in the dataset panel. |
| 2026-09-11 | Reference comparison was client-side only and needed a pixel-identical `.bin`; heatmap clamp was max-abs, not ±3 × NMAD. | Backend | Patched, contract v2: `/validate` also writes reference.bin; the viewer feeds it to stratum's `loadReferenceFiles`, shows the backend's full-resolution metrics, and sets the clamp to ±3 × NMAD. |
| 2026-09-11 | mask.png is not rendered, so filled cells look like data. | Backend | Patched: `backend.ts` turns mask.png cells into NaN before loading, so stratum draws them as holes and never measures them (backend-loaded results; local-file mode still shows them). |
| 2026-09-11 | No way to switch between results without knowing a job id. | Backend | Patched, contract v3: `GET /api/jobs` plus a Terrains dialog in `backend.ts` (results and the built-in sample). |
| 2026-09-11 | stratum caps the ortho texture at 2048 px; the contract allows 4096. | n/a | Accepted: the contract lets the viewer downsample. |
| 2026-09-11 | Fly mode has no ground collision, and pointer lock can't be automated in browser tests. | n/a | Accepted: flight is checked by hand. |
| 2026-09-23 | No way to show what the model adds over the DEM. | Backend | Patched, contract v4: bundles carry `dem.bin`; `backend.ts` adds a "DEM only" toolbar button (key B, works in fly mode). `main.ts` `loadDataset` and `viewer.ts` `setDataset` take a keep-view option, so the swap keeps the camera, flight mode, surface, exaggeration, mesh quality and profile. |
| 2026-09-23 | No flood tool. | Backend | Patched: `viewer.ts` `setWaterLevel` adds a translucent water plane inside the scaled group; `backend.ts` adds a "Water level" slider (metric results) showing the rise above the lowest point and the share of the area under water. |
| 2026-09-23 | The header, page title and profile CSV name said "stratum", not the product name. | Backend | Patched on request: `main.ts` and `index.html` show "DepthWizard"; the internal `window.stratum` bridge keeps its name. Upstream credit stays in viewer/UPSTREAM.md and the docs. |

## Changelog

- **v4 (2026-09-23):** optional `dem.bin` (the calibration DEM on the DSM grid) and meta field `dem_file`, for the viewer's DEM-only flip. The viewer also gains a water-level tool (no contract change). Bundles carry `contract_version: 4`.
- **v3 (2026-09-11):** `GET /api/jobs` lists finished results for the viewer's terrain switcher; the viewer keeps the open result in `?job=<id>` and renders mask.png cells as holes. Bundles carry `contract_version: 3`.
- **v2 (2026-09-11):** the viewer is stratum (vendored), not the ChatGPT build. `/validate` additionally writes `reference.bin` on the bundle grid and returns `reference_file` and `scale_aligned`; relative-result validation is scale-aligned; results without georeference validate only against a pixel-aligned reference. Bundles carry `contract_version: 2`.
- **v1:** Initial contract. Differences from the first spec sent to ChatGPT:
  - reference-DSM validation moved to the backend (`/validate`)
  - upload and polling flow added
  - new meta fields: `mask.png`/`has_mask`, `pixel_size_assumed`, `calibration`, `contract_version`
  - exact pixel-center projection and UV formulas added
