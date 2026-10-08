import './style.css';
import {
  createIcons,
  Mountain,
  Layers,
  FolderOpen,
  ChevronDown,
  ChevronRight,
  Check,
  Plus,
  Minus,
  MoveUpRight,
  MousePointer2,
  Navigation,
  RotateCcw,
  Maximize,
  ScanLine,
  Move3d,
  PanelLeftClose,
  SlidersHorizontal,
  ChartNoAxesCombined,
  Upload,
  FileImage,
  FileJson,
  FileBox,
  ArrowUpRight,
  X,
  Info,
  Keyboard,
  Download,
  MapPin,
  Focus,
  LoaderCircle,
  Image,
  Sun,
  Grip,
  Trash2,
} from 'lucide';
import { TerrainViewer, type Surface } from './viewer';
import { TerrainWorker } from './worker-client';
import { ProfileChart } from './chart';
import type { GridPoint, MeshData, Meta, Metrics, ProfilePoint, Sample } from './terrain';
import { validateMeta } from './terrain';
import { installBackend } from './backend';
const icons = {
  Mountain,
  Layers,
  FolderOpen,
  ChevronDown,
  ChevronRight,
  Check,
  Plus,
  Minus,
  MoveUpRight,
  MousePointer2,
  Navigation,
  RotateCcw,
  Maximize,
  ScanLine,
  Move3d,
  PanelLeftClose,
  SlidersHorizontal,
  ChartNoAxesCombined,
  Upload,
  FileImage,
  FileJson,
  FileBox,
  ArrowUpRight,
  X,
  Info,
  Keyboard,
  Download,
  MapPin,
  Focus,
  LoaderCircle,
  Image,
  Sun,
  Grip,
  Trash2,
};
const icon = (name: string, cls = '') => `<i data-lucide="${name}" class="${cls}"></i>`;
const $ = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T;
const refreshIcons = () => createIcons({ icons, attrs: { 'stroke-width': 1.65 } });
document.querySelector('#app')!.innerHTML = `
  <header class="app-header">
    <!-- DepthWizard patch: product name --><a class="brand" href="./" aria-label="DepthWizard home"><span class="brand-mark">${icon('mountain')}</span><span>DepthWizard<span class="brand-dot">.</span></span></a>
    <div class="breadcrumb"><span class="header-divider"></span>Workspace ${icon('chevron-right')} <strong>Terrain explorer</strong></div>
    <div class="header-actions"><span class="offline-badge"><span class="status-dot"></span>Local workspace</span><button id="help" class="icon-button" title="Keyboard shortcuts" aria-label="Keyboard shortcuts">${icon('keyboard')}</button><button id="open-dataset" class="primary-button">${icon('folder-open')} Open dataset <span class="key-hint">O</span></button></div>
  </header>
  <div class="app-body">
    <aside class="sidebar" aria-label="Terrain settings">
      <div class="sidebar-title"><span>EXPLORER</span>${icon('sliders-horizontal')}</div>
      <section class="dataset-section"><div class="dataset-title"><span class="dataset-icon">${icon('mountain')}</span><div><h1 id="dataset-name">Alpine catchment</h1><span id="dataset-subtitle">Generated sample terrain</span></div><span id="demo-badge" class="tiny-badge">DEMO</span></div>
        <div class="file-tree"><div>${icon('file-box')}<span>dsm.bin</span><span id="file-dsm-size" class="file-size">2.25 MB</span>${icon('check', 'file-check')}</div><div>${icon('file-image')}<span>ortho.png</span><span class="file-size">RGB</span>${icon('check', 'file-check')}</div><div>${icon('file-json')}<span>meta.json</span><span class="file-size">Metadata</span>${icon('check', 'file-check')}</div></div>
        <div class="dataset-meta"><span>Resolution <strong id="resolution">3.00 m / px</strong></span><span>Grid size <strong id="grid-size">768 × 768</strong></span></div><div id="dw-calibration" class="dataset-meta" hidden></div>
      </section>
      <section class="surface-section"><div class="section-title"><h2>Surface</h2><span class="section-note">VISUALIZATION</span></div>
        <div class="surface-options" role="group" aria-label="Surface visualization">
          <button class="surface-option active" data-surface="ortho" aria-pressed="true"><span class="surface-swatch ortho-swatch"></span><span>Orthophoto<small>Original imagery</small></span><span class="radio-indicator"></span></button>
          <button class="surface-option" data-surface="elevation" aria-pressed="false"><span class="surface-swatch elevation-swatch"></span><span>Elevation<small>Height gradient</small></span><span class="radio-indicator"></span></button>
          <button class="surface-option" data-surface="slope" aria-pressed="false"><span class="surface-swatch slope-swatch"></span><span>Slope<small>Surface inclination</small></span><span class="radio-indicator"></span></button>
          <button class="surface-option" data-surface="error" aria-pressed="false" disabled id="error-surface"><span class="surface-swatch error-swatch"></span><span>Difference<small id="difference-subtitle">Add a reference DSM</small></span><span class="radio-indicator"></span></button>
        </div>
        <label class="switch-row"><span>${icon('sun')} Hillshade</span><input id="hillshade" type="checkbox" role="switch" checked/><span class="switch"></span></label>
        <label class="switch-row"><span>${icon('layers')} Contour lines <span class="small-muted" id="contour-unit">50 m</span></span><input id="contours" type="checkbox" role="switch"/><span class="switch"></span></label>
      </section>
      <section class="exaggeration-section"><div class="section-title"><h2>Vertical exaggeration</h2><output id="exaggeration-value" for="exaggeration">1.0<span>×</span></output></div><input type="range" id="exaggeration" aria-label="Vertical exaggeration" min="0.5" max="5" step="0.1" value="1"/><div class="range-labels"><span>0.5×</span><button id="true-scale">1× true scale</button><span>5×</span></div></section>
      <section class="reference-section"><div class="section-title"><h2>Reference comparison</h2>${icon('layers')}</div><p>Compare surfaces. Find the difference.</p><button id="open-reference" class="reference-button">${icon('plus')} Add reference DSM</button><div id="reference-results" hidden><div class="reference-name">${icon('check')}<span id="reference-name"></span></div><div class="metric-grid"><div><span>RMSE</span><strong id="rmse">—</strong></div><div><span>MAE</span><strong id="mae">—</strong></div></div><p id="reference-count"></p></div></section>
      <section class="inspector-section"><div class="section-title"><h2>Surface inspector</h2><button id="clear-pin" class="text-button" hidden>Unpin</button><span id="inspector-state" class="small-muted">Hover to inspect</span></div><div class="inspector-height"><span id="inspect-height">—</span><span id="inspect-unit">m</span></div><div class="inspector-details"><span>Slope <strong id="inspect-slope">—</strong></span><span>Grid <strong id="inspect-grid">—</strong></span></div></section>
      <div class="sidebar-bottom"><div class="private-icon">${icon('focus')}</div><div><strong>Your data stays here.</strong><span>Fully local. No uploads. No cloud.</span></div></div>
    </aside>
    <main class="workspace">
      <div class="workspace-heading"><div><span class="eyebrow">TERRAIN WORKSPACE</span><h2 id="view-title">Alpine catchment <span class="title-separator">/</span> <span id="surface-title">Orthophoto</span></h2></div><div class="heading-meta"><span class="status-dot"></span><span id="dataset-status">Preparing sample</span><span class="separator"></span><span id="extent-label">2.30 × 2.30 km</span></div></div>
      <div class="view-and-chart">
        <section id="viewport" class="viewport" aria-label="Terrain view">
          <div class="view-topbar"><div class="view-label"><span class="live-dot"></span><span id="view-mode-label">3D ORBIT</span><span class="view-label-divider"></span><span id="crs-label">LOCAL GRID</span></div><div class="view-tools"><button id="reset-camera" title="Reset view (R)" aria-label="Reset view">${icon('rotate-ccw')}</button><button id="top-view" title="Top view (T)" aria-label="Top view">${icon('scan-line')}</button><span></span><button id="fullscreen" title="Toggle fullscreen" aria-label="Toggle fullscreen">${icon('maximize')}</button></div></div>
          <div class="navigation-toolbar"><div class="nav-segment"><button id="orbit-mode" class="active" aria-pressed="true">${icon('mouse-pointer-2')}Orbit</button><button id="fly-mode" aria-pressed="false">${icon('navigation')}Fly</button></div><span class="toolbar-divider"></span><button id="draw-profile" aria-pressed="false">${icon('chart-no-axes-combined')}Draw profile<span class="toolbar-key">P</span></button></div>
          <div id="draw-instruction" class="draw-instruction" hidden>Click a start point on the terrain <kbd>Esc</kbd> to cancel</div>
          <div id="fly-instruction" class="draw-instruction" hidden>Click the terrain to fly · WASD move · Q / E descend / ascend · Esc release</div>
          <div id="crosshair" class="crosshair" hidden>+</div>
          <div class="compass" aria-hidden="true"><span>N</span><div id="compass-needle"><svg viewBox="0 0 40 40"><path d="M20 3 27 31 20 26 13 31Z" fill="#edf1d9"/><path d="M20 3V26L13 31Z" fill="#7d9086"/></svg></div><small>E</small></div>
          <div class="zoom-controls"><button id="zoom-in" title="Zoom in" aria-label="Zoom in">${icon('plus')}</button><button id="zoom-out" title="Zoom out" aria-label="Zoom out">${icon('minus')}</button></div>
          <div class="legend" id="legend"><div class="legend-heading"><span id="legend-title">ELEVATION</span><span id="legend-unit">m</span></div><div id="legend-gradient" class="legend-gradient"></div><div class="legend-values"><span id="legend-min">1,080</span><span id="legend-mid">1,510</span><span id="legend-max">1,940</span></div></div>
          <div class="viewport-bottom"><div class="terrain-hint" id="terrain-hint">${icon('mouse-pointer-2')} Drag to orbit <span>·</span> Scroll to zoom <span>·</span> Right-drag to pan</div><div class="local-coordinates"><span>X <strong id="coord-x">—</strong></span><span>Y <strong id="coord-y">—</strong></span><span>Z <strong id="coord-z">—</strong></span></div></div>
          <div id="loading" class="loading-overlay"><div class="loading-card">${icon('loader-circle', 'spinner')}<strong id="loading-title">Building your terrain</strong><span id="loading-detail">Generating the sample surface locally…</span><button id="cancel-load" class="text-button" hidden>Cancel</button></div></div>
        </section>
        <section class="profile-panel" aria-label="Elevation profile"><div class="profile-header"><div class="profile-heading">${icon('chart-no-axes-combined')}<h2>Elevation profile</h2><span id="profile-badge" class="profile-badge">A → B</span><span id="profile-type" class="small-muted">Demo transect</span></div><div class="profile-actions"><span id="profile-distance">—</span><span class="separator"></span><button id="export-profile" title="Export profile as CSV" aria-label="Export profile as CSV">${icon('download')}</button><button id="clear-profile" title="Clear profile" aria-label="Clear profile">${icon('x')}</button></div></div>
          <div class="profile-body"><div class="chart-container"><canvas id="profile-chart" role="img" aria-label="Elevation profile of the selected transect"></canvas><div id="profile-empty" class="profile-empty" hidden><span>${icon('chart-no-axes-combined')}</span><strong>A different perspective on your terrain</strong><p>Draw a line on the surface to inspect its elevation.</p><button id="empty-draw" class="text-button">Draw your first profile ${icon('arrow-up-right')}</button></div></div><div class="profile-stats"><span id="profile-height-label">ELEVATION · m</span><div><small>Minimum</small><strong id="profile-min">—</strong></div><div><small>Maximum</small><strong id="profile-max">—</strong></div><div><small>Net change</small><strong id="profile-change">—</strong></div></div></div>
        </section>
      </div>
      <footer class="status-bar"><div><span class="status-dot"></span>Offline ready<span class="status-divider"></span><span id="mesh-status">Initializing renderer</span></div><div><label class="quality-label" for="quality">Quality</label><select id="quality" aria-label="Mesh quality"><option value="auto">Auto</option><option value="257">Performance · 257</option><option value="513">Balanced · 513</option><option value="1024">Detail · 1024</option></select><span class="status-divider"></span><span class="fps-dot"></span><span id="fps">— fps</span></div></footer>
    </main>
  </div>
  <dialog id="dataset-dialog"><div class="dialog-heading"><span class="dialog-icon">${icon('folder-open')}</span><button class="icon-button close-dialog" aria-label="Close dialog">${icon('x')}</button></div><h2>Bring your terrain to life.</h2><p>Open the three files from your Python backend. Everything is processed on this device.</p><label class="drop-area" id="file-drop">${icon('upload')}<strong>Choose files or drop them here</strong><span>dsm.bin + ortho.png + meta.json</span><input id="dataset-input" type="file" multiple accept=".bin,.png,.json"/></label><div id="selected-files" class="selected-files">No files selected</div><div class="dialog-note">${icon('info')} Float32, little-endian · Row-major · Heights in metres or relative units</div><div class="dialog-footer"><button id="load-demo" class="secondary-button">Explore sample</button><button id="load-selected" class="primary-button" disabled>Open terrain ${icon('arrow-up-right')}</button></div></dialog>
  <dialog id="reference-dialog"><div class="dialog-heading"><span class="dialog-icon">${icon('layers')}</span><button class="icon-button close-dialog" aria-label="Close dialog">${icon('x')}</button></div><h2>A second surface. More insight.</h2><p>Load a reference DSM to visualize signed differences and calculate RMSE and MAE across every valid source cell.</p><label class="form-file-label">Reference DSM (.bin)<input id="reference-input" type="file" accept=".bin"/></label><label class="form-file-label">Reference metadata (.json, optional)<input id="reference-meta-input" type="file" accept=".json"/></label><div class="dialog-note">${icon('info')} Without metadata, the reference is assumed to have exactly the same grid, alignment, CRS, and height units. With metadata, these are checked. Difference = source − reference.</div><div class="dialog-footer"><span class="small-muted">Raw Float32 · No resampling</span><button id="load-reference" class="primary-button" disabled>Compare surfaces ${icon('arrow-up-right')}</button></div></dialog>
  <dialog id="help-dialog"><div class="dialog-heading"><span class="dialog-icon">${icon('keyboard')}</span><button class="icon-button close-dialog" aria-label="Close dialog">${icon('x')}</button></div><h2>A little orientation.</h2><p>Your shortcuts to exploring the surface.</p><div class="shortcut-list"><div><span>Open dataset</span><kbd>O</kbd></div><div><span>Draw elevation profile</span><kbd>P</kbd></div><div><span>Reset / top view</span><span><kbd>R</kbd> <kbd>T</kbd></span></div><div><span>Fly forward / left / back / right</span><span><kbd>W</kbd> <kbd>A</kbd> <kbd>S</kbd> <kbd>D</kbd></span></div><div><span>Fly down / up</span><span><kbd>Q</kbd> <kbd>E</kbd></span></div><div><span>Fly faster</span><kbd>Shift</kbd></div><div><span>Release mouse / cancel profile</span><kbd>Esc</kbd></div></div><p class="help-footnote">Click a point to pin its height. Profile and inspector values always use original elevations, independent of vertical exaggeration.</p></dialog>
  <div id="toast" class="toast" role="status" hidden><span id="toast-message"></span><button id="dismiss-toast" aria-label="Dismiss notification">${icon('x')}</button></div>
  <div id="global-drop" class="global-drop" hidden>${icon('upload')}<strong>Drop your terrain files</strong><span>dsm.bin, ortho.png, and meta.json</span></div>
`;
refreshIcons();
let viewer: TerrainViewer;
try {
  viewer = new TerrainViewer($('viewport'));
} catch (e) {
  $('loading-title').textContent = 'WebGL 2 is unavailable';
  $('loading-detail').textContent =
    'Enable hardware acceleration in your browser or WebView2, then reload.';
  throw e;
}
const chart = new ProfileChart($<HTMLCanvasElement>('profile-chart'));
let worker: TerrainWorker | undefined,
  candidate: TerrainWorker | undefined,
  meta: Meta | undefined,
  metrics: Metrics | undefined;
