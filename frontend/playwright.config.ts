import { defineConfig, devices } from '@playwright/test';

/**
 * End-to-end tests run against the real backend and the real frontend.
 * Nothing is mocked: the assertions below are about what the product actually
 * does, not about what the components would do given fabricated data.
 */
export default defineConfig({
  testDir: './e2e',
  // The analysis pipeline genuinely takes seconds; these are not unit tests.
  timeout: 240_000,
  expect: { timeout: 30_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [['list']],
  use: {
    baseURL: process.env.SYLVASENSE_URL ?? 'http://127.0.0.1:5173',
    viewport: { width: 1680, height: 1000 },
    acceptDownloads: true,
    trace: 'retain-on-failure',
    launchOptions: {
      executablePath:
        process.env.PLAYWRIGHT_CHROMIUM_PATH ?? '/opt/pw-browsers/chromium',
    },
  },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'] } },
  ],
});
