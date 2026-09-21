import { expect, test } from '@playwright/test';

import {
  mapLayerIds,
  openApp,
  renderedFeatureCount,
  runAnalysis,
  runAudit,
  selectDemoArea,
} from './helpers';

test.describe('Map interaction', () => {
  test('a polygon can be drawn, closed and measured', async ({ page }) => {
    const errors = await openApp(page);

    // Frame a forest first — the map view is setup here, not the behaviour
    // under test. Drawing at world zoom would produce a continental AOI.
    await page.evaluate(() => {
      (window as never as {
        __sylvasenseMap?: { jumpTo(o: { center: [number, number]; zoom: number }): void };
      }).__sylvasenseMap!.jumpTo({ center: [-60.02, -3.12], zoom: 10 });
    });
    await page.waitForTimeout(800);

    await page.getByTestId('draw-aoi').click();
    const box = (await page.locator('.map-canvas').boundingBox())!;

    const cx = box.x + box.width * 0.45;
    const cy = box.y + box.height * 0.45;
    const corners: [number, number][] = [
      [cx - 90, cy - 70],
      [cx + 90, cy - 70],
      [cx + 90, cy + 70],
      [cx - 90, cy + 70],
    ];
    for (const [x, y] of corners) {
      await page.mouse.click(x, y);
      await page.waitForTimeout(160);
    }

    // Closing with Enter is one of the documented affordances.
    await page.keyboard.press('Enter');

    await expect(page.locator('.stat-row', { hasText: 'Identifier' })).toBeVisible({
      timeout: 30_000,
    });
    const area = await page.locator('.stat-row', { hasText: 'Area' }).first().textContent();
    expect(area).toMatch(/km²|ha/);

    // The committed polygon is genuinely on the map.
    expect(await renderedFeatureCount(page, 'aoi-fill')).toBeGreaterThan(0);

    expect(errors, `console errors: ${errors.join(' | ')}`).toEqual([]);
  });

  test('Escape cancels a drawing in progress', async ({ page }) => {
    await openApp(page);
    await page.getByTestId('draw-aoi').click();
    const box = (await page.locator('.map-canvas').boundingBox())!;
    await page.mouse.click(box.x + 400, box.y + 300);
    await page.mouse.click(box.x + 500, box.y + 300);
    await page.keyboard.press('Escape');

    // Back to the idle toolbar, with no AOI committed.
    await expect(page.getByTestId('draw-aoi')).toBeVisible();
    await expect(page.getByTestId('panel-audit')).toContainText('Select a forest area');
  });

  test('clearing an area resets every derived result', async ({ page }) => {
    await openApp(page);
    await selectDemoArea(page);
    await runAudit(page);
    await runAnalysis(page);
    await expect.poll(() => mapLayerIds(page)).toContain('analysis-agb');

    await page.getByTestId('clear-aoi').click();

    await expect(page.getByTestId('panel-audit')).toContainText('Select a forest area');
    await expect(page.getByTestId('tab-analysis')).toBeDisabled();
    await expect.poll(() => mapLayerIds(page)).not.toContain('analysis-agb');
    expect(await renderedFeatureCount(page, 'aoi-fill')).toBe(0);
  });

  test('zoom controls move the map', async ({ page }) => {
    await openApp(page);
    const readZoom = () =>
      page.evaluate(() =>
        (window as never as { __sylvasenseMap?: { getZoom(): number } }).__sylvasenseMap!.getZoom(),
      );
    const before = await readZoom();
    await page.getByRole('button', { name: 'Zoom in' }).click();
    await page.waitForTimeout(500);
    expect(await readZoom()).toBeGreaterThan(before);
  });
});

test.describe('Error and empty states', () => {
  test('an oversized area is refused with a readable explanation', async ({ page }) => {
    await openApp(page);

    // Drawn the way a user would: a big rectangle at world zoom is a
    // continent-sized AOI, which the backend must refuse rather than attempt.
    await page.getByTestId('draw-aoi').click();
    const box = (await page.locator('.map-canvas').boundingBox())!;
    const corners: [number, number][] = [
      [box.x + box.width * 0.30, box.y + box.height * 0.35],
      [box.x + box.width * 0.62, box.y + box.height * 0.35],
      [box.x + box.width * 0.62, box.y + box.height * 0.68],
      [box.x + box.width * 0.30, box.y + box.height * 0.68],
    ];
    for (const [x, y] of corners) {
      await page.mouse.click(x, y);
      await page.waitForTimeout(160);
    }
    await page.keyboard.press('Enter');

    const sheet = page.getByTestId('error-sheet');
    await expect(sheet).toBeVisible({ timeout: 30_000 });
    // The user-facing contract: a plain title, causes, and a next step.
    await expect(sheet.locator('.error-sheet__title')).toContainText(/TOO LARGE/i);
    await expect(sheet.locator('.error-sheet__causes li').first()).toBeVisible();
    await expect(sheet.locator('.note--info')).toBeVisible();
    // Never a raw stack trace or a bare status code.
    const body = await sheet.textContent();
    expect(body).not.toMatch(/Traceback|Internal Server Error/);

    await page.getByTestId('error-dismiss').click();
    await expect(sheet).toBeHidden();
  });

  test('tabs that need results are disabled until those results exist', async ({ page }) => {
    await openApp(page);
    for (const tab of ['tab-analysis', 'tab-confidence', 'tab-fieldplan', 'tab-export']) {
      await expect(page.getByTestId(tab)).toBeDisabled();
    }
    await selectDemoArea(page);
    // Audit and Change need only an area.
    await expect(page.getByTestId('tab-change')).toBeEnabled();
    await expect(page.getByTestId('tab-analysis')).toBeDisabled();
  });

  test('the data-status popover names the exact remediation when unconfigured', async ({ page }) => {
    await openApp(page);
    await page.getByTestId('data-status').click();
    const dialog = page.getByRole('dialog', { name: 'Data status' });
    await expect(dialog).toBeVisible();
    await expect(dialog).toContainText(/Earth Engine/);

    const text = (await dialog.textContent()) ?? '';
    if (text.includes('Not available')) {
      // A missing credential must always come with the concrete next step.
      expect(text).toMatch(/SYLVASENSE_EE_SERVICE_ACCOUNT_FILE|EARTH_ENGINE_SETUP/);
    }
  });
});

test.describe('Responsive and accessible', () => {
  test('the map stays dominant on a tablet viewport', async ({ page }) => {
    await page.setViewportSize({ width: 1024, height: 768 });
    await openApp(page);
    await selectDemoArea(page);

    const map = (await page.locator('.map-canvas').boundingBox())!;
    const panel = (await page.getByTestId('side-panel').boundingBox())!;
    // The map must still be the larger element, not a strip beside the panel.
    expect(map.width).toBeGreaterThan(panel.width * 1.5);

    // No horizontal overflow at any supported width.
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);
  });

  test('primary controls are reachable and labelled', async ({ page }) => {
    await openApp(page);
    await selectDemoArea(page);

    // Semantic buttons, not divs with click handlers.
    await expect(page.getByTestId('run-audit')).toHaveRole('button');
    await expect(page.getByRole('tablist')).toBeVisible();
    await expect(page.getByRole('toolbar', { name: 'Map tools' })).toBeVisible();
    await expect(page.getByLabel('Zoom in')).toBeVisible();

    // The run action can be reached and fired from the keyboard alone.
    await page.getByTestId('run-audit').focus();
    await expect(page.getByTestId('run-audit')).toBeFocused();
    await page.keyboard.press('Enter');
    await expect(page.locator('.source-list')).toBeVisible({ timeout: 90_000 });
  });
});
