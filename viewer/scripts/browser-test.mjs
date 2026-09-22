// Reproducible end-to-end regression test. Run a local preview first.
import { chromium, expect } from '@playwright/test';
import { makeFixtures } from './fixtures.mjs';
import { resolve } from 'node:path';
const directory = await makeFixtures();
const browser = await chromium.launch({
  channel: process.env.BROWSER_CHANNEL || 'chrome',
  headless: true,
});
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errors = [],
  external = [];
page.on('pageerror', (error) => errors.push(error.message));
await page.route('**/*', (route) => {
  const url = new URL(route.request().url());
  if (
    !['127.0.0.1', 'localhost'].includes(url.hostname) &&
    ['http:', 'https:'].includes(url.protocol)
  ) {
    external.push(url.href);
    return route.abort();
  }
  return route.continue();
});
try {
  await page.goto(process.env.VIEWER_URL || 'http://127.0.0.1:5175');
  await expect(page.locator('#loading')).toBeHidden({ timeout: 30000 });
  await expect(page.locator('#profile-type')).toHaveText('Demo transect');
  await page.locator('[data-surface="slope"]').click();
  await expect(page.locator('#legend-title')).toHaveText('SLOPE');
  await page.locator('#open-dataset').click();
  await page
    .locator('#dataset-input')
    .setInputFiles(['dsm.bin', 'ortho.png', 'meta.json'].map((file) => resolve(directory, file)));
  await page.locator('#load-selected').click();
  await expect(page.locator('#loading')).toBeHidden({ timeout: 30000 });
  await expect(page.locator('#grid-size')).toHaveText('4,000 × 4,000');
  await page.locator('#open-reference').click();
  await page.locator('#reference-input').setInputFiles(resolve(directory, 'reference.bin'));
  await page
    .locator('#reference-meta-input')
    .setInputFiles(resolve(directory, 'reference-meta.json'));
  await page.locator('#load-reference').click();
  await expect(page.locator('#loading')).toBeHidden({ timeout: 30000 });
  await expect(page.locator('#rmse')).toHaveText('2.000 m');
  await expect(page.locator('#mae')).toHaveText('2.000 m');
  await expect(page.locator('#reference-count')).toContainText('16,000,000 valid pairs');
  await page.locator('#top-view').click();
  await page.locator('#draw-profile').click();
  const rect = await page.locator('#viewport').boundingBox();
  await page.mouse.click(rect.x + rect.width * 0.46, rect.y + rect.height * 0.44);
  await page.mouse.click(rect.x + rect.width * 0.54, rect.y + rect.height * 0.62);
  await expect(page.locator('#profile-type')).toHaveText('Selected transect');
  const before = await page.locator('#profile-max').textContent();
  await page.locator('#exaggeration').press('End');
  await expect(page.locator('#exaggeration-value')).toHaveText('5.0×');
  await expect(page.locator('#profile-max')).toHaveText(before);
  await page.locator('#quality').selectOption('257');
  await expect(page.locator('#mesh-status')).toContainText('257 × 257');
  await page.screenshot({ path: 'test-results/browser-comparison.png' });
  // Verify invalid reference metadata leaves the previous comparison intact.
  await page.locator('#open-reference').click();
  await page.locator('#reference-meta-input').setInputFiles(resolve(directory, 'mismatch.json'));
  await page.locator('#load-reference').click();
  await expect(page.locator('#loading')).toBeHidden();
  await expect(page.locator('#toast-message')).toContainText('pixel_size_m');
  await expect(page.locator('#rmse')).toHaveText('2.000 m');
  if (errors.length || external.length)
    throw new Error(JSON.stringify({ errors, external }, null, 2));
  console.log(
    'PASS: demo, source import, 16M-cell reference metrics, profiles, exaggeration, quality, invalid reference, no remote requests or runtime errors.',
  );
} finally {
  await browser.close();
}
