/**
 * DepthWizard backend integration for stratum (docs/VIEWER_CONTRACT.md). Not upstream code.
 *
 * - "Terrains": every result processed on this computer (plus the built-in sample); pick one to
 *   switch. The open result is kept in the URL as `?job=<id>`, so a reload or a shared link
 *   reopens it.
 * - "Process image": upload -> poll about once a second -> load the bundle through stratum's
 *   own loadDataset path. Cells flagged in mask.png are shown as holes, not as data.
 * - A link to the full-resolution DSM GeoTIFF.
 * - "Validate with GeoTIFF": the backend reprojects the reference, returns metrics and writes
 *   reference.bin on the bundle grid, which then feeds stratum's own difference tools.
 * - "DEM only" (key B): swaps the terrain between the calibration DEM (dem.bin) and DepthWizard's
 *   DSM under the same camera: what a 30 m DEM knows, and what the model adds.
 * - "Water level": a flood plane over metric results, with the share of the area under water.
 */

export interface BackendHooks {
  loadDataset: (files?: File[], options?: { keepView?: boolean }) => Promise<void>;
  loadReferenceFiles: (dsm: File, meta?: File) => Promise<void>;
  loading: (value: boolean, title?: string, detail?: string) => void;
  notify: (message: string, error?: boolean) => void;
  setErrorRange: (range: number | undefined) => void;
  icon: (name: string, cls?: string) => string;
  refreshIcons: () => void;
  setWaterLevel: (level: number | null) => void;
}

interface JobStatus {
  status: 'queued' | 'running' | 'done' | 'error';
  stage: string;
  progress: number;
  message: string;
}

interface ValidationReport {
  rmse: number;
  mae: number;
  bias: number;
  nmad: number;
  pearson_r: number;
  n_pixels: number;
  units: string;
  scale_aligned?: boolean;
  error_file: string;
  reference_file?: string;
}

interface TerrainSummary {
  job_id: string;
  name: string;
  units: string;
  width: number;
  height: number;
  pixel_size_m: number;
  crs: string | null;
  calibration: { method?: string; confidence?: string; dem_source?: string | null };
  finished: number; // seconds since the epoch
}

interface BundleMeta {
  crs: string | null;
  width: number;
  height: number;
  units: string;
  has_mask?: boolean;
  dem_file?: string | null; // contract v4: the calibration DEM on the same grid
  calibration?: { method?: string; confidence?: string; dem_source?: string | null } | null;
}

/** One surface the viewer can show for the open job: its heights (masked cells NaN) and meta. */
interface Surface {
  heights: Float32Array;
  meta: File;
  sorted?: Float32Array; // finite heights in ascending order, for the flooded share
}

const POLL_INTERVAL_MS = 1000; // the contract asks for about one status request per second
const ERROR_RANGE_NMAD = 3; // difference heatmap clamp: ±3 × NMAD
const MASKED = 127; // mask.png is 0 or 255; anything above the midpoint is a filled cell
// The water slider runs from the DSM's lowest point to its highest. Positions map to height along a
// curve (rise ∝ position²), so the first half of the slider is fine control over the lowest quarter.
const FLOOD_CURVE = 2;
const FLOOD_STEPS = 500; // water slider positions; 0 means no water
const DEM_NAMES: Record<string, string> = {
  cartodem: 'CartoDEM (ISRO)',
  copernicus_glo30: 'Copernicus GLO-30',
  srtm: 'SRTM',
  nasadem: 'NASADEM',
};
const STAGE_TITLES: Record<string, string> = {
  depth: 'Estimating heights',
  calibrate: 'Calibrating to metres',
  export: 'Preparing the terrain',
};

const apiBase = () =>
  String((window as unknown as { DW_API_BASE?: string }).DW_API_BASE ?? '').replace(/\/$/, '');
const apiUrl = (path: string) => `${apiBase()}${path}`;
const jobUrl = (jobId: string, path = '') =>
  apiUrl(`/api/jobs/${encodeURIComponent(jobId)}${path}`);
const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
const $ = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T;
const escapeHtml = (s: string) =>
  s.replace(
    /[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]!,
  );

