import { defineConfig } from '@playwright/test';
import tlsConfig from './playwright.tls-oidc.config.mjs';

export default defineConfig({
  ...tlsConfig,
  reporter: [['./tls-oidc-reporter.mjs', { target: 'restore' }]],
  outputDir: './.runtime/playwright-tls-restore-oidc-artifacts',
});
