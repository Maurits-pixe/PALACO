import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { applyFixtureEvent, normalizeWorldManifest, validateWorldManifest } from '../src/world.js';

const manifest = JSON.parse(fs.readFileSync(new URL('../src/manifest.json', import.meta.url), 'utf8'));

test('EVA fixture has explicit design-only and non-authoritative boundaries', () => {
  assert.equal(validateWorldManifest(manifest).state, 'STRUCTURALLY_VALID');
  assert.equal(manifest.status, 'DESIGN_DRAFT');
  assert.equal(manifest.engine.authority, 'NON_AUTHORITATIVE');
  assert.equal(manifest.lifecycle.execution_state, 'NOT_AUTHORIZED');
  assert.equal(manifest.visual_reference.type, 'CONCEPT_DESIGN_REFERENCE');
  assert.equal(manifest.visual_reference.constitutional_authority, false);
});

test('missing Citadel binding remains incomplete', () => {
  const candidate = structuredClone(manifest);
  delete candidate.citadel.binding_id;
  assert.equal(validateWorldManifest(candidate).state, 'INCOMPLETE');
});

test('duplicate region or landmark IDs are rejected', () => {
  const candidate = structuredClone(manifest);
  candidate.structure.landmarks[0].id = candidate.structure.regions[0].id;
  assert.equal(validateWorldManifest(candidate).state, 'INVALID');
});

test('unknown manifest fields are rejected by the schema stub', () => {
  const candidate = structuredClone(manifest);
  candidate.unreviewedAuthority = true;
  assert.equal(validateWorldManifest(candidate).state, 'INVALID');
});

test('manifest cannot promote design into activation or authority', () => {
  const candidate = structuredClone(manifest);
  candidate.lifecycle.execution_state = 'AUTHORIZED';
  assert.equal(validateWorldManifest(candidate).state, 'INVALID');
});

test('missing provenance remains invalid rather than being repaired', () => {
  const candidate = structuredClone(manifest);
  delete candidate.provenance.source_class;
  assert.equal(validateWorldManifest(candidate).state, 'INCOMPLETE');
});

test('unknown world identity is reported as a conflict', () => {
  const candidate = structuredClone(manifest);
  candidate.world.id = 'WORLD-OTHER-001';
  assert.equal(validateWorldManifest(candidate).state, 'CONFLICT');
});

test('normalization is deterministic and does not mutate the source', () => {
  const candidate = structuredClone(manifest);
  const before = JSON.stringify(candidate);
  const first = normalizeWorldManifest(candidate);
  const second = normalizeWorldManifest(candidate);
  assert.equal(first, second);
  assert.equal(JSON.stringify(candidate), before);
});

test('fixture events advance monotonically and reject duplicates and gaps', () => {
  const initial = { sequence: 41, validationState: 'UNKNOWN', events: [], issues: [] };
  const next = { sequence: 42, eventType: 'RIO_SIGNAL_RECEIVED', region: 'PROOF', validationState: 'UNKNOWN', traceRef: 'synthetic:eva:42' };
  const advanced = applyFixtureEvent(initial, next);
  assert.equal(advanced.sequence, 42);
  assert.equal(advanced.validationState, 'UNKNOWN');
  assert.equal(advanced.events.length, 1);
  assert.equal(applyFixtureEvent(advanced, next).transportState, 'DUPLICATE');
  assert.equal(applyFixtureEvent(initial, { ...next, sequence: 44 }).transportState, 'CONFLICT');
});

test('malformed fixture events are rejected without advancing sequence', () => {
  const initial = { sequence: 41, validationState: 'UNKNOWN', events: [], issues: [] };
  const valid = { sequence: 42, eventType: 'RIO_SIGNAL_RECEIVED', region: 'PROOF', validationState: 'UNKNOWN', traceRef: 'synthetic:eva:42' };
  for (const event of [
    { ...valid, region: 'UNKNOWN_REGION' },
    { ...valid, validationState: 'AUTHORIZED' },
    { ...valid, traceRef: '' },
    { ...valid, sequence: 0 },
  ]) {
    const result = applyFixtureEvent(initial, event);
    assert.equal(result.transportState, 'INVALID');
    assert.equal(result.sequence, initial.sequence);
    assert.equal(result.events.length, 0);
  }
});

test('preview source has no live transport, external write, or activation path', () => {
  for (const file of ['../src/App.vue', '../src/world.js', '../src/animation.js']) {
    const source = fs.readFileSync(new URL(file, import.meta.url), 'utf8');
    assert.doesNotMatch(source, /\b(fetch|EventSource|WebSocket)\b/);
    assert.doesNotMatch(source, /\b(activate|publish|execute)\s*\(/i);
  }
});
