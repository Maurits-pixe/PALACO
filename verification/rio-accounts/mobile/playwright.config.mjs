import { defineConfig, devices } from '@playwright/test';
import standardConfig from '../playwright.config.mjs';

export default defineConfig({
  ...standardConfig,
  testDir: '.',
  testMatch: '**/*.spec.mjs',
  reporter: [['../safe-reporter.mjs', { mobileVerification: true }]],
  outputDir: '../.runtime/playwright-mobile-artifacts',
  use: { ...standardConfig.use, acceptDownloads: true },
  projects: [
    {
      name: 'android-emulation',
      testMatch: ['**/interaction.spec.mjs', '**/consent.spec.mjs', '**/login-observation.spec.mjs', '**/callback-interruption.spec.mjs', '**/post-consent-fault.spec.mjs'],
      use: { ...devices['Pixel 7'], viewport: { width: 390, height: 844 } },
    },
    {
      name: 'desktop-keyboard',
      testMatch: ['**/interaction.spec.mjs', '**/login-observation.spec.mjs', '**/callback-interruption.spec.mjs', '**/post-consent-fault.spec.mjs'],
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } },
    },
  ],
});