let currentJob: string | undefined;
let currentMetaFile: File | undefined;
let surfaces: { ortho: File; dsm: Surface; dem?: Surface; demName: string } | undefined;
let showingDem = false;
let switching = false;

async function readJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (body.detail) detail = String(body.detail);
    } catch {
      /* body was not JSON */
    }
    throw new Error(detail);
  }
  return (await response.json()) as T;
}

async function bundleFile(jobId: string, name: string, type: string): Promise<File> {
  const response = await fetch(jobUrl(jobId, `/bundle/${name}`));
  if (!response.ok)
    throw new Error(`Could not load ${name} from the backend (${response.status}).`);
  return new File([await response.blob()], name, { type });
}

export function installBackend(hooks: BackendHooks) {
  const { icon } = hooks;
  const terrainsButton = document.createElement('button');
  terrainsButton.id = 'dw-terrains';
  terrainsButton.className = 'secondary-button';
  terrainsButton.title = 'Switch terrain';
  terrainsButton.innerHTML = `${icon('layers')} Terrains`;
  const processButton = document.createElement('button');
  processButton.id = 'process-image';
  processButton.className = 'primary-button';
  processButton.innerHTML = `${icon('upload')} Process image`;
  $('open-dataset').before(terrainsButton, processButton);
  $('dw-calibration').insertAdjacentHTML(
    'afterend',
    '<div id="dw-job-links" class="dataset-meta" hidden></div>',
  );
  $('open-reference').insertAdjacentHTML(
    'afterend',
    `<button id="dw-open-validate" class="reference-button" hidden>${icon('layers')} Validate with GeoTIFF</button>`,
  );
  $('draw-profile').insertAdjacentHTML(
    'afterend',
    `<span id="dw-flip-divider" class="toolbar-divider" hidden></span><button id="dw-flip" aria-pressed="false" title="Switch between the DEM alone and DepthWizard (B)" hidden>${icon('layers')}<span id="dw-flip-label">DEM only</span><span class="toolbar-key">B</span></button>`,
  );
  document
    .querySelector('.exaggeration-section')!
    .insertAdjacentHTML(
      'afterend',
      `<section id="dw-water" class="exaggeration-section" hidden><div class="section-title"><h2>Water level</h2><output id="dw-water-value" for="dw-water-level">Off</output></div><input type="range" id="dw-water-level" aria-label="Water level" min="0" max="${FLOOD_STEPS}" step="1" value="0"/><div class="range-labels"><span>Off</span><span id="dw-water-share"></span><span id="dw-water-max"></span></div></section>`,
    );
  document.body.insertAdjacentHTML(
    'beforeend',
    `<dialog id="terrains-dialog"><div class="dialog-heading"><span class="dialog-icon">${icon('layers')}</span><button class="icon-button close-dialog" aria-label="Close dialog">${icon('x')}</button></div><h2>Your terrains.</h2><p>Everything processed on this computer, newest first. Pick one to open it.</p><div id="dw-terrain-list" class="surface-options" role="list" style="max-height: 52vh; overflow-y: auto; padding-right: 4px"></div><div class="dialog-footer"><span id="dw-terrain-state" class="small-muted"></span><button id="dw-terrain-process" class="secondary-button">${icon('upload')} Process a new image</button></div></dialog>
    <dialog id="process-dialog"><div class="dialog-heading"><span class="dialog-icon">${icon('mountain')}</span><button class="icon-button close-dialog" aria-label="Close dialog">${icon('x')}</button></div><h2>One image in. A height map out.</h2><p>Upload a PNG, JPG or GeoTIFF. GeoTIFFs come back in metres, calibrated with a DEM. Plain images come back as relative heights.</p><label class="form-file-label">Image (.tif, .png, .jpg)<input id="dw-image" type="file" accept=".tif,.tiff,.png,.jpg,.jpeg"/></label><label class="form-file-label">DEM (.tif, optional; default Copernicus GLO-30)<input id="dw-dem" type="file" accept=".tif,.tiff"/></label><label class="form-file-label">Ground control points (.csv, optional)<input id="dw-gcps" type="file" accept=".csv"/></label><label class="form-file-label">Ground sample distance in m/px (plain images, optional)<input id="dw-gsd" type="number" min="0" step="any" placeholder="e.g. 0.5"/></label><div class="dialog-note">${icon('info')} Processing runs on this computer. The only network access is an optional DEM download.</div><div class="dialog-footer"><span id="dw-backend-state" class="small-muted">Checking the backend…</span><button id="dw-process" class="primary-button" disabled>Process ${icon('arrow-up-right')}</button></div></dialog>
    <dialog id="validate-dialog"><div class="dialog-heading"><span class="dialog-icon">${icon('layers')}</span><button class="icon-button close-dialog" aria-label="Close dialog">${icon('x')}</button></div><h2>Check it against the truth.</h2><p>Upload a reference DSM GeoTIFF, such as LiDAR. The backend reprojects it onto this result and computes RMSE, MAE, NMAD and correlation.</p><label class="form-file-label">Reference DSM (.tif)<input id="dw-reference" type="file" accept=".tif,.tiff"/></label><div class="dialog-note">${icon('info')} Heights must use the same vertical datum as the DEM behind this result.</div><div class="dialog-footer"><span class="small-muted">Metrics on the full-resolution DSM</span><button id="dw-validate" class="primary-button" disabled>Validate ${icon('arrow-up-right')}</button></div></dialog>`,
  );
  hooks.refreshIcons();

  const terrainsDialog = $<HTMLDialogElement>('terrains-dialog');
  const processDialog = $<HTMLDialogElement>('process-dialog');
  const validateDialog = $<HTMLDialogElement>('validate-dialog');
  for (const dialog of [terrainsDialog, processDialog, validateDialog])
    dialog
      .querySelectorAll<HTMLElement>('.close-dialog')
      .forEach((button) => (button.onclick = () => dialog.close()));

  terrainsButton.onclick = () => void showTerrains(hooks);
  $('dw-terrain-process').onclick = () => {
    terrainsDialog.close();
    processButton.click();
  };
  processButton.onclick = () => {
    processDialog.showModal();
    void checkHealth();
  };
  $('dw-image').onchange = () =>
    ($<HTMLButtonElement>('dw-process').disabled = !$<HTMLInputElement>('dw-image').files?.length);
  $('dw-process').onclick = () => {
    const pick = (id: string) => $<HTMLInputElement>(id).files?.[0];
    const image = pick('dw-image');
    if (!image) return;
    const form = new FormData();
    form.append('image', image);
    const dem = pick('dw-dem');
    if (dem) form.append('dem', dem);
    const gcps = pick('dw-gcps');
    if (gcps) form.append('gcps', gcps);
    const gsd = $<HTMLInputElement>('dw-gsd').value.trim();
    if (gsd) form.append('gsd_m', gsd);
    processDialog.close();
    void runJob(form, hooks);
  };
  $('dw-open-validate').onclick = () => validateDialog.showModal();
  $('dw-flip').onclick = () => void flip(hooks);
  $('dw-water-level').oninput = () => updateWater(hooks);
  window.addEventListener('keydown', (e) => {
    if (
      e.key.toLowerCase() !== 'b' ||
      e.ctrlKey ||
      e.metaKey ||
      e.altKey ||
      // Sliders and dropdowns keep focus after use; B should still flip then. Text fields don't.
      (e.target as HTMLElement).matches('input:not([type=range]):not([type=checkbox]),textarea') ||
      document.querySelector('dialog[open]')
    )
      return;
    e.preventDefault(); // also stops a focused dropdown from jumping to an option starting with B
    void flip(hooks); // works in fly mode too: the pointer lock stays on
  });
  $('dw-reference').onchange = () =>
    ($<HTMLButtonElement>('dw-validate').disabled =
      !$<HTMLInputElement>('dw-reference').files?.length);
  $('dw-validate').onclick = () => {
    const file = $<HTMLInputElement>('dw-reference').files?.[0];
    if (!file || !currentJob) return;
    validateDialog.close();
    void validate(currentJob, file, hooks);
  };
  // A local-file or demo dataset replaces the backend job, so hide the job-specific tools.
  $('load-selected').addEventListener('click', forgetJob);
  $('load-demo').addEventListener('click', forgetJob);

  const job = new URLSearchParams(location.search).get('job');
  if (job) void openJob(job, hooks);
}

