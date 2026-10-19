import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import { events, metrics, trafficSamples } from '../src/telemetry.js';

const manifest = JSON.parse(await readFile(new URL('../public/.well-known/palaco-app.json', import.meta.url), 'utf8'));

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
