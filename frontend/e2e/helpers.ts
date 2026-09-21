import { expect, type Page } from '@playwright/test';

/**
 * Tile hosts outside the app are blocked in some environments (and can simply
 * be down). Those failures are handled by the offline basemap fallback and are
 * not defects, so they are excluded from console-error assertions.
 */
const EXPECTED_NETWORK_NOISE = [
  'ERR_TUNNEL_CONNECTION_FAILED',
  'ERR_NAME_NOT_RESOLVED',
  'ERR_CONNECTION_REFUSED',
  'basemaps.cartocdn.com',
];

export function collectConsoleErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on('console', (message) => {
    if (message.type() !== 'error') return;
    const text = message.text();
    if (EXPECTED_NETWORK_NOISE.some((noise) => text.includes(noise))) return;
    errors.push(text);
  });
  page.on('pageerror', (error) => errors.push(`[pageerror] ${error.message}`));
  return errors;
}

export async function openApp(page: Page): Promise<string[]> {
  const errors = collectConsoleErrors(page);
  await page.goto('/', { waitUntil: 'networkidle' });
  await expect(page.getByTestId('data-status')).toBeVisible();
  await page.waitForFunction(
    () => Boolean((window as never as { __sylvasenseMap?: { loaded(): boolean } }).__sylvasenseMap?.loaded()),
    null,
    { timeout: 30_000 },
  );
  return errors;
}

/** Pick the first demo area offered on the audit panel. */
export async function selectDemoArea(page: Page): Promise<void> {
  await page.locator('[data-testid^="demo-"]').first().click();
  await expect(page.locator('.stat-row', { hasText: 'Identifier' })).toBeVisible();
}

export async function searchAndSelect(page: Page, query: string): Promise<void> {
  await page.getByTestId('search-input').fill(query);
  await expect(page.getByTestId('search-results')).toBeVisible();
  await page.locator('.search-result').first().click();
  await expect(page.locator('.stat-row', { hasText: 'Identifier' })).toBeVisible();
}

export async function runAudit(page: Page): Promise<void> {
  await page.getByTestId('run-audit').click();
  await expect(page.locator('.source-list')).toBeVisible({ timeout: 90_000 });
}

export async function runAnalysis(page: Page): Promise<void> {
  await page.getByTestId('run-analysis').click();
  await expect(page.getByTestId('metric-agb')).toBeVisible({ timeout: 200_000 });
}

/** Layer ids currently present on the live MapLibre style. */
export async function mapLayerIds(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const map = (window as never as { __sylvasenseMap?: { getStyle(): { layers: { id: string }[] } } })
      .__sylvasenseMap;
    return map ? map.getStyle().layers.map((layer) => layer.id) : [];
  });
}

export async function renderedFeatureCount(page: Page, layer: string): Promise<number> {
  return page.evaluate((id) => {
    const map = (window as never as {
      __sylvasenseMap?: { queryRenderedFeatures(o: { layers: string[] }): unknown[] };
    }).__sylvasenseMap;
    if (!map) return 0;
    try {
      return map.queryRenderedFeatures({ layers: [id] }).length;
    } catch {
      return 0;
    }
  }, layer);
}

/** Numeric value out of a metric card, e.g. "252" from the biomass card. */
export async function metricValue(page: Page, testId: string): Promise<number> {
  const text = await page.getByTestId(testId).locator('.metric__value').textContent();
  const match = (text ?? '').replace(/,/g, '').match(/-?\d+(\.\d+)?/);
  return match ? Number(match[0]) : Number.NaN;
}