function forgetJob() {
  currentJob = undefined;
  currentMetaFile = undefined;
  surfaces = undefined;
  showingDem = false;
  $('dw-open-validate').hidden = true;
  $('dw-job-links').hidden = true;
  $('dw-flip').hidden = $('dw-flip-divider').hidden = true;
  $('dw-water').hidden = true;
  history.replaceState(null, '', location.pathname);
}

async function showTerrains(hooks: BackendHooks) {
  const dialog = $<HTMLDialogElement>('terrains-dialog');
  const list = $('dw-terrain-list');
  const state = $('dw-terrain-state');
  list.innerHTML = sampleEntry();
  state.textContent = 'Looking for results…';
  dialog.showModal();
  try {
    const results = await readJson<TerrainSummary[]>(await fetch(apiUrl('/api/jobs')));
    list.innerHTML = sampleEntry() + results.map(terrainEntry).join('');
    state.textContent = results.length
      ? `${results.length} result${results.length === 1 ? '' : 's'} on this computer`
      : 'No results yet. Process an image to add one.';
  } catch {
    state.textContent = 'Backend not reachable: only the built-in sample is available.';
  }
  list.querySelectorAll<HTMLButtonElement>('button').forEach(
    (button) =>
      (button.onclick = () => {
        dialog.close();
        const jobId = button.dataset.job;
        if (jobId) {
          hooks.loading(true, 'Opening terrain', 'Fetching the bundle from the backend…');
          void openJob(jobId, hooks);
        } else {
          forgetJob();
          void hooks.loadDataset();
        }
      }),
  );
}

