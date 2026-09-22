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
 */

export interface BackendHooks {
  loadDataset: (files?: File[]) => Promise<void>;
  loadReferenceFiles: (dsm: File, meta?: File) => Promise<void>;
  loading: (value: boolean, title?: string, detail?: string) => void;
  notify: (message: string, error?: boolean) => void;
  setErrorRange: (range: number | undefined) => void;
  icon: (name: string, cls?: string) => string;
  refreshIcons: () => void;
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
  has_mask?: boolean;
}

const POLL_INTERVAL_MS = 1000; // the contract asks for about one status request per second
const ERROR_RANGE_NMAD = 3; // difference heatmap clamp: ±3 × NMAD
const MASKED = 127; // mask.png is 0 or 255; anything above the midpoint is a filled cell
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
  $('dw-open-validate').hidden = true;
  $('dw-job-links').hidden = true;
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

/** Filled cells (mask.png = 255) become NaN, which stratum draws as holes and never measures. */
async function maskHeights(dsm: File, mask: File, meta: BundleMeta): Promise<File> {
  const little = new Uint8Array(new Uint32Array([1]).buffer)[0] === 1;
  if (!little) return dsm; // Float32Array below assumes the contract's little-endian layout
  const bitmap = await createImageBitmap(mask);
  const canvas = new OffscreenCanvas(meta.width, meta.height);
  const ctx = canvas.getContext('2d')!;
  ctx.drawImage(bitmap, 0, 0, meta.width, meta.height);
  bitmap.close();
  const pixels = ctx.getImageData(0, 0, meta.width, meta.height).data;
  const heights = new Float32Array(await dsm.arrayBuffer());
  for (let i = 0; i < heights.length; i++) if (pixels[i * 4] > MASKED) heights[i] = NaN;
  return new File([heights.buffer], 'dsm.bin', { type: 'application/octet-stream' });
}

async function openJob(jobId: string, hooks: BackendHooks, message?: string) {
  try {
    const metaFile = await bundleFile(jobId, 'meta.json', 'application/json');
    const meta = JSON.parse(await metaFile.text()) as BundleMeta;
    let dsm = await bundleFile(jobId, 'dsm.bin', 'application/octet-stream');
    if (meta.has_mask)
      dsm = await maskHeights(dsm, await bundleFile(jobId, 'mask.png', 'image/png'), meta);
    const files = [dsm, await bundleFile(jobId, 'ortho.png', 'image/png'), metaFile];
    hooks.loading(false);
    await hooks.loadDataset(files);
    currentJob = jobId;
    currentMetaFile = metaFile;
    history.replaceState(null, '', `${location.pathname}?job=${encodeURIComponent(jobId)}`);
    const links = $('dw-job-links');
    links.innerHTML = `<span>Full-resolution DSM <a class="text-button" href="${jobUrl(jobId, '/dsm.tif')}" download>${hooks.icon('download')} GeoTIFF</a></span>`;
    links.hidden = false;
    $('dw-open-validate').hidden = !meta.crs;
    hooks.refreshIcons();
    if (message) hooks.notify(message);
  } catch (e) {
    hooks.loading(false);
    hooks.notify((e as Error).message, true);
  }
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
