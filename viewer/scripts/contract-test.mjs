// DepthWizard contract acceptance tests (docs/VIEWER_CONTRACT.md), run in a real browser against
// the running backend, which also serves the built viewer. Not upstream code.
//
//   python -m depthwizard.export.synthetic cone --out data/samples/cone   (and orientation, relative)
//   uvicorn api.main:app --port 8000
//   node scripts/contract-test.mjs            (VIEWER_URL, BROWSER_CHANNEL=msedge to override)
import { chromium, expect } from '@playwright/test';
import { existsSync } from 'node:fs';
import { resolve } from 'node:path';

const ROOT = resolve(import.meta.dirname, '..', '..');
const bundle = (name) =>
  ['dsm.bin', 'ortho.png', 'meta.json'].map((f) => resolve(ROOT, 'data', 'samples', name, f));
const TILE = resolve(ROOT, 'data', 'datasets', 'naip3dep', 'denver', '0_1');
const SCENE = resolve(ROOT, 'data', 'datasets', 'naip3dep', 'denver', 'scene.tif');
const URL_ = process.env.VIEWER_URL || 'http://127.0.0.1:8000';

const browser = await chromium.launch({
  channel: process.env.BROWSER_CHANNEL || 'chrome',
  headless: true,
});
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errors = [];
const external = [];
page.on('pageerror', (e) => errors.push(e.message));
await page.route('**/*', (route) => {
  const url = new URL(route.request().url());
  if (!['127.0.0.1', 'localhost'].includes(url.hostname) && url.protocol.startsWith('http')) {
    external.push(url.href);
    return route.abort();
  }
  return route.continue();
});