function sampleEntry(): string {
  const active = currentJob ? '' : ' active';
  return `<button class="surface-option${active}" data-sample="1" role="listitem"><span class="surface-swatch slope-swatch"></span><span>Sample terrain<small>Built-in synthetic catchment · works without the backend</small></span><span class="radio-indicator"></span></button>`;
}

function terrainEntry(r: TerrainSummary): string {
  const units = r.units === 'm' ? 'metres' : 'relative';
  const source = r.calibration?.dem_source ?? r.calibration?.method ?? '';
  const when = new Date(r.finished * 1000).toLocaleString(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  });
  const details = [units, String(source).replace(/_/g, ' '), `${r.width} × ${r.height}`, when]
    .filter(Boolean)
    .map((part) => escapeHtml(part))
    .join(' · ');
  const active = r.job_id === currentJob ? ' active' : '';
  const swatch = r.units === 'm' ? 'elevation-swatch' : 'ortho-swatch';
  return `<button class="surface-option${active}" data-job="${escapeHtml(r.job_id)}" role="listitem"><span class="surface-swatch ${swatch}"></span><span>${escapeHtml(r.name)}<small>${details}</small></span><span class="radio-indicator"></span></button>`;
}

async function checkHealth() {
  const state = $('dw-backend-state');
  try {
    const health = await readJson<{ model_loaded: boolean; gpu: string | null }>(
      await fetch(apiUrl('/api/health')),
    );
    state.textContent = health.model_loaded
      ? `Backend ready · ${health.gpu ?? 'CPU only'}`
      : 'Backend is running, but the depth model is missing';
  } catch {
    state.textContent = 'Backend not reachable. Start it with: uvicorn api.main:app';
  }
}

async function runJob(form: FormData, hooks: BackendHooks) {
  hooks.loading(true, 'Uploading', 'Sending the image to the local backend…');
  try {
    const { job_id } = await readJson<{ job_id: string }>(
      await fetch(apiUrl('/api/jobs'), { method: 'POST', body: form }),
    );
    let status: JobStatus;
    do {
      await sleep(POLL_INTERVAL_MS);
      status = await readJson<JobStatus>(await fetch(jobUrl(job_id)));
      hooks.loading(
        true,
        STAGE_TITLES[status.stage] ?? 'Processing',
        `${status.message} · ${Math.round(status.progress * 100)}%`,
      );
    } while (status.status === 'queued' || status.status === 'running');
    if (status.status === 'error') throw new Error(status.message);
    await openJob(job_id, hooks, status.message);
  } catch (e) {
    hooks.loading(false);
    hooks.notify(`Processing failed: ${(e as Error).message}`, true);
  }
}

