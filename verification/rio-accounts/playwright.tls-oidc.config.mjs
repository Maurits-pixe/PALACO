import { defineConfig } from '@playwright/test';
import standardConfig from './playwright.config.mjs';

export default defineConfig({
  ...standardConfig,
  testMatch: '**/accounts.spec.mjs',
  reporter: [['./tls-oidc-reporter.mjs']],
  outputDir: './.runtime/playwright-tls-oidc-artifacts',
  preserveOutput: 'never',
  retries: 0,
});