let selectedFiles: File[] = [],
  surface: Surface = 'ortho',
  profilePoints: ProfilePoint[] = [],
  profileEndpoints:
    | {
        a: GridPoint;
        b: GridPoint;
      }
    | undefined;
let pinned = false,
  drawingStart: GridPoint | undefined,
  sampling = false,
  sampleVersion = 0,
  operation = 0,
  profileVersion = 0;
let cap = 513,
  busy = true,
  autoSlow = 0,
  qualityChanging = false,
  currentName = 'Alpine catchment';
let toastTimer: ReturnType<typeof setTimeout>;
const fmt = (n: number, d = 0) =>
  n.toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });
const unit = () => (meta?.units === 'm' ? 'm' : 'relative');
// DepthWizard patch (VIEWER_CONTRACT): relative heights are shown as percentages.
const hUnit = () => (meta?.units === 'm' ? 'm' : '%');
const hv = (h: number) => (meta?.units === 'm' ? h : h * 100);
let errorRangeOverride: number | undefined;
const escapeHtml = (s: string) =>
  s.replace(
    /[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]!,
  );
// DepthWizard patch (VIEWER_CONTRACT): calibration info panel from meta.json.
function renderCalibration(cal?: Record<string, unknown> | null) {
  const el = $('dw-calibration');
  el.hidden = !cal;
  if (!cal) return;
  const show = (v: unknown) => escapeHtml(v == null ? '—' : String(v).replace(/_/g, ' '));
  el.innerHTML =
    `<span>Calibration <strong>${show(cal.method)}</strong></span>` +
    `<span>Confidence <strong>${show(cal.confidence)}</strong></span>` +
    (cal.dem_source ? `<span>DEM <strong>${show(cal.dem_source)}</strong></span>` : '');
}
function notify(message: string, error = false) {
  clearTimeout(toastTimer);
  $('toast-message').textContent = message;
  $('toast').classList.toggle('error', error);
  $('toast').hidden = false;
  toastTimer = setTimeout(() => ($('toast').hidden = true), error ? 14000 : 6000);
}
function loading(
  value: boolean,
  title = 'Processing terrain',
  detail = 'Working on this device…',
  cancel = false,
) {
  busy = value;
  $('loading').hidden = !value;
  $('loading-title').textContent = title;
  $('loading-detail').textContent = detail;
  $('cancel-load').hidden = !cancel;
  $<HTMLSelectElement>('quality').disabled = value;
  $('open-reference').toggleAttribute('disabled', value || !meta);
}
function meshStatus(mesh: MeshData) {
  $('mesh-status').textContent =
    `${fmt(mesh.cols * mesh.rows)} vertices · ${mesh.cols} × ${mesh.rows}`;
  $('mesh-status').title =
    `${fmt(mesh.indices.length / 3)} triangles. Full-resolution measurements retained in a worker.`;
}
function updateLegend() {
  if (!meta) return;
  const error = surface === 'error',
    slope = surface === 'slope';
  $('legend-title').textContent = slope ? 'SLOPE' : error ? 'SIGNED DIFFERENCE' : 'ELEVATION';
  $('legend-unit').textContent = slope
    ? meta.units === 'm'
      ? 'degrees'
      : 'relative*'
    : error
      ? unit()
      : hUnit();
  $('legend').title =
    slope && meta.units !== 'm'
      ? 'Slope is an uncalibrated inclination proxy because the vertical unit is relative.'
      : '';
  $('legend-gradient').className = `legend-gradient ${surface}`;
  const max = error ? (errorRangeOverride ?? metrics?.maxAbs ?? 1) : slope ? 60 : hv(meta.max_h),
    min = error ? -max : slope ? 0 : hv(meta.min_h);
  $('legend-min').textContent = fmt(min, error ? 2 : 0);
  $('legend-mid').textContent = fmt((min + max) / 2, error ? 2 : 0);
  $('legend-max').textContent = `${fmt(max, error ? 2 : 0)}${slope ? '+' : ''}`;
}
function setSurface(value: Surface) {
  if (value === 'error' && !metrics) return;
  surface = value;
  viewer.setSurface(value, errorRangeOverride ?? metrics?.maxAbs);
  document.querySelectorAll<HTMLButtonElement>('[data-surface]').forEach((button) => {
    button.classList.toggle('active', button.dataset.surface === value);
    button.setAttribute('aria-pressed', String(button.dataset.surface === value));
  });
  $('surface-title').textContent = {
    ortho: 'Orthophoto',
    elevation: 'Elevation',
    slope: 'Slope',
    error: 'Difference',
  }[value];
  updateLegend();
}
function setMode(value: 'orbit' | 'fly') {
  viewer.setDrawing(false);
  drawingStart = undefined;
  $('draw-instruction').hidden = true;
  $('draw-profile').classList.remove('active');
  $('draw-profile').setAttribute('aria-pressed', 'false');
  viewer.setMode(value);
  for (const name of ['orbit', 'fly']) {
    $(`${name}-mode`).classList.toggle('active', name === value);
    $(`${name}-mode`).setAttribute('aria-pressed', String(name === value));
  }
  $('view-mode-label').textContent = value === 'orbit' ? '3D ORBIT' : 'FREE FLIGHT';
  $('fly-instruction').hidden = value !== 'fly';
  $('terrain-hint').style.visibility = value === 'fly' ? 'hidden' : '';
}
function clearInspector() {
  pinned = false;
  sampleVersion++;
  viewer.clearMarker();
  $('clear-pin').hidden = true;
  $('inspector-state').hidden = false;
  ['inspect-height', 'inspect-slope', 'inspect-grid', 'coord-x', 'coord-y', 'coord-z'].forEach(
    (id) => ($(id).textContent = '—'),
  );
}
function showSample(s: Sample, pin = false) {
  if (!meta) return;
  $('inspect-height').textContent = s.height === null ? 'No data' : fmt(hv(s.height), 2);
  $('inspect-unit').textContent = hUnit();
  $('inspect-slope').textContent =
    s.slope === null ? '—' : `${fmt(s.slope, 1)}°${meta.units !== 'm' ? '*' : ''}`;
  $('inspect-grid').textContent = `${Math.round(s.col)}, ${Math.round(s.row)}`;
  $('coord-x').textContent = `${fmt(s.col * meta.pixel_size_m, 1)} m`;
  $('coord-y').textContent = `${fmt(s.row * meta.pixel_size_m, 1)} m`;
  $('coord-z').textContent = s.height === null ? 'No data' : `${fmt(hv(s.height), 2)} ${hUnit()}`;
  if (pin && s.height !== null) {
    pinned = true;
    viewer.setMarker(s, s.height);
    $('clear-pin').hidden = false;
    $('inspector-state').hidden = true;
  }
}
function clearProfile() {
  profileVersion++;
  profilePoints = [];
  profileEndpoints = undefined;
  viewer.clearProfile();
  chart.clear();
  $('profile-empty').hidden = false;
  $('profile-type').textContent = 'No transect selected';
  $('profile-distance').textContent = '';
  $('profile-badge').hidden = true;
  $('profile-height-label').textContent = `ELEVATION · ${hUnit()}`;
  $('profile-chart').setAttribute(
    'aria-label',
    'No elevation profile selected. Draw a line on the terrain to begin.',
  );
  $('export-profile').toggleAttribute('disabled', true);
  for (const id of ['profile-min', 'profile-max', 'profile-change']) $(id).textContent = '—';
}
async function buildProfile(a: GridPoint, b: GridPoint, demo = false) {
  if (!worker || !meta) return;
  const version = ++profileVersion,
    source = worker;
  const points = await source.call<ProfilePoint[]>('profile', { a, b });
  if (version !== profileVersion || source !== worker) return;
  profilePoints = points;
  profileEndpoints = { a, b };
  viewer.setProfile(points);
  chart.set(points, meta);
  $('profile-empty').hidden = true;
  $('profile-badge').hidden = false;
  $('export-profile').toggleAttribute('disabled', false);
  $('profile-type').textContent = demo ? 'Demo transect' : 'Selected transect';
  $('profile-distance').textContent = `${fmt(points.at(-1)!.distance, 1)} m`;
  const values = points.filter((p) => p.height !== null).map((p) => p.height!);
  $('profile-height-label').textContent = `ELEVATION · ${hUnit()}`;
  $('profile-min').textContent = values.length
    ? `${fmt(hv(Math.min(...values)), 1)} ${hUnit()}`
    : 'No data';
  $('profile-max').textContent = values.length
    ? `${fmt(hv(Math.max(...values)), 1)} ${hUnit()}`
    : 'No data';
  const start = points[0].height,
    end = points.at(-1)!.height;
  $('profile-change').textContent =
    start !== null && end !== null
      ? `${end - start >= 0 ? '+' : ''}${fmt(hv(end - start), 1)} ${hUnit()}`
      : 'No data';
  $<HTMLCanvasElement>('profile-chart').setAttribute(
    'aria-label',
    `Elevation profile, ${fmt(points.at(-1)!.distance, 1)} metres long. Minimum ${$('profile-min').textContent}; maximum ${$('profile-max').textContent}. Export CSV for all samples.`,
  );
}
function toggleDrawing() {
  if (busy) return;
  if (viewer.drawing) {
    viewer.setDrawing(false);
    viewer.clearMarker();
    $('draw-instruction').hidden = true;
    $('draw-profile').classList.remove('active');
    $('draw-profile').setAttribute('aria-pressed', 'false');
    drawingStart = undefined;
    return;
  }
  if (viewer.mode === 'fly') setMode('orbit');
  clearInspector();
  viewer.setDrawing(true);
  drawingStart = undefined;
  $('draw-profile').classList.add('active');
  $('draw-profile').setAttribute('aria-pressed', 'true');
  $('draw-instruction').hidden = false;
  $('draw-instruction').innerHTML = 'Click a start point on the terrain <kbd>Esc</kbd> to cancel';
}
viewer.onPick = async (point, click) => {
  if (!worker || busy) return;
  if (!point) {
    if (!pinned && !viewer.drawing) clearInspector();
    return;
  }
  if (click && viewer.drawing) {
    if (!drawingStart) {
      drawingStart = point;
      const source = worker;
      try {
        const s = await source.call<Sample>('sample', point);
        if (source !== worker || !viewer.drawing || drawingStart !== point) return;
        if (s.height !== null) viewer.setMarker(point, s.height);
        $('draw-instruction').innerHTML =
          'Click an end point to complete the profile <kbd>Esc</kbd> to cancel';
      } catch (error) {
        if (source === worker) notify((error as Error).message, true);
      }
    } else {
      const start = drawingStart;
      toggleDrawing();
      viewer.clearMarker();
      await buildProfile(start, point).catch((e) => notify(e.message, true));
    }
    return;
  }
  if ((pinned && !click) || (sampling && !click)) return;
  sampling = true;
  const version = ++sampleVersion,
    source = worker;
  try {
    const s = await source.call<Sample>('sample', point);
    if (source === worker && version === sampleVersion) showSample(s, click);
  } catch {
  } finally {
    sampling = false;
  }
};
viewer.onError = (message) => notify(message, true);
viewer.onLock = (locked) => {
  $('crosshair').hidden = !locked;
  $('fly-instruction').hidden = locked || viewer.mode !== 'fly';
};
viewer.onHeading = (angle) => ($('compass-needle').style.transform = `rotate(${-angle}deg)`);
viewer.onPerformance = (fps, ratio) => {
  $('fps').textContent = `${Math.round(fps)} fps`;
  $('fps').title = `Measured frame rate · ${ratio.toFixed(2)}× pixel ratio`;
  if (!busy && $<HTMLSelectElement>('quality').value === 'auto' && cap > 257) {
    autoSlow = fps < 45 ? autoSlow + 1 : 0;
    if (autoSlow >= 4) {
      autoSlow = 0;
      void changeQuality(257);
    }
  }
};
chart.onHover = (p, index) => {
  if (p && !pinned) showSample(p);
  if (profilePoints.length) viewer.setProfile(profilePoints, index);
};
// DepthWizard patch: keepView swaps the surface in place (the DEM flip): same camera, flight
// mode, surface, exaggeration and profile.
async function loadDataset(files?: File[], options: { keepView?: boolean } = {}) {
  const keep = !!options.keepView && !!meta;
  const kept = {
    profile: profileEndpoints,
    surface: surface === 'error' ? ('ortho' as Surface) : surface,
    exaggeration: Number($<HTMLInputElement>('exaggeration').value),
  };
  const op = ++operation;
  candidate?.dispose();
  candidate = new TerrainWorker();
  const next = candidate;
  loading(
    true,
    files ? 'Opening your terrain' : 'Building your terrain',
    files
      ? 'Reading the full DSM in a background worker…'
      : 'Generating sample imagery and terrain locally…',
    !!meta,
  );
  let prepared: Awaited<ReturnType<TerrainViewer['prepareTexture']>> | undefined;
  try {
    let payload: Record<string, unknown> = { cap: keep ? cap : 513 },
      ortho: File | undefined;
    if (files) {
      const dsm = files.find((f) => f.name.toLowerCase() === 'dsm.bin'),
        json = files.find((f) => f.name.toLowerCase() === 'meta.json');
      ortho = files.find((f) => f.name.toLowerCase() === 'ortho.png');
      if (!dsm || !json || !ortho)
        throw new Error('Select dsm.bin, ortho.png, and meta.json together.');
      if (json.size > 1024 * 1024)
        throw new Error('meta.json is too large. Expected a small metadata object.');
      const parsed = validateMeta(JSON.parse(await json.text()));
      if (dsm.size !== parsed.width * parsed.height * 4)
        throw new Error(
          `DSM size mismatch: expected ${fmt(parsed.width * parsed.height * 4)} bytes.`,
        );
      payload = { ...payload, meta: parsed, file: dsm };
    }
    const result = await next.call<{
      meta: Meta;
      mesh: MeshData;
      image?: Blob;
      validCount: number;
      declared: {
        min: number;
        max: number;
      };
    }>(files ? 'load' : 'demo', payload);
    if (op !== operation) return;
    $('loading-detail').textContent = 'Preparing the local orthophoto and GPU buffers…';
    prepared = await viewer.prepareTexture(ortho ?? result.image!);
    if (op !== operation) {
      prepared.texture.dispose();
      prepared.texture.image.close();
      return;
    }
    // Raster dimensions may differ: both images cover the same geographic extent.
    const old = worker;
    worker = next;
    candidate = undefined;
    meta = result.meta;
    metrics = undefined;
    errorRangeOverride = undefined;
    if (!keep) cap = 513; // a flip keeps the chosen mesh quality
    autoSlow = 0;
    old?.dispose();
    if (!keep) setMode('orbit');
    viewer.setDataset(meta, result.mesh, prepared.texture, keep);
    prepared = undefined;
    clearInspector();
    clearProfile();
    if (keep) {
      setSurface(kept.surface);
      viewer.setExaggeration(kept.exaggeration);
    } else {
      setSurface('ortho');
      $<HTMLInputElement>('exaggeration').value = '1';
      $('exaggeration-value').innerHTML = '1.0<span>×</span>';
    }
    if (!keep) $<HTMLSelectElement>('quality').value = 'auto';
    currentName = files
      ? ((meta as Meta & { source_name?: string }).source_name ?? 'Imported terrain')
      : 'Alpine catchment';
    $('dataset-name').textContent = currentName;
    $('view-title').firstChild!.textContent = `${currentName} `;
    $('dataset-subtitle').textContent = files ? 'Local surface model' : 'Generated sample terrain';
    $('demo-badge').hidden = !!files;
    $('grid-size').textContent = `${fmt(meta.width)} × ${fmt(meta.height)}`;
    $('resolution').textContent = `${fmt(meta.pixel_size_m, 2)} m / px`;
    // DepthWizard patch (VIEWER_CONTRACT): assumed-scale label and calibration panel.
    const extra = meta as Meta & {
      pixel_size_assumed?: boolean;
      calibration?: Record<string, unknown> | null;
    };
    if (extra.pixel_size_assumed) $('resolution').textContent += ' · approximate scale';
    renderCalibration(extra.calibration);
    $('file-dsm-size').textContent = `${fmt((meta.width * meta.height * 4) / 1024 / 1024, 2)} MB`;
    $('extent-label').textContent =
      `${fmt(((meta.width - 1) * meta.pixel_size_m) / 1000, 2)} × ${fmt(((meta.height - 1) * meta.pixel_size_m) / 1000, 2)} km`;
    $('crs-label').textContent = meta.crs?.startsWith('LOCAL')
      ? 'LOCAL GRID'
      : (meta.crs ?? 'UNSPECIFIED CRS');
    $('crs-label').title =
      `Bounds: ${JSON.stringify(meta.bounds ?? 'not provided')} · Local X east, Y south from the first pixel centre`;
    $('dataset-status').textContent = 'Dataset ready';
    $('inspect-unit').textContent = hUnit();
    $('contour-unit').textContent = `50 ${unit()}`;
    $('error-surface').toggleAttribute('disabled', true);
    $('reference-results').hidden = true;
    $('difference-subtitle').textContent = 'Add a reference DSM';
    $('open-reference').innerHTML = `${icon('plus')} Add reference DSM`;
    meshStatus(result.mesh);
    refreshIcons();
    if (!files) await buildProfile({ col: 90, row: 550 }, { col: 660, row: 190 }, true);
    if (keep && kept.profile) await buildProfile(kept.profile.a, kept.profile.b);
    loading(false);
    if (keep) return;
    if (meta.units === 'relative')
      notify(
        'Relative vertical units: horizontal distances are metres; slope is an uncalibrated inclination proxy.',
      );
    else if (files) notify(`Terrain ready · ${fmt(result.validCount)} valid source cells`);
  } catch (e) {
    if (op === operation) {
      next.dispose();
      candidate = undefined;
      if (prepared) {
        prepared.texture.dispose();
        prepared.texture.image.close();
      }
      loading(false);
      notify(e instanceof Error ? e.message : String(e), true);
      if (!meta) {
        $('dataset-status').textContent = 'Open a dataset to begin';
        clearProfile();
      }
    }
  }
}
async function changeQuality(value: number) {
  if (!worker || busy || qualityChanging) return;
  qualityChanging = true;
  const source = worker;
  try {
    const mesh = await source.call<MeshData>('mesh', { cap: value });
    if (source !== worker) return;
    viewer.setMesh(mesh);
    cap = value;
    meshStatus(mesh);
  } catch (e) {
    notify((e as Error).message, true);
  } finally {
    qualityChanging = false;
  }
}
async function loadReference() {
  if (!worker || !meta) return;
  const file = $<HTMLInputElement>('reference-input').files?.[0],
    json = $<HTMLInputElement>('reference-meta-input').files?.[0];
  if (!file) return;
  if (file.size !== meta.width * meta.height * 4) {
    notify('Reference byte size does not match the source grid.', true);
    return;
  }
  $<HTMLDialogElement>('reference-dialog').close();
  loading(true, 'Comparing surfaces', 'Computing errors across every valid full-resolution cell…');
  const source = worker,
    op = operation;
  try {
    if (json && json.size > 1024 * 1024) throw new Error('Reference metadata is too large.');
    const referenceMeta = json ? JSON.parse(await json.text()) : undefined;
    const result = await source.call<{
      metrics: Metrics;
      mesh: MeshData;
    }>('reference', { file, meta: referenceMeta, cap });
    if (source !== worker || op !== operation) return;
    metrics = result.metrics;
    viewer.setMesh(result.mesh);
    meshStatus(result.mesh);
    $('reference-results').hidden = false;
    $('reference-name').textContent = file.name;
    $('rmse').textContent = `${fmt(metrics.rmse, 3)} ${unit()}`;
    $('mae').textContent = `${fmt(metrics.mae, 3)} ${unit()}`;
    $('reference-count').textContent =
      `${fmt(metrics.count)} valid pairs · Bias ${fmt(metrics.bias, 3)} ${unit()}`;
    $('error-surface').toggleAttribute('disabled', false);
    $('difference-subtitle').textContent = 'Source − reference';
    $('open-reference').innerHTML = `${icon('layers')} Replace reference`;
    refreshIcons();
    setSurface('error');
    if (profileEndpoints) await buildProfile(profileEndpoints.a, profileEndpoints.b);
    notify('Reference comparison complete. Metrics use the full source grid.');
  } catch (e) {
    notify((e as Error).message, true);
  } finally {
    if (op === operation) loading(false);
  }
}
function chooseFiles(files: File[]) {
  selectedFiles = files;
  const names = new Set(files.map((f) => f.name.toLowerCase()));
  $('selected-files').textContent = files.length
    ? files.map((f) => f.name).join(' · ')
    : 'No files selected';
  $<HTMLButtonElement>('load-selected').disabled = !['dsm.bin', 'ortho.png', 'meta.json'].every(
    (name) => names.has(name),
  );
}
$('open-dataset').onclick = () => $<HTMLDialogElement>('dataset-dialog').showModal();
$('help').onclick = () => $<HTMLDialogElement>('help-dialog').showModal();
$('open-reference').onclick = () => {
  if (meta) $<HTMLDialogElement>('reference-dialog').showModal();
};
document
  .querySelectorAll<HTMLElement>('.close-dialog')
  .forEach((button) => (button.onclick = () => button.closest('dialog')?.close()));