/** mask.png pixels (RGBA) on the bundle grid. */
async function maskPixels(mask: File, meta: BundleMeta): Promise<Uint8ClampedArray> {
  const bitmap = await createImageBitmap(mask);
  const canvas = new OffscreenCanvas(meta.width, meta.height);
  const ctx = canvas.getContext('2d')!;
  ctx.drawImage(bitmap, 0, 0, meta.width, meta.height);
  bitmap.close();
  return ctx.getImageData(0, 0, meta.width, meta.height).data;
}

/** Heights from a .bin. Filled cells (mask.png = 255) become NaN, which stratum draws as holes
 * and never measures. Float32Array assumes the contract's little-endian layout. */
async function readHeights(file: File, mask?: Uint8ClampedArray): Promise<Float32Array> {
  const heights = new Float32Array(await file.arrayBuffer());
  const little = new Uint8Array(new Uint32Array([1]).buffer)[0] === 1;
  if (mask && little)
    for (let i = 0; i < heights.length; i++) if (mask[i * 4] > MASKED) heights[i] = NaN;
  return heights;
}

const binFile = (heights: Float32Array) =>
  new File([heights], 'dsm.bin', { type: 'application/octet-stream' });

async function openJob(jobId: string, hooks: BackendHooks, message?: string) {
  try {
    const metaFile = await bundleFile(jobId, 'meta.json', 'application/json');
    const meta = JSON.parse(await metaFile.text()) as BundleMeta;
    const mask = meta.has_mask
      ? await maskPixels(await bundleFile(jobId, 'mask.png', 'image/png'), meta)
      : undefined;
    const bin = (name: string) => bundleFile(jobId, name, 'application/octet-stream');
    const dsm: Surface = { heights: await readHeights(await bin('dsm.bin'), mask), meta: metaFile };
    const ortho = await bundleFile(jobId, 'ortho.png', 'image/png');
    const source = meta.calibration?.dem_source ?? '';
    const demName = DEM_NAMES[source] ?? (source || 'the DEM');
    let dem: Surface | undefined;
    if (meta.dem_file) {
      // The DEM keeps the job's name and extent; its calibration panel says what it is.
      const demMeta = {
        ...meta,
        calibration: { method: 'dem_only (no model)', confidence: 'n/a', dem_source: source },
      };
      dem = {
        heights: await readHeights(await bin(meta.dem_file), mask),
        meta: new File([JSON.stringify(demMeta)], 'meta.json', { type: 'application/json' }),
      };
    }
    hooks.loading(false);
    await hooks.loadDataset([binFile(dsm.heights), ortho, metaFile]);
    currentJob = jobId;
    currentMetaFile = metaFile;
    surfaces = { ortho, dsm, dem, demName };
    showingDem = false;
    history.replaceState(null, '', `${location.pathname}?job=${encodeURIComponent(jobId)}`);
    const links = $('dw-job-links');
    links.innerHTML = `<span>Full-resolution DSM <a class="text-button" href="${jobUrl(jobId, '/dsm.tif')}" download>${hooks.icon('download')} GeoTIFF</a></span>`;
    links.hidden = false;
    $('dw-open-validate').hidden = !meta.crs;
    $('dw-flip').hidden = $('dw-flip-divider').hidden = !dem;
    updateFlipButton();
    $('dw-water').hidden = meta.units !== 'm';
    $<HTMLInputElement>('dw-water-level').value = '0';
    updateWater(hooks);
    hooks.refreshIcons();
    if (message) hooks.notify(message);
  } catch (e) {
    hooks.loading(false);
    hooks.notify((e as Error).message, true);
  }
}

function updateFlipButton() {
  $('dw-flip-label').textContent = showingDem ? 'DepthWizard' : 'DEM only';
  $('dw-flip').classList.toggle('active', showingDem);
  $('dw-flip').setAttribute('aria-pressed', String(showingDem));
}

