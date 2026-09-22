# Stratum

An offline Three.js terrain workspace for DSMs and orthophotos. Includes a generated demo, orbit and pointer-lock flight, height inspection, slope and error heatmaps, elevation profiles, CSV export, and reference RMSE / MAE.

## Run

Requires Node.js 22+ and a WebGL 2 browser (Chrome, Edge, or WebView2).

```sh
npm ci
npm run dev
```

The development server uses `http://127.0.0.1:5173`. If that port is occupied, use `npm run dev -- --port 5175`.

```sh
npm run build
npm run preview
npm test
npm run benchmark
```

`dist/` is the self-contained production frontend. Three.js, its controls, icons, CSS, and the module worker are bundled locally; the app makes no requests to CDNs, APIs, font services, or telemetry. Installing dependencies requires access to npm once. Runtime needs no internet. Serve the build through Tauri's asset protocol or a local static server; ES modules / workers do not work from `file://`.

## Input contract

Select or drop these three files together:

- `dsm.bin`: little-endian IEEE 754 Float32, row-major, exactly `width * height * 4` bytes, no header. Row 0 is the top / north image row. NaN and infinity are missing values. Convert any finite no-data sentinel (such as -9999) to NaN in Python.
- `ortho.png`: orthorectified RGB imagery with the same extent and orientation as the DSM. Different raster dimensions are supported when the outer pixel-edge extent matches exactly.
- `meta.json`:

```json
{
  "width": 4000,
  "height": 4000,
  "pixel_size_m": 0.25,
  "min_h": 102.3,
  "max_h": 289.7,
  "units": "m",
  "bounds": [500000, 4200000, 501000, 4201000],
  "crs": "EPSG:32643"
}
```

Dimensions must be integers ≥ 2. Pixel spacing must be finite and positive. The source uses square, metre-spaced, axis-aligned pixels; reproject rotated grids / geographic-degree grids in the backend first. Bounds are retained for display and reference validation, not used to position the camera at large georeferenced coordinates. Use one consistent bounds representation for source and reference (e.g. `[xmin, ymin, xmax, ymax]`).

Grid vertices represent **pixel centres**. Their horizontal span is `(width - 1) * pixel_size_m` by `(height - 1) * pixel_size_m`. UVs are `((column + 0.5) / width, 1 - (row + 0.5) / height)`, aligning the DSM samples to image texel centres. World X increases east, world Z increases south, and world Y is elevation. The UI's local X / Y readout measures east / south from the first source pixel centre. It is not a georeferenced coordinate readout.

Original elevations are centred around the actual minimum height to preserve GPU precision. The worker measures the actual finite height range, so stale `min_h` / `max_h` values do not clip geometry. Elevations are restored in all readouts and exports.

Missing or `"relative"` units display **relative**. Horizontal distances remain metres; relative vertical values cannot define a calibrated physical slope, so slope values are marked with an asterisk and described as an uncalibrated inclination proxy. Metre-valued input uses true physical slopes.

## Controls and analysis

| Action                           | Control                                                 |
| -------------------------------- | ------------------------------------------------------- |
| Orbit / zoom / pan               | Left drag / wheel / right drag                          |
| Fly                              | Select **Fly**, then click the terrain for pointer lock |
| Move in flight                   | WASD; Q down; E or Space up; Shift faster               |
| Release pointer / cancel drawing | Escape                                                  |
| Open data / reset / top view     | O / R / T                                               |
| Elevation profile                | P or **Draw profile**, then click A and B               |
| Inspect                          | Hover; click to pin; **Unpin** to release               |
| Export profile                   | Download button in the profile panel                    |

Pointer lock requires a trusted click, a focused window, and host support. A denial shows a recoverable message; orbit stays available. Embedded preview hosts may deny pointer lock. Flight does not impose ground collision and can move through or below the surface.

