import { defineConfig } from '@playwright/test';
import standardConfig from './playwright.config.mjs';

const CASE_BY_PHASE = new Map([
  ['prepare', 'RIO-DURABLE-01'],
  ['outage', 'RIO-DURABLE-02'],
  ['revoke', 'RIO-DURABLE-03'],
  ['verify', 'RIO-DURABLE-04'],
]);
const phase = process.env.RIO_DURABLE_BROWSER_PHASE;
const caseId = CASE_BY_PHASE.get(phase);
if (!caseId) throw new Error('Choose a fixed synthetic durable browser phase');

export default defineConfig({
  ...standardConfig,
  testDir: './durable',
  testMatch: '**/*.spec.mjs',
  grep: new RegExp('\\[' + caseId + '\\]'),
  reporter: [['./safe-reporter.mjs', { durablePhase: phase }]],
  outputDir: './.runtime/playwright-durable-artifacts',
});
