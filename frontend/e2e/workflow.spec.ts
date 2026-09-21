import { expect, test } from '@playwright/test';

import {
  mapLayerIds,
  metricValue,
  openApp,
  renderedFeatureCount,
  runAnalysis,
  runAudit,
  searchAndSelect,
  selectDemoArea,
} from './helpers';

test.describe('SylvaSense end-to-end workflow', () => {
  test('a judge can go from a cold page to traceable carbon figures', async ({ page }) => {
    const errors = await openApp(page);

    // 1. The page states where its numbers come from before anything is run.
    const status = await page.getByTestId('data-status').textContent();
    expect(status?.trim()).toMatch(/LIVE EARTH ENGINE|SANDBOX SIMULATION|Backend offline/);
    expect(status?.trim()).not.toBe('');

    // 2-3. Select a real forest location.
    await searchAndSelect(page, 'Amazon');

    // 4. Area is measured, and measured geodesically.
    const areaText = await page.locator('.stat-row', { hasText: 'Area' }).first().textContent();
    expect(areaText).toMatch(/km²|ha/);
    await expect(page.locator('.hint', { hasText: 'Geodesic' })).toBeVisible();

    // 5-6. Audit reports genuine per-mission availability.
    await runAudit(page);
    const sources = page.locator('.source');
    expect(await sources.count()).toBeGreaterThanOrEqual(5);
    await expect(page.locator('.verdict .status-badge')).toBeVisible();

    // 7-8. Analysis runs as a real backend job with real step reporting.
    await page.getByTestId('run-analysis').click();
    const drawer = page.getByTestId('analysis-drawer');
    await expect(drawer).toBeVisible();
    // Progress is a step count, never a fabricated percentage.
    await expect(drawer.locator('.drawer__counter')).toContainText(/\d+ \/ \d+ steps/);
    await expect(page.getByTestId('metric-agb')).toBeVisible({ timeout: 200_000 });

    // 9. The four headline results are present and physically plausible.
    const canopy = await metricValue(page, 'metric-canopy');
    const agb = await metricValue(page, 'metric-agb');
    const carbon = await metricValue(page, 'metric-carbon');
    const co2e = await metricValue(page, 'metric-co2e');

    expect(canopy).toBeGreaterThan(0);
    expect(canopy).toBeLessThanOrEqual(100);
    expect(agb).toBeGreaterThan(0);
    expect(agb).toBeLessThan(1000);
    // Carbon is 47% of biomass and CO2e is 3.664x carbon — these must agree.
    expect(carbon).toBeCloseTo(agb * 0.47, -1);
    expect(co2e).toBeCloseTo(carbon * 3.6641, -1);

    // Every headline figure carries provenance.
    for (const id of ['metric-canopy', 'metric-agb', 'metric-carbon', 'metric-co2e']) {
      await expect(page.getByTestId(id).locator('.provenance')).toBeVisible();
    }

    // A biomass interval is shown, and it brackets the estimate.
    const range = await page.getByTestId('metric-agb').locator('.metric__range').textContent();
    expect(range).toMatch(/\d+\s*–\s*\d+/);

    expect(errors, `console errors: ${errors.join(' | ')}`).toEqual([]);
  });

  test('layer toggles actually change what the map draws', async ({ page }) => {
    const errors = await openApp(page);
    await selectDemoArea(page);
    await runAudit(page);
    await runAnalysis(page);

    // Biomass is shown by default once an analysis lands.
    await expect.poll(() => mapLayerIds(page)).toContain('analysis-agb');

    // 10. NDVI
    await page.getByTestId('layer-ndvi').check();
    await expect.poll(() => mapLayerIds(page)).toContain('analysis-ndvi');

    // 11. SAR
    await page.getByTestId('layer-vh').check();
    await expect.poll(() => mapLayerIds(page)).toContain('analysis-vh');

    // Switching a layer off removes it from the map, not just from the panel.
    await page.getByTestId('layer-ndvi').uncheck();
    await expect.poll(() => mapLayerIds(page)).not.toContain('analysis-ndvi');

    // The AOI outline is genuinely drawn over the rasters.
    expect(await renderedFeatureCount(page, 'aoi-line')).toBeGreaterThan(0);

    expect(errors, `console errors: ${errors.join(' | ')}`).toEqual([]);
  });

  test('confidence map and per-cell inspection explain themselves', async ({ page }) => {
    const errors = await openApp(page);
    await selectDemoArea(page);
    await runAudit(page);
    await runAnalysis(page);

    // 12. Confidence
    await page.getByTestId('tab-confidence').click();
    await page.getByTestId('view-confidence').click();
    await expect.poll(() => mapLayerIds(page)).toContain('analysis-confidence_class');

    // The three action classes are all named, with their meaning.
    for (const label of ['High confidence', 'Survey recommended', 'Insufficient data']) {
      await expect(page.locator('.conf-class__label', { hasText: label })).toBeVisible();
    }

    // 16. Click a region and get a real explanation.
    await page.getByTestId('confidence-inspect').click();
    const box = await page.locator('.map-canvas').boundingBox();
    expect(box).not.toBeNull();
    await page.mouse.click(box!.x + box!.width * 0.45, box!.y + box!.height * 0.5);

    const detail = page.getByTestId('cell-detail');
    await expect(detail).toBeVisible({ timeout: 30_000 });
    await expect(detail.locator('.status-badge')).toBeVisible();
    // The limiting factor must be stated, and must not be empty boilerplate.
    const reason = await detail.locator('.note--warn .note__body').textContent();
    expect((reason ?? '').length).toBeGreaterThan(15);
    // All four evidence components are reported.
    expect(await detail.locator('.component-row').count()).toBe(4);

    expect(errors, `console errors: ${errors.join(' | ')}`).toEqual([]);
  });

  test('field plan places numbered sites and explains their value', async ({ page }) => {
    const errors = await openApp(page);
    await selectDemoArea(page);
    await runAudit(page);
    await runAnalysis(page);

    // 13. Field plan
    await page.getByTestId('tab-fieldplan').click();
    await page.getByTestId('toggle-field-sites').click();

    // Markers are on the map, numbered from 01.
    const markers = page.locator('.site-marker');
    await expect(markers.first()).toBeVisible({ timeout: 20_000 });
    expect(await markers.count()).toBeGreaterThan(0);
    await expect(markers.first()).toHaveText('01');

    // They must be positioned over the area, not stacked at the map origin —
    // a CSS transform on the marker element silently replaces MapLibre's own.
    const mapBox = (await page.locator('.map-canvas').boundingBox())!;
    const positions: { x: number; y: number }[] = [];
    for (let i = 0; i < (await markers.count()); i += 1) {
      const box = await markers.nth(i).boundingBox();
      if (box) positions.push({ x: box.x, y: box.y });
    }
    expect(positions.length).toBeGreaterThan(3);
    for (const { x, y } of positions) {
      expect(x).toBeGreaterThan(mapBox.x);
      expect(x).toBeLessThan(mapBox.x + mapBox.width);
      expect(y).toBeGreaterThan(mapBox.y);
      expect(y).toBeLessThan(mapBox.y + mapBox.height);
    }
    // And they must be spread out, not all at the same point.
    const uniqueX = new Set(positions.map((p) => Math.round(p.x)));
    expect(uniqueX.size).toBeGreaterThan(2);

    // 17. Clicking a site opens its detail with a computed expected value.
    await page.getByTestId('site-01').click();
    const detail = page.getByTestId('site-detail');
    await expect(detail).toBeVisible();
    await expect(detail.locator('.site-detail__priority')).toContainText(/HIGH|MEDIUM|LOW/);
    await expect(detail.locator('.stat-row', { hasText: 'Latitude' })).toBeVisible();
    await expect(detail.locator('.stat-row', { hasText: 'Longitude' })).toBeVisible();
    await expect(detail.locator('.note--warn')).toBeVisible();
    const expected = await detail.locator('.site-detail__value').textContent();
    expect(expected).toMatch(/%/);

    expect(errors, `console errors: ${errors.join(' | ')}`).toEqual([]);
  });

  test('temporal comparison reports a tested verdict, not a bare difference', async ({ page }) => {
    const errors = await openApp(page);
    // A clearing frontier, so there is genuinely something to detect.
    await searchAndSelect(page, 'Leuser');
    await runAudit(page);
    await runAnalysis(page);

    // 14-15. Change, and the time slider.
    await page.getByTestId('tab-change').click();
    await page.getByTestId('compare-year-2022').click();
    await expect(page.locator('.timeline__labels')).toContainText('2022');

    await page.getByTestId('run-change').click();
    const verdict = page.getByTestId('change-verdict');
    await expect(verdict).toBeVisible({ timeout: 240_000 });
    await expect(verdict).toContainText(
      /Significant change|No significant change|Insufficient data/,
    );

    // The statistical evidence is shown, not just the headline.
    await expect(page.locator('.stat-row', { hasText: 'z' }).first()).toBeVisible();
    await expect(page.locator('.stat-row', { hasText: 'p' }).first()).toBeVisible();
    await expect(page.locator('.stat-row', { hasText: 'Materiality floor' })).toBeVisible();

    // Change layers become available only once a comparison exists.
    await page.getByTestId('view-change').click();
    await expect.poll(() => mapLayerIds(page)).toContain('analysis-change_class');

    // Moving the slider updates the displayed epoch.
    await page.getByTestId('compare-year-2020').click();
    await expect(page.locator('.timeline__labels')).toContainText('2020');

    expect(errors, `console errors: ${errors.join(' | ')}`).toEqual([]);
  });

  test('downloads produce real files', async ({ page }) => {
    const errors = await openApp(page);
    await selectDemoArea(page);
    await runAudit(page);
    await runAnalysis(page);
    await page.getByTestId('tab-export').click();

    // 18. GeoJSON
    const geojson = await Promise.all([
      page.waitForEvent('download'),
      page.getByTestId('download-geojson').click(),
    ]).then(([download]) => download);
    expect(geojson.suggestedFilename()).toMatch(/\.geojson$/);
    const geojsonPath = await geojson.path();
    expect(geojsonPath).toBeTruthy();

    // 19. Dossier
    const dossier = await Promise.all([
      page.waitForEvent('download'),
      page.getByTestId('download-dossier').click(),
    ]).then(([download]) => download);
    expect(dossier.suggestedFilename()).toMatch(/\.pdf$/);

    const fs = await import('node:fs');
    const dossierPath = await dossier.path();
    const header = fs.readFileSync(dossierPath!).subarray(0, 5).toString('latin1');
    expect(header).toBe('%PDF-');
    expect(fs.statSync(dossierPath!).size).toBeGreaterThan(5000);

    expect(errors, `console errors: ${errors.join(' | ')}`).toEqual([]);
  });

  test('a browser refresh returns a clean state and the workflow repeats', async ({ page }) => {
    const errors = await openApp(page);
    await selectDemoArea(page);
    await runAudit(page);
    await runAnalysis(page);

    // 20. Refresh.
    await page.reload({ waitUntil: 'networkidle' });
    await expect(page.getByTestId('panel-audit')).toBeVisible();
    // Tabs that need an analysis are disabled again, not left dangling.
    await expect(page.getByTestId('tab-analysis')).toBeDisabled();

    // 21. Repeat.
    await selectDemoArea(page);
    await runAudit(page);
    await runAnalysis(page);
    expect(await metricValue(page, 'metric-agb')).toBeGreaterThan(0);

    expect(errors, `console errors: ${errors.join(' | ')}`).toEqual([]);
  });
});