/** Swap the terrain between DepthWizard's DSM and the DEM alone, keeping the camera. */
async function flip(hooks: BackendHooks) {
  if (!surfaces?.dem || switching) return;
  switching = true;
  const toDem = !showingDem;
  const surface = toDem ? surfaces.dem : surfaces.dsm;
  try {
    await hooks.loadDataset([binFile(surface.heights), surfaces.ortho, surface.meta], {
      keepView: true,
    });
    showingDem = toDem;
    updateFlipButton();
    updateWater(hooks); // same water height, new surface
    hooks.notify(
      toDem
        ? `DEM only: ${surfaces.demName}, about 30 m per cell. This is all the DEM knows. Press B for DepthWizard.`
        : 'DepthWizard: the same terrain, plus the buildings and trees the model sees. Press B for the DEM only.',
    );
  } finally {
    switching = false;
  }
}

/** Finite heights in ascending order, cached per surface. */
function sortedHeights(surface: Surface): Float32Array {
  if (!surface.sorted) surface.sorted = surface.heights.filter((h) => Number.isFinite(h)).sort();
  return surface.sorted;
}

/** Share of the values below level in an ascending array (binary search). */
function shareBelow(sorted: Float32Array, level: number): number {
  let lo = 0,
    hi = sorted.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (sorted[mid] < level) lo = mid + 1;
    else hi = mid;
  }
  return sorted.length ? lo / sorted.length : 0;
}

/** Water level from the slider. Its scale comes from the DSM, so a slider position is the same
 * absolute height on the DSM and on the DEM. */
function updateWater(hooks: BackendHooks) {
  if (!surfaces || $('dw-water').hidden) return;
  const step = Number($<HTMLInputElement>('dw-water-level').value);
  const base = sortedHeights(surfaces.dsm);
  if (!base.length) return;
  const low = base[0],
    span = base[base.length - 1] - low,
    rise = (step / FLOOD_STEPS) ** FLOOD_CURVE * span;
  const f = (v: number, digits = 1) =>
    v.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
  $('dw-water-max').textContent = `+${f(span, 0)} m`;
  if (step === 0) {
    hooks.setWaterLevel(null);
    $('dw-water-value').textContent = 'Off';
    $('dw-water-share').textContent = '';
    return;
  }
  const level = low + rise;
  hooks.setWaterLevel(level);
  const shown = showingDem && surfaces.dem ? surfaces.dem : surfaces.dsm;
  $('dw-water-value').innerHTML = `+${f(rise)}<span> m</span>`;
  $('dw-water-share').textContent =
    `${f(100 * shareBelow(sortedHeights(shown), level))} % under water`;
  $('dw-water').title = `Water surface at ${f(level, 2)} m, ${f(rise, 2)} m above the lowest point`;
}

async function validate(jobId: string, reference: File, hooks: BackendHooks) {
  hooks.loading(
    true,
    'Validating',
    'Reprojecting the reference onto this DSM and computing metrics…',
  );
  try {
    const form = new FormData();
    form.append('reference', reference);
    const report = await readJson<ValidationReport>(
      await fetch(jobUrl(jobId, '/validate'), { method: 'POST', body: form }),
    );
    const referenceBin = await bundleFile(
      jobId,
      report.reference_file ?? 'reference.bin',
      'application/octet-stream',
    );
    hooks.loading(false);
    await hooks.loadReferenceFiles(referenceBin, currentMetaFile);
    hooks.setErrorRange(ERROR_RANGE_NMAD * report.nmad);
    showReport(report, reference.name);
  } catch (e) {
    hooks.loading(false);
    hooks.notify(`Validation failed: ${(e as Error).message}`, true);
  }
}

/** Backend metrics replace the panel values: they use the full-resolution DSM. */
function showReport(r: ValidationReport, name: string) {
  const unit = r.units === 'm' ? 'm' : 'relative';
  const f = (v: number, digits = 3) =>
    v.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
  $('reference-name').textContent = name;
  $('rmse').textContent = `${f(r.rmse)} ${unit}`;
  $('mae').textContent = `${f(r.mae)} ${unit}`;
  $('reference-count').textContent =
    `NMAD ${f(r.nmad)} ${unit} · r ${f(r.pearson_r)} · bias ${f(r.bias)} ${unit} · ` +
    `${r.n_pixels.toLocaleString()} full-resolution pixels${r.scale_aligned ? ' · scale-aligned' : ''}`;
}