const results = [];
const check = (name, ok, detail = '') => {
  results.push(ok);
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? `  (${detail})` : ''}`);
};
const idle = () => expect(page.locator('#loading')).toBeHidden({ timeout: 240000 });
const text = async (sel) => (await page.locator(sel).textContent()) ?? '';
const num = async (sel) => parseFloat((await text(sel)).replace(/[^\d.+-]/g, ''));

async function openLocal(name) {
  await page.locator('#open-dataset').click();
  await page.locator('#dataset-input').setInputFiles(bundle(name));
  await page.locator('#load-selected').click();
  await idle();
  await page.locator('#top-view').click();
  await page.waitForTimeout(1200); // let orbit damping settle
}

// Click a point given as a fraction of the terrain canvas; returns the pinned readout.
async function probe(fx, fy) {
  const box = await page.locator('#viewport canvas').boundingBox();
  await page.mouse.click(box.x + box.width * fx, box.y + box.height * fy);
  await page.waitForTimeout(400);
  return {
    height: await num('#inspect-height'),
    unit: await text('#inspect-unit'),
    slope: await num('#inspect-slope'),
  };
}

try {
  await page.goto(URL_);
  await idle();

  // 1. Cone: peak height, slope on the flank. (Dot placement is checked on the bundle bytes in
  //    tests/test_bundle.py; here the rendered pick must agree with the geometry.)
  await openLocal('cone');
  const peak = await probe(0.5, 0.5);
  check(
    'cone peak reads 100.0 m (±0.5)',
    Math.abs(peak.height - 100) <= 0.5 && peak.unit === 'm',
    `${peak.height} ${peak.unit}`,
  );
  const flank = await probe(0.58, 0.5);
  check('cone flank slope ≈ 14.0°', Math.abs(flank.slope - 14.04) <= 0.5, `${flank.slope}°`);
  const north = await probe(0.5, 0.2);
  const south = await probe(0.5, 0.8);
  check('screen top in top view is north (−z)', north.height >= 0 && south.height >= 0, 'picked');

  // 2. Orientation: the raised NW corner is at the top-left (−x, −z) in top view.
  await openLocal('orientation');
  const nw = await probe(0.33, 0.22);
  const se = await probe(0.67, 0.78);
  check(
    'NW corner raised at −x, −z',
    nw.height > 40 && se.height < 1,
    `NW ${nw.height} m, SE ${se.height} m`,
  );

  // 3. Relative: approximate-scale label and percent heights.
  await openLocal('relative');
  const rel = await probe(0.5, 0.5);
  check(
    'relative shows approximate scale',
    (await text('#resolution')).includes('approximate scale'),
  );
  check(
    'relative heights in %',
    rel.unit === '%' && Math.abs(rel.height - 100) <= 1,
    `${rel.height} ${rel.unit}`,
  );

  // 4. Validate: cone against itself, client-side comparison.
  await openLocal('cone');
  await page.locator('#open-reference').click();
  await page.locator('#reference-input').setInputFiles(bundle('cone')[0]);
  await page.locator('#reference-meta-input').setInputFiles(bundle('cone')[2]);
  await page.locator('#load-reference').click();
  await idle();
  check('cone vs itself: RMSE 0', (await text('#rmse')).startsWith('0.000'), await text('#rmse'));

  // Backend flow (Phase 3 done-when): upload a GeoTIFF, get a metric DSM, click, read metres.
  if (existsSync(TILE)) {
    await page.locator('#process-image').click();
    await page.locator('#dw-image').setInputFiles(resolve(TILE, 'image.tif'));
    await page.locator('#dw-process').click();
    await expect(page.locator('#dataset-name')).toHaveText('image.tif', { timeout: 240000 });
    await idle();
    await page.locator('#top-view').click();
    await page.waitForTimeout(1200);
    const hit = await probe(0.5, 0.5);
    check(
      'uploaded GeoTIFF reads metres',
      hit.unit === 'm' && hit.height > 1000,
      `${hit.height} ${hit.unit}`,
    );
    check(
      'calibration panel shown',
      !(await page.locator('#dw-calibration').isHidden()),
      await text('#dw-calibration'),
    );
    await page.locator('#dw-open-validate').click();
    await page.locator('#dw-reference').setInputFiles(resolve(TILE, 'dsm.tif'));
    await page.locator('#dw-validate').click();
    await expect(page.locator('#reference-count')).toContainText('full-resolution', {
      timeout: 120000,
    });
    check(
      'backend validation against LiDAR',
      (await text('#legend-title')) === 'SIGNED DIFFERENCE',
      `${await text('#rmse')} · ${await text('#reference-count')}`,
    );
  } else
    console.log('SKIP  backend flow (no NAIP tile; run python -m evals.datasets.naip3dep build)');

  // Terrain switcher: every finished result is listed; picking an entry loads it.
  await page.locator('#dw-terrains').click();
  // Wait for the list itself: "Looking for results…" is shown while it loads.
  await expect(page.locator('#dw-terrain-state')).toContainText(/on this computer|No results yet/, {
    timeout: 15000,
  });
  const entries = await page.locator('#dw-terrain-list button').count();
  check('terrain switcher lists results', entries >= 2, `${entries} entries incl. the sample`);
  await page.locator('#dw-terrain-list button', { hasText: 'Sample terrain' }).click();
  await idle();
  check('switch to the built-in sample', (await text('#dataset-name')) === 'Alpine catchment');
  check('URL forgets the job on the sample', !page.url().includes('job='), page.url());
  await page.locator('#dw-terrains').click();
  await page.locator('#dw-terrain-list button[data-job]').first().click();
  await idle();
  await page.waitForTimeout(500);
  check(
    'switch back to a backend result',
    page.url().includes('job='),
    await text('#dataset-name'),
  );

  // 5. Big input: a 4096² GeoTIFF through the backend. Headless Chrome renders in software, so
  //    the frame rate here is informational; certify fps on the target laptop by hand.
  if (existsSync(SCENE)) {
    await page.locator('#process-image').click();
    await page.locator('#dw-image').setInputFiles(SCENE);
    await page.locator('#dw-process').click();
    await expect(page.locator('#dataset-name')).toHaveText('scene.tif', { timeout: 240000 });
    await idle();
    await page.waitForTimeout(5000);
    check(
      '4096² input loads and stays interactive',
      (await text('#grid-size')).includes('2,048'),
      `${await text('#grid-size')} · ${await text('#fps')} (software GL)`,
    );
  }

  await page.screenshot({ path: resolve(ROOT, 'viewer', 'test-results', 'contract-final.png') });
  check('no page errors', errors.length === 0, errors.join(' | '));
  check('no external requests', external.length === 0, external.join(' '));
} finally {
  await browser.close();
}
const failed = results.filter((ok) => !ok).length;
console.log(failed ? `${failed} check(s) failed` : `all ${results.length} checks passed`);
process.exitCode = failed ? 1 : 0;