Profiles sample the **original DSM**, bilinearly, up to 2,048 points including both endpoints. Distance is horizontal plan distance, not 3D ground distance. Missing data creates gaps. The chart supports hovering and CSV export. The profile line uses original elevations and is drawn on top of the terrain; it can differ slightly from the coarser displayed mesh. The demo's initial transect is clearly labelled.

Slope uses central finite differences from adjacent source cells, one-sided at the boundary: `atan(hypot(dh/dx, dh/dy))`. Missing derivative neighbours are marked unknown. A 0–60° ramp saturates at 60°; the inspector reports actual slope values. Contours are spaced at 50 vertical units **above the dataset minimum**. Exaggeration changes only the scene's Y scale, never source values, slopes, profiles, distances, or comparison metrics.

Reference comparison accepts a `.bin` plus optional metadata. If metadata is supplied, grid dimensions, spacing, units, bounds, and CRS must match; no resampling is silently performed. Without metadata, **you assert that these match**. Reference heights must share the source vertical datum. Finite cells valid in both rasters contribute to the metrics:

```text
error = source - reference
RMSE  = sqrt(sum(error²) / valid_pair_count)
MAE   = sum(abs(error)) / valid_pair_count
bias  = sum(error) / valid_pair_count
```

Error heatmaps sample the display grid while RMSE / MAE / bias include **all source cells**, including those omitted from the display mesh. Blue is negative, red positive; the symmetric scale is the largest absolute full-grid error. An invalid replacement reference keeps the previous comparison.

## Performance

- Raw DSMs stay in a dedicated module Web Worker. File reading, range scanning, resampling, normals, slopes, profiles and reference statistics run there.
- The default display mesh is at most **513 × 513** vertices. Auto quality reduces to 257 × 257 when sustained frame rate drops. Explicit presets offer 257, 513, and at most **1024 × 1024** vertices; all preserve extent and grid aspect.
- Typed mesh buffers transfer to the main thread without copying. The source and reference arrays are retained only in the worker. A 4000 × 4000 Float32 source occupies 61 MiB; source plus reference 122 MiB, excluding transient decode / file buffers.
- Orthophotos decode asynchronously and are capped at 2048 pixels on the longest axis (or the GPU limit), with mipmaps and capped anisotropy. This is a deliberate GPU-memory tradeoff; full-resolution imagery is not retained on the GPU.
- Device pixel ratio starts at at most 1.5 and falls as low as 0.75 during sustained slow rendering. FPS reflects real animation frames, not a claimed target.
- Hover picking traverses only the intersected heightfield cells rather than raycasting every triangle; it is limited to ~12 Hz. Samples use a single outstanding hover request. Dense work stays off the UI thread.
- Dataset replacement terminates the old worker and disposes geometry, textures, and image bitmaps. Loading is cancellable. Invalid source files leave the existing dataset available.
- No-data triangles at display vertices are omitted. Features or holes smaller than the display sampling interval can be missed visually; readouts and metrics retain original data semantics. No claim is made that a 1024² mesh preserves every feature in a 4000² input.

The implementation targets 60 fps on integrated GPUs using those budgets. **60 fps cannot be guaranteed across unspecified GPUs, display sizes, drivers, or Tauri hosts.** Validate on the actual target machine, especially at the explicit 1024 preset. The local browser sustained approximately 144 fps at 513² on the demo and the 4000² fixture during testing; that is not an integrated-GPU certification.

CPU benchmark from this development host for 4000² input: finite-range scan ~277 ms, 513² mesh ~99 ms, reference comparison ~122 ms, 2,048-point profile ~2 ms, and 1,000 grid picks ~13 ms. These are indicative, not performance assertions. Rerun `npm run benchmark` on the target laptop.

## Tauri integration

This repository is the frontend, ready to include in an existing Tauri 2 application; it does not include a Rust backend or a packaged desktop executable. Configure the host's build paths approximately as follows (adjust relative paths to its `src-tauri` directory):

