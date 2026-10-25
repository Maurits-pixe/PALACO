import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import { runInNewContext } from 'node:vm';

const source = await readFile(new URL('../hara-runtime.js', import.meta.url), 'utf8');

function createRuntime() {
  const window = {};
  runInNewContext(source, {window});
  return window.PalacoHaraDemoRuntime.create();
}

test('only fixed fictional services can enter the in-memory preview', () => {
  const runtime = createRuntime();

  assert.equal(runtime.prepare('unknown').ok, false);
  assert.equal(runtime.prepare('__proto__').ok, false);
  assert.equal(runtime.snapshot().phase, 'READY');
  assert.equal(runtime.snapshot().service, null);
});

test('preview follows bounded transitions and closes without a decision', () => {
  const runtime = createRuntime();

  assert.equal(runtime.showReviewBoundary().ok, false);
  assert.equal(runtime.close().ok, false);

  const prepared = runtime.prepare('care');
  assert.equal(prepared.ok, true);
  assert.equal(prepared.state.phase, 'PREPARED');
  assert.equal(prepared.state.service, 'Care & wellbeing');
  assert.equal(Object.isFrozen(prepared.state), true);
  assert.equal(runtime.prepare('guide').ok, false);

  assert.equal(runtime.showReviewBoundary().state.phase, 'REVIEW_BOUNDARY');
  assert.equal(runtime.close().state.phase, 'CLOSED');
  assert.equal(runtime.close().ok, false);

  assert.equal(runtime.reset().phase, 'READY');
  assert.equal(runtime.prepare('guide').state.service, 'Citadel guide');
});