document.querySelectorAll<HTMLDialogElement>('dialog').forEach((dialog) =>
  dialog.addEventListener('click', (e) => {
    if (e.target === dialog) {
      const rect = dialog.getBoundingClientRect();
      if (
        e.clientX < rect.left ||
        e.clientX > rect.right ||
        e.clientY < rect.top ||
        e.clientY > rect.bottom
      )
        dialog.close();
    }
  }),
);
$('dataset-input').onchange = () =>
  chooseFiles(Array.from($<HTMLInputElement>('dataset-input').files ?? []));
$('load-selected').onclick = () => {
  $<HTMLDialogElement>('dataset-dialog').close();
  void loadDataset(selectedFiles);
};
$('load-demo').onclick = () => {
  $<HTMLDialogElement>('dataset-dialog').close();
  void loadDataset();
};
$('cancel-load').onclick = () => {
  operation++;
  candidate?.dispose();
  candidate = undefined;
  loading(false);
  notify('Loading cancelled.');
};
$('reference-input').onchange = () => {
  $<HTMLButtonElement>('load-reference').disabled =
    !$<HTMLInputElement>('reference-input').files?.length;
};
$('load-reference').onclick = () => {
  errorRangeOverride = undefined;
  void loadReference();
};
document
  .querySelectorAll<HTMLButtonElement>('[data-surface]')
  .forEach((button) => (button.onclick = () => setSurface(button.dataset.surface as Surface)));