```json
{
  "build": {
    "beforeDevCommand": "npm run dev",
    "devUrl": "http://127.0.0.1:5173",
    "beforeBuildCommand": "npm run build",
    "frontendDist": "../dist"
  },
  "app": {
    "security": {
      "csp": "default-src 'self'; script-src 'self'; worker-src 'self' blob:; img-src 'self' blob: data:; style-src 'self' 'unsafe-inline'; connect-src 'self' ipc: http://ipc.localhost"
    }
  }
}
```

Validate CSP / local protocol origins for your Tauri OS target and development server. No remote origin is required. Keep filesystem permissions in the native host scoped to user-chosen datasets. Do not pass privileged filesystem APIs into worker code.

The bridge can create browser `File` objects from backend bytes and call:

```js
await window.stratum.loadDataset([
  new File([dsmBytes], 'dsm.bin'),
  new File([orthoBytes], 'ortho.png', { type: 'image/png' }),
  new File([JSON.stringify(meta)], 'meta.json', { type: 'application/json' }),
]);
await window.stratum.loadReferenceFiles(
  new File([referenceBytes], 'reference.bin'),
  new File([JSON.stringify(referenceMeta)], 'meta.json'), // optional
);
```

Both methods finish once the UI has handled the operation; validation errors are displayed in the viewer. No native filesystem or networking permissions are needed for the browser file picker path.

Python export example:

```python
import json
import numpy as np
from PIL import Image

# heights: 2D numeric array; ortho_rgb: matching orthorectified RGB array
grid = np.asarray(heights, dtype='<f4')
grid.tofile('dsm.bin')
Image.fromarray(np.asarray(ortho_rgb, dtype=np.uint8), 'RGB').save('ortho.png')
valid = grid[np.isfinite(grid)]
if not valid.size:
    raise ValueError('No finite height samples')
metadata = dict(width=grid.shape[1], height=grid.shape[0], pixel_size_m=0.25,
                min_h=float(valid.min()), max_h=float(valid.max()),
                units='m', bounds=[500000, 4200000, 501000, 4201000], crs='EPSG:32643')
with open('meta.json', 'w') as f:
    json.dump(metadata, f)
```

## Verification

`npm test` covers metadata / byte validation, interpolation and no-data, true slope, metre-scale geometry, pixel-centre UVs, triangle winding, vertex limits, alignment rejection, full-grid errors, profile distances, and grid traversal picking against brute-force ray intersection.

`npm run test:browser` supplies a repeatable Playwright regression test. Start the app on port 5175 first, or set `VIEWER_URL`. It uses installed Chrome; set `BROWSER_CHANNEL=msedge` to use Edge. It creates generated test files in ignored `test-results/`, checks a 4000² import and exact comparison metrics, draws a profile, adjusts exaggeration and quality, tests invalid reference replacement, and blocks external network requests. It intentionally does not assume automated pointer lock is supported.

Manually checked in the embedded browser: demo, 4000² upload, correctly oriented quadrant orthophoto, two-point profile, full-grid reference metrics, exaggeration without changing original measurements, and quality switching. Pointer lock requires further testing in the destination WebView2 host. Tauri packaging and hardware-specific FPS certification are outside these frontend checks.

## Source map

- `src/terrain.ts` — pure validation, sampling, geometry, slope and comparison functions.
- `src/terrain.worker.ts` / `worker-client.ts` — worker protocol, ownership and cancellation.
- `src/viewer.ts` / `picking.ts` — Three.js renderer, camera controls and bounded picking.
- `src/chart.ts` — local canvas profile chart.
- `src/main.ts` / `style.css` — application and responsive interface.
- `src/demo.ts` — deterministic synthetic terrain and imagery; no external assets.

Three.js controls and texture behavior follow the [official OrbitControls](https://threejs.org/docs/pages/OrbitControls.html), [PointerLockControls](https://threejs.org/docs/pages/PointerLockControls.html), and [texture documentation](https://threejs.org/docs/pages/Texture.html). These links are documentation only, never runtime dependencies.
