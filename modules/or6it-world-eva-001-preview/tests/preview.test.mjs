import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import { events, indicators, snapshot } from '../src/fixtures.js';

const root = new URL('../', import.meta.url);
const read = file => fs.readFileSync(new URL(file, root), 'utf8');

test('fixture identity and every sample are explicitly synthetic', () => {
  assert.equal(snapshot.project, 'OR6IT');
  assert.equal(snapshot.worldId, 'WORLD-EVA-001');
  assert.equal(snapshot.mode, 'SYNTHETIC / NOT LIVE');
  assert.equal(Object.isFrozen(snapshot), true);
  assert.equal(indicators.length, 4);
  assert.equal(events.length, 3);
  assert.ok(indicators.every(item => Object.isFrozen(item) && item.note === 'illustrative'));
  assert.ok(events.every(Object.isFrozen));
});

test('preview has no interactive or external data paths', () => {
  const app = read('src/App.vue');
  const productionSources = ['src/App.vue', 'src/main.js', 'src/fixtures.js']
    .map(read).join('\n');
  assert.doesNotMatch(app, /<(?:a|button|input|form)\b/i);
  assert.doesNotMatch(productionSources, /\b(?:fetch|EventSource|WebSocket|setInterval|setTimeout)\b|https?:\/\//);
  assert.doesNotMatch(read('index.html'), /https?:\/\//i);
  assert.match(read('index.html'), /href="\/favicon\.svg"/);
  assert.doesNotMatch(read('src/style.css'), /@import|https?:\/\//i);
  assert.match(app, /SYNTHETIC PREVIEW/);
  assert.match(app, /read-only concept/);
  assert.match(app, /no API/);
});

test('orbital illustration is 2D and honors reduced motion', () => {
  const app = read('src/App.vue');
  const css = read('src/style.css');
  assert.match(app, /<svg\b/);
  assert.doesNotMatch(app, /<canvas\b/i);
  assert.match(css, /@keyframes orbit-drift/);
  assert.match(css, /@media \(prefers-reduced-motion: reduce\)/);
  assert.match(css, /\.orbit-marker\s*\{\s*animation:\s*none;/);
});