$('hillshade').onchange = () => viewer.setHillshade($<HTMLInputElement>('hillshade').checked);
$('contours').onchange = () => viewer.setContours($<HTMLInputElement>('contours').checked);
function exaggerate() {
  const value = Number($<HTMLInputElement>('exaggeration').value);
  viewer.setExaggeration(value);
  $('exaggeration-value').innerHTML = `${value.toFixed(1)}<span>×</span>`;
}
$('exaggeration').oninput = exaggerate;
$('true-scale').onclick = () => {
  $<HTMLInputElement>('exaggeration').value = '1';
  exaggerate();
};
$('orbit-mode').onclick = () => setMode('orbit');
$('fly-mode').onclick = () => setMode('fly');
$('draw-profile').onclick = toggleDrawing;
$('empty-draw').onclick = toggleDrawing;
$('reset-camera').onclick = () => viewer.reset();
$('top-view').onclick = () => viewer.reset(true);
$('zoom-in').onclick = () => viewer.zoom(0.8);
$('zoom-out').onclick = () => viewer.zoom(1.25);
$('fullscreen').onclick = async () => {
  try {
    if (document.fullscreenElement) await document.exitFullscreen();
    else await $('viewport').requestFullscreen();
  } catch {
    notify('Fullscreen is unavailable in this window.', true);
  }
};
$('clear-pin').onclick = clearInspector;
$('clear-profile').onclick = clearProfile;
$('dismiss-toast').onclick = () => ($('toast').hidden = true);
$('quality').onchange = () =>
  void changeQuality(
    $<HTMLSelectElement>('quality').value === 'auto'
      ? 513
      : Number($<HTMLSelectElement>('quality').value),
  );
