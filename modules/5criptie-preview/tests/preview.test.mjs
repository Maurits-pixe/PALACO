import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import { events, metrics, reviewBreakdown, reviewBreakdownLabel, reviewSummaryLabel, trafficSamples } from '../src/telemetry.js';

const manifest = JSON.parse(await readFile(new URL('../public/.well-known/palaco-app.json', import.meta.url), 'utf8'));
const appSource = await readFile(new URL('../src/App.vue', import.meta.url), 'utf8');

test('launcher metadata identifies 5CRIPTIE as a preview only', () => {
  assert.equal(manifest.appId, '5criptie');
  assert.equal(manifest.status, 'preview-only');
});

test('dashboard fixtures are static and labeled as synthetic', () => {
  assert.equal(metrics.length, 4);
  assert.equal(events.length, 6);
  assert.equal(trafficSamples.length, 12);
  assert.ok(events.every(event => event.source.includes('fixture')));
  assert.ok(Object.isFrozen(metrics) && Object.isFrozen(events) && Object.isFrozen(trafficSamples));
});

test('review metric agrees with the event fixture statuses and severity', () => {
  const reviewCount = events.filter(event => event.status === 'Review').length;
  const highReviewCount = events.filter(event => event.status === 'Review' && event.severity === 'Hoog').length;
  const reviewMetric = metrics.find(metric => metric.id === 'review');
  assert.equal(reviewMetric.value, String(reviewCount).padStart(2, '0'));
  assert.equal(reviewMetric.change, `${highReviewCount} hoog`);
  assert.deepEqual(reviewBreakdown, [
    { severity: 'Hoog', count: 2 },
    { severity: 'Middel', count: 1 },
    { severity: 'Laag', count: 0 }
  ]);
  assert.equal(reviewBreakdown.reduce((total, item) => total + item.count, 0), reviewCount);
  assert.equal(reviewSummaryLabel(reviewCount), '3 reviewmeldingen');
  assert.equal(reviewBreakdownLabel(reviewBreakdown, reviewCount), 'Hoog: 2 reviewmeldingen, 67%. Middel: 1 reviewmelding, 33%. Laag: 0 reviewmeldingen, 0%');
});

test('review summary label handles empty and singular states', () => {
  assert.equal(reviewSummaryLabel(0), 'Geen reviewmeldingen');
  assert.equal(reviewSummaryLabel(1), '1 reviewmelding');
  assert.equal(reviewBreakdownLabel(reviewBreakdown.map(item => ({ ...item, count: 0 })), 0), 'Geen openstaande reviewmeldingen.');
  assert.equal(reviewBreakdownLabel([{ severity: 'Hoog', count: 1 }], 1), 'Hoog: 1 reviewmelding, 100%');
});

test('dashboard contains no network collection or scan client', () => {
  assert.doesNotMatch(appSource, /\bfetch\s*\(|\bWebSocket\b|\bXMLHttpRequest\b|sendBeacon/);
});
