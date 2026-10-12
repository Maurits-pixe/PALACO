import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  testMatch: '**/*.spec.mjs',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: Boolean(process.env.CI),
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: [['./safe-reporter.mjs']],
  outputDir: './.runtime/playwright-artifacts',
  preserveOutput: 'never',
  use: {
    browserName: 'chromium',
    // Applies only to this synthetic loopback certificate; no global TLS bypass.
    ignoreHTTPSErrors: true,
    headless: true,
    trace: 'off',
    screenshot: 'off',
    video: 'off',
    acceptDownloads: false,
    serviceWorkers: 'block',
    viewport: { width: 1280, height: 800 },
  },
});