$('export-profile').onclick = () => {
  if (!profilePoints.length) return;
  const csv =
    `distance_m,height_${unit()},column,row,slope_${meta?.units === 'm' ? 'deg' : 'relative_proxy'},error_${unit()}\n` +
    profilePoints
      .map((p) =>
        [p.distance, p.height ?? '', p.col, p.row, p.slope ?? '', p.error ?? ''].join(','),
      )
      .join('\n');
  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }));
  const a = document.createElement('a');
  a.href = url;
  a.download = 'depthwizard-elevation-profile.csv'; // DepthWizard patch: product name
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
};
window.addEventListener('keydown', (e) => {
  if (
    (e.target as HTMLElement).matches('input,select,textarea') ||
    document.querySelector('dialog[open]') ||
    viewer.fly.isLocked
  )
    return;
  if (e.key === 'Escape' && viewer.drawing) {
    toggleDrawing();
    viewer.clearMarker();
  }
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  switch (e.key.toLowerCase()) {
    case 'o':
      e.preventDefault();
      $('open-dataset').click();
      break;
    case 'p':
      toggleDrawing();
      break;
    case 'r':
      viewer.reset();
      break;
    case 't':
      viewer.reset(true);
      break;
  }
});
let dragDepth = 0;
window.addEventListener('dragenter', (e) => {
  if (e.dataTransfer?.types.includes('Files')) {
    e.preventDefault();
    dragDepth++;
    if (!document.querySelector('dialog[open]')) $('global-drop').hidden = false;
  }
});
window.addEventListener('dragover', (e) => {
  if (e.dataTransfer?.types.includes('Files')) e.preventDefault();
});
window.addEventListener('dragleave', () => {
  dragDepth--;
  if (dragDepth <= 0) $('global-drop').hidden = true;
});
window.addEventListener('drop', (e) => {
  e.preventDefault();
  dragDepth = 0;
  $('global-drop').hidden = true;
  const files = Array.from(e.dataTransfer?.files ?? []);
  if (!files.length) return;
  if ($<HTMLDialogElement>('reference-dialog').open) {
    notify('Use the reference file controls to select a DSM and optional metadata.');
    return;
  }
  chooseFiles(files);
  if (!$<HTMLDialogElement>('dataset-dialog').open)
    $<HTMLDialogElement>('dataset-dialog').showModal();
});
window.addEventListener('beforeunload', () => {
  worker?.dispose();
  candidate?.dispose();
  viewer.dispose();
});
// Integration seam for a Tauri bridge: pass File objects read from its scoped filesystem API.
Object.assign(window, {
  stratum: {
    loadDataset,
    loadReferenceFiles: async (dsm: File, metadata?: File) => {
      const input = new DataTransfer();
      input.items.add(dsm);
      $<HTMLInputElement>('reference-input').files = input.files;
      const mi = new DataTransfer();
      if (metadata) mi.items.add(metadata);
      $<HTMLInputElement>('reference-meta-input').files = mi.files;
      await loadReference();
    },
  },
});
// DepthWizard patch: backend upload, job loading and validation (src/backend.ts).
installBackend({
  loadDataset,
  loadReferenceFiles: (dsm, metadata) =>
    (
      window as unknown as {
        stratum: { loadReferenceFiles: (d: File, m?: File) => Promise<void> };
      }
    ).stratum.loadReferenceFiles(dsm, metadata),
  loading,
  notify,
  setErrorRange: (range) => {
    errorRangeOverride = range;
    if (surface === 'error') setSurface('error');
    else updateLegend();
  },
  icon,
  refreshIcons,
  setWaterLevel: (level) => viewer.setWaterLevel(level),
});
void loadDataset();
